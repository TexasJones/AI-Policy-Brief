"""
AI Policy Brief job feed.

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
    # ── General policy think tanks (AI signal required) ──
    {"source": "greenhouse", "slug": "centerforamericanprogress", "name": "Center for American Progress", "kind": "gated"},
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
        \bdata\b\s+(?:engineer|analyst|operations) | analytics | \bresearcher\b |
        research\s+(?:scientist|engineer|lead) | technical\s+(?:program|project|lead) |
        \btutor\b | annotator | \brater\b | data\s+labeling | contributor\s+program |
        account\s+(?:executive|director|manager) | sales | \bbdr\b | business\s+development |
        customer\s+(?:success|support|trust) | partnerships?\s+(?:lead|manager|director) |
        head\s+of\s+partnerships? |
        marketing | brand\s+(?:manager|design) | copywriter | designer |
        accountant | accounting | controller | payroll | \btax\b | treasury |
        finance | financial | investor | capital\s+markets | procurement | sourcing |
        recruit | talent | sourcer | people\s+(?:partner|ops|operations) | \bhr\b |
        executive\s+assistant | administrative | office\s+manager | receptionist |
        facilities | \bav\b | data\s+center\s+(?:operations|architect|controls|electrical|mechanical|supply) |
        expressions?\s+of\s+interest | future\s+opportunit | general\s+application |
        deployment\s+specialist | solutions? | enablement | \bcsm\b
    )""",
    re.IGNORECASE | re.VERBOSE,
)

BUCKET_TITLE_PATTERNS = [
    ("Legal", re.compile(
        r"\b(counsel|attorney|lawyer|legal|paralegal|privacy\s+officer|regulatory\s+affairs)\b",
        re.IGNORECASE)),
    # Communications is checked before Policy so "Policy Communications
    # Manager" lands in Communications, where a comms professional would look.
    ("Communications", re.compile(
        r"(communications?|\bcomms\b|public\s+relations|\bpr\b|media\s+relations|"
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
    r"(artificial\s+intelligence|ai\s+(?:policy|governance|regulation|safety|client|practice|sector)|"
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
    "apac", "ch", "ie",
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
    if US_STATE_RE.search(f" ,{location}") or US_WORD_RE.search(location):
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


RAW_FETCHERS = {
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

def write_feed(jobs: list, path: str = FEED_FILE):
    root = ET.Element("jobs")
    root.set("generated", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    root.set("count", str(len(jobs)))
    for job in jobs:
        el = ET.SubElement(root, "job")
        for k, v in job.items():
            ET.SubElement(el, k).text = str(v)
    xml_str = minidom.parseString(
        '<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(root, encoding="unicode")
    ).toprettyxml(indent="  ")
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml_str)
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


def main():
    jobs = collect()
    log.info("Total AI-relevant non-technical jobs: %d", len(jobs))
    write_feed(jobs)
    history = save_history(load_history(), jobs)
    pulse = build_pulse(history)
    log.info("Pulse: %s", json.dumps(pulse.get("by_bucket", {})))


if __name__ == "__main__":
    main()
