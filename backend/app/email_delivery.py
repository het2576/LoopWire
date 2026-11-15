"""Resend email delivery for Loopwire sends (Phase 4).

HTML uses table-based layout with inline styles only - no flexbox/grid - so
it renders correctly in Gmail's mobile app and Outlook, per PRD. A plain-text
alternative and a List-Unsubscribe header are included because HTML-only,
single-part emails from a brand-new sending domain are exactly what spam
filters flag first - this at least removes the parts that are within our
control (domain reputation and recipient engagement are not).
"""

from html import escape

import resend

from app.config import get_settings
from app.loopwire_send import DispatchBundle, LoopwireItemView
from app.models import ADAPTIVE_HALF_WEIGHT_SIGNALS
from app.timeutil import local_today

TYPE_LABEL = {
    "article": "Article", "youtube": "YouTube", "reddit": "Reddit", "github": "GitHub",
    "hn": "Hacker News", "pdf": "PDF", "unsupported": "Link",
}


def _e(value: object) -> str:
    """Every model- or page-derived string goes through this. Titles come from
    arbitrary web pages; unescaped, a crafted <title> could inject markup or
    phishing links into the user's own inbox under Loopwire's name."""
    return escape(str(value), quote=True) if value is not None else ""

INK = "#12161b"
PAPER = "#f6f2e9"
SIGNAL = "#c96a1f"  # darkened from the dashboard's #e08a3c for AA contrast on white
WIRE = "#6b7680"
ALERT = "#b23b30"
FONT_MONO = "ui-monospace, Menlo, Consolas, 'SFMono-Regular', monospace"
FONT_SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"


def _item_html(item: LoopwireItemView) -> str:
    read_link = _e(item.read_url)
    type_label = TYPE_LABEL.get(item.type, "Link")
    accent = ALERT if item.couldnt_extract else SIGNAL

    if item.couldnt_extract:
        reason = f"Couldn't process this one: {_e(item.failure_reason or 'unknown reason')}."
        body = f"""
          <div style="font-family:{FONT_MONO};font-size:11px;font-weight:600;letter-spacing:0.08em;color:{ALERT};text-transform:uppercase;">
            {type_label} &middot; couldn't extract
          </div>
          <div style="font-family:{FONT_SANS};font-size:17px;font-weight:600;color:{INK};margin:6px 0 8px;">{_e(item.title)}</div>
          <div style="font-family:{FONT_SANS};font-size:14px;color:#555555;line-height:1.55;">
            {reason} The original link is still here.
          </div>
        """
        link_label = "Open raw link"
    else:
        read_time = f"{item.read_time_minutes} min" if item.read_time_minutes else ""
        key_takeaway_html = (
            f'<div style="margin:8px 0 6px;padding-left:10px;border-left:3px solid {SIGNAL};'
            f'font-family:{FONT_SANS};font-size:14px;font-weight:600;color:{INK};line-height:1.5;">'
            f"{_e(item.key_takeaway)}</div>"
            if item.key_takeaway
            else ""
        )
        relevance = (
            f'<div style="font-family:{FONT_SANS};font-size:13px;font-style:italic;color:{WIRE};margin-top:8px;">{_e(item.relevance_note)}</div>'
            if item.relevance_note
            else ""
        )
        body = f"""
          <div style="font-family:{FONT_MONO};font-size:11px;font-weight:600;letter-spacing:0.08em;color:{WIRE};text-transform:uppercase;">
            {type_label}{" &middot; " + read_time if read_time else ""}
          </div>
          <div style="font-family:{FONT_SANS};font-size:17px;font-weight:600;color:{INK};margin:6px 0 4px;">{_e(item.title)}</div>
          {key_takeaway_html}
          <div style="font-family:{FONT_SANS};font-size:14px;color:#333333;line-height:1.55;">{_e(item.summary)}</div>
          {relevance}
        """
        link_label = "Read source"

    feedback_html = (
        ""
        if item.couldnt_extract
        else f'''<a href="{_e(item.feedback_up_url)}" style="font-family:{FONT_SANS};font-size:13px;color:{WIRE};text-decoration:none;margin-left:14px;">&#128077; More like this</a>
                <a href="{_e(item.feedback_down_url)}" style="font-family:{FONT_SANS};font-size:13px;color:{WIRE};text-decoration:none;margin-left:12px;">&#128078; Less</a>'''
    )

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
                {feedback_html}
              </div>
            </td>
          </tr>
        </table>
      </td>
    </tr>
    """


def personalization_note(bundle: DispatchBundle) -> str:
    """Says honestly how this dispatch was ordered, instead of implying it's
    personalized when it isn't yet."""
    ctx = bundle.ctx
    if ctx.is_adaptive:
        return "Ordered by what you've actually clicked and rated."
    if ctx.n_positive > 0:
        return (
            f"Learning from you — {ctx.n_positive}/{ADAPTIVE_HALF_WEIGHT_SIGNALS} clicks or ratings until "
            "your history outweighs your written profile."
        )
    if ctx.profile_vector is not None:
        return "Ordered by your written interest profile. Click or rate items to make it adaptive."
    return "Chronological order — set an interest profile or rate a few items to personalize this."


def _recall_html(bundle: DispatchBundle) -> str:
    if not bundle.recall:
        return ""
    dashboard = get_settings().dashboard_base_url.rstrip("/")
    questions = "".join(
        f'<div style="font-family:{FONT_SANS};font-size:14px;color:{INK};margin:10px 0 2px;font-weight:600;">{_e(c.question)}</div>'
        f'<div style="font-family:{FONT_SANS};font-size:12px;color:{WIRE};">from &ldquo;{_e(c.source_title)}&rdquo;</div>'
        for c in bundle.recall
    )
    return f"""
    <tr><td style="padding:0 0 16px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#ffffff;border:1px solid #e8e3d8;border-left:4px solid {INK};border-radius:6px;">
        <tr><td style="padding:18px 22px;">
          <div style="font-family:{FONT_MONO};font-size:11px;font-weight:600;letter-spacing:0.08em;color:{WIRE};text-transform:uppercase;">Recall &middot; do you still remember?</div>
          {questions}
          <div style="margin-top:12px;font-family:{FONT_SANS};font-size:13px;">
            Answer with <b>/quiz</b> in Telegram or on <a href="{_e(dashboard)}/recall" style="color:{SIGNAL};">your dashboard</a>.
          </div>
        </td></tr>
      </table>
    </td></tr>"""


def render_loopwire_html(bundle: DispatchBundle, period: str) -> str:
    items = bundle.items
    today = local_today().strftime("%B %d, %Y")
    rows = "\n".join(_item_html(item) for item in items)
    cold_start_note = personalization_note(bundle)
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
                  {_recall_html(bundle)}
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
                <img src="{_e(bundle.open_pixel_url)}" width="1" height="1" alt="" style="display:block;border:0;">
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def render_loopwire_text(bundle: DispatchBundle, period: str) -> str:
    items = bundle.items
    today = local_today().strftime("%B %d, %Y")
    lines = [f"LOOPWIRE - {period.upper()} DISPATCH", f"{today} - {len(items)} item(s)", ""]

    if bundle.recall:
        lines.append("RECALL - do you still remember?")
        lines.extend(f"  * {c.question}  (from \"{c.source_title}\")" for c in bundle.recall)
        lines.append("  Answer with /quiz in Telegram.")
        lines.append("")

    for item in items:
        read_link = item.read_url
        type_label = TYPE_LABEL.get(item.type, "Link")
        lines.append("-" * 40)
        if item.couldnt_extract:
            lines.append(f"[{type_label}] {item.title} (couldn't extract)")
            lines.append(f"Couldn't process this one: {item.failure_reason or 'unknown reason'}.")
        else:
            read_time = f" - {item.read_time_minutes} min" if item.read_time_minutes else ""
            lines.append(f"[{type_label}{read_time}] {item.title}")
            lines.append(item.summary or "")
            if item.relevance_note:
                lines.append(f"({item.relevance_note})")
        lines.append(f"Read: {read_link}")
        if not item.couldnt_extract:
            lines.append(f"More like this: {item.feedback_up_url}   Less: {item.feedback_down_url}")
        lines.append("")

    cold_start_note = personalization_note(bundle)
    lines.append("-- \nSent by Loopwire, your personal reading wire.")
    if cold_start_note:
        lines.append(cold_start_note)
    return "\n".join(lines)


def send_loopwire_email(bundle: DispatchBundle, period: str, to_email: str) -> str | None:
    """Returns the Resend email id, or None if sending was skipped (no key
    configured). `to_email` is the recipient's own account email (Phase A -
    multi-tenant, each user gets their own dispatch)."""
    settings = get_settings()
    if not settings.resend_api_key or not to_email:
        return None

    resend.api_key = settings.resend_api_key
    html = render_loopwire_html(bundle, period)
    text = render_loopwire_text(bundle, period)
    unsubscribe_address = settings.loopwire_from_email

    result = resend.Emails.send(
        {
            "from": f"Loopwire <{settings.loopwire_from_email}>",
            "to": [to_email],
            "subject": f"Loopwire - {period.capitalize()} dispatch - {len(bundle.items)} item(s)",
            "html": html,
            "text": text,
            "headers": {
                "List-Unsubscribe": f"<mailto:{unsubscribe_address}?subject=unsubscribe>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            },
        }
    )
    return result.get("id")
