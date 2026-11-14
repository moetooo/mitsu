"""SVC-07: the embedding service has a lifecycle.

These tests pin the four properties the fix is for, without ever loading the
real fastembed weights: importing the module builds nothing, the model is built
once on first use, the coroutine uses the running loop instead of the deprecated
`get_event_loop()`, and `shutdown_embedding()` releases the pool (and the module
still works afterwards). The last test proves `app.main`'s lifespan calls it.
"""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import embedding

REPO_ROOT = Path(__file__).resolve().parents[1]


class _Vec:
    def __init__(self, values):
        self._values = list(values)

    def tolist(self):
        return list(self._values)


class _StubModel:
    def __init__(self, values=(0.1, 0.2, 0.3)):
        self.values = list(values)
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [_Vec(self.values) for _ in texts]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Never touch the real model or executor from these tests."""
    monkeypatch.setattr(embedding, "_model", None)
    monkeypatch.setattr(embedding, "_executor", None)
    yield
    embedding.shutdown_embedding()


def test_importing_the_module_does_not_build_the_model():
    """A fresh interpreter: no weights at import time, no executor either."""
    code = (
        "import app.services.embedding as e;"
        "print(e.is_model_loaded(), e._executor is None)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False True"


def test_model_is_built_once_on_first_use(monkeypatch):
    built = []
    stub = _StubModel()

    def fake_load():
        built.append(1)
        return stub

    monkeypatch.setattr(embedding, "_load_model", fake_load)

    assert embedding.is_model_loaded() is False
    assert embedding._get_model() is stub
    assert embedding._get_model() is stub
    assert built == [1]
    assert embedding.is_model_loaded() is True


async def test_generate_embedding_uses_the_running_loop(monkeypatch):
    stub = _StubModel([1.0, 2.0])
    monkeypatch.setattr(embedding, "_model", stub)

    def boom():
        raise AssertionError("get_event_loop() must not be used inside a coroutine")

    monkeypatch.setattr(embedding.asyncio, "get_event_loop", boom)

    assert await embedding.generate_embedding("berserk") == [1.0, 2.0]
    assert stub.calls == [["berserk"]]


async def test_shutdown_releases_the_executor_and_is_idempotent(monkeypatch):
    stub = _StubModel()
    monkeypatch.setattr(embedding, "_model", stub)

    await embedding.generate_embedding("first")
    executor = embedding._executor
    assert executor is not None

    embedding.shutdown_embedding()

    assert embedding._model is None
    assert embedding._executor is None
    assert embedding.is_model_loaded() is False
    with pytest.raises(RuntimeError):
        executor.submit(lambda: None)

    # Safe to call again, and the module is usable afterwards.
    embedding.shutdown_embedding()
    monkeypatch.setattr(embedding, "_model", stub)
    assert await embedding.generate_embedding("second") == stub.values


async def test_lifespan_warms_then_releases_the_embedding_service(monkeypatch):
    from app import main

    warmed = []
    released = []

    async def fake_embed(text):
        warmed.append(text)

    async def noop():
        return None

    monkeypatch.setattr(main, "generate_embedding", fake_embed)
    monkeypatch.setattr(main, "verify_schema", noop)
    monkeypatch.setattr(main, "engine", SimpleNamespace(dispose=noop))
    monkeypatch.setattr(main, "redis_client", SimpleNamespace(aclose=noop))
    monkeypatch.setattr(main, "shutdown_embedding", lambda: released.append(True))

    async with main.lifespan(main.app):
        assert warmed == ["warmup"]

    assert released == [True]
