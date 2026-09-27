# Polly AI Brief

Twice-weekly newsletter (Tuesday and Friday, 7 a.m. Eastern): AI + policy news from top outlets, plus non-technical AI jobs (policy, communications, legal, consulting) with direct apply links.

This repo is fully self-contained. It shares no code, data, workflows or secrets with any other newsletter.

## Layout
- `ai_policy_brief/jobs_scraper.py` reads employer job boards (Greenhouse, Ashby, Lever) and writes `data/ai-feed.xml`, history and a weekly pulse.
- `ai_policy_brief/jobs.py` picks featured jobs and the hiring pulse from that feed.
- `ai_policy_brief/news.py` gathers, filters, groups and ranks stories (Axios, Politico, WSJ, Washington Post, NYT, Reuters, AP, The Hill, Tech Policy Press, Lawfare) plus a Research & Partnerships lane (KPMG, Deloitte, PwC, EY, McKinsey, BCG, Accenture, UT Austin, Stanford HAI, MIT, Harvard, CSET, Brookings, RAND, CSIS, Pew). Paywalled outlets: headline and link only.
- `ai_policy_brief/template.py` renders the email. `generate.py` builds an issue. `send.py` sends via Brevo.
- `config.py` holds names, cadence, window and selection limits.

## Workflows
- `refresh-jobs.yml`: daily job scrape, commits `data/`.
- `send-brief.yml`: manual dispatch. Only runs Tuesday/Friday (Eastern) unless `allow_off_day`. Put `test_to` emails to send a test only.
- `watchdog.yml`: Tue/Fri 15:00 UTC; dispatches the send if none ran in the last 6 hours.

## Setup
1. Secrets: `BREVO_API_KEY`, `BREVO_LIST_ID`, `BREVO_SENDER_EMAIL`, `MAILING_ADDRESS`. Optional variable: `SUBSCRIBE_URL`.
2. Settings > Pages: deploy from `main`, `/docs`.
3. External scheduler (e.g. cron-job.org) calls `workflow_dispatch` for `send-brief.yml` at 7:00 America/New_York.
4. Run `refresh-jobs` once, then `send-brief` with `test_to` set to your email.

## Local
    pip install -r requirements.txt
    python -m ai_policy_brief.generate --sample
    python tests/test_news.py && python tests/test_jobs_scraper.py

## Source status (as of the first build)
Checked live from a browser-style fetch: The Hill technology feed and Tech Policy Press feed (both valid RSS); Google careers results (server-rendered HTML); Microsoft's Eightfold search API (returns JSON; field names read defensively); Federal Register API. PwC and Accenture use Workday's standard public search.

Not wired, and why: Axios and Politico feeds (the sites disallow automated fetching, so this repo does not fetch them directly; they are covered through Google News headlines), Meta careers (no public feed), Deloitte, KPMG, McKinsey and BCG careers (custom sites), congressional hearings (needs a congress.gov API key).

Candidates to verify and add later (feeds not yet tested): Brookings, CSET, CDT, The Verge policy, Transformer, Lawfare, NIST news, FTC press releases.

## Design notes
- `docs/mockup.html` is a sample issue with fictional content and a SAMPLE banner.
- `generate --commit-state` runs only after a successful send; a failed send never marks stories as delivered.
- The jobs scraper refuses to overwrite data if a run finds under half the previous job count.
- Optional: set `ANTHROPIC_API_KEY` to add a one-sentence "Why it matters" written only from each story's own description.
