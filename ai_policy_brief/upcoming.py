"""'Coming up': open federal comment periods on AI, from the Federal Register API
(public, no key). Congressional hearings are not included: the congress.gov
API needs a key, so that is left for a later pass.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlencode

from .news import AI_RE, default_fetch

log = logging.getLogger(__name__)

API = "https://www.federalregister.gov/api/v1/documents.json"
FIELDS = ["title", "abstract", "comments_close_on", "html_url", "agency_names", "type", "publication_date"]
MAX_DAYS_AHEAD = 60
MAX_ITEMS = 5


@dataclass
class Deadline:
    title: str
    agency: str
    due: dt.date
    url: str
    kind: str


def api_url(today: dt.date) -> str:
    params = [("conditions[term]", "artificial intelligence"),
              ("conditions[type][]", "PRORULE"), ("conditions[type][]", "NOTICE"),
              ("conditions[publication_date][gte]", (today - dt.timedelta(days=75)).isoformat()),
              ("per_page", "100"), ("order", "newest")]
    params += [("fields[]", f) for f in FIELDS]
    return API + "?" + urlencode(params)


def parse_deadlines(text: str, today: dt.date) -> list[Deadline]:
    try:
        results = json.loads(text).get("results", [])
    except (ValueError, AttributeError):
        return []
    out = []
    for r in results:
        due_raw = r.get("comments_close_on")
        if not due_raw:
            continue
        try:
            due = dt.date.fromisoformat(due_raw)
        except ValueError:
            continue
        if due < today or due > today + dt.timedelta(days=MAX_DAYS_AHEAD):
            continue
        title = (r.get("title") or "").strip()
        # The API's term search also matches incidental mentions, so require
        # AI to be part of the document's subject.
        abstract = r.get("abstract") or ""
        if not (AI_RE.search(title) or len(AI_RE.findall(abstract)) >= 2):
            continue
        agencies = r.get("agency_names") or []
        out.append(Deadline(
            title=re.sub(r"\s+", " ", title), agency=", ".join(agencies[:2]), due=due,
            url=r.get("html_url") or "", kind="Proposed rule" if r.get("type") == "Proposed Rule" else "Notice"))
    out.sort(key=lambda d: d.due)
    return out[:MAX_ITEMS]


def get_deadlines(today: dt.date, fetch: Optional[Callable] = None) -> list[Deadline]:
    fetch = fetch or default_fetch
    text = fetch(api_url(today))
    if not text:
        log.warning("Federal Register unavailable; skipping Coming up")
        return []
    return parse_deadlines(text, today)
