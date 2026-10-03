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
            # A real fetch of a resolved URL returns that outlet's own page.
            # If enrich() ever regresses to fetching the raw Google News
            # link directly (the original bug: that link doesn't do a plain
            # HTTP redirect), this stub would have no entry for it and KeyError,
            # failing the test loudly instead of silently passing like the
            # old stub -- which always returned the axios page regardless of
            # input URL and so never would have caught the real bug.
            if "blocked" in url: return R("https://news.google.com/consent", "x")
            pages = {"https://www.axios.com/2026/09/28/story": page}
            return R(url, pages[url])
    enrich.allowed = lambda url: True
    a = news.Story("t", "Axios", "https://news.google.com/rss/articles/abc", None)
    b = news.Story("t", "WSJ", "https://news.google.com/rss/articles/def", None, paywalled=True)
    c = news.Story("t", "Axios", "https://blocked", None)
    # Stands in for gnewsdecoder: resolves the two Google News links to real
    # publisher URLs in one batched call, exactly like the real thing but
    # with no network. This is the fix for the bug where every story's link
    # stayed on news.google.com, enrich()'s own BAD_HOSTS check then rejected
    # it, and no story (paywalled or not) ever got a summary.
    mapping = {"https://news.google.com/rss/articles/abc": "https://www.axios.com/2026/09/28/story",
               "https://news.google.com/rss/articles/def": "https://www.wsj.com/articles/chip-export-limits"}
    def fake_decode(urls):
        return [{"success": True, "decoded_url": mapping[u]} if u in mapping
                else {"success": False, "message": "no mapping"} for u in urls]
    stats = enrich.enrich([a, b, c], session=Sess(), decode=fake_decode)
    assert stats["resolved"] == 2, stats
    assert a.summary and a.url == "https://www.axios.com/2026/09/28/story", (a.summary, a.url)
    assert not b.summary and b.url == "https://www.wsj.com/articles/chip-export-limits", \
        "paywalled outlet's link must still resolve to the real page, just never fetched for a summary"
    assert not c.summary and c.url == "https://blocked", "non-Google link must pass through untouched"
    assert stats["summaries"] == 1 and stats["tried"] == 2, stats

    # A decode failure (Google changed its format, network down, whatever)
    # must leave stories exactly as if resolution had never run -- never
    # raise, never partially rewrite a URL.
    class StillGoogleSess:
        # Decode failed, so the fetch below hits the raw Google News link --
        # same as production's real BAD_HOSTS rejection, with no real network.
        def get(s, url, **k): return R("https://news.google.com/rss/articles/xyz", "x")
    d = news.Story("t", "Axios", "https://news.google.com/rss/articles/xyz", None)
    broken_stats = enrich.enrich([d], session=StillGoogleSess(),
                                 decode=lambda urls: (_ for _ in ()).throw(RuntimeError("boom")))
    assert broken_stats["resolved"] == 0 and not d.summary \
        and d.url == "https://news.google.com/rss/articles/xyz", broken_stats

    # A result list that doesn't match the input length can't be trusted to
    # line up positionally -- must bail out rather than risk zip() pairing a
    # story with someone else's decoded URL.
    e = news.Story("t", "Axios", "https://news.google.com/rss/articles/one", None)
    f = news.Story("t", "Axios", "https://news.google.com/rss/articles/two", None)
    short_stats = enrich.enrich([e, f], session=StillGoogleSess(),
                                decode=lambda urls: [{"success": True, "decoded_url": "https://x/only-one"}])
    assert short_stats["resolved"] == 0, short_stats
    assert e.url == "https://news.google.com/rss/articles/one", e.url
    assert f.url == "https://news.google.com/rss/articles/two", f.url

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
    # a large employer bulk-posting the same title/city under separate req
    # IDs (real Accenture/Workday behavior) must not show twice in the
    # featured spotlight -- each req is still a distinct, real listing, so
    # this is about what gets featured, not deduping the feed itself
    dup_lst = [J(10, "Accenture", "Consulting", reg="India"), J(11, "Accenture", "Consulting", reg="India"),
               J(12, "Accenture", "Consulting", reg="India")]
    for j, loc in zip(dup_lst, ("Mumbai", "Mumbai", "Gurugram")):
        j.title, j.location = "Enterprise AI Value Strategy Consultant", loc
    feat_dup = jobs.pick_featured(dup_lst, seen=set(), per_company=5)
    slots = [(j.title, j.company, j.location) for j in feat_dup]
    assert len(slots) == len(set(slots)), f"same title/company/city featured twice: {slots}"
    assert len(feat_dup) == 2, "the two distinct city listings should both be kept"

    pulse = jobs.build_pulse(lst, seen={"1"}, pulse_json={})
    assert pulse.total == 7 and pulse.new_since_last == 6 and pulse.week_change is None
    assert jobs.build_pulse([], set(), {}).total == 0
    print("ALL UPCOMING/ENRICH/JOBS TESTS PASSED")


if __name__ == "__main__":
    main()
