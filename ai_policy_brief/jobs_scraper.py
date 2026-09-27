"""
Polly AI Brief job feed.

Self-contained: this repo shares no code, data or workflows with any other
newsletter. Files written (all under data/):

    data/ai-feed.xml            direct-apply job listings
    data/ai_job_history.json    one snapshot per day (rolling window)
    data/ai_hiring_pulse.json   week-over-week counts by bucket

Every job carries the employer's own apply URL. The newsletter links straight
to it, so no job board is involved.

Buckets: Policy, Communications, Legal, Consulting. Technical roles are
excluded on purpose (engineering, research science, ML, data science).

Two kinds of employer:
  * AI-native (labs, AI safety orgs): every non-technical role that fits a
    bucket is kept.
  * Gated (PR / public affairs firms, general policy think tanks): a role is
    kept only if it shows an AI signal, so routine PR openings stay out.

Candidate employers found in research but NOT wired in (no supported public
API), for a later pass:
    Center for Democracy & Technology  -> Trakstar (cdt.hire.trakstar.com)
    Americans for Responsible Innovation -> JazzHR (ari.applytojob.com)
    GovAI, CSET, AI Now, Data & Society, Partnership on AI, FAS -> own sites
    Google, Google DeepMind, Meta, Microsoft, Amazon, Apple -> own career sites
"""

import html
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from xml.dom import minidom

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
FEED_FILE = os.path.join(DATA_DIR, "ai-feed.xml")
HISTORY_FILE = os.path.join(DATA_DIR, "ai_job_history.json")
PULSE_FILE = os.path.join(DATA_DIR, "ai_hiring_pulse.json")
HISTORY_RETENTION_DAYS = 35
DESCRIPTION_CHARS = 600
UNDATED_AGE_DAYS = 14

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# ─────────────────────────────────────────────
# Employers
#
# kind: "ai_native" keeps every role that fits a bucket.
#       "gated"     also requires an AI signal (see has_ai_signal).
# us_only: drop postings from non-US offices (global agencies).
# Slugs below were confirmed against the live public APIs on 2026-09-26,
# except where noted.
# ─────────────────────────────────────────────

EMPLOYERS = [
    # ── AI labs and AI safety orgs ──
    {"source": "greenhouse", "slug": "anthropic", "name": "Anthropic", "kind": "ai_native"},
    {"source": "greenhouse", "slug": "xai", "name": "xAI", "kind": "ai_native"},
    {"source": "greenhouse", "slug": "scaleai", "name": "Scale AI", "kind": "ai_native"},
    # OpenAI's Ashby board is confirmed (jobs.ashbyhq.com/openai); its full job
    # count could not be verified from the research environment.
    {"source": "ashby", "slug": "openai", "name": "OpenAI", "kind": "ai_native"},
    {"source": "ashby", "slug": "perplexity", "name": "Perplexity", "kind": "ai_native"},
    {"source": "ashby", "slug": "cohere", "name": "Cohere", "kind": "ai_native"},
    {"source": "ashby", "slug": "elevenlabs", "name": "ElevenLabs", "kind": "ai_native"},
    {"source": "lever", "slug": "aisafety", "name": "Center for AI Safety", "kind": "ai_native"},
    {"source": "lever", "slug": "futureof-life", "name": "Future of Life Institute", "kind": "ai_native"},
    # ── PR / public affairs firms (AI signal required) ──
    {"source": "greenhouse", "slug": "hillandknowlton", "name": "Hill & Knowlton", "kind": "gated"},
    {"source": "greenhouse", "slug": "webershandwick", "name": "Weber Shandwick", "kind": "gated", "us_only": True},
    {"source": "greenhouse", "slug": "fleishmanhillard", "name": "FleishmanHillard", "kind": "gated"},
    {"source": "greenhouse", "slug": "ketchumuscareers", "name": "Ketchum", "kind": "gated"},
    {"source": "greenhouse", "slug": "bursonglobalcareers", "name": "Burson", "kind": "gated", "us_only": True},
    {"source": "greenhouse", "slug": "golin", "name": "Golin", "kind": "gated"},
    {"source": "greenhouse", "slug": "voxglobal", "name": "VOX Global", "kind": "gated"},
    {"source": "greenhouse", "slug": "brunswickgroup", "name": "Brunswick Group", "kind": "gated", "us_only": True},
    # ── Big tech and consultancies with their own career sites (AI signal in the
    # title required: these boards give no description text to check). ──
    # Google: server-rendered results pages; no dates or locations are exposed
    # in the markup this parser reads, so postings are treated as undated.
    {"source": "google", "slug": "google", "name": "Google", "kind": "gated", "undated": True,
     "queries": ["AI policy", "AI public affairs", "AI communications", "AI legal counsel", "AI governance"]},
    # Microsoft: Eightfold search API (GET). Field names are read defensively.
    {"source": "eightfold", "slug": "microsoft", "name": "Microsoft", "kind": "gated",
     "host": "apply.careers.microsoft.com", "domain": "microsoft.com",
     "queries": ["AI policy", "responsible AI", "AI public affairs", "AI legal counsel", "AI communications"]},
    # PwC and Accenture: Workday career sites (public JSON search).
    {"source": "workday", "slug": "pwc", "name": "PwC", "kind": "gated", "us_only": True,
     "host": "pwc.wd3.myworkdayjobs.com", "tenant": "pwc", "site": "US_Experienced_Careers",
     "queries": ["AI strategy", "responsible AI", "AI governance", "AI policy", "generative AI"]},
    {"source": "workday", "slug": "accenture", "name": "Accenture", "kind": "gated", "us_only": True,
     "host": "accenture.wd103.myworkdayjobs.com", "tenant": "accenture", "site": "AccentureCareers",
     "queries": ["AI strategy", "responsible AI", "AI governance", "AI policy", "generative AI"]},
    {"source": "workday", "slug": "rand", "name": "RAND Corporation", "kind": "gated",
     "host": "rand.wd5.myworkdayjobs.com", "tenant": "rand", "site": "External_Career_Site",
     "queries": ["AI policy", "artificial intelligence", "AI governance"]},
    # ── Finance / private equity / venture capital (AI signal required) ──
    # Firms with real Government Relations / Corporate Affairs / Legal teams
    # where an AI-specific role can appear (confirmed real postings exist,
    # e.g. Blackstone's own "Government Relations - Analyst" listing, and
    # a "Corporate Responsibility - Associate, AI Policy, Global Government
    # Relations" role at BlackRock -- though BlackRock itself uses Talentbrew,
    # not a source this scraper supports yet, so it is not wired in).
    {"source": "workday", "slug": "blackstone", "name": "Blackstone", "kind": "gated", "us_only": True,
     "host": "blackstone.wd1.myworkdayjobs.com", "tenant": "blackstone", "site": "Blackstone_Careers",
     "queries": ["AI policy", "artificial intelligence", "responsible AI", "government relations AI"]},
    {"source": "workday", "slug": "carlyle", "name": "Carlyle", "kind": "gated", "us_only": True,
     "host": "carlyle.wd1.myworkdayjobs.com", "tenant": "carlyle", "site": "Carlyle",
     "queries": ["AI policy", "artificial intelligence", "responsible AI", "government relations AI"]},
    # Venture capital: mostly investment-team roles (out of the Policy/
    # Communications/Legal/Consulting scope by title alone), kept anyway --
    # the bucket classifier and AI-signal gate below naturally filter to
    # whatever legal/comms/policy roles do come up.
    {"source": "greenhouse", "slug": "bessemerventurepartners", "name": "Bessemer Venture Partners", "kind": "gated"},
    {"source": "greenhouse", "slug": "generalcatalyst", "name": "General Catalyst", "kind": "gated"},
    # Center for American Progress: not wired in. Its careers page is on
    # its own site (americanprogress.org/about-us/jobs/), not a
    # Greenhouse/Ashby/Lever board (confirmed 404 on the guessed slug) --
    # no public JSON API found for it. Would need HTML scraping.
]

KIND_LABELS = {
    "ai_native": "AI organization",
    "gated": "Public affairs / policy",
}

# ─────────────────────────────────────────────
# Role classification
# ─────────────────────────────────────────────

# Roles that are technical, or outside the four buckets entirely. Checked
# against the TITLE first; a match here always wins.
EXCLUDE_TITLE = re.compile(
    r"""(
        engineer | developer | software | devops | \bsre\b | architect |
        scientist | \bml\b | machine\ learning | reinforcement |
        \bdata\b\s+(?:engineer|analyst|operations) |
        research\s+(?:scientist|engineer|lead) | technical\s+(?:program|project|lead) |
        \btutor\b | annotator | \brater\b | data\s+labeling | contributor\s+program |
        account\s+(?:executive|director|manager) | sales | \bbdr\b | business\s+development |
        customer\s+(?:success|support|trust) | partnerships?\s+(?:lead|manager|director) |
        head\s+of\s+partnerships? |
        marketing | brand\s+(?:manager|design) | copywriter | designer |
        accountant | accounting | controller | payroll | treasury |
        capital\s+markets | procurement | sourcing | content\s+strategist | social\s+media |
        recruit | talent | sourcer | people\s+(?:partner|ops|operations) | \bhr\b |
        executive\s+assistant | office\s+manager | receptionist |
        facilities | \bav\b | data\s+center\s+(?:operations|architect|controls|electrical|mechanical|supply) |
        expressions?\s+of\s+interest | future\s+opportunit | general\s+application |
        deployment\s+specialist | solutions? | enablement | \bcsm\b
    )""",
    re.IGNORECASE | re.VERBOSE,
)

# Soft exclusions: words that usually mean a non-bucket role, but not when the
# title is clearly a policy or legal role ("Tax Policy Advisor", "Senior Policy
# Researcher", "Administrative Law Counsel", "Financial Services Policy Counsel").
EXCLUDE_TITLE_SOFT = re.compile(
    r"analytics|\bresearcher\b|\btax\b|financ|investor|administrative", re.IGNORECASE)
SOFT_OVERRIDE = re.compile(
    r"\b(polic(?:y|ies)|counsel|attorney|legal|regulatory|government\s+affairs|public\s+affairs)\b",
    re.IGNORECASE)

BUCKET_TITLE_PATTERNS = [
    ("Legal", re.compile(
        r"\b(counsel|attorney|lawyer|legal|paralegal|privacy\s+officer|regulatory\s+affairs)\b",
        re.IGNORECASE)),
    # Communications is checked before Policy so "Policy Communications
    # Manager" lands in Communications, where a comms professional would look.
    ("Communications", re.compile(
        r"(\bcommunications?\b|\bcomms\b|public\s+relations|\bpr\b|media\s+relations|"
        r"\bpress\b|spokes|speechwriter|external\s+affairs|community\s+engagement|"
        r"stakeholder\s+engagement|editorial|storytelling)",
        re.IGNORECASE)),
    ("Policy", re.compile(
        r"(polic(?:y|ies)|government\s+(?:affairs|relations)|public\s+affairs|"
        r"legislative|regulatory|governance|geopolitic|national\s+security|"
        r"economist|economics|international\s+affairs|trust\s*&\s*safety\s+policy)",
        re.IGNORECASE)),
    ("Consulting", re.compile(
        r"(consultant|advisory|management\s+consulting|strategist|"
        r"strategy\s+(?:lead|manager|director|principal)|transformation\s+(?:lead|director|manager))",
        re.IGNORECASE)),
]

# Department / team names that place an otherwise-unmatched title in a bucket.
BUCKET_DEPARTMENT_PATTERNS = [
    ("Legal", re.compile(r"\blegal\b", re.IGNORECASE)),
    ("Communications", re.compile(r"communications?|public\s+relations|\bcomms\b", re.IGNORECASE)),
    ("Policy", re.compile(r"polic(?:y|ies)|government\s+affairs|global\s+affairs|public\s+affairs|public\s+sector\s+policy", re.IGNORECASE)),
]

# Department fallback is only trusted for titles that look like an actual role
# for that function, not a generic word like "Manager" on its own.
DEPARTMENT_FALLBACK_TITLE = re.compile(
    r"(manager|director|lead|head|counsel|specialist|associate|advisor|analyst|principal|"
    r"strategist|officer|partner|fellow|editor|writer|producer)",
    re.IGNORECASE,
)

AI_TITLE_SIGNAL = re.compile(
    r"(\bai\b|artificial\s+intelligence|generative|\bllm\b|machine\s+learning|"
    r"emerging\s+tech|technology\s+(?:policy|practice|sector)|tech\s+(?:policy|practice|sector))",
    re.IGNORECASE,
)
AI_DESC_STRONG = re.compile(
    r"\b(artificial\s+intelligence|ai\s+(?:policy|governance|regulation|safety|client|practice|sector)|"
    r"responsible\s+ai|generative\s+ai|frontier\s+(?:ai|model))",
    re.IGNORECASE,
)
AI_WORD = re.compile(r"\bAI\b")

EVERGREEN_TITLE = re.compile(
    r"(expressions?\s+of\s+interest|talent\s+(?:community|pool|network)|job\s+bank|future\s+opportunit|general\s+application)",
    re.IGNORECASE,
)

NON_US_SIGNALS = [
    "germany", "deutschland", "canada", "can", "united kingdom", "uk", "france", "spain",
    "italy", "netherlands", "belgium", "switzerland", "sweden", "poland", "ireland",
    "mexico", "brazil", "argentina", "colombia", "singapore", "hong kong", "china",
    "japan", "tokyo", "india", "australia", "uae", "dubai", "south africa", "korea",
    "south korea", "london", "brussels", "berlin", "munich", "paris", "dublin",
    "zürich", "zurich", "mumbai", "bangalore", "sydney", "toronto", "seoul", "milan",
    "ontario", "alberta", "british columbia", "international", "europe", "emea",
    "apac", "ch", "ie", "frankfurt", "hamburg", "vancouver", "montreal", "ottawa", "bengaluru",
    "delhi", "hyderabad", "pune", "gurgaon", "chennai", "tel aviv", "haifa", "israel",
]

# US signals: explicit country name, a two-letter US state/DC code after a
# comma (case-sensitive, so "London, UK" and "Zürich, CH" do not match), or a
# major US city. Non-US signals are only consulted when none of these appear
# anywhere in the location string.
_US_STATE_CODES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|"
    "MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY"
)
US_STATE_RE = re.compile(rf"(?:,|;|\|)\s*(?:{_US_STATE_CODES})\b")
US_WORD_RE = re.compile(
    r"(united\s+states|\bu\.?s\.?a?\b|washington,?\s*d\.?c|new\s+york|san\s+francisco|"
    r"seattle|austin|boston|chicago|los\s+angeles|palo\s+alto|memphis|atlanta|denver|"
    r"remote-friendly,?\s*us\b)",
    re.IGNORECASE,
)


def clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def truncate(text: str, max_chars: int = DESCRIPTION_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "…"


def is_us_location(location: str) -> bool:
    """
    True if the location string names any US office, or names no country at
    all (e.g. "Remote"). Multi-office strings like "London, UK | San
    Francisco, CA" count as US, since a US-based candidate can apply.
    False only when every signal in the string is non-US.
    """
    if not location:
        return True  # unknown -> keep
    # Judge each office separately: "Berlin, DE" carries a code that is also a
    # US state (Delaware), and "Toronto, CA" one that is also California.
    for segment in re.split(r"[;|]", location):
        low_seg = segment.lower()
        foreign = any(re.search(rf"\b{re.escape(s)}\b", low_seg) for s in NON_US_SIGNALS)
        if US_WORD_RE.search(segment):
            return True
        if US_STATE_RE.search(f" ,{segment}") and not foreign:
            return True
    low = location.lower()
    if any(re.search(rf"\b{re.escape(s)}\b", low) for s in NON_US_SIGNALS):
        return False
    return True  # no country named anywhere -> keep


def region_of(location: str) -> str:
    """
    "US" means a US-based candidate can apply: a US office, or a remote /
    unspecified location that names no country. "International" means every
    location named is outside the US.
    """
    return "US" if is_us_location(location) else "International"


def has_ai_signal(title: str, description: str) -> bool:
    if AI_TITLE_SIGNAL.search(title):
        return True
    if AI_DESC_STRONG.search(description):
        return True
    # Boilerplate mentions ("we use AI tools") are common in agency postings, so
    # a bare "AI" needs to show up repeatedly to count.
    return len(AI_WORD.findall(description)) >= 4


def classify(title: str, departments=None):
    """
    Returns (bucket, matched_by) or (None, reason).
    Title is the primary signal; department is a fallback for generic titles.
    """
    if EXCLUDE_TITLE.search(title):
        return None, "excluded title"
    if EXCLUDE_TITLE_SOFT.search(title) and not SOFT_OVERRIDE.search(title):
        return None, "excluded title"
    if EVERGREEN_TITLE.search(title):
        return None, "evergreen"
    for bucket, pattern in BUCKET_TITLE_PATTERNS:
        if pattern.search(title):
            return bucket, "title"
    if departments and DEPARTMENT_FALLBACK_TITLE.search(title):
        for bucket, pattern in BUCKET_DEPARTMENT_PATTERNS:
            if any(pattern.search(d) for d in departments):
                return bucket, "department"
    return None, "no bucket"


# ─────────────────────────────────────────────
# Fetching
# ─────────────────────────────────────────────

def fetch_url(url: str, timeout: int = 20, retries: int = 3) -> str:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404 or attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def normalize_posted(value) -> str:
    """Greenhouse/Ashby give ISO strings, Lever gives epoch milliseconds."""
    if not value:
        return str(date.today())
    s = str(value)
    if re.match(r"^\d{13}$", s):
        return datetime.fromtimestamp(int(s) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    return s[:10]


def raw_jobs_greenhouse(employer: dict):
    url = f"https://boards-api.greenhouse.io/v1/boards/{employer['slug']}/jobs?content=true"
    data = json.loads(fetch_url(url))
    for j in data.get("jobs", []):
        loc = j.get("location")
        yield {
            "raw_id": str(j.get("id", "")),
            "title": j.get("title", ""),
            "location": loc.get("name", "") if isinstance(loc, dict) else "",
            "apply_url": j.get("absolute_url") or f"https://job-boards.greenhouse.io/{employer['slug']}/jobs/{j.get('id', '')}",
            "description": j.get("content", "") or "",
            # Greenhouse's public API exposes updated_at, not the original
            # posting date; it is the closest proxy available.
            "posted": j.get("updated_at", ""),
            "departments": [d.get("name", "") for d in (j.get("departments") or []) if isinstance(d, dict)],
        }


def raw_jobs_ashby(employer: dict):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{employer['slug']}"
    data = json.loads(fetch_url(url))
    for j in data.get("jobs", []):
        job_id = str(j.get("id", ""))
        departments = [x for x in (j.get("department"), j.get("team")) if x]
        yield {
            "raw_id": job_id,
            "title": j.get("title", ""),
            "location": j.get("location") or j.get("locationName") or "",
            "apply_url": j.get("jobUrl") or j.get("applyUrl") or f"https://jobs.ashbyhq.com/{employer['slug']}/{job_id}",
            "description": j.get("descriptionHtml", "") or j.get("descriptionPlain", "") or "",
            "posted": j.get("publishedAt", ""),
            "departments": departments,
        }


def raw_jobs_lever(employer: dict):
    url = f"https://api.lever.co/v0/postings/{employer['slug']}?mode=json"
    for j in json.loads(fetch_url(url)):
        cats = j.get("categories") or {}
        yield {
            "raw_id": j.get("id", ""),
            "title": j.get("text", ""),
            "location": cats.get("location", "") or "",
            "apply_url": j.get("hostedUrl") or j.get("applyUrl", ""),
            "description": j.get("descriptionPlain", "") or j.get("description", "") or "",
            "posted": str(j.get("createdAt", "")),
            "departments": [x for x in (cats.get("team"), cats.get("department")) if x],
        }


def post_json(url: str, payload: dict, timeout: int = 20, retries: int = 3):
    body = json.dumps(payload).encode("utf-8")
    headers = dict(HEADERS, **{"Content-Type": "application/json"})
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            if e.code == 404 or attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def _workday_posted(text: str) -> str:
    """Workday gives 'Posted Today', 'Posted 3 Days Ago', 'Posted 30+ Days Ago'."""
    text = (text or "").lower()
    if "yesterday" in text:
        return str(date.today() - timedelta(days=1))
    m = re.search(r"(\d+)\+?\s+day", text)
    if m:
        return str(date.today() - timedelta(days=int(m.group(1))))
    return str(date.today())


WORKDAY_PAGE_SIZE = 20
WORKDAY_MAX_PAGES = 10  # hard cap so a bad response can't loop forever

# Workday's own posting id, e.g. "...Manager_R123" -> "R123". Preferred over
# bulletFields, whose contents are tenant-configured and not guaranteed to be
# a stable unique id -- two different postings colliding on it would silently
# drop one of them (collect() dedupes by job_id).
_WORKDAY_REQ_ID = re.compile(r"_((?:R|REQ)[-\w]*\d[-\w]*)$", re.IGNORECASE)


def _workday_job_id(path: str, bullets: list) -> str:
    m = _WORKDAY_REQ_ID.search(path or "")
    if m:
        return m.group(1)
    if bullets:
        return str(bullets[0])
    return path


def raw_jobs_workday(employer: dict):
    base = f"https://{employer['host']}"
    api = f"{base}/wday/cxs/{employer['tenant']}/{employer['site']}/jobs"
    for query in employer["queries"]:
        offset, total = 0, None
        for _page in range(WORKDAY_MAX_PAGES):
            data = post_json(api, {"appliedFacets": {}, "limit": WORKDAY_PAGE_SIZE, "offset": offset,
                                   "searchText": query})
            postings = data.get("jobPostings", [])
            if total is None:
                total = data.get("total")
            for j in postings:
                path = j.get("externalPath", "")
                yield {
                    "raw_id": _workday_job_id(path, j.get("bulletFields") or []),
                    "title": j.get("title", ""),
                    "location": j.get("locationsText", "") or "",
                    "apply_url": f"{base}/en-US/{employer['site']}{path}" if path else "",
                    "description": "",
                    "posted": _workday_posted(j.get("postedOn", "")),
                    "departments": [],
                }
            offset += WORKDAY_PAGE_SIZE
            if len(postings) < WORKDAY_PAGE_SIZE or (isinstance(total, int) and offset >= total):
                break
        time.sleep(0.3)


EIGHTFOLD_PAGE_SIZE = 10
EIGHTFOLD_MAX_PAGES = 10


def raw_jobs_eightfold(employer: dict):
    base = f"https://{employer['host']}"
    for query in employer["queries"]:
        start, total = 0, None
        for _page in range(EIGHTFOLD_MAX_PAGES):
            qs = urllib.parse.urlencode({"domain": employer["domain"], "query": query, "start": start})
            data = json.loads(fetch_url(f"{base}/api/pcsx/search?{qs}"))
            payload = data.get("data") or {}
            positions = payload.get("positions", [])
            if total is None:
                total = payload.get("count")
            for j in positions:
                pid = str(j.get("id", ""))
                locs = j.get("locations") or j.get("standardizedLocations") or j.get("location") or ""
                if isinstance(locs, list):
                    locs = "; ".join(str(x) for x in locs[:2])
                ts = j.get("postedTs") or j.get("creationTs") or j.get("postedDate") or ""
                posted = ""
                if isinstance(ts, (int, float)) or str(ts).isdigit():
                    posted = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
                yield {
                    "raw_id": pid,
                    "title": j.get("name") or j.get("title") or "",
                    "location": str(locs),
                    "apply_url": f"{base}{j.get('positionUrl') or '/careers/job/' + pid}" if pid else "",
                    "description": "",
                    "posted": posted,
                    "departments": [],
                }
            start += len(positions) or EIGHTFOLD_PAGE_SIZE
            if len(positions) < EIGHTFOLD_PAGE_SIZE or (isinstance(total, int) and start >= total):
                break
        time.sleep(0.3)


GOOGLE_JOB_LINK = re.compile(
    r'href="(?:https://www\.google\.com)?(/about/careers/applications/jobs/results/(\d+)-([a-z0-9\-]+))[^"]*"')
_UPPER_WORDS = {"ai": "AI", "erm": "ERM", "ux": "UX", "us": "US", "emea": "EMEA", "gtm": "GTM",
                "llm": "LLM", "uk": "UK", "eu": "EU", "cx": "CX", "hr": "HR"}
_SMALL_WORDS = {"and", "of", "for", "the", "to", "in", "at", "on"}


def _title_from_slug(slug: str) -> str:
    words = slug.split("-")
    out = []
    for i, w in enumerate(words):
        if w in _UPPER_WORDS:
            out.append(_UPPER_WORDS[w])
        elif w in _SMALL_WORDS and i:
            out.append(w)
        else:
            out.append(w.capitalize())
    return " ".join(out)


GOOGLE_PAGE_SIZE = 20   # Google's results page shows 20 per page
GOOGLE_MAX_PAGES = 10


def raw_jobs_google(employer: dict):
    seen = set()
    for query in employer["queries"]:
        for page_num in range(GOOGLE_MAX_PAGES):
            qs = urllib.parse.urlencode({"q": query, "page": page_num + 1})
            page = fetch_url(f"https://www.google.com/about/careers/applications/jobs/results?{qs}")
            found_this_page = 0
            for m in GOOGLE_JOB_LINK.finditer(page):
                path, job_id, slug = m.groups()
                found_this_page += 1
                if job_id in seen:
                    continue
                seen.add(job_id)
                yield {
                    "raw_id": job_id,
                    "title": _title_from_slug(slug),
                    "location": "",
                    "apply_url": f"https://www.google.com{path}",
                    "description": "",
                    "posted": "",
                    "departments": [],
                }
            time.sleep(0.5)
            if found_this_page == 0:
                break


RAW_FETCHERS = {
    "workday": raw_jobs_workday,
    "eightfold": raw_jobs_eightfold,
    "google": raw_jobs_google,
    "greenhouse": raw_jobs_greenhouse,
    "ashby": raw_jobs_ashby,
    "lever": raw_jobs_lever,
}


def build_job(employer: dict, raw: dict):
    """Apply all filters. Returns a job dict, or None if the role is out."""
    title = html.unescape((raw.get("title") or "").strip())
    if not title or not raw.get("raw_id") or not raw.get("apply_url"):
        return None

    bucket, why = classify(title, raw.get("departments"))
    if not bucket:
        return None

    location = raw.get("location", "")
    if employer.get("us_only") and not is_us_location(location):
        return None

    description = truncate(clean(raw.get("description", "")))
    full_text = clean(raw.get("description", ""))
    if employer["kind"] == "gated" and not has_ai_signal(title, full_text):
        return None

    if employer.get("undated") or not raw.get("posted"):
        # No posting date available: use a neutral age so these are not
        # ranked as brand new just because their date is unknown.
        posted = str(date.today() - timedelta(days=UNDATED_AGE_DAYS))
    else:
        posted = normalize_posted(raw.get("posted"))
    try:
        age_days = (date.today() - datetime.strptime(posted, "%Y-%m-%d").date()).days
    except ValueError:
        posted, age_days = str(date.today()), 0

    return {
        "job_id": f"{employer['source']}-{employer['slug']}-{raw['raw_id']}",
        "title": title,
        "company": employer["name"],
        "employer_type": KIND_LABELS[employer["kind"]],
        "bucket": bucket,
        "apply_url": raw["apply_url"],
        "office_location": location,
        "region": region_of(location),
        "date_posted": posted,
        "age_days": max(age_days, 0),
        "source": employer["source"],
        "description": description,
    }


def collect(employers=None, fetchers=None) -> list:
    employers = EMPLOYERS if employers is None else employers
    fetchers = RAW_FETCHERS if fetchers is None else fetchers
    jobs, seen = [], set()

    for employer in employers:
        label = f"{employer['source']}/{employer['slug']}"
        try:
            kept = 0
            for raw in fetchers[employer["source"]](employer):
                job = build_job(employer, raw)
                if job and job["job_id"] not in seen:
                    seen.add(job["job_id"])
                    jobs.append(job)
                    kept += 1
            log.info("%s: %d kept", label, kept)
            time.sleep(0.3)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                log.warning("%s: board not found (404) — remove from EMPLOYERS", label)
            else:
                log.warning("%s: HTTP %s", label, e.code)
        except Exception as e:
            log.warning("%s: %s", label, e)

    # Newest first, so the newsletter can take the top of each bucket.
    jobs.sort(key=lambda j: (j["date_posted"], j["job_id"]), reverse=True)
    return jobs


# ─────────────────────────────────────────────
# Output
# ─────────────────────────────────────────────

_XML_BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def write_feed(jobs: list, path: str = FEED_FILE):
    root = ET.Element("jobs")
    root.set("generated", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    root.set("count", str(len(jobs)))
    for job in jobs:
        el = ET.SubElement(root, "job")
        for k, v in job.items():
            ET.SubElement(el, k).text = _XML_BAD.sub("", str(v))
    xml_str = minidom.parseString(
        '<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(root, encoding="unicode")
    ).toprettyxml(indent="  ")
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml_str)
    log.info("Written -> %s (%d jobs)", path, len(jobs))


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOBS_PAGE_PATH = os.path.join(ROOT_DIR, "docs", "jobs.html")

# Kept in sync with template.py's BUCKET_COLORS by hand -- jobs_scraper.py
# stays free of any import on template.py so the scraper can run standalone.
_BUCKET_COLORS = {
    "Policy": "#3357A8",
    "Communications": "#A8324A",
    "Legal": "#6B3FA0",
    "Consulting": "#9F620E",
}


def write_jobs_page(jobs: list, path: str = JOBS_PAGE_PATH) -> None:
    """Static, no-JS listing of every open role currently in the feed --
    the newsletter can only feature a handful per issue, and this is where
    the rest live. Grouped by bucket, newest first (jobs is already sorted
    that way by collect()); every title links straight to the employer's
    own application page, exactly like the newsletter does.

    Visual language (colors, card, top accent bar, footer) is kept in sync
    by hand with template.py's -- this module stays free of any import on
    template.py so the scraper can run standalone."""
    INK, MUTED, HAIRLINE, BG, CARD = "#14202B", "#475569", "#E3E8EC", "#F2F5F7", "#FFFFFF"
    HEADLINE_FONT = "Georgia, 'Times New Roman', serif"
    BODY_FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"

    buckets = ["Policy", "Communications", "Legal", "Consulting"]
    by_bucket: dict = {b: [] for b in buckets}
    for j in jobs:
        if j["bucket"] in by_bucket:
            by_bucket[j["bucket"]].append(j)

    jump_links = " &nbsp;&middot;&nbsp; ".join(
        f'<a href="#{b.lower()}" style="color:{_BUCKET_COLORS.get(b, "#0C7E87")};font-weight:600;text-decoration:none;">'
        f'{html.escape(b)} <span style="color:{MUTED};font-weight:400;">({len(by_bucket[b])})</span></a>'
        for b in buckets if by_bucket[b]
    )

    sections = []
    for b in buckets:
        rows = by_bucket[b]
        if not rows:
            continue
        color = _BUCKET_COLORS.get(b, "#0C7E87")
        items = "".join(
            f'<li style="padding:14px 0;border-bottom:1px solid {HAIRLINE};">'
            f'<a href="{html.escape(j["apply_url"])}" target="_blank" rel="noopener noreferrer" '
            f'style="color:{INK};text-decoration:none;font-weight:700;font-size:15px;">{html.escape(j["title"])}</a>'
            + (f' <span style="background-color:#ECFDF5;color:#047857;font-size:10px;font-weight:800;'
               f'letter-spacing:0.4px;text-transform:uppercase;padding:2px 6px;border-radius:4px;'
               f'vertical-align:middle;">New</span>' if j.get("age_days", 99) <= 7 else "")
            + f'<div style="font-size:13px;color:{MUTED};margin-top:3px;">{html.escape(j["company"])}'
            + (f' &middot; {html.escape(j["office_location"])}' if j.get("office_location") else "")
            + '</div></li>'
            for j in rows
        )
        sections.append(
            f'<h2 id="{b.lower()}" style="font-size:15px;font-weight:800;color:{color};'
            f'text-transform:uppercase;letter-spacing:0.4px;margin:36px 0 4px;'
            f'border-left:4px solid {color};padding-left:10px;">{html.escape(b)} '
            f'<span style="color:{MUTED};font-weight:400;text-transform:none;letter-spacing:0;font-size:13px;">'
            f'({len(rows)})</span></h2>'
            f'<ul style="list-style:none;padding:0;margin:0 0 0 14px;">{items}</ul>'
        )

    generated = datetime.now(timezone.utc).strftime("%B %d, %Y")
    year = datetime.now(timezone.utc).year
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Polly AI Brief — All Open Roles</title>
<style>
  body {{ font-family: {BODY_FONT}; margin: 0; padding: 32px 16px; color: {INK}; background: {BG}; }}
  a:hover {{ text-decoration: underline !important; }}
  .apb-card {{ max-width: 640px; margin: 0 auto; background: {CARD}; border-radius: 14px;
               overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.06); }}
  .apb-pad {{ padding: 32px 36px 36px; }}
  li a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
  <div class="apb-card">
    <div style="height:6px;background:linear-gradient(90deg,#3357A8,#A8324A,#9F620E,#6B3FA0,#15803D,#0C7E87,#BE185D,#C2410C);"></div>
    <div class="apb-pad">
      <p style="margin:0 0 14px;"><a href="index.html" style="color:{MUTED};font-size:13px;text-decoration:none;">&larr; Polly AI Brief</a></p>
      <div style="font-size:24px;font-weight:900;color:{INK};letter-spacing:-0.5px;font-family:{HEADLINE_FONT};">All open roles</div>
      <p style="color:{MUTED};font-size:13px;margin:10px 0 2px;">{len(jobs):,} AI-relevant policy, communications, legal and consulting roles &middot; updated {generated}</p>
      <p style="color:{MUTED};font-size:12px;margin:0 0 18px;">Every title links straight to the employer's own application page.</p>
      <div style="font-size:13px;padding:12px 14px;background:{BG};border-radius:8px;">{jump_links}</div>
      {''.join(sections)}
      <div style="border-top:1px solid {HAIRLINE};margin-top:28px;padding-top:16px;text-align:center;">
        <div style="font-size:11px;color:{MUTED};">Polly AI Brief &middot; AI + policy news and non-technical AI jobs, twice a week.</div>
        <div style="font-size:11px;color:{MUTED};margin-top:6px;">&copy; {year} Polly AI Brief. All rights reserved.</div>
      </div>
    </div>
  </div>
</body>
</html>
"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    log.info("Written -> %s (%d jobs)", path, len(jobs))


def snapshot(jobs: list) -> dict:
    by_bucket, by_company, by_region = {}, {}, {}
    for j in jobs:
        by_bucket[j["bucket"]] = by_bucket.get(j["bucket"], 0) + 1
        by_company[j["company"]] = by_company.get(j["company"], 0) + 1
        by_region[j["region"]] = by_region.get(j["region"], 0) + 1
    return {
        "total": len(jobs),
        "by_bucket": by_bucket,
        "by_company": by_company,
        "by_region": by_region,
        "new_last_7_days": sum(1 for j in jobs if j["age_days"] <= 7),
    }


def load_history(path: str = HISTORY_FILE) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_history(history: dict, jobs: list, path: str = HISTORY_FILE, today: date = None) -> dict:
    today = today or date.today()
    history[str(today)] = snapshot(jobs)
    cutoff = today - timedelta(days=HISTORY_RETENTION_DAYS)
    history = {
        d: s for d, s in history.items()
        if datetime.strptime(d, "%Y-%m-%d").date() >= cutoff
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)
    return history


def build_pulse(history: dict, path: str = PULSE_FILE, today: date = None) -> dict:
    today = today or date.today()
    today_snap = history[str(today)]
    prior = history.get(str(today - timedelta(days=7)))
    pulse = {
        "date": str(today),
        "total_jobs": today_snap["total"],
        "new_last_7_days": today_snap["new_last_7_days"],
        "by_bucket": today_snap["by_bucket"],
        "has_comparison": prior is not None,
    }
    if prior:
        pulse["total_change"] = today_snap["total"] - prior["total"]
        buckets = set(today_snap["by_bucket"]) | set(prior["by_bucket"])
        pulse["bucket_trends"] = sorted(
            (
                {
                    "bucket": b,
                    "current": today_snap["by_bucket"].get(b, 0),
                    "prior": prior["by_bucket"].get(b, 0),
                    "change": today_snap["by_bucket"].get(b, 0) - prior["by_bucket"].get(b, 0),
                }
                for b in buckets
            ),
            key=lambda t: t["change"],
            reverse=True,
        )
        pulse["new_employers"] = sorted(set(today_snap["by_company"]) - set(prior["by_company"]))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pulse, f, indent=2)
    return pulse


def previous_total(path: str = HISTORY_FILE) -> int:
    history = load_history(path)
    return history[max(history)]["total"] if history else 0


def main():
    jobs = collect()
    log.info("Total AI-relevant non-technical jobs: %d", len(jobs))
    # An outage on one big board must not overwrite good data with a partial
    # feed: keep the last committed files and fail the run visibly instead.
    prev = previous_total()
    if not jobs or (prev >= 20 and len(jobs) < prev * 0.5):
        log.error("Only %d jobs found (previous %d); keeping existing data files.", len(jobs), prev)
        raise SystemExit(1)
    write_feed(jobs)
    write_jobs_page(jobs)
    history = save_history(load_history(), jobs)
    pulse = build_pulse(history)
    log.info("Pulse: %s", json.dumps(pulse.get("by_bucket", {})))


if __name__ == "__main__":
    main()
