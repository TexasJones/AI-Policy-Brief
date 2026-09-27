"""Reads the AI jobs feed written by jobs_scraper.py and builds the jobs half
of the newsletter: a small hiring pulse plus a bucket-balanced featured list.

Every job links straight to the employer's own application page.
"""
from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

from . import config

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
FEED_PATH = os.path.join(DATA_DIR, "ai-feed.xml")
PULSE_PATH = os.path.join(DATA_DIR, "ai_hiring_pulse.json")
SEEN_PATH = os.path.join(DATA_DIR, "seen_jobs.json")

BUCKETS = ("Policy", "Communications", "Legal", "Consulting")


@dataclass
class Job:
    job_id: str
    title: str
    company: str
    bucket: str
    url: str
    location: str = ""
    region: str = "US"
    age_days: int = 0
    employer_type: str = ""


@dataclass
class Pulse:
    total: int = 0
    new_since_last: int = 0
    week_change: Optional[int] = None
    by_bucket: list = field(default_factory=list)      # [(bucket, count, change or None)]
    top_employers: list = field(default_factory=list)  # [(company, count)]
    us_count: int = 0
    intl_count: int = 0
    featured: list = field(default_factory=list)


def load_jobs(path: str = FEED_PATH) -> list[Job]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return []
    jobs = []
    for el in root.findall("job"):
        def g(tag, default=""):
            node = el.find(tag)
            return (node.text or default) if node is not None else default
        url = g("apply_url")
        if not url.startswith("http"):
            continue
        try:
            age = int(g("age_days", "0") or 0)
        except ValueError:
            age = 0
        jobs.append(Job(
            job_id=g("job_id"), title=g("title"), company=g("company"),
            bucket=g("bucket"), url=url, location=g("office_location"),
            region=g("region", "US"), age_days=age, employer_type=g("employer_type"),
        ))
    return jobs


def load_seen(path: str = SEEN_PATH) -> set:
    try:
        with open(path, encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, json.JSONDecodeError):
        return set()


def save_seen(jobs: list[Job], path: str = SEEN_PATH) -> None:
    """Remember which jobs the current issue has already shown as 'live', so
    the next issue can count only what is genuinely new. Only the ids in the
    current feed are kept, so the file cannot grow without bound."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(j.job_id for j in jobs), f)


def pick_featured(jobs: list[Job], seen: set, per_bucket: int = None, max_total: int = None,
                  max_age_days: int = None, per_company: int = None) -> list[Job]:
    """Round-robin across buckets so one bucket (usually Legal or Policy at the
    big labs) cannot crowd out the others. Within a bucket: new since last
    issue first, then US-eligible, then most recently posted. At most
    `per_company` roles from any one employer."""
    per_bucket = per_bucket or config.FEATURED_PER_BUCKET
    max_total = max_total or config.FEATURED_MAX
    max_age_days = max_age_days or config.FEATURED_MAX_AGE_DAYS
    per_company = per_company or config.FEATURED_PER_COMPANY

    by_bucket = {b: [] for b in BUCKETS}
    for j in jobs:
        if j.bucket in by_bucket and j.age_days <= max_age_days:
            by_bucket[j.bucket].append(j)
    for b in by_bucket:
        by_bucket[b].sort(key=lambda j: (j.job_id in seen, j.region != "US", j.age_days, j.company, j.title))

    picked, company_counts, taken, picked_slots = [], {}, {b: 0 for b in BUCKETS}, set()
    progress = True
    while progress and len(picked) < max_total:
        progress = False
        for b in BUCKETS:
            if taken[b] >= per_bucket or len(picked) >= max_total:
                continue
            while by_bucket[b]:
                j = by_bucket[b].pop(0)
                if company_counts.get(j.company, 0) >= per_company:
                    continue
                # Large employers (Accenture, PwC, ...) sometimes post several
                # near-identical requisitions -- same title, same company,
                # same city -- under separate req IDs. Each is a real,
                # separately-applicable posting (kept in full on jobs.html and
                # counted in the total), but showing the same-looking listing
                # twice in an 8-job spotlight reads as a bug. Skip a repeat
                # here and let the next distinct listing take the slot.
                slot = (j.title.strip().lower(), j.company, j.location)
                if slot in picked_slots:
                    continue
                picked.append(j)
                company_counts[j.company] = company_counts.get(j.company, 0) + 1
                picked_slots.add(slot)
                taken[b] += 1
                progress = True
                break
    return picked


def _load_pulse_json(path: str = PULSE_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def build_pulse(jobs: list[Job], seen: set, pulse_json: dict = None) -> Pulse:
    pulse_json = _load_pulse_json() if pulse_json is None else pulse_json
    trends = {t["bucket"]: t["change"] for t in pulse_json.get("bucket_trends", [])}
    has_cmp = pulse_json.get("has_comparison", False)

    counts = {b: 0 for b in BUCKETS}
    employers: dict = {}
    us = intl = 0
    for j in jobs:
        if j.bucket in counts:
            counts[j.bucket] += 1
        employers[j.company] = employers.get(j.company, 0) + 1
        if j.region == "US":
            us += 1
        else:
            intl += 1

    new_count = sum(1 for j in jobs if j.job_id not in seen) if seen else 0
    return Pulse(
        total=len(jobs),
        new_since_last=new_count,
        week_change=pulse_json.get("total_change") if has_cmp else None,
        by_bucket=[(b, counts[b], trends.get(b) if has_cmp else None) for b in BUCKETS],
        top_employers=sorted(employers.items(), key=lambda kv: (-kv[1], kv[0]))[:5],
        us_count=us,
        intl_count=intl,
        featured=pick_featured(jobs, seen),
    )


def get_pulse() -> Pulse:
    jobs = load_jobs()
    return build_pulse(jobs, load_seen())
