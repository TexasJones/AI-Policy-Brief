"""Regression tests for bugs found in code review."""
import datetime as dt, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai_policy_brief import news, jobs_scraper as js, enrich, template, generate

UTC = dt.timezone.utc


def main():
    # HTML entities in feed summaries are decoded once, then escaped once
    assert news._summary("Trump&#8217;s plan &amp; more") == "Trump’s plan & more"

    # og:description with an apostrophe is not truncated
    assert enrich.extract_description('<meta property="og:description" content="The senator\'s bill would bar states from acting on AI.">') \
        == "The senator's bill would bar states from acting on AI."

    # clustering: different stories that share a few words stay separate
    a = news.tokens("Trump signs executive order on AI chips export to China")
    b = news.tokens("Trump signs executive order on AI data centers permitting")
    assert not news.similar(a, b)
    assert news.similar(news.tokens("Senate panel advances AI preemption bill after hearing"),
                        news.tokens("Senate panel advances AI preemption bill after tense hearing on states"))

    # sections
    S = lambda t: news.classify(news.Story(t, "x", "u", None))
    assert S("State Department weighs new AI chip export rules") == "White House & Agencies"
    assert S("Senate passes bill to restrict Nvidia chip sales to China") == "Congress"
    assert S("Governor signs AI bill into law") == "States"
    assert S("EU lawmakers back AI Act changes") == "Global"
    assert not news.GENERIC_TITLE.search("The latest on Trump's AI executive order")
    assert not news.GENERIC_TITLE.search("Watch: Senate hearing on AI")
    assert news.GENERIC_TITLE.search("Podcast: AI and the election")

    # calendar-day labels in Eastern time
    et = dt.timezone(dt.timedelta(hours=-4))
    now = dt.datetime(2026, 9, 29, 7, 0, tzinfo=et)          # Tuesday 7am ET
    sunday_8am = dt.datetime(2026, 9, 27, 12, 0, tzinfo=UTC)  # 47h earlier
    assert template._ago(sunday_8am, now) == "2 days ago"
    assert template._ago(dt.datetime(2026, 9, 28, 23, 0, tzinfo=UTC), now) == "Yesterday"
    assert template._ago(dt.datetime(2026, 9, 29, 5, 0, tzinfo=UTC), now) == "Today"

    # locations and titles
    for loc in ("Berlin, DE", "Toronto, CA", "Bangalore, IN", "Tel Aviv, IL"):
        assert not js.is_us_location(loc), loc
    assert js.is_us_location("Berlin, DE | Chicago, IL") and js.is_us_location("San Francisco, CA")
    for title, bucket in (("Senior Policy Researcher", "Policy"), ("Administrative Law Counsel", "Legal"),
                          ("Financial Services Policy Counsel", "Legal"), ("Tax Policy Advisor", "Policy"),
                          ("Telecommunications Policy Analyst", "Policy")):
        assert js.classify(title)[0] == bucket, title
    for title in ("Content Strategist", "Director, Investor Relations", "Research Scientist, Policy"):
        assert js.classify(title)[0] is None, title
    assert not js.has_ai_signal("Practice Lead", "our Dubai practice")

    # a control character in a title must not break the feed
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "f.xml")
        js.write_feed([{"job_id": "1", "title": "Policy\x0bManager\x1b", "company": "X"}], path)
        assert "PolicyManager" in open(path, encoding="utf-8").read()

    # a scrape that finds far fewer jobs than before must not overwrite data
    with tempfile.TemporaryDirectory() as d:
        hist = os.path.join(d, "h.json")
        import json
        json.dump({"2026-09-01": {"total": 100}}, open(hist, "w"))
        assert js.previous_total(hist) == 100

    # consecutive stories in the same section show the section badge only
    # once, not once per story (found in live output: two "Global" stories
    # back to back each carried their own colored badge)
    now = dt.datetime(2026, 9, 29, 11, 0, tzinfo=UTC)
    stories = [
        news.Story("Global one", "AP", "https://x/1", now, section="Global"),
        news.Story("Global two", "Reuters", "https://x/2", now, section="Global"),
        news.Story("Courts one", "Axios", "https://x/3", now, section="Courts & Legal"),
    ]
    nr = news.NewsResult(lead=None, stories=stories)
    from ai_policy_brief.jobs import Pulse
    html_out = template.render_brief(Pulse(), nr, today=dt.date(2026, 9, 29), now=now)
    assert html_out.count(">\U0001F30D Global<") == 1, "repeated section badge not suppressed"
    assert html_out.count("Courts &amp; Legal<") == 1

    # public web copy has no dead unsubscribe placeholder
    with tempfile.TemporaryDirectory() as d:
        generate.ROOT = type(generate.ROOT)(d)
        url = generate.publish_to_pages('<a href="{{ unsubscribe }}">Unsubscribe</a>', dt.date(2026, 9, 29))
        assert "{{" not in open(os.path.join(d, "docs", "briefs", "2026-09-29.html")).read()
    print("ALL REGRESSION TESTS PASSED")


if __name__ == "__main__":
    main()
