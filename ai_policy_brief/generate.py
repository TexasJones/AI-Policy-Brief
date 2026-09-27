"""Build one issue of the Polly AI Brief.

    python -m ai_policy_brief.generate                 # live issue
    python -m ai_policy_brief.generate --sample        # fixture data, no network
    python -m ai_policy_brief.generate --commit-state  # run after a successful send

State (which stories and jobs an issue used, and when it went out) is written
to data/pending_state.json at build time and only applied by --commit-state,
so a failed send never marks stories as already delivered.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, enrich, jobs, news, upcoming as upcoming_mod
from .template import render_brief

ROOT = Path(__file__).resolve().parent.parent
PENDING_PATH = ROOT / "data" / "pending_state.json"


def sample_data(now: dt.datetime):
    """Clearly fictional illustration content for previews. Links go to
    example.com; the template shows a SAMPLE banner when this is used."""
    def st(title, outlet, section, hrs, cov=1, also=(), paywalled=False, summary="", why=""):
        s = news.Story(title=title, outlet=outlet, url="https://example.com/" + section.split()[0].lower(),
                       published=now - dt.timedelta(hours=hrs), section=section, summary=summary,
                       paywalled=paywalled, coverage=cov, also_covered_by=list(also))
        s.why = why
        return s
    lead = st("Senate committee advances federal AI preemption bill after tense hearing", "Politico",
              "Congress", 6, 4, ("Axios", "The Hill", "Reuters"),
              summary="The measure would bar states from enforcing their own AI safety rules for ten years, "
                      "setting up a floor fight before the October recess.",
              why="It would decide whether AI is governed mainly in Washington or in the states.")
    rest = [
        st("Senate hearing on chatbot safeguards for minors draws bipartisan support", "The Hill",
           "Congress", 22, summary="Members of both parties signaled interest in age-verification and disclosure requirements."),
        st("White House weighs new export limits on advanced AI chips", "The Wall Street Journal",
           "White House & Agencies", 20, 2, ("Reuters",), paywalled=True),
        st("California attorney general opens probe into chatbot safeguards for minors", "Axios", "States", 30,
           summary="The inquiry seeks documents from three companies on how their products handle conversations with children.",
           why="State enforcement is moving faster than federal rules."),
        st("Judge rejects bid to dismiss authors' copyright suit against AI developer", "Reuters", "Courts & Legal", 40,
           summary="The ruling lets claims over training data proceed toward discovery."),
        st("EU delays parts of its AI Act rules for general-purpose models", "Politico", "Global", 55, 2, ("AP",),
           summary="Regulators cited unfinished technical standards as the reason for the pause."),
        st("KPMG and a Texas business school launch AI governance research partnership", "KPMG",
           "Research & Partnerships", 30,
           summary="The program will publish quarterly benchmarks on how large employers govern AI use.",
           why="Corporate governance practice is becoming a policy input."),
        st("New survey: most federal agencies lack a dedicated AI policy lead", "Brookings", "Research & Partnerships", 44,
           summary="Fewer than a third of surveyed agencies report a named official responsible for AI policy."),
        st("AI safety auditing startup launches with $40M seed round", "TechCrunch", "Startups & Funding", 18,
           summary="The company plans to sell third-party model evaluations to enterprises facing new state disclosure rules.",
           why="A market for independent AI audits is forming ahead of state compliance deadlines."),
    ]
    j = lambda i, t, c, b, loc, age, reg="US": jobs.Job(f"s{i}", t, c, b, f"https://example.com/job/{i}", loc, reg, age)
    listing = [
        j(1, "Head of Policy Communications", "Anthropic", "Communications", "Washington, DC", 2),
        j(2, "Policy Manager, Frontier Safety", "OpenAI", "Policy", "San Francisco, CA", 3),
        j(3, "Commercial Counsel", "Anthropic", "Legal", "San Francisco, CA", 5),
        j(4, "Responsible AI Consultant", "PwC", "Consulting", "New York, NY", 8),
        j(5, "Director, AI Public Affairs", "Edelman", "Communications", "Washington, DC", 4),
        j(6, "Program Director, Policy", "Future of Life Institute", "Policy", "Remote", 9),
        j(7, "Government Affairs Manager, AI", "Microsoft", "Policy", "Washington, DC", 6),
        j(8, "Regulatory Counsel, AI", "Google", "Legal", "Washington, DC", 12),
    ]
    pulse = jobs.build_pulse(listing, {"s0"}, {"has_comparison": True, "total_change": 3,
                             "bucket_trends": [{"bucket": "Policy", "change": 2}, {"bucket": "Legal", "change": -1}]})
    return pulse, news.NewsResult(lead=lead, stories=rest, window_hours=96)


def sample_deadlines(today):
    return [upcoming_mod.Deadline("Request for Information on Artificial Intelligence Safety Standards",
                                  "Commerce Department, NIST", today + dt.timedelta(days=12),
                                  "https://example.com/rfi", "Proposed rule")]


def build_subject(lead) -> str:
    if lead is None:
        return config.BRAND_NAME
    limit = config.SUBJECT_MAX_CHARS - len(config.SUBJECT_PREFIX)
    title = lead.title
    if len(title) > limit:
        title = title[:limit].rsplit(" ", 1)[0] + "..."
    return config.SUBJECT_PREFIX + title


def publish_to_pages(html_out: str, today: dt.date, preview: bool = False) -> str:
    # The unsubscribe placeholder only works inside the email; on the public
    # web copy it would be a dead link.
    web = html_out.replace('href="{{ unsubscribe }}"', 'href="#"').replace(">Unsubscribe<", ">Unsubscribe (link in the email)<")
    if preview:
        # Preview builds are never sent and never recorded as used, so they
        # must not land on the same dated URL a real send would use -- that
        # would overwrite the page a real issue's "View in browser" link
        # points to. One fixed, always-overwritten file instead; it's never
        # listed in the archive since write_index() only looks at docs/briefs.
        (ROOT / "docs" / "preview.html").write_text(web, encoding="utf-8")
        return f"{config.PAGES_BASE_URL}/preview.html"
    docs = ROOT / "docs" / "briefs"
    docs.mkdir(parents=True, exist_ok=True)
    name = f"{today.isoformat()}.html"
    (docs / name).write_text(web, encoding="utf-8")
    write_index()
    return f"{config.PAGES_BASE_URL}/briefs/{name}"


def write_index() -> None:
    """Regenerate docs/index.html so the Pages site root isn't a 404. Lists
    every published issue, newest first. Safe to call any time; harmless if
    docs/briefs has nothing in it yet."""
    docs = ROOT / "docs"
    briefs_dir = docs / "briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    dates = sorted(
        (p.stem for p in briefs_dir.glob("*.html") if p.stem[:1].isdigit()),
        reverse=True,
    )
    if dates:
        rows = "\n".join(
            f'        <li><a href="briefs/{d}.html">{d}</a></li>' for d in dates
        )
        list_html = f"      <ul>\n{rows}\n      </ul>"
    else:
        list_html = (
            '      <p>No issues have gone out yet. '
            'Here\'s a <a href="mockup.html">sample issue</a> in the meantime.</p>'
        )
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{config.BRAND_NAME} — Archive</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif;
         max-width: 640px; margin: 48px auto; padding: 0 20px; color: #1a1a1a; }}
  h1 {{ font-size: 1.4rem; }}
  ul {{ list-style: none; padding: 0; }}
  li {{ padding: 10px 0; border-bottom: 1px solid #eee; }}
  a {{ color: #1a56db; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
  <h1>{config.BRAND_NAME}</h1>
  <p>AI + policy news and non-technical AI jobs, twice a week.</p>
  <p><a href="jobs.html">See all open AI policy, communications, legal &amp; consulting roles &rarr;</a></p>
{list_html}
</body>
</html>
"""
    (docs / "index.html").write_text(html, encoding="utf-8")


def write_pending(now, today, pulse, result) -> None:
    all_stories = ([result.lead] if result.lead else []) + list(result.stories)
    state = {
        "date": today.isoformat(),
        "sent_at": now.isoformat(),
        "story_tokens": [sorted(getattr(s, "_tokens", news.tokens(s.title))) for s in all_stories],
        "job_ids": [j.job_id for j in jobs.load_jobs()],
    }
    PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    PENDING_PATH.write_text(json.dumps(state), encoding="utf-8")


def commit_state() -> int:
    if not PENDING_PATH.exists():
        print("No pending state to commit.")
        return 0
    state = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
    today = dt.date.fromisoformat(state["date"])
    stubs = []
    for toks in state["story_tokens"]:
        s = news.Story("", "", "", None)
        s._tokens = frozenset(toks)  # type: ignore[attr-defined]
        stubs.append(s)
    news.save_recent(stubs, today)
    news.save_last_issue(dt.datetime.fromisoformat(state["sent_at"]))
    os.makedirs(os.path.dirname(jobs.SEEN_PATH), exist_ok=True)
    with open(jobs.SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(state["job_ids"]), f)
    PENDING_PATH.unlink()
    print("State committed for", state["date"])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--commit-state", action="store_true")
    parser.add_argument("--out", default="ai_policy_brief.html")
    parser.add_argument("--subject-out", default="ai_policy_brief_subject.txt")
    args = parser.parse_args()

    if args.commit_state:
        return commit_state()

    now = dt.datetime.now(ZoneInfo(config.SEND_TIMEZONE))
    today = now.date()
    mailing = os.environ.get("MAILING_ADDRESS", "")
    is_preview = os.environ.get("PREVIEW", "").strip().lower() == "true"

    if args.sample:
        pulse, result = sample_data(now)
        deadlines = sample_deadlines(today)
        view_url = None
    else:
        print("Reading jobs feed...")
        pulse = jobs.get_pulse()
        print("Open roles:", pulse.total, "| new since last issue:", pulse.new_since_last)
        if pulse.total == 0:
            print("ERROR: jobs feed is empty; refusing to build an issue.")
            return 1
        print("Fetching news...")
        result = news.get_news(now=now.astimezone(dt.timezone.utc))
        picked = ([result.lead] if result.lead else []) + result.stories
        print("Enrichment:", enrich.enrich(picked), "| why-it-matters:", enrich.why_it_matters(picked))
        deadlines = upcoming_mod.get_deadlines(today)
        print("Open comment periods:", len(deadlines))
        print(f"Window {result.window_hours}h, {result.candidates} raw items")
        for key, count in result.feed_status.items():
            print("  ", key, count)
        for s in ([result.lead] if result.lead else []) + result.stories:
            print(" -", s.section, "|", s.outlet, "|", s.title)
        # A test send (TEST_TO set) never gets its web copy committed and
        # pushed -- the workflow skips that step on purpose so test issues
        # don't clutter the public archive. Linking to it anyway would just
        # be a 404 in the recipient's inbox, so leave the link out entirely
        # for test sends, same as sample mode does. A preview build does get
        # published, but to a fixed docs/preview.html, never the dated URL a
        # real send would use.
        is_test = bool(os.environ.get("TEST_TO", "").strip())
        if is_test:
            view_url = None
        elif is_preview:
            view_url = f"{config.PAGES_BASE_URL}/preview.html"
        else:
            view_url = f"{config.PAGES_BASE_URL}/briefs/{today.isoformat()}.html"

    html_out = render_brief(pulse, result, today=today, now=now, view_url=view_url, mailing_address=mailing, upcoming=deadlines, sample=args.sample)
    Path(args.out).write_text(html_out, encoding="utf-8")
    print("Wrote", args.out)

    subject = build_subject(result.lead)
    Path(args.subject_out).write_text(subject, encoding="utf-8")
    print("Subject:", subject)

    if not args.sample:
        print("Published to", publish_to_pages(html_out, today, preview=is_preview))
        # Preview never sends and is never recorded (the Record step is
        # skipped for it too), so there's nothing for pending_state.json to
        # do -- writing it would just add a no-op commit every preview run.
        if not is_preview:
            write_pending(now.astimezone(dt.timezone.utc), today, pulse, result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
