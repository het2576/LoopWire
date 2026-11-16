"""Signed, unguessable tokens for the public engagement links.

/r/<token> (click-through), /f/<token>/<up|down> (feedback) and the per-send
open pixel all have to work from inside an email client, which can't send an
auth header - so the link itself is the credential. A bare sequential id is
not a credential: it let anyone enumerate every user's saved URLs and forge
engagement into anyone's ranking. Each token is `<id>.<hmac>` with the HMAC
bound to a purpose string, so a click token can't be replayed as a feedback
token for the same item.
"""

import base64
import hashlib
import hmac

from app.config import get_settings

PURPOSE_CLICK = "click"
PURPOSE_FEEDBACK = "feedback"
PURPOSE_SEND_OPEN = "send-open"

_SIG_BYTES = 12  # 96-bit tag: far beyond brute-force range for a URL token


def _key() -> bytes:
    settings = get_settings()
    secret = settings.tracking_signing_secret or settings.internal_auth_secret
    if not secret:
        raise RuntimeError(
            "TRACKING_SIGNING_SECRET (or INTERNAL_AUTH_SECRET) must be set - "
            "engagement links are never issued unsigned."
        )
    return secret.encode()


def _sig(purpose: str, object_id: int) -> str:
    mac = hmac.new(_key(), f"{purpose}:{object_id}".encode(), hashlib.sha256).digest()[:_SIG_BYTES]
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()


def sign(purpose: str, object_id: int) -> str:
    return f"{object_id}.{_sig(purpose, object_id)}"


def verify(purpose: str, token: str) -> int | None:
    """Returns the object id if the token is authentic for this purpose."""
    raw_id, sep, signature = token.partition(".")
    if not sep or not raw_id.isdigit():
        return None
    object_id = int(raw_id)
    if not hmac.compare_digest(signature, _sig(purpose, object_id)):
        return None
    return object_id


def click_url(item_id: int) -> str:
    return f"{get_settings().backend_base_url.rstrip('/')}/r/{sign(PURPOSE_CLICK, item_id)}"


def feedback_url(item_id: int, vote: str) -> str:
    return f"{get_settings().backend_base_url.rstrip('/')}/f/{sign(PURPOSE_FEEDBACK, item_id)}/{vote}"


def send_open_pixel_url(send_id: int) -> str:
    return f"{get_settings().backend_base_url.rstrip('/')}/track/send/{sign(PURPOSE_SEND_OPEN, send_id)}.png"
