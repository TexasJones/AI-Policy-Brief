"""Offline tests for the Google / Microsoft / Workday fetchers (fixtures are
inferred response shapes, not captured live responses)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai_policy_brief import jobs_scraper as a


def employer(source):
    return next(e for e in a.EMPLOYERS if e["source"] == source)


def main():
    a.fetch_url = lambda u, **k: (
        '<a href="/about/careers/applications/jobs/results/1-policy-development-lead?q=x">x</a>'
        '<a href="https://www.google.com/about/careers/applications/jobs/results/2-ai-policy-manager-public-affairs?q=y">y</a>'
        '<a href="/about/careers/applications/jobs/results/3-senior-software-engineer-ai?q=y">z</a>'
        '<a href="/about/careers/applications/jobs/results/2-ai-policy-manager-public-affairs?q=z">dup</a>')
    jobs = a.collect([dict(employer("google"), queries=["q"])])
    titles = [j["title"] for j in jobs]
    assert titles == ["AI Policy Manager Public Affairs"], titles      # gated, engineer excluded, dup collapsed
    assert jobs[0]["age_days"] == a.UNDATED_AGE_DAYS                   # undated => neutral age

    a.post_json = lambda u, p, **k: {"jobPostings": [
        {"title": "Responsible AI Policy Manager", "externalPath": "/job/DC/Responsible-AI_R123",
         "locationsText": "Washington, DC", "postedOn": "Posted 3 Days Ago", "bulletFields": ["R123"]},
        {"title": "Tax Manager", "externalPath": "/job/x_R9", "locationsText": "NY", "postedOn": "Posted Today", "bulletFields": ["R9"]},
        {"title": "AI Governance Consultant", "externalPath": "/job/y_R8", "locationsText": "London, UK",
         "postedOn": "Posted 30+ Days Ago", "bulletFields": ["R8"]}]}
    jobs = a.collect([dict(employer("workday"), queries=["q"])])
    assert [j["title"] for j in jobs] == ["Responsible AI Policy Manager"], [j["title"] for j in jobs]  # us_only drops London
    assert jobs[0]["apply_url"].startswith("https://pwc.wd3.myworkdayjobs.com/en-US/US_Experienced_Careers/job/")
    assert jobs[0]["age_days"] == 3

    a.fetch_url = lambda u, **k: ('{"data":{"positions":[{"id":1970393556988251,"name":"Director, AI Public Policy",'
                                  '"locations":["Washington, DC, US"],"postedTs":1790406000},'
                                  '{"id":2,"name":"Data Center Technician","locations":["Santa Clara, CA, US"],"postedTs":1790406000}]}}')
    jobs = a.collect([dict(employer("eightfold"), queries=["q"])])
    assert [j["title"] for j in jobs] == ["Director, AI Public Policy"]
    assert jobs[0]["apply_url"] == "https://apply.careers.microsoft.com/careers/job/1970393556988251"

    # Workday: two pages of results are both fetched, offset advances, and the
    # job id is pulled from the posting's own _R###### suffix rather than the
    # tenant-configured bulletFields (which are not guaranteed unique).
    pages = [
        {"total": 3, "jobPostings": [
            {"title": "AI Policy Manager A", "externalPath": "/job/x/A_R100", "locationsText": "NY", "postedOn": "Posted Today", "bulletFields": ["dup"]},
            {"title": "AI Policy Manager B", "externalPath": "/job/x/B_R200", "locationsText": "NY", "postedOn": "Posted Today", "bulletFields": ["dup"]}]},
        {"total": 3, "jobPostings": [
            {"title": "AI Policy Manager C", "externalPath": "/job/x/C_R300", "locationsText": "NY", "postedOn": "Posted Today", "bulletFields": ["dup"]}]},
    ]
    calls = []
    def paged_post(u, p, **k):
        calls.append(p["offset"])
        return pages[p["offset"] // 2]
    a.post_json = paged_post
    real_page_size = a.WORKDAY_PAGE_SIZE
    a.WORKDAY_PAGE_SIZE = 2  # match the fixture's page size so the "short page" stop condition fires correctly
    try:
        ids = {j["job_id"].rsplit("-", 1)[-1] for j in a.collect([dict(employer("workday"), queries=["q"], us_only=False)])}
    finally:
        a.WORKDAY_PAGE_SIZE = real_page_size
    assert ids == {"R100", "R200", "R300"}, ids   # not collapsed by the shared "dup" bulletFields
    assert calls == [0, 2], calls  # stopped after a short (final) page, no third call

    # Google: pagination continues while a page returns results, stops on an empty page
    def paged_google(u, **k):
        n = int(u.split("page=")[1].split("&")[0])
        if n > 2:
            return "<html></html>"
        return f'<a href="/about/careers/applications/jobs/results/{n}00-ai-policy-role-{n}?q=x">x</a>'
    a.fetch_url = paged_google
    jobs = a.collect([dict(employer("google"), queries=["q"])])
    assert {j["title"] for j in jobs} == {"AI Policy Role 1", "AI Policy Role 2"}, jobs

    # one broken source must not stop the others
    def boom(u, **k): raise RuntimeError("down")
    a.fetch_url = boom
    assert a.collect([dict(employer("eightfold"), queries=["q"])]) == []
    print("ALL CAREER-SITE TESTS PASSED")


if __name__ == "__main__":
    main()
