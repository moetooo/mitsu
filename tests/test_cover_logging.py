"""Logging discipline for the cover code.

The cover subsystem is where the outage hid, so its log lines are the audit trail.
These tests keep that trail readable, and readable means four boring rules:

* the logger name says where the line came from, so the message does not repeat it
  in a `[canary]`-style prefix;
* a message is formatted lazily, so a disabled DEBUG line costs nothing;
* no full cover URL at INFO or above - hosts are what an operator acts on, and a
  URL in the log is a 100-character line that says "some image";
* no transport noise: `httpx` was writing one INFO line per probe and burying the
  summary this subsystem exists to produce.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent

COVER_MODULES = [
    "app/services/cover_canary.py",
    "app/services/cover_health.py",
    "app/services/cover_reports.py",
]

#: Modules that log about covers but are not themselves the cover subsystem.
RELATED_MODULES = [
    "app/ingestion/tenrai_client.py",
    "scripts/resolve_covers.py",
]

ALL_MODULES = COVER_MODULES + RELATED_MODULES
LOGGER_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}


def _tree(module: str) -> ast.Module:
    return ast.parse((APP_ROOT / module).read_text(encoding="utf-8"))


def _logger_calls(tree: ast.Module):
    """`(lineno, method, first_arg)` for every `logger.<level>(...)` call."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in LOGGER_METHODS:
            continue
        if not isinstance(func.value, ast.Name):
            continue
        if "log" not in func.value.id.lower():
            continue
        first = node.args[0] if node.args else None
        yield node.lineno, func.attr, first


def _literal_text(node) -> str:
    """The literal part of a message: a constant, or the left side of `"x %s" % value`."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp):
        return _literal_text(node.left)
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value for part in node.values if isinstance(part, ast.Constant)
        )
    return ""


def _call_texts(node: ast.Call) -> str:
    """Every literal string in the call, so a URL passed as an argument is caught."""
    return " ".join(_literal_text(arg) for arg in node.args)


def _getlogger_names(tree: ast.Module) -> list[str]:
    names = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "getLogger" and node.args:
            value = node.args[0]
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                names.append(value.value)
    return names


@pytest.mark.parametrize("module", ALL_MODULES)
def test_every_logger_is_namespaced_under_the_application(module):
    names = _getlogger_names(_tree(module))
    assert names, f"{module} logs nothing; if it is silent, remove it from this list"
    for name in names:
        assert name.startswith("mitsu."), f"{module} uses the unnamespaced logger {name!r}"


@pytest.mark.parametrize("module", COVER_MODULES)
def test_cover_modules_log_under_the_cover_namespace(module):
    # So `LOG_LEVEL` and log filters can be applied to the whole area at once, and a
    # reader knows where the line came from without reading the message.
    for name in _getlogger_names(_tree(module)):
        assert name.startswith("mitsu.covers."), f"{module} logs to {name!r}"


@pytest.mark.parametrize("module", ALL_MODULES)
def test_no_message_repeats_the_logger_name_as_a_prefix(module):
    """`"[canary] still blocked"` is a message that will drift from its logger."""
    offenders = []
    for number, level, first in _logger_calls(_tree(module)):
        text = _literal_text(first) if first is not None else ""
        if re.match(r"\s*\[[a-zA-Z_.-]+\]\s", text):
            offenders.append(f"{module}:{number} {level} -> {text[:40]!r}")
    assert not offenders, "drop the bracketed tag; the logger name carries it: " + ", ".join(offenders)


@pytest.mark.parametrize("module", ALL_MODULES)
def test_messages_are_formatted_lazily(module):
    """An f-string is built even when the line is filtered out at DEBUG."""
    offenders = [
        f"{module}:{number} {level}"
        for number, level, first in _logger_calls(_tree(module))
        if isinstance(first, ast.JoinedStr)
    ]
    assert not offenders, "use logger.info('...%s', value), not an f-string: " + ", ".join(offenders)


@pytest.mark.parametrize("module", ALL_MODULES)
def test_no_full_url_in_a_message_a_human_reads(module):
    """INFo and above are read by a person: a host is actionable, a 100-char URL is not."""
    offenders = []
    for node in ast.walk(_tree(module)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr in LOGGER_METHODS - {"debug"}):
            continue
        texts = _call_texts(node)
        if "http://" in texts or "https://" in texts:
            offenders.append(f"{module}:{node.lineno} {func.attr}")
    assert not offenders, "log the host, not the URL: " + ", ".join(offenders)


@pytest.mark.parametrize("module", COVER_MODULES)
def test_cover_services_do_not_print(module):
    # A `print` bypasses the log configuration: no level, no timestamp, and in the API
    # process it lands in the middle of a JSON body someone is streaming.
    source = (APP_ROOT / module).read_text(encoding="utf-8")
    assert not re.search(r"^\s*print\(", source, re.MULTILINE), f"{module} uses print()"


def test_the_repair_script_uses_the_project_log_configuration():
    # `basicConfig(level=INFO)` left `httpx` at INFO: 60 probe lines buried the
    # 4-line summary, and LOG_LEVEL / LOG_FORMAT were ignored.
    source = (APP_ROOT / "scripts/resolve_covers.py").read_text(encoding="utf-8")
    assert "configure_logging(" in source
    assert "logging.basicConfig(" not in source, "configure_logging silences the transport libraries"



def test_transport_libraries_are_kept_out_of_info():
    from app.core.logging import NOISY_LOGGERS

    for name in ("httpx", "httpcore"):
        assert name in NOISY_LOGGERS, f"{name} at INFO writes one line per request"


def test_the_verify_run_emits_a_bounded_number_of_lines(tmp_path, monkeypatch):
    """A summary per host plus one total, not one line per probed cover."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "scripts/resolve_covers.py", "--mode", "verify", "--sample-per-host", "2"],
        cwd=APP_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    log_lines = [line for line in (result.stderr + result.stdout).splitlines() if " covers." in line]
    # Three hosts plus the summary; anything near the probe count means per-item logging.
    assert len(log_lines) <= 8, "\n".join(log_lines)
