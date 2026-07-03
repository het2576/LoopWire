"""Resend email delivery for Loopwire sends (Phase 4).

HTML uses table-based layout with inline styles only - no flexbox/grid - so
it renders correctly in Gmail's mobile app and Outlook, per PRD. A plain-text
alternative and a List-Unsubscribe header are included because HTML-only,
single-part emails from a brand-new sending domain are exactly what spam
filters flag first - this at least removes the parts that are within our
control (domain reputation and recipient engagement are not).
"""

import datetime as dt

import resend

from app.config import get_settings
from app.loopwire_send import LoopwireItemView
from app.models import COLD_START_ENGAGEMENT_THRESHOLD

TYPE_LABEL = {"article": "Article", "youtube": "YouTube", "unsupported": "Link"}

INK = "#12161b"
PAPER = "#f6f2e9"
SIGNAL = "#c96a1f"  # darkened from the dashboard's #e08a3c for AA contrast on white
WIRE = "#6b7680"
ALERT = "#b23b30"
FONT_MONO = "ui-monospace, Menlo, Consolas, 'SFMono-Regular', monospace"
FONT_SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"


def _item_html(item: LoopwireItemView, backend_base_url: str) -> str:
    read_link = f"{backend_base_url}/r/{item.item_id}"
    open_pixel = (
        f'<img src="{backend_base_url}/track/opened/{item.item_id}.png" '
        f'width="1" height="1" alt="" style="display:block;border:0;">'
    )
    type_label = TYPE_LABEL.get(item.type, "Link")
    accent = ALERT if item.couldn_t_extract else SIGNAL

    if item.couldn_t_extract:
        reason = (
            "This source isn't supported for extraction yet (e.g. social posts or playlists)."
            if item.type == "unsupported"
            else "We couldn't pull readable content from this one (paywall or missing captions, most likely)."
        )
        body = f"""
          <div style="font-family:{FONT_MONO};font-size:11px;font-weight:600;letter-spacing:0.08em;color:{ALERT};text-transform:uppercase;">
            {type_label} &middot; couldn't extract
          </div>
          <div style="font-family:{FONT_SANS};font-size:17px;font-weight:600;color:{INK};margin:6px 0 8px;">{item.title}</div>
          <div style="font-family:{FONT_SANS};font-size:14px;color:#555555;line-height:1.55;">
            {reason} The raw link is still here.
          </div>
        """
        link_label = "Open raw link"
    else:
        read_time = f"{item.read_time_minutes} min" if item.read_time_minutes else ""
        key_takeaway_html = (
            f'<div style="margin:8px 0 6px;padding-left:10px;border-left:3px solid {SIGNAL};'
            f'font-family:{FONT_SANS};font-size:14px;font-weight:600;color:{INK};line-height:1.5;">'
            f"{item.key_takeaway}</div>"
            if item.key_takeaway
            else ""
        )
        relevance = (
            f'<div style="font-family:{FONT_SANS};font-size:13px;font-style:italic;color:{WIRE};margin-top:8px;">{item.relevance_note}</div>'
            if item.relevance_note
            else ""
        )
        body = f"""
          <div style="font-family:{FONT_MONO};font-size:11px;font-weight:600;letter-spacing:0.08em;color:{WIRE};text-transform:uppercase;">
            {type_label}{" &middot; " + read_time if read_time else ""}
          </div>
          <div style="font-family:{FONT_SANS};font-size:17px;font-weight:600;color:{INK};margin:6px 0 4px;">{item.title}</div>
          {key_takeaway_html}
          <div style="font-family:{FONT_SANS};font-size:14px;color:#333333;line-height:1.55;">{item.summary}</div>
          {relevance}
        """
        link_label = "Read source"

    return f"""
    <tr>
      <td style="padding:0 0 16px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#ffffff;border:1px solid #e8e3d8;border-left:4px solid {accent};border-radius:6px;">
          <tr>
            <td style="padding:20px 22px;">
              {body}
              <div style="margin-top:14px;">
                <a href="{read_link}" style="display:inline-block;font-family:{FONT_MONO};font-size:12px;font-weight:600;letter-spacing:0.04em;color:#ffffff;background-color:{INK};padding:9px 16px;border-radius:5px;text-decoration:none;">
                  {link_label} &rarr;
                </a>
              </div>
            </td>
          </tr>
        </table>
        {open_pixel}
      </td>
    </tr>
    """


def _cold_start_footer_note(cold_start: bool, engagement_count: int | None) -> str:
    """Bonus UX item (prdv2.md, bottom section): tells still-cold-start
    users the dispatch is still using their static profile, not silently
    pretending it's already adaptive."""
    if not cold_start or engagement_count is None:
        return ""
    return (
        f"Digests get sharper as you use Loopwire — {engagement_count}/"
        f"{COLD_START_ENGAGEMENT_THRESHOLD} interactions to go before they adapt to you."
    )


def render_loopwire_html(
    items: list[LoopwireItemView],
    period: str,
    backend_base_url: str,
    cold_start: bool = False,
    engagement_count: int | None = None,
) -> str:
    today = dt.date.today().strftime("%B %d, %Y")
    rows = "\n".join(_item_html(item, backend_base_url) for item in items)
    cold_start_note = _cold_start_footer_note(cold_start, engagement_count)
    cold_start_html = (
        f'<div style="font-family:{FONT_SANS};font-size:12px;color:{SIGNAL};margin-top:8px;">{cold_start_note}</div>'
        if cold_start_note
        else ""
    )

    return f"""<!doctype html>
<html>
  <body style="margin:0;padding:0;background-color:{PAPER};">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{PAPER};">
      <tr>
        <td align="center" style="padding:28px 12px;">
          <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:600px;max-width:100%;">
            <tr>
              <td style="background-color:{INK};border-radius:8px 8px 0 0;padding:22px 24px;">
                <div style="font-family:{FONT_MONO};font-size:15px;font-weight:700;letter-spacing:0.18em;color:#ffffff;">
                  &#9679; LOOPWIRE
                </div>
                <div style="font-family:{FONT_MONO};font-size:11px;letter-spacing:0.06em;color:#9aa3a6;margin-top:6px;">
                  {period.upper()} DISPATCH &middot; {today} &middot; {len(items)} ITEM{"S" if len(items) != 1 else ""}
                </div>
              </td>
            </tr>
            <tr>
              <td style="background-color:{PAPER};padding:22px 20px 4px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
                  {rows}
                </table>
              </td>
            </tr>
            <tr>
              <td style="background-color:{PAPER};border-radius:0 0 8px 8px;padding:4px 24px 24px;">
                <div style="font-family:{FONT_SANS};font-size:12px;color:#9a9488;border-top:1px solid #e8e3d8;padding-top:16px;">
                  Sent by Loopwire, your personal reading wire.
                </div>
                {cold_start_html}
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def render_loopwire_text(
    items: list[LoopwireItemView],
    period: str,
    backend_base_url: str,
    cold_start: bool = False,
    engagement_count: int | None = None,
) -> str:
    today = dt.date.today().strftime("%B %d, %Y")
    lines = [f"LOOPWIRE - {period.upper()} DISPATCH", f"{today} - {len(items)} item(s)", ""]

    for item in items:
        read_link = f"{backend_base_url}/r/{item.item_id}"
        type_label = TYPE_LABEL.get(item.type, "Link")
        lines.append("-" * 40)
        if item.couldn_t_extract:
            lines.append(f"[{type_label}] {item.title} (couldn't extract)")
            lines.append("We couldn't pull readable content from this one.")
        else:
            read_time = f" - {item.read_time_minutes} min" if item.read_time_minutes else ""
            lines.append(f"[{type_label}{read_time}] {item.title}")
            lines.append(item.summary or "")
            if item.relevance_note:
                lines.append(f"({item.relevance_note})")
        lines.append(f"Read: {read_link}")
        lines.append("")

    cold_start_note = _cold_start_footer_note(cold_start, engagement_count)
    lines.append("-- \nSent by Loopwire, your personal reading wire.")
    if cold_start_note:
        lines.append(cold_start_note)
    return "\n".join(lines)


def send_loopwire_email(
    items: list[LoopwireItemView],
    period: str,
    to_email: str,
    cold_start: bool = False,
    engagement_count: int | None = None,
) -> str | None:
    """Returns the Resend email id, or None if sending was skipped (no key
    configured). `to_email` is the recipient's own account email (Phase A -
    multi-tenant, each user gets their own dispatch)."""
    settings = get_settings()
    if not settings.resend_api_key or not to_email:
        return None

    resend.api_key = settings.resend_api_key
    html = render_loopwire_html(items, period, settings.backend_base_url, cold_start, engagement_count)
    text = render_loopwire_text(items, period, settings.backend_base_url, cold_start, engagement_count)
    unsubscribe_address = settings.loopwire_from_email

    result = resend.Emails.send(
        {
            "from": f"Loopwire <{settings.loopwire_from_email}>",
            "to": [to_email],
            "subject": f"Loopwire - {period.capitalize()} dispatch - {len(items)} item(s)",
            "html": html,
            "text": text,
            "headers": {
                "List-Unsubscribe": f"<mailto:{unsubscribe_address}?subject=unsubscribe>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            },
        }
    )
    return result.get("id")
