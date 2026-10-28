import hmac

from fastapi import Header, HTTPException, status
from firebase_admin import auth

from .config import get_settings
from .firebase import init_app


def require_user(authorization: str = Header(default="")) -> str:
    """Verify the Firebase ID token sent by the dashboard."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    init_app()
    try:
        decoded = auth.verify_id_token(authorization.removeprefix("Bearer "))
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    if decoded["uid"] != get_settings().jarvis_uid:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your Jarvis")
    return decoded["uid"]


def require_cron(x_cron_secret: str = Header(default="")) -> None:
    expected = get_settings().cron_secret
    if not expected or not hmac.compare_digest(x_cron_secret, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad cron secret")
