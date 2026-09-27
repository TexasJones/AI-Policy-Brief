"""Send an issue through the Brevo campaigns API.

    python -m ai_policy_brief.send --html brief.html --subject-file subject.txt
    python -m ai_policy_brief.send ... --test-to you@example.com   # test send only
    python -m ai_policy_brief.send ... --dry-run                    # no network

Environment: BREVO_API_KEY, BREVO_LIST_ID, BREVO_SENDER_EMAIL,
BREVO_SENDER_NAME (defaults to the brand name).
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from . import config

API = "https://api.brevo.com/v3"


def _headers() -> dict:
    return {"api-key": os.environ["BREVO_API_KEY"], "accept": "application/json",
            "content-type": "application/json"}


def campaign_name(today: dt.date) -> str:
    return f"{config.BRAND_NAME} {today.isoformat()}"


def already_sent(name: str) -> bool:
    """Guard against a double send if the workflow is triggered twice for the
    same issue (for example by the scheduler and the watchdog)."""
    try:
        r = requests.get(f"{API}/emailCampaigns", headers=_headers(),
                         params={"limit": 50, "sort": "desc"}, timeout=30)
        r.raise_for_status()
        return any(c.get("name") == name and c.get("status") in ("sent", "queued", "inProcess")
                   for c in r.json().get("campaigns", []))
    except Exception as exc:
        print("Duplicate check failed, continuing:", exc)
        return False


def build_payload(html: str, subject: str, name: str) -> dict:
    return {
        "name": name,
        "subject": subject,
        "sender": {"name": os.environ.get("BREVO_SENDER_NAME", config.BRAND_NAME),
                   "email": os.environ["BREVO_SENDER_EMAIL"]},
        "type": "classic",
        "htmlContent": html,
        "recipients": {"listIds": [int(os.environ["BREVO_LIST_ID"])]},
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--html", default="ai_policy_brief.html")
    p.add_argument("--subject-file", default="ai_policy_brief_subject.txt")
    p.add_argument("--test-to", default=None, help="comma-separated; sends a test only")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    html = Path(args.html).read_text(encoding="utf-8")
    subject = Path(args.subject_file).read_text(encoding="utf-8").strip()
    today = dt.datetime.now(ZoneInfo(config.SEND_TIMEZONE)).date()
    name = campaign_name(today)

    if args.dry_run:
        print("DRY RUN:", name, "|", subject, "|", len(html), "bytes")
        return 0

    if not args.test_to and already_sent(name):
        print("Campaign", name, "already sent; skipping.")
        return 0

    r = requests.post(f"{API}/emailCampaigns", headers=_headers(),
                      json=build_payload(html, subject, name + (" (test)" if args.test_to else "")), timeout=60)
    if r.status_code >= 300:
        print("Create failed:", r.status_code, r.text)
        return 1
    cid = r.json()["id"]
    print("Created campaign", cid)

    if args.test_to:
        emails = [e.strip() for e in args.test_to.split(",") if e.strip()]
        r = requests.post(f"{API}/emailCampaigns/{cid}/sendTest", headers=_headers(),
                          json={"emailTo": emails}, timeout=60)
    else:
        r = requests.post(f"{API}/emailCampaigns/{cid}/sendNow", headers=_headers(), timeout=60)
    if r.status_code >= 300:
        print("Send failed:", r.status_code, r.text)
        return 1
    print("Sent." if not args.test_to else "Test sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
