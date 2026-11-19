"""The logging contract: one configuration, compact lines, no transport chatter.

Three defects this pins, all observed in a real run:

1. `httpx` logged a full-URL line for every outbound call because the root logger
   was configured at INFO, so the application line was buried in transport detail.
2. A provider failure printed its whole multi-line error dict on every request.
3. Nothing tied a log line to the request that produced it.

The format is a contract here, not decoration: tests read the formatted output.
"""

import json
import logging

import pytest

from app.core.logging import (
    NOISY_LOGGERS,
    configure_logging,
    request_id_var,
)


def _root_handler():
    handlers = logging.getLogger().handlers
    assert len(handlers) == 1, f"expected one root handler, found {len(handlers)}"
    return handlers[0]


def _format(record: logging.LogRecord) -> str:
    handler = _root_handler()
    for log_filter in handler.filters:
        log_filter.filter(record)
    return handler.format(record)


@pytest.fixture(autouse=True)
def _restore_logging():
    root = logging.getLogger()
    original_level = root.level
    original_handlers = list(root.handlers)
    yield
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in original_handlers:
        root.addHandler(handler)
    root.setLevel(original_level)
    request_id_var.set("")


def test_configure_is_idempotent_and_keeps_one_handler():
    configure_logging()
    configure_logging()
    configure_logging()

    assert len(logging.getLogger().handlers) == 1


def test_plain_lines_are_compact_and_carry_a_short_level_and_logger():
    configure_logging(level_override="INFO", log_format="plain")
    record = logging.LogRecord("mitsu.llm", logging.WARNING, __file__, 1, "reasoning skipped", None, None)

    line = _format(record)

    # "16:26:03 WARN llm: reasoning skipped" - no date, no package prefix, no
    # brackets around the level, one line, no empty request-id slot.
    assert line.endswith(" WARN llm: reasoning skipped")
    assert "mitsu." not in line
    assert "[" not in line
    assert line.count("\n") == 0


def test_json_lines_are_one_object_per_record():
    configure_logging(level_override="INFO", log_format="json")

    payload = json.loads(_format(logging.LogRecord("mitsu.http", logging.INFO, __file__, 1, "GET /health 200 2ms", None, None)))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "mitsu.http"
    assert payload["msg"] == "GET /health 200 2ms"
    assert "request_id" not in payload


def test_request_id_is_stamped_on_records_emitted_inside_a_request():
    configure_logging(level_override="INFO", log_format="plain")
    token = request_id_var.set("12ab34cd")
    try:
        line = _format(logging.LogRecord("mitsu.http", logging.INFO, __file__, 1, "POST /recommend 200 84ms", None, None))
    finally:
        request_id_var.reset(token)

    assert "[12ab34cd]" in line
    assert "POST /recommend 200 84ms" in line


def test_transport_libraries_are_pinned_above_info():
    configure_logging(level_override="INFO")

    for name in NOISY_LOGGERS:
        assert logging.getLogger(name).level >= logging.WARNING
    # Our own loggers still honour the configured level.
    assert logging.getLogger().level == logging.INFO


def test_log_level_override_beats_the_environment_and_junk_falls_back(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "WARNING")

    configure_logging(level_override="DEBUG")
    assert logging.getLogger().level == logging.DEBUG

    configure_logging(level_override="not-a-level")
    assert logging.getLogger().level == logging.INFO


def test_json_format_from_environment_is_honoured(monkeypatch):
    monkeypatch.setattr("app.config.settings.LOG_FORMAT", "json")

    configure_logging(level_override="INFO")

    payload = json.loads(_format(logging.LogRecord("mitsu", logging.INFO, __file__, 1, "schema ok", None, None)))
    assert payload == {"ts": payload["ts"], "level": "INFO", "logger": "mitsu", "msg": "schema ok"}


def test_stream_argument_keeps_a_machine_read_stdout_clean(capsys):
    """The sync CLI prints one JSON object on stdout.

    Its logs must go to stderr, otherwise every caller that parses stdout sees
    a log line in front of the JSON (a real run reported `unknown error`).
    """
    import sys

    configure_logging(level_override="INFO", log_format="plain", stream=sys.stderr)
    logging.getLogger("mitsu.core.schema").info("Seeded 0 external-ID mappings.")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Seeded 0 external-ID mappings." in captured.err


def test_uvicorn_access_logger_is_silenced_in_favour_of_our_own_line():
    """uvicorn prints `127.0.0.1:8918 - "GET /vocabulary HTTP/1.1" 200 OK` - no
    timestamp, no duration, no request id - for every request we already log.
    Two formats for one event is the inconsistency; ours is the one that stays.
    """
    access = logging.getLogger("uvicorn.access")
    access.handlers = [logging.StreamHandler()]
    access.propagate = True
    access.disabled = False

    configure_logging(level_override="INFO")

    assert access.handlers == []
    assert access.propagate is False
    assert access.disabled is True
