from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from ..config import settings
from ..db import AsyncSessionLocal
from ..db_models import SyncSetting

logger = logging.getLogger("mitsu.sync.control")

AUTO_ENABLED_KEY = "auto_enabled"


def _as_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in ("true", "1", "yes", "on")


async def auto_state() -> dict[str, bool | str]:
    """Effective auto-sync state: a database override wins over the env default."""
    try:
        async with AsyncSessionLocal() as session:
            value = await session.scalar(
                select(SyncSetting.value).where(SyncSetting.key == AUTO_ENABLED_KEY)
            )
    except Exception as exc:
        # A fresh database may not have sync_settings yet; env stays authoritative.
        # Log it: silently falling back made a broken connection look like an
        # unset switch.
        logger.warning("auto_state could not read sync_settings: %s", exc)
        return {"enabled": bool(settings.SYNC_AUTO_ENABLED), "source": "env"}
    if value is None:
        return {"enabled": bool(settings.SYNC_AUTO_ENABLED), "source": "env"}
    return {"enabled": _as_bool(value), "source": "database"}


async def get_auto_enabled() -> bool:
    return bool((await auto_state())["enabled"])


async def set_auto_enabled(enabled: bool) -> dict[str, bool | str]:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            row = await session.get(SyncSetting, AUTO_ENABLED_KEY)
            if row is None:
                session.add(SyncSetting(key=AUTO_ENABLED_KEY, value="true" if enabled else "false"))
            else:
                row.value = "true" if enabled else "false"
                row.updated_at = datetime.now(timezone.utc)
    return {"enabled": bool(enabled), "source": "database"}
