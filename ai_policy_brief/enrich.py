"""Adds a one-line summary to stories that have none by reading the page's own
description metadata (og:description), the same thing a link preview shows.

Every story's URL comes in pointing at a Google News redirect page
(news.py sources outlets through Google News "site:" search so paywalled
outlets are reachable). That redirect is no longer a plain HTTP 3xx -- the
real URL is embedded in a signed payload that only resolves through
Google's internal batchexecute endpoint, which `googlenewsdecoder`
replicates. `resolve_google_news` decodes every story's link to the real
publisher URL -- one GET per story to fetch its signature/timestamp, then a
single shared POST to decode them all -- BEFORE anything else below runs:
without it, every fetch in `enrich()` just gets the Google interstitial
back, `BAD_HOSTS` correctly rejects it, and no story -- paywalled or not --
ever gets a summary. Resolution runs for paywalled stories too (so "Read
at The Wall Street Journal" actually opens wsj.com instead of a Google
redirect); only the description fetch below skips them.

Rules: never fetch a paywalled outlet's page for a summary; skip a page if
the site's robots.txt disallows it; any failure (decode or fetch) just
leaves the story as headline-only, exactly as before this existed.

Optional: with ANTHROPIC_API_KEY set, `why_it_matters` adds one grounded
sentence, written only from the fetched description.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import urllib.robotparser
from typing import Optional
from urllib.parse import urlparse

from .news import Story, _summary

log = logging.getLogger(__name__)

META_TAG = re.compile(r"<meta\b[^>]*>", re.I)
META_KEY = re.compile(r"""(?:property|name)\s*=\s*(["'])(?:og:description|description|twitter:description)\1""", re.I)
META_CONTENT = re.compile(r"""content\s*=\s*(["'])(.*?)\1""", re.I | re.S)
BAD_HOSTS = ("news.google.com", "consent.google.com", "accounts.google.com")
UA = "Mozilla/5.0 (compatible; AIPolicyBrief/1.0)"
_robots: dict = {}


def extract_description(page: str) -> str:
    best = ""
    for tag in META_TAG.findall(page or ""):
        if not META_KEY.search(tag):
            continue
        m = META_CONTENT.search(tag)
        if m:
            text = re.sub(r"\s+", " ", html.unescape(m.group(2))).strip()
            if len(text) > len(best):
                best = text
    return best


def allowed(url: str) -> bool:
    parts = urlparse(url)
    host = f"{parts.scheme}://{parts.netloc}"
    if host not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            import requests
            r = requests.get(host + "/robots.txt", headers={"User-Agent": UA}, timeout=8)
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
            else:
                rp = None  # no robots.txt (or unreadable): nothing disallows it
        except Exception:
            rp = None
        _robots[host] = rp
    rp = _robots[host]
    return True if rp is None else rp.can_fetch(UA, url)


def resolve_google_news(stories: list[Story], decode=None) -> int:
    """Decode every story's Google News redirect link to the real publisher
    URL (one GET per story, then a single shared decode POST). Runs for
    paywalled stories too -- this only resolves the URL, it never fetches
    or reads the paywalled page itself.

    `decode` is injectable for tests; it defaults to `gnewsdecoder` and is
    called with a list of URLs, returning a list of
    `{"success": bool, "decoded_url": str}`-shaped dicts in the same order
    (matching googlenewsdecoder's own return shape). Any failure -- import,
    network, a changed Google response format -- just leaves the affected
    stories pointed at their original Google News link, same as if this
    function didn't run at all.
    """
    targets = [s for s in stories if urlparse(s.url).netloc == "news.google.com"]
    if not targets:
        return 0
    if decode is None:
        try:
            from googlenewsdecoder import gnewsdecoder
        except Exception as exc:
            log.info("googlenewsdecoder unavailable: %s", exc)
            return 0
        decode = gnewsdecoder
    try:
        results = decode([s.url for s in targets])
        if isinstance(results, dict):  # a single URL in, dict back -- normalize
            results = [results]
        results = list(results)
    except Exception as exc:
        log.info("gnewsdecoder batch failed for %d stories: %s", len(targets), exc)
        return 0
    if len(results) != len(targets):
        # A mismatched length means the response can't be trusted to line up
        # positionally with `targets` -- zip() would silently pair each story
        # with the wrong result rather than error, so bail out instead of
        # risking a story's URL getting overwritten with someone else's
        # decoded link.
        log.info("gnewsdecoder returned %d results for %d URLs -- skipping", len(results), len(targets))
        return 0
    resolved = 0
    for s, result in zip(targets, results):
        if isinstance(result, dict) and result.get("success") and result.get("decoded_url"):
            s.url = result["decoded_url"]
            resolved += 1
        else:
            log.info("gnewsdecoder could not resolve %s: %s", s.url,
                     result.get("message") if isinstance(result, dict) else result)
    return resolved


def enrich(stories: list[Story], session=None, decode=None) -> dict:
    """`decode` is forwarded to `resolve_google_news` -- see its docstring.
    Only ever set by tests; a live run leaves it as None so the real
    `gnewsdecoder` is used."""
    import requests
    session = session or requests.Session()
    stats = {"resolved": 0, "tried": 0, "summaries": 0, "direct_links": 0}
    stats["resolved"] = resolve_google_news(stories, decode=decode)
    for s in stories:
        if s.paywalled or s.summary:
            continue
        stats["tried"] += 1
        try:
            r = session.get(s.url, headers={"User-Agent": UA}, timeout=15, allow_redirects=True)
            final = r.url
            if r.status_code != 200 or urlparse(final).netloc in BAD_HOSTS:
                continue
            if not allowed(final):
                continue
            desc = extract_description(r.text)
            if len(desc) >= 40:
                s.summary = _summary(desc)
                stats["summaries"] += 1
            if final != s.url:
                s.url = final
                stats["direct_links"] += 1
        except Exception as exc:
            log.info("enrich failed for %s: %s", s.url, exc)
    return stats


def write_intro(lead: Optional[Story], stories: list[Story], pulse_total: int, pulse_new: int,
                model: Optional[str] = None) -> Optional[str]:
    """One conversational sentence (<=25 words) introducing the issue, grounded
    strictly in the lead story's headline, the section names of the other
    stories, and the jobs-pulse counts -- never invented facts. Returns None
    (never a placeholder string) if there's no API key or the call fails, so
    a missing intro just means the newsletter opens straight on the lead
    story, exactly as it did before this existed."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or lead is None:
        return None
    import requests
    model = model or os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    sections = ", ".join(sorted({s.section for s in stories})) or "none"
    prompt = (
        "Write one conversational, upbeat sentence (max 25 words) to open a policy newsletter, "
        "the kind a friendly human editor would write, not a headline mashup. "
        "Use ONLY the facts given below -- no invented names, numbers, or events. "
        "You may mention the lead story and, if natural, the number of open jobs.\n\n"
        f"Lead story headline: {lead.title}\n"
        f"Other sections covered this issue: {sections}\n"
        f"Open jobs in this issue: {pulse_total} ({pulse_new} new since last issue)\n\n"
        "Reply with ONLY the sentence, no quotation marks.")
    try:
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=40,
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"},
                          data=json.dumps({"model": model, "max_tokens": 80,
                                           "messages": [{"role": "user", "content": prompt}]}))
        text = r.json()["content"][0]["text"].strip().strip('"')
        return text or None
    except Exception as exc:
        log.info("write_intro failed: %s", exc)
        return None


def why_it_matters(stories: list[Story], model: Optional[str] = None) -> int:
    """One sentence per story that has a summary, grounded strictly in it."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return 0
    import requests
    model = model or os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    done = 0
    for s in stories:
        if not s.summary:
            continue
        prompt = (
            "Write one sentence (max 25 words) on why this story matters to people who work in AI policy. "
            "Use ONLY the headline and description below. Do not add facts, names, numbers or context "
            "that are not in them. If the text does not support a 'why it matters' point, reply exactly: NONE.\n\n"
            f"Headline: {s.title}\nDescription: {s.summary}")
        try:
            r = requests.post("https://api.anthropic.com/v1/messages", timeout=40,
                              headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                       "content-type": "application/json"},
                              data=json.dumps({"model": model, "max_tokens": 80,
                                               "messages": [{"role": "user", "content": prompt}]}))
            text = r.json()["content"][0]["text"].strip()
            if text and text.upper() != "NONE":
                s.why = text  # type: ignore[attr-defined]
                done += 1
        except Exception as exc:
            log.info("why_it_matters failed: %s", exc)
    return done
