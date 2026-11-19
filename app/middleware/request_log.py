"""One line per request, and the id that ties a failure back to it.

Before this, the API had no request log of its own: uvicorn printed an access
line with its own timestamp and format, our log lines carried no request
reference at all, and a slow endpoint left no duration anywhere. Reproducing a
user report meant guessing from timestamps.

The line is deliberately short — `POST /recommend 200 84ms` — because it is the
most frequent record in the log and the request id is already stamped on it by
the logging filter. Health checks and static assets are skipped: they are noise
that would drown the endpoints a user actually calls.
"""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from ..core.logging import request_id_var

logger = logging.getLogger("mitsu.http")

# Not application traffic: probes, the dashboard bundle, the OpenAPI pages.
SKIP_PREFIXES = (
    "/health",
    "/admin/assets",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon",
)


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith(SKIP_PREFIXES):
            return await call_next(request)

        # 8 hex characters: long enough to be unique inside one log file, short
        # enough that it does not dominate the line.
        token = request_id_var.set(uuid.uuid4().hex[:8])
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.exception("%s %s failed after %.0fms", request.method, path, elapsed_ms)
            raise
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info("%s %s %s %.0fms", request.method, path, status, elapsed_ms)
            request_id_var.reset(token)
