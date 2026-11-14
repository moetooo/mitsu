import secrets
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ..auth import (
    SESSION_COOKIE,
    auth_required,
    credentials_configured,
    issue_session,
    read_session,
    verify_credentials,
)
from ..config import settings
from ..db import get_db
from ..sync.control import set_auto_enabled
from ..sync.guardrails import (
    GuardrailError,
    backfill_request_limit,
    effective_daily_limit,
    preflight_trigger,
)
from ..sync.service import run_backfill, run_sync, sync_status

router = APIRouter(prefix="/admin", tags=["admin"])

_DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "static" / "dashboard"
_DASHBOARD_FILE = _DASHBOARD_DIR / "dashboard.html"

_LOGIN_FAILURES: dict[str, tuple[int, float]] = {}
_LOGIN_MAX_FAILURES = 5
_LOGIN_WINDOW_SECONDS = 300


class LoginRequest(BaseModel):
    username: str = ""
    password: str = ""


def _guard_http(exc: GuardrailError) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail=exc.as_dict(),
        headers={"Retry-After": str(exc.retry_after or 60)},
    )


def _admin_authenticated(request: Request, x_admin_token: str | None) -> bool:
    """True when the caller presents a valid API token or session cookie."""
    if (
        settings.SYNC_ADMIN_TOKEN
        and x_admin_token
        and secrets.compare_digest(x_admin_token, settings.SYNC_ADMIN_TOKEN)
    ):
        return True
    return bool(read_session(request.cookies.get(SESSION_COOKIE)))


async def require_sync_admin(
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    """Protect admin endpoints with a session cookie or API token.

    The browser dashboard logs in with username/password and receives an
    HttpOnly cookie. `X-Admin-Token` stays available for cron/CLI jobs. This
    fails closed: with no token and no password login configured, callers get
    503 rather than anonymous access.
    """
    if _admin_authenticated(request, x_admin_token):
        return
    if not credentials_configured() and not settings.SYNC_ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="admin credentials are not configured")
    raise HTTPException(status_code=401, detail="Authentication required")


@router.get("/session")
async def admin_session(request: Request, response: Response):
    """Return login state without raising, so the dashboard can render a form."""
    response.headers["Cache-Control"] = "no-store"
    username = read_session(request.cookies.get(SESSION_COOKIE))
    return {
        "authenticated": bool(username),
        "username": username,
        "auth_required": auth_required(),
        "login_enabled": credentials_configured(),
    }


@router.post("/login")
async def admin_login(payload: LoginRequest, request: Request, response: Response):
    host = request.client.host if request.client else "unknown"
    failures, blocked_until = _LOGIN_FAILURES.get(host, (0, 0.0))
    now = time.time()
    if blocked_until > now:
        raise HTTPException(
            status_code=429,
            detail="too many login attempts; try again later",
            headers={"Retry-After": str(max(1, int(blocked_until - now)))},
        )
    if not credentials_configured():
        if not auth_required():
            return {"authenticated": True, "username": "", "auth_required": False}
        raise HTTPException(
            status_code=503,
            detail=(
                "password login is not configured; set SYNC_ADMIN_USERNAME and "
                "SYNC_ADMIN_PASSWORD"
            ),
        )
    if not verify_credentials(payload.username.strip(), payload.password):
        failures += 1
        blocked_until = now + _LOGIN_WINDOW_SECONDS if failures >= _LOGIN_MAX_FAILURES else 0.0
        _LOGIN_FAILURES[host] = (0 if blocked_until else failures, blocked_until)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    _LOGIN_FAILURES.pop(host, None)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    max_age = max(1, int(settings.SYNC_ADMIN_SESSION_HOURS)) * 3600
    response.set_cookie(
        SESSION_COOKIE,
        issue_session(settings.SYNC_ADMIN_USERNAME),
        max_age=max_age,
        httponly=True,
        secure=settings.SYNC_ADMIN_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return {
        "authenticated": True,
        "username": settings.SYNC_ADMIN_USERNAME,
        "auth_required": True,
        "login_enabled": True,
    }


@router.post("/logout")
async def admin_logout(response: Response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"authenticated": False}


@router.get("/ingestion-status", dependencies=[Depends(require_sync_admin)])
async def get_ingestion_status(db: AsyncSession = Depends(get_db)):
    query = text("""
        SELECT source,
               count(*) FILTER (WHERE enriched) AS done,
               count(*) FILTER (WHERE NOT enriched AND enrich_attempts < 5) AS pending,
               count(*) FILTER (WHERE NOT enriched AND enrich_attempts >= 5) AS stuck,
               count(*) AS total
        FROM discovery_queue
        GROUP BY source;
    """)

    result = await db.execute(query)
    rows = result.mappings().all()

    manga_count_res = await db.execute(text("SELECT count(*) FROM manga;"))
    total_manga = manga_count_res.scalar()

    anilist_count_res = await db.execute(text("SELECT count(*) FROM manga WHERE anilist_id IS NOT NULL;"))
    total_anilist = anilist_count_res.scalar()

    return {
        "total_manga_in_db": total_manga,
        "anilist_manga_count": total_anilist,
        "discovery_queue_status": [dict(r) for r in rows]
    }


@router.post("/sync", dependencies=[Depends(require_sync_admin)])
async def trigger_sync(
    background_tasks: BackgroundTasks,
    mode: str = Query(default="manual", pattern="^(manual|auto)$"),
    dry_run: bool = Query(default=False),
    max_pages: int | None = Query(default=None, ge=1, le=30),
    include_mangadex: bool = Query(default=True),
):
    """Queue one catalog refresh and return immediately.

    The job is lock-protected, so calling this twice produces one real run and
    one `skipped` run record. Daily run/cooldown guardrails are checked before
    the request is accepted so a rejected trigger spends no provider request.
    """
    try:
        guard = await preflight_trigger(mode)
    except GuardrailError as exc:
        raise _guard_http(exc)

    run_id = str(uuid.uuid4())
    background_tasks.add_task(
        run_sync,
        mode=mode,
        dry_run=dry_run,
        max_pages=max_pages,
        include_mangadex=include_mangadex,
        run_id=run_id,
    )
    return {
        "status": "accepted",
        "run_id": run_id,
        "mode": mode,
        "dry_run": dry_run,
        "daily_limit": effective_daily_limit("anilist"),
        "guardrails": guard,
        "status_url": "/admin/sync/status",
    }


@router.post("/backfill", dependencies=[Depends(require_sync_admin)])
async def trigger_backfill(
    background_tasks: BackgroundTasks,
    until: str = Query(default=settings.SYNC_BACKFILL_CUTOFF),
    dry_run: bool = Query(default=False),
    max_pages: int | None = Query(default=None, ge=1, le=30),
    budget: int | None = Query(default=None, ge=1),
):
    """Queue a resumable historical refresh up to the cutoff.

    `budget` can only lower or raise today's cap up to
    `SYNC_HARD_DAILY_CEILING`; the service clamps it again and keeps the
    daily-sync reserve.
    """
    effective_budget = backfill_request_limit(budget)
    if effective_budget <= 0:
        raise HTTPException(
            status_code=422,
            detail="backfill reserve leaves no requests for backfill today",
        )
    try:
        guard = await preflight_trigger("backfill")
    except GuardrailError as exc:
        raise _guard_http(exc)

    run_id = str(uuid.uuid4())
    background_tasks.add_task(
        run_backfill,
        until=until,
        dry_run=dry_run,
        max_pages=max_pages,
        budget_limit=budget,
        run_id=run_id,
    )
    return {
        "status": "accepted",
        "run_id": run_id,
        "mode": "backfill",
        "until": until,
        "effective_budget": effective_budget,
        "guardrails": guard,
        "status_url": "/admin/sync/status",
    }


@router.get("/sync/status", dependencies=[Depends(require_sync_admin)])
async def get_sync_status(
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
):
    return await sync_status(limit=limit, offset=offset)


@router.post("/auto", dependencies=[Depends(require_sync_admin)])
async def set_auto(enabled: bool = Query(...)):
    """Persist the auto-sync switch used by scheduled `mode=auto` runs."""
    state = await set_auto_enabled(enabled)
    return {"status": "ok", **state}


@router.get("/sync/health", dependencies=[Depends(require_sync_admin)])
async def get_sync_health():
    """Lightweight scheduler probe: enabled flags and last run outcome."""
    status = await sync_status(limit=1)
    last_run = status["runs"][0] if status["runs"] else None
    return {
        "enabled": status["enabled"],
        "auto_enabled": status["auto_enabled"],
        "budgets": status["budgets"],
        "guardrails": status["guardrails"],
        "last_run": last_run,
    }


@router.get("/dashboard", include_in_schema=False)
async def sync_dashboard():
    """Serve the control page shell.

    This one route has to stay public: the shell is the login form, so gating it
    would leave a signed-out operator with no way to sign in. It contains no
    data and no credentials (the admin token is never embedded in the HTML);
    every byte behind it comes from an endpoint guarded by `require_sync_admin`.
    """
    if not _DASHBOARD_FILE.is_file():
        raise HTTPException(
            status_code=503,
            detail="dashboard build is missing; run npm run build:dashboard in frontend/",
        )
    body = _DASHBOARD_FILE.read_text(encoding="utf-8")
    return HTMLResponse(
        body,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )