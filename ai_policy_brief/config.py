"""Settings for the AI Policy Brief. Nothing here is shared with any other
newsletter; change values here rather than hunting through modules."""
import os

BRAND_NAME = "AI Policy Brief"
SUBJECT_PREFIX = "AI Policy Brief: "
SUBJECT_MAX_CHARS = 60

# GitHub Pages copy of each issue (Settings -> Pages: main branch, /docs).
PAGES_BASE_URL = "https://texasjones.github.io/AI-Policy-Brief"

# Optional. When empty, the "Subscribe" and "Share" prompts are left out
# rather than pointing nowhere. Set as a repository variable or env var.
SUBSCRIBE_URL = os.environ.get("SUBSCRIBE_URL", "").strip()

# One optional credit link in the footer (empty = no link).
FOOTER_LINK_TEXT = ""
FOOTER_LINK_URL = ""

# Cadence: issues go out Tuesday and Friday at 7 a.m. Eastern.
SEND_TIMEZONE = "America/New_York"
SEND_WEEKDAYS = (1, 4)  # Monday=0, so Tuesday=1, Friday=4

# Each issue covers everything since the last one, bounded by these limits.
MIN_WINDOW_HOURS = 48
MAX_WINDOW_HOURS = 96
WINDOW_BUFFER_HOURS = 6

# Story selection
MAX_STORIES_PER_SECTION = 2
MAX_STORIES_TOTAL = 9
SUMMARY_CHARS = 240

# Jobs
FEATURED_PER_BUCKET = 2
FEATURED_MAX = 8
FEATURED_MAX_AGE_DAYS = 45
FEATURED_PER_COMPANY = 2
