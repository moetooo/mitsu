"""One logging configuration for the API, the CLI and the maintenance scripts.

Three entry points used to call `logging.basicConfig` with three different
formats, and all of them configured the *root* logger at INFO. That had two
consequences worth naming:

1. Every third-party library inherited INFO, so `httpx` printed a full-URL line
   for every outbound call ("HTTP Request: POST https://api.groq.com/...") next
   to our own lines. The interesting line was buried in transport chatter.
2. A provider failure logged its whole error dict, wrapping one 404 across three
   terminal lines, and nothing tied a log line to the request that caused it.

What this module does instead, in one place:

- `LOG_LEVEL` (default INFO) and `LOG_FORMAT=plain|json` from the environment;
- a compact plain line — time, 4-character level, short logger name, message;
- transport libraries pinned to WARNING, so our lines are the only lines unless
  something actually goes wrong;
- a request id carried in a context variable and stamped onto every record
  emitted while a request is in flight (`app/middleware/request_log.py` sets it);
- idempotent setup: calling it twice does not double every line.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any, Dict, Optional

# Set for the duration of a request by `RequestLogMiddleware`; empty otherwise.
request_id_var: ContextVar[str] = ContextVar("mitsu_request_id", default="")

# Libraries whose INFO output is transport detail, not application events.
NOISY_LOGGERS = ("httpx", "httpcore", "urllib3", "hpack", "multipart", "asyncio", "watchfiles")

PLAIN_FORMAT = "%(asctime)s %(level_short)s %(name_short)s: %(message)s"
DATE_FORMAT = "%H:%M:%S"
# 4 characters so the level column stays aligned without finishing a line.
_LEVEL_SHORT = {
    "CRITICAL": "CRIT",
    "ERROR": "ERR ",
    "WARNING": "WARN",
    "INFO": "INFO",
    "DEBUG": "DEBG",
    "NOTSET": "    ",
}


class _RecordShape(logging.Filter):
    """Adds the derived fields the compact format prints, plus the request id."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.level_short = _LEVEL_SHORT.get(record.levelname, record.levelname[:4])
        name = record.name
        # "mitsu.llm" -> "llm": the package is on every line and says nothing new.
        if name == "mitsu":
            name = "api"
        elif name.startswith("mitsu."):
            name = name[len("mitsu."):]
        record.name_short = name
        record.request_id = request_id_var.get()
        return True


class _PlainFormatter(logging.Formatter):
    """`16:26:03 WARN llm: message`, with `[request id]` only when relevant.

    A fixed format string cannot make a field conditional without leaving an
    empty bracket on every background line, so the line is assembled here.
    """

    def format(self, record: logging.LogRecord) -> str:
        stamp = self.formatTime(record, DATE_FORMAT)
        request_id = getattr(record, "request_id", "")
        prefix = f"{stamp} {record.level_short} "
        if request_id:
            prefix += f"[{request_id}] "
        line = f"{prefix}{record.name_short}: {record.getMessage()}"
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


class _JsonFormatter(logging.Formatter):
    """One object per line, for a log shipper. No multi-line records."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        request_id = getattr(record, "request_id", "") or ""
        if request_id:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _build_handler(log_format: str, stream: Any = None) -> logging.Handler:
    # Default is stdout, which is right for the API. The sync CLI passes stderr
    # instead: its stdout is a machine-read JSON blob (`app/sync/service.py`),
    # and one log line in front of it breaks every caller that parses it.
    handler = logging.StreamHandler(stream or sys.stdout)
    if log_format == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(_PlainFormatter())
    handler.addFilter(_RecordShape())
    return handler


def configure_logging(
    level_override: Optional[str] = None,
    log_format: Optional[str] = None,
    stream: Any = None,
) -> logging.Logger:
    """Configure the root logger once, from `LOG_LEVEL` / `LOG_FORMAT`.

    `level_override` exists for the sync CLI's `--log-level`, which must beat the
    environment for a single run. Unknown values fall back to INFO instead of
    raising: a bad log level must not stop the process that logs.

    `stream` defaults to stdout. A command whose stdout is consumed by a program
    (the sync CLI prints one JSON summary) must pass stderr instead.
    """
    from ..config import settings

    level_name = (level_override or settings.LOG_LEVEL or "INFO").upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        level = logging.INFO
    shape = (log_format or settings.LOG_FORMAT or "plain").lower()

    root = logging.getLogger()
    # Replace, never append: a second call (or an earlier basicConfig) must not
    # leave two handlers writing every line twice.
    for existing in list(root.handlers):
        root.removeHandler(existing)
        existing.close()
    root.addHandler(_build_handler(shape, stream))
    root.setLevel(level)

    # Transport libraries keep their own level: WARNING still reports retries and
    # connection problems, INFO only reports "I called a URL".
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(max(level, logging.WARNING))

    # uvicorn installs its own handlers with its own ``INFO:     `` prefix. Drop
    # them for the two startup/shutdown loggers and let those records travel to
    # the root handler, so a boot sequence is one style rather than two.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        for handler in list(uvicorn_logger.handlers):
            uvicorn_logger.removeHandler(handler)
        uvicorn_logger.propagate = True

    # The access line is ours (`RequestLogMiddleware`): it carries the request id
    # and the duration, which uvicorn's does not. Silencing uvicorn's copy here -,
    # not only via `--no-access-log` - means one line per request whichever way
    # the server was started, and no reliance on a flag being remembered.
    access_logger = logging.getLogger("uvicorn.access")
    for handler in list(access_logger.handlers):
        access_logger.removeHandler(handler)
    access_logger.propagate = False
    access_logger.disabled = True

    logging.getLogger("mitsu").debug(
        "Logging configured (level=%s, format=%s).", logging.getLevelName(level), shape
    )
    return logging.getLogger("mitsu")
