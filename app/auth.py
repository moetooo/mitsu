"""Password login and cookie sessions for the admin dashboard.

Credentials come from ``SYNC_ADMIN_USERNAME`` and ``SYNC_ADMIN_PASSWORD``.
Both default to ``admin`` for local use; change them before exposing the API.
Passwords are compared in constant time and sent only in a POST body; the
browser receives an HttpOnly, SameSite=Lax cookie.

The legacy ``X-Admin-Token`` header remains available for scheduler/API
automation, but the browser dashboard uses the login form.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from .config import settings

SESSION_COOKIE = "mitsu_admin_session"


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def credentials_configured() -> bool:
    return bool(settings.SYNC_ADMIN_USERNAME and settings.SYNC_ADMIN_PASSWORD)


def auth_required() -> bool:
    """The admin surface is always authenticated.

    With no password credentials and no API token, guarded endpoints fail
    closed with 503 instead of falling through to an anonymous caller.
    """
    return True


def verify_credentials(username: str, password: str) -> bool:
    if not credentials_configured():
        return False
    user_ok = hmac.compare_digest(username, settings.SYNC_ADMIN_USERNAME)
    password_ok = hmac.compare_digest(password, settings.SYNC_ADMIN_PASSWORD)
    return user_ok and password_ok


def _session_secret() -> bytes:
    # A dedicated secret is best. Fall back to a value derived from the
    # credentials so multiple workers agree and sessions survive a restart.
    secret = settings.SYNC_ADMIN_SESSION_SECRET or (
        f"{settings.SYNC_ADMIN_USERNAME}:{_configured_secret()}"
    )
    return hashlib.sha256(secret.encode("utf-8")).digest()


def issue_session(username: str) -> str:
    """Return a signed, expiring session value for the cookie."""
    expires_at = int(time.time()) + max(1, int(settings.SYNC_ADMIN_SESSION_HOURS)) * 3600
    payload = _b64encode(
        json.dumps(
            {"u": username, "exp": expires_at},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signature = hmac.new(_session_secret(), payload.encode("ascii"), hashlib.sha256).digest()
    return f"{payload}.{_b64encode(signature)}"


def read_session(value: str | None) -> str | None:
    """Return the authenticated username for a valid cookie, else ``None``."""
    if not value or "." not in value:
        return None
    payload, signature = value.rsplit(".", 1)
    expected = hmac.new(_session_secret(), payload.encode("ascii"), hashlib.sha256).digest()
    try:
        provided = _b64decode(signature)
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(expected, provided):
        return None
    try:
        data = json.loads(_b64decode(payload))
        expires_at = int(data.get("exp") or 0)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    if expires_at <= int(time.time()):
        return None
    username = str(data.get("u") or "")
    if not credentials_configured() or not hmac.compare_digest(username, settings.SYNC_ADMIN_USERNAME):
        return None
    return username
