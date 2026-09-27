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

## Source status
Checked live: The Hill technology feed and Tech Policy Press feed (valid RSS); Google careers results (server-rendered HTML); Federal Register API. PwC, Accenture, RAND, Blackstone and Carlyle use Workday's standard public search (host/tenant/site confirmed live for each by loading the real careers page; the POST search API itself, which this scraper actually calls, could not be tested from here — same caveat as the original PwC/Accenture entries). Bessemer Venture Partners and General Catalyst are real, reachable Greenhouse boards (confirmed via a direct API call; Bessemer currently has an "Associate or Senior Associate - AI" listing, General Catalyst currently has zero open roles). Microsoft's Eightfold search previously used a `sort_by=timestamp` parameter that overrode relevance ranking, so a query for "AI policy" returned Microsoft's newest postings company-wide instead of AI-relevant ones — removed; not yet re-verified live after the fix.

Finance / private equity / venture capital, added on request: Blackstone and Carlyle (Workday) target their real Government Relations / Corporate Affairs teams, where AI-specific roles have appeared before (e.g. Blackstone's own "Government Relations - Analyst" posting, and a "Corporate Responsibility - Associate, AI Policy, Global Government Relations" role once posted at BlackRock). Bessemer and General Catalyst (VC) are included too, though most VC roles are investment-team titles that won't match the Policy/Communications/Legal/Consulting buckets at all -- the existing classifier and AI-signal gate apply unchanged, so this mainly adds a chance at a firm's rare general counsel or comms hire, not their deal-team postings.

Looked for but not added: Andreessen Horowitz (a16z) -- no public ATS found, likely a custom/private system. BlackRock -- uses Talentbrew, a platform this scraper doesn't support yet. Goldman Sachs and JPMorgan -- both have posted real "AI policy"/"government affairs" roles in the past, but neither has a confirmed public JSON API; their career sites appear to be custom-built. Sequoia Capital's public job board (jobs.sequoiacap.com) is for its portfolio companies' openings, not Sequoia's own staff, so it doesn't fit here. Palantir -- no ATS identifiable from its careers page; likely a JavaScript-rendered custom site not reachable this way.

Confirmed working correctly (not a bug): the "gated" AI-signal filter on PR-firm and think-tank postings. Checked live against Hill & Knowlton, FleishmanHillard, Ketchum and Golin's actual open roles — most firms simply have few or zero open roles right now, and the ones that exist (e.g. Golin's Singapore comms role, which mentions "AI" once in a mission statement) correctly don't pass the AI-relevance bar. This is the newsletter being selective, not a scraping failure — expect this list to grow and shrink week to week as real openings change.

Removed: Center for American Progress. Its Greenhouse slug 404s live; its real careers page is on its own site (americanprogress.org/about-us/jobs/), which has no public JSON API this scraper found. Would need HTML scraping to add back.

Not wired, and why: Axios and Politico feeds (the sites disallow automated fetching, so this repo does not fetch them directly; they are covered through Google News headlines), Meta careers (no public feed found), Deloitte, KPMG, McKinsey and BCG careers (custom sites, no public API found), Hugging Face, Mistral AI and Anduril (no confirmed Greenhouse/Ashby/Lever board — may use a different ATS or ID), congressional hearings (needs a congress.gov API key).

Candidates to verify and add later: ITIF (uses Freshteam, a smaller ATS not yet supported), Brookings, CSET, CDT, The Verge policy, Transformer, Lawfare, NIST news, FTC press releases.

## Design notes
- `docs/mockup.html` is a sample issue with fictional content and a SAMPLE banner.
- `generate --commit-state` runs only after a successful send; a failed send never marks stories as delivered.
- The jobs scraper refuses to overwrite data if a run finds under half the previous job count.
- Optional: set `ANTHROPIC_API_KEY` to add a one-sentence "Why it matters" written only from each story's own description.
