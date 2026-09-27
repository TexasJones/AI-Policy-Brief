"""HTML email for the AI Policy Brief. Table layout with inline styles, the
email-safe pattern; one small media query reflows it on phones."""
from __future__ import annotations

import datetime as dt
import html
from typing import Optional
from urllib.parse import quote

from . import config
from .jobs import Pulse, Job
from .news import NewsResult, Story

INK = "#14202B"
MUTED = "#5F6C79"
ACCENT = "#0C7E87"
HAIRLINE = "#E3E8EC"
BG = "#F2F5F7"
CARD = "#FFFFFF"
WHITE = "#FFFFFF"
HEADLINE_FONT = "Georgia, 'Times New Roman', serif"
BODY_FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"

SECTION_COLORS = {
    "Congress": "#3357A8",
    "White House & Agencies": "#A8324A",
    "States": "#9F620E",
    "Courts & Legal": "#6B3FA0",
    "Global": "#15803D",
    "Industry & Labs": "#0C7E87",
}
BUCKET_COLORS = {
    "Policy": "#3357A8",
    "Communications": "#A8324A",
    "Legal": "#6B3FA0",
    "Consulting": "#9F620E",
}


def esc(text) -> str:
    return html.escape(text or "")


def _date_label(today: dt.date) -> str:
    return f"{today.strftime('%A, %B')} {today.day}, {today.year}"


def _ago(published: Optional[dt.datetime], now: dt.datetime) -> str:
    if published is None:
        return ""
    hours = (now - published).total_seconds() / 3600
    if hours < 24:
        return "Today" if published.astimezone(now.tzinfo).date() == now.date() else "Yesterday"
    days = int(hours // 24)
    return "Yesterday" if days == 1 else f"{days} days ago"


def _style_block() -> str:
    return ("<style>@media only screen and (max-width: 620px) {"
            ".apb-card{width:100%!important}"
            ".apb-pad{padding-left:20px!important;padding-right:20px!important}"
            ".apb-col{display:block!important;width:100%!important;padding:0 0 12px 0!important}"
            "}</style>")


def _divider() -> str:
    return (f'<tr><td class="apb-pad" style="padding:0 40px;">'
            f'<div style="border-bottom:1px solid {HAIRLINE};margin:24px 0;"></div></td></tr>')


def _heading(text: str) -> str:
    return (f'<div style="font-family:{BODY_FONT};font-size:18px;font-weight:800;color:{INK};'
            f'margin:0 0 14px 0;">{esc(text)}</div>')


def _badge(text: str, color: str) -> str:
    return (f'<span style="display:inline-block;background-color:{color};color:{WHITE};padding:4px 12px;'
            f'border-radius:20px;font-size:11px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:0.5px;font-family:{BODY_FONT};">{esc(text)}</span>')


def _link(url: str, label: str, color: str, size: int = 13) -> str:
    return (f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer" '
            f'style="color:{color};text-decoration:none;font-weight:700;font-size:{size}px;">{label}</a>')


def _bold_lead_in(text: str, words: int = 8) -> str:
    parts = (text or "").split()
    if not parts:
        return ""
    lead, rest = " ".join(parts[:words]), " ".join(parts[words:])
    return f"<strong>{esc(lead)}</strong> {esc(rest)}" if rest else f"<strong>{esc(lead)}</strong>"


def _story_meta(s: Story, now: dt.datetime) -> str:
    bits = [b for b in (_ago(s.published, now),) if b]
    if s.also_covered_by:
        bits.append("Also: " + ", ".join(esc(o) for o in s.also_covered_by[:3]))
    if s.paywalled:
        bits.append("Paywall")
    if not bits:
        return ""
    return (f'<div style="font-size:12px;color:{MUTED};font-weight:600;margin:4px 0 8px;">'
            f'{" &middot; ".join(bits)}</div>')


def _story_block(s: Story, now: dt.datetime) -> str:
    color = SECTION_COLORS.get(s.section, ACCENT)
    summary = (f'<div style="font-size:14px;color:{MUTED};line-height:1.55;margin:6px 0 4px;">'
               f'{_bold_lead_in(s.summary)}</div>') if s.summary else ""
    return (f'<tr><td style="padding-bottom:18px;">'
            f'<div style="margin-bottom:8px;">{_badge(s.emoji + " " + s.section, color)}</div>'
            f'<div style="font-family:{HEADLINE_FONT};font-size:17px;font-weight:700;color:{INK};line-height:1.35;">'
            f'{esc(s.title)}</div>'
            f'{summary}{_story_meta(s, now)}'
            f'{_link(s.url, f"Read at {esc(s.outlet)} &rarr;", color)}'
            f'</td></tr>')


def _lead_block(s: Story, now: dt.datetime) -> str:
    color = SECTION_COLORS.get(s.section, ACCENT)
    also = (f'<div style="font-size:12px;color:rgba(255,255,255,0.8);margin-top:10px;">'
            f'Also reported by {", ".join(esc(o) for o in s.also_covered_by[:3])}</div>') if s.also_covered_by else ""
    summary = (f'<div style="font-size:14px;color:rgba(255,255,255,0.9);line-height:1.5;margin-top:10px;">'
               f'{esc(s.summary)}</div>') if s.summary else ""
    return (f'<tr><td class="apb-pad" style="padding:0 40px 4px 40px;">'
            f'<div style="background-color:{color};border-radius:14px;padding:26px 28px 24px 28px;">'
            f'<div style="display:inline-block;background-color:rgba(255,255,255,0.18);color:{WHITE};'
            f'padding:5px 14px;border-radius:20px;font-size:11px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:1px;">{s.emoji} {esc(s.section)} &middot; Lead story</div>'
            f'<div style="font-family:{HEADLINE_FONT};font-size:21px;font-weight:800;color:{WHITE};'
            f'line-height:1.35;margin-top:14px;">{esc(s.title)}</div>'
            f'{summary}{also}'
            f'<a href="{esc(s.url)}" target="_blank" rel="noopener noreferrer" '
            f'style="display:inline-block;margin-top:16px;border:1.5px solid {WHITE};border-radius:6px;'
            f'padding:10px 20px;color:{WHITE};text-decoration:none;font-weight:700;font-size:13px;">'
            f'Read at {esc(s.outlet)} &rarr;</a>'
            f'</div></td></tr>')


def _stat(number: str, label: str, bg: str, first: bool) -> str:
    pad = "padding-right:6px;" if first else "padding-left:6px;"
    return (f'<td width="50%" class="apb-col" style="{pad}vertical-align:top;">'
            f'<div style="background-color:{bg};border-radius:10px;padding:18px 16px;text-align:center;">'
            f'<div style="font-size:32px;font-weight:900;line-height:1;color:{WHITE};">{esc(number)}</div>'
            f'<div style="font-size:11px;font-weight:800;text-transform:uppercase;margin-top:8px;'
            f'letter-spacing:0.8px;color:{WHITE};">{esc(label)}</div></div></td>')


def _change(change: Optional[int]) -> str:
    if change is None:
        return ""
    if change == 0:
        return f'<span style="color:{MUTED};"> &ndash; 0 vs last week</span>'
    arrow, color = ("&#9650;", "#15803D") if change > 0 else ("&#9660;", "#A8324A")
    return f'<span style="color:{color};font-weight:700;"> {arrow} {abs(change)} vs last week</span>'


def _pulse_block(p: Pulse) -> str:
    new_label = "New since last issue" if p.new_since_last else "Open roles"
    stats = (_stat(f"{p.total:,}", "Open roles", "#14202B", True) +
             _stat(str(p.new_since_last) if p.new_since_last else f"{p.us_count:,}",
                   new_label if p.new_since_last else "US-eligible", ACCENT, False))
    rows = "".join(
        f'<tr><td style="padding:5px 0;font-size:14px;color:{INK};font-weight:600;">'
        f'<span style="display:inline-block;width:9px;height:9px;border-radius:2px;'
        f'background-color:{BUCKET_COLORS.get(b, ACCENT)};margin-right:8px;"></span>'
        f'{esc(b)} &middot; {c}{_change(chg)}</td></tr>'
        for b, c, chg in p.by_bucket)
    employers = "".join(
        f'<tr><td style="padding:5px 0;font-size:14px;color:{INK};font-weight:500;">'
        f'{esc(name)} &middot; {count}</td></tr>' for name, count in p.top_employers)
    label = f'font-size:11px;font-weight:800;color:{MUTED};text-transform:uppercase;letter-spacing:0.6px;margin-bottom:8px;'
    return (f'<tr><td class="apb-pad" style="padding:0 40px;">{_heading("AI Jobs Pulse")}'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:20px;"><tr>{stats}</tr></table>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
            f'<td width="50%" valign="top" class="apb-col" style="padding-right:20px;"><div style="{label}">By track</div>'
            f'<table role="presentation" cellpadding="0" cellspacing="0">{rows}</table></td>'
            f'<td width="50%" valign="top" class="apb-col"><div style="{label}">Top hiring</div>'
            f'<table role="presentation" cellpadding="0" cellspacing="0">{employers}</table></td>'
            f'</tr></table></td></tr>')


def _job_block(j: Job) -> str:
    color = BUCKET_COLORS.get(j.bucket, ACCENT)
    meta = " &middot; ".join(x for x in (esc(j.company), esc(j.location)) if x)
    initial = esc((j.company[:1] or "?").upper())
    return (f'<tr><td style="padding-bottom:10px;"><div style="background-color:{BG};border-radius:8px;padding:14px 16px;">'
            f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%"><tr>'
            f'<td width="44" valign="middle" align="center" style="width:44px;height:44px;border:1px solid {HAIRLINE};'
            f'border-radius:8px;background-color:{WHITE};font-family:{HEADLINE_FONT};font-weight:800;font-size:17px;color:{color};">{initial}</td>'
            f'<td style="padding-left:14px;" valign="middle">'
            f'<a href="{esc(j.url)}" target="_blank" rel="noopener noreferrer" '
            f'style="color:{INK};text-decoration:none;font-size:15px;font-weight:700;">{esc(j.title)}</a>'
            f'<div style="font-size:13px;color:{MUTED};margin-top:2px;">{meta}</div>'
            f'<div style="margin-top:6px;">{_badge(j.bucket, color)}</div>'
            f'</td></tr></table></div></td></tr>')


def _jobs_block(p: Pulse) -> str:
    if not p.featured:
        return ""
    rows = "".join(_job_block(j) for j in p.featured)
    return (_divider() + f'<tr><td class="apb-pad" style="padding:0 40px;">{_heading("Jobs worth a look")}'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table>'
            f'<div style="font-size:12px;color:{MUTED};margin-top:4px;">Every link goes straight to the employer&rsquo;s application page.</div>'
            f'</td></tr>')


def _read_time(news: NewsResult) -> str:
    chunks = []
    for s in ([news.lead] if news.lead else []) + list(news.stories):
        chunks += [s.title, s.summary]
    words = sum(len((c or "").split()) for c in chunks)
    return f"{words:,} words, a {max(1, round(words / 225))}-min. read"


def _share_link() -> str:
    body = "Thought you'd like this twice-weekly brief on AI policy news and AI jobs."
    if config.SUBSCRIBE_URL:
        body += " Subscribe free: " + config.SUBSCRIBE_URL
    return f"mailto:?subject={quote(config.BRAND_NAME)}&body={quote(body)}"


def render_brief(pulse: Pulse, news: NewsResult, today: dt.date = None, now: dt.datetime = None,
                 view_url: str = None, mailing_address: str = "") -> str:
    now = now or dt.datetime.now(dt.timezone.utc)
    today = today or now.date()

    stories_html = ""
    for i, s in enumerate(news.stories):
        if i:
            stories_html += _divider()
        stories_html += _story_block(s, now)
    if not stories_html:
        stories_html = (f'<tr><td style="font-size:14px;color:{MUTED};">'
                        f'No other stories cleared the bar this issue.</td></tr>')

    preheader = news.lead.title if news.lead else f"{pulse.total:,} open AI policy, comms, legal and consulting roles"
    top_bar = ", ".join(SECTION_COLORS.values())

    view = (f'<div style="margin-top:6px;"><a href="{esc(view_url)}" target="_blank" rel="noopener noreferrer" '
            f'style="font-size:12px;color:{MUTED};text-decoration:underline;font-weight:600;">View in browser</a></div>'
            ) if view_url else ""
    subscribe = (f'<div style="margin-top:4px;font-size:12px;color:{MUTED};">Forwarded to you? '
                 f'<a href="{esc(config.SUBSCRIBE_URL)}" style="color:{MUTED};font-weight:700;">Subscribe free &rarr;</a></div>'
                 ) if config.SUBSCRIBE_URL else ""
    share = (f'<tr><td class="apb-pad" style="padding:24px 40px 8px 40px;text-align:center;">'
             f'<div style="font-size:13px;font-weight:700;color:{INK};margin-bottom:10px;">Know someone who&rsquo;d want this?</div>'
             f'<a href="{esc(_share_link())}" style="display:inline-block;border:1.5px solid {INK};border-radius:6px;'
             f'padding:9px 18px;color:{INK};text-decoration:none;font-size:12px;font-weight:800;">'
             f'Share {esc(config.BRAND_NAME)} &rarr;</a></td></tr>') if config.SUBSCRIBE_URL else ""
    credit = (f'<div style="font-size:11px;margin-top:6px;"><a href="{esc(config.FOOTER_LINK_URL)}" '
              f'style="color:{MUTED};">{esc(config.FOOTER_LINK_TEXT)}</a></div>'
              ) if config.FOOTER_LINK_URL and config.FOOTER_LINK_TEXT else ""
    address = f'<div style="font-size:11px;color:{MUTED};margin-top:6px;">{esc(mailing_address)}</div>' if mailing_address else ""

    parts = [
        '<!DOCTYPE html><html><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        f'<title>{esc(config.BRAND_NAME)}</title>', _style_block(), '</head>',
        f'<body style="margin:0;padding:0;background-color:{BG};font-family:{BODY_FONT};">',
        f'<div style="display:none;max-height:0;overflow:hidden;mso-hide:all">{esc(preheader)}{"&nbsp;" * 40}</div>',
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{BG};padding:32px 0">',
        '<tr><td align="center">',
        f'<table role="presentation" width="600" class="apb-card" cellpadding="0" cellspacing="0" '
        f'style="background-color:{CARD};border-radius:14px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,0.06)">',
        f'<tr><td style="background-color:{ACCENT};background:linear-gradient(90deg,{top_bar});height:6px;line-height:6px;font-size:0">&nbsp;</td></tr>',
        '<tr><td class="apb-pad" style="padding:32px 40px 20px 40px">',
        f'<div style="font-size:26px;font-weight:900;color:{INK};letter-spacing:-0.5px;font-family:{HEADLINE_FONT};line-height:1;">'
        f'{esc(config.BRAND_NAME)}</div>',
        f'<div style="font-size:12px;color:{MUTED};margin-top:10px;font-weight:600;">{esc(_date_label(today))}</div>',
        f'<div style="font-size:12px;color:{MUTED};margin-top:4px;">{esc(_read_time(news))}</div>',
        view, subscribe, '</td></tr>',
        _lead_block(news.lead, now) if news.lead else "",
        _divider(),
        f'<tr><td class="apb-pad" style="padding:0 40px">{_heading("AI + Policy")}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{stories_html}</table></td></tr>',
        _divider(),
        _pulse_block(pulse),
        _jobs_block(pulse),
        share,
        f'<tr><td class="apb-pad" style="padding:16px 40px 36px 40px"><div style="border-top:1px solid {HAIRLINE};'
        f'padding-top:18px;text-align:center">'
        f'<div style="font-size:11px;color:{MUTED};">Headlines link to the original reporting. Paywalled outlets are marked.</div>'
        f'{credit}{address}'
        f'<div style="font-size:11px;color:{MUTED};margin-top:8px;"><a href="{{{{ unsubscribe }}}}" style="color:{MUTED};">Unsubscribe</a></div>'
        f'</div></td></tr>',
        '</table></td></tr></table></body></html>',
    ]
    return "".join(parts)
