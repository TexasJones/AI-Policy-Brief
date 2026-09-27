"""Offline tests for jobs_scraper.py. Titles below are real postings pulled from
the live Greenhouse / Ashby / Lever APIs on 2026-09-26."""
import sys, os, json, tempfile, urllib.error
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai_policy_brief import jobs_scraper as a

# (title, departments, expected bucket or None)
CASES = [
    # Anthropic (Greenhouse)
    ("Anthropic Fellows Program, The Anthropic Institute (Economics & Policy)", [], "Policy"),
    ("Anthropic Fellows Program, AI Safety & Security", [], None),
    ("Anthropic Fellows Program, ML Systems & Reinforcement Learning", [], None),
    ("Commercial Counsel, GTM", [], "Legal"),
    ("Commercial Counsel, Hardware", [], "Legal"),
    ("Commercial Counsel, SPARC", [], "Legal"),
    ("Commercial Legal Specialist, Technical AI Implementation", [], "Legal"),
    ("Compute & Infrastructure Counsel, Real Estate", [], "Legal"),
    ("Corporate Counsel, M&A", [], "Legal"),
    ("Community Engagement Manager, Data Centers (Texas)", [], "Communications"),
    ("Community Engagement Manager, Data Centres (Australia)", [], "Communications"),
    ("Applied AI Strategist, EMEA", [], "Consulting"),
    ("Data Scientist, Policy", [], None),
    ("Applied AI Architect, Public Sector", [], None),
    ("Applied AI Engineer, Enterprise", [], None),
    ("Customer Success Manager, Public Sector (National Security)", [], None),
    ("Enterprise Account Executive, Federal Civilian Sales", [], None),
    ("Director, Investor Relations", [], None),
    ("Corporate Finance & Strategy, Cash Flow Forecasting", [], None),
    ("Director, US International Tax Planning", [], None),
    ("Copywriter, Developer", [], None),
    ("Customer Trust Specialist", [], None),
    ("Contracts Manager, EMEA", [], None),
    ("Capacity Deployment Lead - Data Center Operations", [], None),
    ("Engineering Manager, Safeguards", [], None),
    ("AV Operations Specialist", [], None),
    ("Internal Communications Manager, Policy", [], "Communications"),
    ("Policy Communications Manager", [], "Communications"),
    ("Product Policy Manager, Product Risk", [], "Policy"),
    ("Public Policy Manager, Europe", [], "Policy"),
    # xAI
    ("Corporate Counsel", [], "Legal"),
    ("Corporate Paralegal", [], "Legal"),
    ("Enterprise Commercial Counsel", [], "Legal"),
    ("Energy & Infrastructure Counsel - Memphis", [], "Legal"),
    ("AI Tutor - Legal & Compliance", [], None),
    # Scale AI
    ("Communications Senior Manager, Corporate & Product (Enterprise)", [], "Communications"),
    ("Lead Counsel, Product and Intellectual Property", [], "Legal"),
    ("National Security Policy, Senior Manager", [], "Policy"),
    ("AI Advisory Consultant", [], "Consulting"),
    ("AI Advisory Principal", [], "Consulting"),
    ("AI Strategy Consultant, Frontier Tech", [], "Consulting"),
    ("Chief of Staff, Public Sector Engineering & Security", [], None),
    # Perplexity / Cohere / ElevenLabs
    ("Commercial Counsel/Senior Counsel", [], "Legal"),
    ("Product Marketing Manager, Partnerships", [], None),
    ("Associate Product Marketing Manager", [], None),
    ("Lead - US Government Affairs & Public Policy", [], "Policy"),
    ("Revenue Enablement Program Manager - EMEA", [], None),
    # Future of Life Institute (Lever)
    ("Communications Director and Staff Director", [], "Communications"),
    ("Expressions of Interest", [], None),
    ("AI Offense-Defense Dynamics Lead Researcher", [], None),
    ("AI Safety Argumentation Platform Research Engineer", [], None),
    ("Principal, Project Development", [], None),
    # OpenAI (Ashby) - real titles from the fetch
    ("Technical Program Manager, Compute Infrastructure", [], None),
    ("Account Director, Large Enterprise - Tokyo", [], None),
    ("Software Engineer, Scaled Abuse", [], None),
    ("Researcher, Robustness & Safety Training", [], None),
    # Brunswick (gated PR firm)
    ("Account Director", [], None),
    ("Associate, Litigation Communications", [], "Communications"),
    ("Director, Corporate Leadership & Transformation Communications", [], "Communications"),
    ("AI Enablement Specialist", [], None),
    # Department fallback
    ("Head of Partnerships", ["Global Affairs"], None),            # partnerships excluded
    ("Director", ["Global Affairs"], "Policy"),                     # generic title, policy dept
    ("Manager", ["Legal"], "Legal"),
    ("Engineer", ["Legal"], None),
]

fails = []
for title, depts, want in CASES:
    got, _ = a.classify(title, depts)
    if got != want:
        fails.append((title, depts, want, got))
print(f"classify: {len(CASES)-len(fails)}/{len(CASES)} pass")
for f in fails:
    print("  FAIL", f)

# AI signal gate
sig = [
    ("Associate, Litigation Communications", "We help clients navigate crises. We use tools daily.", False),
    ("Director, AI Communications", "", True),
    ("Senior Account Manager", "Our technology practice advises AI governance clients on regulation.", True),
    ("Communications Manager", "Join a team using AI tools. AI is changing PR. AI AI AI.", True),   # 4+ bare mentions
    ("Communications Manager", "We occasionally use AI for research.", False),
    ("Public Affairs Director", "Lead our artificial intelligence policy work in Washington.", True),
]
sf = [(t, d, w, a.has_ai_signal(t, d)) for t, d, w in sig if a.has_ai_signal(t, d) != w]
print(f"ai gate: {len(sig)-len(sf)}/{len(sig)} pass", sf if sf else "")

# ---- end-to-end with fake fetchers, incl. a 404 board and an exception ----
today = date.today()
old = str(today - timedelta(days=200))
recent = str(today - timedelta(days=3))

def gh(emp):
    yield dict(raw_id="1", title="Commercial Counsel, Hardware", location="San Francisco, CA",
               apply_url="https://job-boards.greenhouse.io/anthropic/jobs/1", description="<p>Legal &amp; AI.</p>",
               posted=recent + "T10:00:00-04:00", departments=["Legal"])
    yield dict(raw_id="2", title="Software Engineer", location="SF", apply_url="u", description="", posted=recent, departments=[])
    yield dict(raw_id="1", title="Commercial Counsel, Hardware", location="San Francisco, CA",   # duplicate id
               apply_url="dup", description="", posted=recent, departments=[])
    yield dict(raw_id="3", title="Policy Communications Manager", location="Washington, DC",
               apply_url="https://x/3", description="", posted=old, departments=[])
    yield dict(raw_id="", title="Public Policy Manager", location="", apply_url="https://x/4", description="", posted="", departments=[])  # no id -> dropped
def gated(emp):
    yield dict(raw_id="9", title="Director, Corporate Communications", location="London, United Kingdom",
               apply_url="https://x/9", description="Advising AI governance clients.", posted=recent, departments=[])
    yield dict(raw_id="10", title="Director, Corporate Communications", location="New York, NY",
               apply_url="https://x/10", description="Advising AI governance clients.", posted=recent, departments=[])
    yield dict(raw_id="11", title="Director, Corporate Communications", location="New York, NY",
               apply_url="https://x/11", description="Consumer brands only.", posted=recent, departments=[])
def notfound(emp):
    raise urllib.error.HTTPError("u", 404, "nf", {}, None)
def boom(emp):
    raise RuntimeError("network down")
def lever(emp):
    yield dict(raw_id="abc", title="Communications Director and Staff Director", location="Anywhere (Open Globally)",
               apply_url="https://jobs.lever.co/x/abc", description="", posted="1737849600000", departments=[])

emps = [
    dict(source="greenhouse", slug="anthropic", name="Anthropic", kind="ai_native"),
    dict(source="ashby", slug="gone", name="Gone", kind="ai_native"),
    dict(source="lever", slug="futureof-life", name="FLI", kind="ai_native"),
    dict(source="greenhouse", slug="agency", name="Agency", kind="gated", us_only=True),
    dict(source="workable", slug="err", name="Err", kind="ai_native"),
]
fetchers = {"greenhouse": lambda e: gh(e) if e["slug"] == "anthropic" else gated(e),
            "ashby": notfound, "lever": lever, "workable": boom}
jobs = a.collect(emps, fetchers)
titles = [(j["company"], j["title"], j["bucket"], j["region"]) for j in jobs]
for t in titles: print("  ", t)
assert len([j for j in jobs if j["company"] == "Anthropic"]) == 2, "dup/tech/no-id handling"
assert len([j for j in jobs if j["company"] == "Agency"]) == 1, "gate + us_only"
assert [j for j in jobs if j["company"] == "Agency"][0]["office_location"] == "New York, NY"
fli = [j for j in jobs if j["company"] == "FLI"][0]
assert fli["date_posted"] == "2025-01-26", fli["date_posted"]     # epoch ms -> date
assert fli["region"] == "US"   # "Anywhere (Open Globally)" names no country: a US candidate can apply
print("  FLI region:", fli["region"])
assert jobs[0]["date_posted"] >= jobs[-1]["date_posted"], "newest first"
assert "&amp;" not in jobs[0]["description"] and "<p>" not in jobs[0]["description"]

# ---- output files ----
with tempfile.TemporaryDirectory() as d:
    fp, hp, pp = (os.path.join(d, n) for n in ("f.xml", "h.json", "p.json"))
    a.write_feed(jobs, fp)
    import xml.etree.ElementTree as ET
    root = ET.parse(fp).getroot()
    assert root.get("count") == str(len(jobs)) and len(root.findall("job")) == len(jobs)
    assert root.find("job/apply_url").text.startswith("http")
    # history + pulse with a comparison
    hist = {str(today - timedelta(days=7)): {"total": 1, "by_bucket": {"Legal": 1}, "by_company": {"Anthropic": 1},
            "by_region": {"US": 1}, "new_last_7_days": 1}}
    hist = a.save_history(hist, jobs, hp, today)
    pulse = a.build_pulse(hist, pp, today)
    print("  pulse:", json.dumps({k: pulse[k] for k in ("total_jobs", "total_change", "by_bucket", "new_employers")}))
    assert pulse["has_comparison"] and pulse["total_change"] == len(jobs) - 1
    # no comparison case + retention
    hist2 = a.save_history({str(today - timedelta(days=90)): {"total": 0, "by_bucket": {}, "by_company": {}, "by_region": {}, "new_last_7_days": 0}}, jobs, hp, today)
    assert list(hist2) == [str(today)], "old snapshot pruned"
    assert a.build_pulse(hist2, pp, today)["has_comparison"] is False

    # static all-jobs page: every job present, apply links intact, grouped
    # so nothing needing a job board gets silently dropped
    jp = os.path.join(d, "jobs.html")
    a.write_jobs_page(jobs, jp)
    page = open(jp, encoding="utf-8").read()
    assert f"{len(jobs):,} AI-relevant" in page, "job count missing from page"
    for j in jobs:
        assert j["apply_url"] in page, f"apply link missing for {j['title']}"
        assert j["title"] in page

print("ALL END-TO-END CHECKS PASSED" if not fails and not sf else "SOME FAILED")
