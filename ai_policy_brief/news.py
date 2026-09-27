"""AI + policy news for the newsletter.

Sources: Axios, Politico, WSJ, Washington Post, NYT, Reuters, AP, The Hill,
Tech Policy Press and Lawfare. Each outlet is searched through a Google News
RSS query restricted to that outlet's domain (site: operator), which works
for paywalled outlets without touching their content. Two outlets also
have direct RSS feeds, read as a bonus when they are up.

Paywalled outlets (WSJ, Washington Post, NYT) get headline + link only.
The story is credited to the outlet; nothing from behind the paywall is
reproduced.

Selection: keep items that are both about AI and about policy, drop opinion
pieces, group items that are the same story across outlets, rank by how
many outlets ran it, drop anything shown in a recent issue, and pick the
top one or two per section.

All network access goes through the `fetch` argument so tests can run on
fixtures.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import urlencode

from . import config

log = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
RECENT_PATH = os.path.join(DATA_DIR, "recent_stories.json")
LAST_ISSUE_PATH = os.path.join(DATA_DIR, "last_issue.json")
MEMORY_DAYS = 14

# (display name, domain, ranking weight, paywalled)
OUTLETS = [
    ("Axios", "axios.com", 1.0, False),
    ("Politico", "politico.com", 1.0, False),
    ("The Wall Street Journal", "wsj.com", 1.2, True),
    ("The Washington Post", "washingtonpost.com", 1.2, True),
    ("The New York Times", "nytimes.com", 1.3, True),
    ("Reuters", "reuters.com", 1.1, False),
    ("AP", "apnews.com", 1.0, False),
    ("The Hill", "thehill.com", 0.8, False),
    ("Tech Policy Press", "techpolicy.press", 0.8, False),
    ("Lawfare", "lawfaremedia.org", 0.8, False),
]

# Direct feeds: (outlet display name, url). Best effort; failures are logged
# and skipped, the Google News queries above still cover these outlets.
DIRECT_FEEDS = [
    ("The Hill", "https://thehill.com/policy/technology/feed/"),
    ("Tech Policy Press", "https://www.techpolicy.press/rss/feed.xml"),
]

QUERIES = [
    '("artificial intelligence" OR AI) (regulation OR legislation OR Congress OR "executive order" OR lawsuit OR "White House")',
    '(AI OR OpenAI OR Anthropic OR Nvidia) (policy OR bill OR ban OR "export controls" OR state OR EU OR China OR antitrust)',
]

SECTIONS = [
    ("Congress", "\U0001F3DB️"),
    ("White House & Agencies", "\U0001F3E2"),
    ("States", "\U0001F5FA️"),
    ("Courts & Legal", "⚖️"),
    ("Global", "\U0001F30D"),
    ("Industry & Labs", "\U0001F916"),
]

AI_RE = re.compile(
    r"\bAI\b|artificial intelligence|chatbot|generative|large language|\bLLMs?\b|"
    r"OpenAI|Anthropic|\bxAI\b|DeepMind|Gemini|ChatGPT|Claude|Nvidia|frontier model|"
    r"superintelligence|deepfake|AI Act|data cent(?:er|re)s?", re.I)
POLICY_RE = re.compile(
    r"regulat|legislat|\blaws?\b|\bbills?\b|congress|senat|\bhouse\b|lawmaker|"
    r"executive order|white house|\bftc\b|\bfcc\b|\bdoj\b|justice department|pentagon|"
    r"commerce department|\bnist\b|export control|\bchips?\b|tariff|antitrust|copyright|"
    r"\bcourts?\b|judge|lawsuit|\bsues?\b|sued|ruling|attorney general|governor|"
    r"state law|statehouse|moratorium|preempt|\bpolicy\b|policymakers|\bban\b|"
    r"\bEU\b|European Union|Brussels|\bAI Act\b|safety|subpoena|hearing|\btrump\b|"
    r"\bpac\b|super pac|lobby|election", re.I)

SECTION_PATTERNS = [
    ("Courts & Legal", re.compile(r"lawsuit|\bsues?\b|sued|\bcourts?\b|judge|ruling|copyright|antitrust trial|settlement|appeal", re.I)),
    ("States", re.compile(r"(?<!united )\bstates?\b|statehouse|governor|legislature|attorney general|california|new york|texas|colorado|illinois|florida|utah|newsom|hochul", re.I)),
    ("Global", re.compile(r"\bEU\b|european|brussels|\bchina\b|chinese|beijing|\buk\b|britain|london|\bindia\b|japan|korea|\bg7\b|\bun\b|united nations|davos|summit", re.I)),
    ("Congress", re.compile(r"congress|senat|(?<!white )\bhouse\b|lawmaker|\bbills?\b|hearing|\bndaa\b|\brep\.|\bsen\.|republicans|democrats|cruz|hawley|blackburn|schumer|thune", re.I)),
    ("White House & Agencies", re.compile(r"white house|trump|executive order|\bftc\b|\bfcc\b|\bdoj\b|commerce|pentagon|\bnist\b|export control|agency|sacks|administration|department of", re.I)),
]

OPINION_TITLE = re.compile(
    r"^\s*(opinion|editorial|commentary|column|analysis|op-ed|letters?)\s*[:|\-–—]|"
    r"[|\-–—]\s*(opinion|editorial|commentary)\s*$|\bopinion\s*[|:]", re.I)
OPINION_URL = ("/opinion/", "/opinions/", "/commentary/", "/editorial/", "/op-ed/", "/columnists/")
GENERIC_TITLE = re.compile(r"^\s*(podcast|newsletter|watch|video|live updates?|the latest|morning|daily)\b", re.I)

STOP = set("""about after again against also amid been before being could does from have into just more most
new not over says said than that their them then there these they this those what when where which while will with
would year your ai artificial intelligence""".split())


@dataclass
class Story:
    title: str
    outlet: str
    url: str
    published: Optional[dt.datetime]
    section: str = "Industry & Labs"
    summary: str = ""
    paywalled: bool = False
    coverage: int = 1
    also_covered_by: list = field(default_factory=list)
    score: float = 0.0
    weight: float = 1.0

    @property
    def emoji(self) -> str:
        return dict(SECTIONS).get(self.section, "")


@dataclass
class NewsResult:
    lead: Optional[Story] = None
    stories: list = field(default_factory=list)   # all selected stories except the lead, in section order
    window_hours: int = config.MAX_WINDOW_HOURS
    candidates: int = 0
    feed_status: dict = field(default_factory=dict)


# ─────────────────────────────────────────────
# Fetching
# ─────────────────────────────────────────────

def default_fetch(url: str, timeout: int = 20, retries: int = 2) -> Optional[str]:
    import requests
    headers = {"User-Agent": "Mozilla/5.0 (compatible; AIPolicyBrief/1.0)"}
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r.text
            log.warning("HTTP %s for %s", r.status_code, url)
        except Exception as exc:  # network errors must never stop the issue
            log.warning("fetch failed (%s): %s", exc, url)
        time.sleep(1.5 * (attempt + 1))
    return None


def google_news_url(query: str, domain: str, days: int) -> str:
    q = f"{query} site:{domain} when:{days}d"
    return "https://news.google.com/rss/search?" + urlencode(
        {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _summary(text: str) -> str:
    text = _strip_html(text)
    if len(text) <= config.SUMMARY_CHARS:
        return text
    cut = text[:config.SUMMARY_CHARS].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "…"


def _entry_time(entry) -> Optional[dt.datetime]:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return dt.datetime.fromtimestamp(calendar.timegm(parsed), tz=dt.timezone.utc)


def _parse(feed_text: str):
    import feedparser
    return feedparser.parse(feed_text).entries


def _outlet_info(name: str):
    for n, domain, weight, paywalled in OUTLETS:
        if n == name:
            return domain, weight, paywalled
    return "", 1.0, False


def collect_google(fetch: Callable, now: dt.datetime, window_hours: int, status: dict) -> list[Story]:
    days = max(1, -(-window_hours // 24))
    stories = []
    for name, domain, weight, paywalled in OUTLETS:
        got = 0
        for query in QUERIES:
            text = fetch(google_news_url(query, domain, days))
            if not text:
                continue
            for e in _parse(text):
                title = (e.get("title") or "").strip()
                # Google appends " - Outlet"; strip it, the outlet is known.
                if " - " in title:
                    head, tail = title.rsplit(" - ", 1)
                    if len(tail) <= 40:
                        title = head.strip()
                src = e.get("source") or {}
                href = (src.get("href") or "") if isinstance(src, dict) else ""
                if href and domain not in href:
                    continue  # site: restriction leaked another outlet
                url = e.get("link") or ""
                if not title or not url:
                    continue
                stories.append(Story(title=title, outlet=name, url=url, published=_entry_time(e),
                                     paywalled=paywalled, weight=weight))
                got += 1
        status[f"google:{name}"] = got
    return stories


def collect_direct(fetch: Callable, status: dict) -> list[Story]:
    stories = []
    for name, url in DIRECT_FEEDS:
        text = fetch(url)
        got = 0
        if text:
            _, weight, paywalled = _outlet_info(name)
            for e in _parse(text):
                title = (e.get("title") or "").strip()
                link = e.get("link") or ""
                if not title or not link:
                    continue
                stories.append(Story(title=title, outlet=name, url=link, published=_entry_time(e),
                                     summary=_summary(e.get("summary") or ""),
                                     paywalled=paywalled, weight=weight))
                got += 1
        status[f"direct:{name}"] = got
    return stories


# ─────────────────────────────────────────────
# Filtering, grouping, ranking
# ─────────────────────────────────────────────

def is_relevant(s: Story) -> bool:
    blob = f"{s.title} {s.summary}"
    return bool(AI_RE.search(blob) and POLICY_RE.search(blob))


def is_opinion(s: Story) -> bool:
    if OPINION_TITLE.search(s.title):
        return True
    return any(m in s.url.lower() for m in OPINION_URL)


def classify(s: Story) -> str:
    blob = f"{s.title} {s.summary}"
    for name, pattern in SECTION_PATTERNS:
        if pattern.search(blob):
            return name
    return "Industry & Labs"


def tokens(title: str) -> frozenset:
    words = re.findall(r"[a-z0-9$%]+", title.lower())
    return frozenset(w for w in words if len(w) > 3 and w not in STOP)


def similar(a: frozenset, b: frozenset) -> bool:
    if not a or not b:
        return False
    inter = len(a & b)
    return inter >= 4 or inter / len(a | b) >= 0.5


def cluster(stories: list[Story]) -> list[Story]:
    """Collapse the same story across outlets into one Story whose coverage is
    the number of distinct outlets that ran it."""
    groups: list[dict] = []
    for s in sorted(stories, key=lambda x: x.published or dt.datetime.min.replace(tzinfo=dt.timezone.utc)):
        t = tokens(s.title)
        for g in groups:
            if similar(t, g["tokens"]):
                g["items"].append(s)
                g["tokens"] = g["tokens"] | t
                break
        else:
            groups.append({"tokens": t, "items": [s]})

    out = []
    for g in groups:
        items = g["items"]
        outlets = sorted({i.outlet for i in items})
        # Representative: prefer an item with a real summary, then the
        # heaviest outlet, then the earliest.
        rep = max(items, key=lambda i: (bool(i.summary), i.weight, -(i.published.timestamp() if i.published else 0)))
        rep.coverage = len(outlets)
        rep.also_covered_by = [o for o in outlets if o != rep.outlet]
        rep._tokens = g["tokens"]  # type: ignore[attr-defined]
        out.append(rep)
    return out


def score(s: Story, now: dt.datetime) -> float:
    age_h = (now - s.published).total_seconds() / 3600 if s.published else 96
    recency = 1.5 if age_h <= 24 else 1.0 if age_h <= 48 else 0.5
    return s.coverage * 3.0 + s.weight + recency


# ─────────────────────────────────────────────
# Memory between issues
# ─────────────────────────────────────────────

def load_recent(path: str = RECENT_PATH) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def save_recent(stories: list[Story], today: dt.date, path: str = RECENT_PATH) -> None:
    keep = []
    cutoff = today - dt.timedelta(days=MEMORY_DAYS)
    for entry in load_recent(path):
        try:
            if dt.date.fromisoformat(entry["date"]) >= cutoff:
                keep.append(entry)
        except (KeyError, ValueError):
            continue
    for s in stories:
        keep.append({"date": today.isoformat(), "tokens": sorted(getattr(s, "_tokens", tokens(s.title)))})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(keep, f)


def _seen_recently(s: Story, recent: list) -> bool:
    t = getattr(s, "_tokens", tokens(s.title))
    return any(similar(t, frozenset(e.get("tokens", []))) for e in recent)


# ─────────────────────────────────────────────
# Window
# ─────────────────────────────────────────────

def window_hours(now: dt.datetime, path: str = LAST_ISSUE_PATH) -> int:
    """Hours since the previous issue plus a small buffer, kept between the
    configured min and max (Tuesday to Friday is ~72h, Friday to Tuesday ~96h)."""
    try:
        with open(path, encoding="utf-8") as f:
            last = dt.datetime.fromisoformat(json.load(f)["sent_at"])
        hours = (now - last).total_seconds() / 3600 + config.WINDOW_BUFFER_HOURS
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        hours = config.MAX_WINDOW_HOURS
    return int(min(config.MAX_WINDOW_HOURS, max(config.MIN_WINDOW_HOURS, hours)))


def save_last_issue(now: dt.datetime, path: str = LAST_ISSUE_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"sent_at": now.isoformat()}, f)


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

def get_news(now: dt.datetime = None, fetch: Callable = None, recent: list = None,
             hours: int = None) -> NewsResult:
    now = now or dt.datetime.now(dt.timezone.utc)
    fetch = fetch or default_fetch
    hours = hours or window_hours(now)
    recent = load_recent() if recent is None else recent
    status: dict = {}

    raw = collect_google(fetch, now, hours, status) + collect_direct(fetch, status)
    cutoff = now - dt.timedelta(hours=hours)

    fresh = []
    for s in raw:
        if s.published is None or s.published < cutoff or s.published > now + dt.timedelta(hours=2):
            continue  # undated or outside the window
        if GENERIC_TITLE.search(s.title) or is_opinion(s) or not is_relevant(s):
            continue
        s.section = classify(s)
        fresh.append(s)

    clustered = cluster(fresh)
    clustered = [s for s in clustered if not _seen_recently(s, recent)]
    for s in clustered:
        s.score = score(s, now)
    clustered.sort(key=lambda s: (-s.score, s.title))

    per_section: dict = {}
    chosen = []
    for s in clustered:
        if per_section.get(s.section, 0) >= config.MAX_STORIES_PER_SECTION:
            continue
        chosen.append(s)
        per_section[s.section] = per_section.get(s.section, 0) + 1
        if len(chosen) >= config.MAX_STORIES_TOTAL:
            break

    lead = chosen[0] if chosen else None
    rest = [s for s in chosen[1:]]
    order = {name: i for i, (name, _e) in enumerate(SECTIONS)}
    rest.sort(key=lambda s: (order.get(s.section, 99), -s.score))
    return NewsResult(lead=lead, stories=rest, window_hours=hours,
                      candidates=len(raw), feed_status=status)
