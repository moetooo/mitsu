"""One line per request, with the id that ties a failure to it.

The API had no request log of its own: uvicorn printed an access line in a
different format, our records carried no request reference, and a slow endpoint
left no duration anywhere.
"""

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.logging import configure_logging, request_id_var
from app.middleware.request_log import RequestLogMiddleware


class _Collect(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _client(handler_collector):
    app = FastAPI()
    app.add_middleware(RequestLogMiddleware)

    @app.get("/items")
    async def items():
        logging.getLogger("mitsu.testing").info("inside the request")
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/boom")
    async def boom():
        raise RuntimeError("kaboom")

    target = logging.getLogger("mitsu.http")
    target.addHandler(handler_collector)
    target.setLevel(logging.INFO)
    return TestClient(app, raise_server_exceptions=False), target


def test_one_log_line_per_request_with_status_and_duration():
    configure_logging(level_override="INFO", log_format="plain")
    collector = _Collect()
    client, target = _client(collector)
    try:
        client.get("/items")
    finally:
        target.removeHandler(collector)

    lines = [r.getMessage() for r in collector.records]
    assert len(lines) == 1
    assert lines[0].startswith("GET /items 200 ")
    assert lines[0].endswith("ms")


def test_health_and_static_paths_are_not_logged():
    configure_logging(level_override="INFO", log_format="plain")
    collector = _Collect()
    client, target = _client(collector)
    try:
        client.get("/health")
    finally:
        target.removeHandler(collector)

    assert collector.records == []


def test_the_request_id_reaches_the_records_the_request_emitted():
    configure_logging(level_override="INFO", log_format="plain")
    collector = _Collect()
    other = _Collect()
    client, target = _client(collector)
    inner = logging.getLogger("mitsu.testing")
    inner.addHandler(other)
    inner.setLevel(logging.INFO)
    try:
        client.get("/items")
    finally:
        target.removeHandler(collector)
        inner.removeHandler(other)

    request_id = getattr(other.records[0], "request_id", "")
    assert len(request_id) == 8
    # The access line carries the same id, so the two lines pair up.
    assert getattr(collector.records[0], "request_id", "") == request_id
    # And the id does not leak past the request.
    assert request_id_var.get() == ""


def test_a_failing_request_logs_the_traceback_once_and_still_reports_the_line():
    configure_logging(level_override="INFO", log_format="plain")
    collector = _Collect()
    client, target = _client(collector)
    try:
        client.get("/boom")
    finally:
        target.removeHandler(collector)

    errors = [r for r in collector.records if r.levelname == "ERROR"]
    infos = [r for r in collector.records if r.levelname == "INFO"]
    assert len(errors) == 1
    assert errors[0].exc_info is not None
    assert len(infos) == 1
    assert "GET /boom 500 " in infos[0].getMessage()
