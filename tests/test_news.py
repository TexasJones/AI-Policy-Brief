"""Offline tests for news.py using fixture RSS. Run: python tests/test_news.py"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai_policy_brief import news, config  # noqa: E402

NOW = dt.datetime(2026, 9, 29, 11, 0, tzinfo=dt.timezone.utc)


def rfc(hours_ago):
    t = NOW - dt.timedelta(hours=hours_ago)
    return t.strftime("%a, %d %b %Y %H:%M:%S GMT")


def feed(items):
    body = ""
    for title, hrs, url, src_url in items:
        body += (f"<item><title>{title}</title><link>{url}</link><pubDate>{rfc(hrs)}</pubDate>"
                 f'<source url="{src_url}">x</source></item>')
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{body}</channel></rss>'


FIXTURES = {
    "politico.com": [
        ("Senate panel advances AI preemption bill after hearing - Politico", 6, "https://n.google/1", "https://www.politico.com"),
        ("Opinion: Why Congress must regulate AI now - Politico", 5, "https://n.google/2", "https://www.politico.com"),
        ("Playoff bracket set - Politico", 4, "https://n.google/3", "https://www.politico.com"),
        ("Old AI regulation story from last week - Politico", 200, "https://n.google/4", "https://www.politico.com"),
    ],
    "axios.com": [
        ("Senate panel advances AI preemption bill after hearing on states - Axios", 7, "https://n.google/5", "https://www.axios.com"),
        ("California attorney general probes chatbot safeguards for minors - Axios", 30, "https://n.google/6", "https://www.axios.com"),
    ],
    "wsj.com": [
        ("White House weighs new export limits on AI chips - The Wall Street Journal", 20, "https://n.google/7", "https://www.wsj.com"),
        ("Leaked domain item - The Wall Street Journal", 3, "https://n.google/8", "https://www.example.org"),
    ],
    "reuters.com": [
        ("Judge rejects motion to dismiss authors' copyright lawsuit against AI developer - Reuters", 40, "https://n.google/9", "https://www.reuters.com"),
    ],
}


RESEARCH_FIXTURES = {
    "kpmg.com": [
        ("KPMG and UT Austin launch AI governance research partnership - KPMG", 30, "https://n.google/r1", "https://kpmg.com"),
    ],
    "query2": [
        ("New study finds AI policy skills gap across federal workforce - Brookings", 12, "https://n.google/r2", "https://www.brookings.edu"),
        ("Company unveils new chatbot app - TechBlog", 5, "https://n.google/r3", "https://techblog.example"),
    ],
}


def fake_fetch(url):
    if "site%3Akpmg.com" in url:
        return feed(RESEARCH_FIXTURES["kpmg.com"])
    if "new+study" in url:
        return feed(RESEARCH_FIXTURES["query2"])
    for domain, items in FIXTURES.items():
        if f"site%3A{domain}" in url:
            return feed(items)
    return None


def main():
    news_cfg_hours = 96
    res = news.get_news(now=NOW, fetch=fake_fetch, recent=[], hours=news_cfg_hours)
    titles = [s.title for s in ([res.lead] if res.lead else []) + res.stories]
    print("\n".join(" - " + t for t in titles))

    assert res.lead and "preemption" in res.lead.title, "lead should be the widest-covered story"
    assert res.lead.coverage == 2 and res.lead.also_covered_by, "cross-outlet coverage not counted"
    assert not any("Opinion" in t for t in titles), "opinion piece leaked"
    assert not any("Playoff" in t for t in titles), "off-topic item leaked"
    assert not any("Old AI" in t for t in titles), "stale item leaked"
    assert not any("Leaked domain" in t for t in titles), "site restriction not enforced"
    assert not any(" - " in t and t.endswith("Reuters") for t in titles), "outlet suffix not stripped"

    by_title = {s.title: s for s in ([res.lead] + res.stories)}
    wsj = next(s for s in by_title.values() if "export limits" in s.title)
    assert wsj.paywalled and wsj.section == "White House & Agencies", (wsj.paywalled, wsj.section)
    assert next(s for s in by_title.values() if "attorney general" in s.title).section == "States"
    assert next(s for s in by_title.values() if "copyright" in s.title).section == "Courts & Legal"

    research = [s for s in by_title.values() if s.section == news.RESEARCH_SECTION]
    assert any("KPMG" in s.title and s.outlet == "KPMG" for s in research), "KPMG/UT partnership missing"
    assert any("skills gap" in s.title for s in research), "study missing"
    assert not any("chatbot app" in s.title for s in by_title.values()), "off-topic research item leaked"

    # cross-issue memory: same stories are dropped next time
    recent = [{"date": "2026-09-26", "tokens": sorted(news.tokens(t))} for t in titles]
    again = news.get_news(now=NOW, fetch=fake_fetch, recent=recent, hours=news_cfg_hours)
    assert again.lead is None and not again.stories, "recent stories were repeated"

    # window: no previous issue -> max; recent issue -> clamped to min
    assert news.window_hours(NOW, path="/nonexistent.json") == config.MAX_WINDOW_HOURS
    import json, tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"sent_at": (NOW - dt.timedelta(hours=10)).isoformat()}, f)
    assert news.window_hours(NOW, path=f.name) == config.MIN_WINDOW_HOURS
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"sent_at": (NOW - dt.timedelta(hours=72)).isoformat()}, f)
    assert news.window_hours(NOW, path=f.name) == 78

    # a dead source must not break the run
    dead = news.get_news(now=NOW, fetch=lambda u: None, recent=[], hours=96)
    assert dead.lead is None
    print("ALL NEWS TESTS PASSED")


if __name__ == "__main__":
    main()
