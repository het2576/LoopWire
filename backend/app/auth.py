"""Auth bridge between the Next.js dashboard and this API (Phase A, prdv2.md).

NextAuth handles Google sign-in entirely on the Next.js side and only ever
calls this backend from server-side code, which has already validated the
session. So the bridge is a shared secret proving "this call really came
from our Next.js server" plus an explicit user id to act as - no JWT/session
verification needed here, FastAPI just has to trust the header pair.
"""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User

INTERNAL_SECRET_HEADER = "X-Internal-Secret"
USER_ID_HEADER = "X-User-Id"


def verify_internal_secret(request: Request) -> None:
    """Used by endpoints that don't have a user yet (e.g. first-login
    provisioning) but still must only be callable by our own Next.js server."""
    settings = get_settings()
    secret = request.headers.get(INTERNAL_SECRET_HEADER)
    if not settings.internal_auth_secret or secret != settings.internal_auth_secret:
        raise HTTPException(status_code=401, detail="Invalid or missing internal secret")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    verify_internal_secret(request)

    user_id_header = request.headers.get(USER_ID_HEADER)
    if not user_id_header:
        raise HTTPException(status_code=401, detail="Missing user id")

    try:
        user_id = int(user_id_header)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid user id") from None

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    return user
