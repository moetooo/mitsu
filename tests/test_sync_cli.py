"""The sync CLI's stdout is a program-facing contract: one JSON blob, no logs.

The launcher prompt redirects stdout to a file and parses it as JSON. A real
auto run on 2026-11-18 printed `Seeded 0 external-ID mappings.` on stdout, so the
parse failed and the popup reported `The sync failed ... unknown error` for a run
that had actually succeeded. Logs belong on stderr.
"""

import json
import logging

import pytest

from app.sync import cli


@pytest.fixture(autouse=True)
def _restore_logging():
    root = logging.getLogger()
    original_level = root.level
    original_handlers = list(root.handlers)
    yield
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    for handler in original_handlers:
        root.addHandler(handler)
    root.setLevel(original_level)


def test_status_keeps_stdout_parseable_and_sends_logs_to_stderr(monkeypatch, capsys):
    async def fake_status(**kwargs):
        logging.getLogger("mitsu.core.schema").info("Seeded 0 external-ID mappings.")
        return {"guardrails": {"runs_today": 1}}

    monkeypatch.setattr(cli, "sync_status", fake_status)

    assert cli.main(["status"]) == 0

    captured = capsys.readouterr()
    # Exactly the JSON summary, with no timestamped line glued to the front.
    assert json.loads(captured.out) == {"guardrails": {"runs_today": 1}}
    assert "Seeded 0 external-ID mappings." in captured.err
