import datetime as dt, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai_policy_brief import upcoming, enrich, news, jobs

TODAY = dt.date(2026, 9, 29)


def main():
    payload = {"results": [
        {"title": "Request for Information on AI Safety Standards", "abstract": "", "comments_close_on": "2026-10-15",
         "html_url": "https://fr/1", "agency_names": ["Commerce Department", "NIST"], "type": "Proposed Rule"},
        {"title": "Medicare Part D pharmacy rule", "abstract": "Mentions artificial intelligence once far below.",
         "comments_close_on": "2026-10-10", "html_url": "https://fr/2", "agency_names": ["HHS"], "type": "Proposed Rule"},
        {"title": "AI procurement guidance", "comments_close_on": "2026-09-01", "html_url": "https://fr/3", "agency_names": [], "type": "Notice"},
        {"title": "AI something with no deadline", "comments_close_on": None, "html_url": "https://fr/4", "agency_names": [], "type": "Notice"},
        {"title": "AI export rule", "comments_close_on": "2027-06-01", "html_url": "https://fr/5", "agency_names": [], "type": "Notice"},
        {"title": "Artificial Intelligence in health care notice", "comments_close_on": "2026-10-02", "html_url": "https://fr/6",
         "agency_names": ["FDA"], "type": "Notice"}]}
    got = upcoming.parse_deadlines(json.dumps(payload), TODAY)
    assert [d.url for d in got] == ["https://fr/6", "https://fr/1"], [d.url for d in got]
    assert upcoming.parse_deadlines("not json", TODAY) == []
    assert upcoming.get_deadlines(TODAY, fetch=lambda u: None) == []
    assert "conditions%5Bterm%5D=artificial+intelligence" in upcoming.api_url(TODAY)

    page = '<head><meta property="og:description" content="Lawmakers &amp; regulators clash over a federal AI bill this week."></head>'
    assert enrich.extract_description(page) == "Lawmakers & regulators clash over a federal AI bill this week."
    assert enrich.extract_description('<meta content="Reversed attribute order description text here that is long" name="description">')
    assert enrich.extract_description("<html></html>") == ""

    class R:
        def __init__(s, url, text, code=200): s.url, s.text, s.status_code = url, text, code
    class Sess:
        def get(s, url, **k):
            if "blocked" in url: return R("https://news.google.com/consent", "x")
            return R("https://www.axios.com/2026/09/28/story", page)
    enrich.allowed = lambda url: True
    a = news.Story("t", "Axios", "https://news.google.com/rss/articles/abc", None)
    b = news.Story("t", "WSJ", "https://news.google.com/rss/articles/def", None, paywalled=True)
    c = news.Story("t", "Axios", "https://blocked", None)
    stats = enrich.enrich([a, b, c], session=Sess())
    assert a.summary and a.url.startswith("https://www.axios.com/"), (a.summary, a.url)
    assert not b.summary and b.url.endswith("def"), "paywalled outlet must not be fetched"
    assert not c.summary and c.url == "https://blocked"
    assert stats["summaries"] == 1 and stats["direct_links"] == 1, stats
    os.environ.pop("ANTHROPIC_API_KEY", None)
    assert enrich.why_it_matters([a]) == 0

    # jobs: featured selection is bucket-balanced, company-capped, and prefers unseen
    J = lambda i, c, b, age=1, reg="US": jobs.Job(str(i), f"T{i}", c, b, f"https://x/{i}", "", reg, age)
    lst = [J(1, "A", "Policy"), J(2, "A", "Policy"), J(3, "A", "Policy"), J(4, "B", "Legal"), J(5, "C", "Consulting", 60),
           J(6, "D", "Communications", 3, "International"), J(7, "E", "Communications", 5)]
    feat = jobs.pick_featured(lst, seen={"1", "2"})
    ids = [j.job_id for j in feat]
    assert "5" not in ids, "stale job featured"
    assert sum(1 for j in feat if j.company == "A") <= 2
    assert "7" in ids and "3" in ids
    pulse = jobs.build_pulse(lst, seen={"1"}, pulse_json={})
    assert pulse.total == 7 and pulse.new_since_last == 6 and pulse.week_change is None
    assert jobs.build_pulse([], set(), {}).total == 0
    print("ALL UPCOMING/ENRICH/JOBS TESTS PASSED")


if __name__ == "__main__":
    main()
