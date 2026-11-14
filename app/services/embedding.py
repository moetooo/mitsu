"""The embedding service, with a lifecycle (SVC-07).

fastembed's model is tens of megabytes of weights plus its own inference
runtime, and it used to be built while this module was being **imported**. That
made every importer pay for it — Alembic, a management script, a test run, or a
worker that will never embed anything — and the process then held the memory for
its whole life. It is now built on first use, warmed deliberately at startup
(``app.main`` lifespan), and released together with its thread pool at shutdown
(``shutdown_embedding``).

The thread pool is created lazily for the same reason and shut down explicitly:
a module-level ``ThreadPoolExecutor`` is never collected on its own, so the
worker threads outlived the app. ``shutdown_embedding`` is idempotent and leaves
the module usable — a later call rebuilds both, which is what tests and a
restarted lifespan need.
"""

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from fastembed import TextEmbedding

logger = logging.getLogger("mitsu.embedding")

PRIMARY_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
FALLBACK_MODEL = "BAAI/bge-small-en-v1.5"
MAX_WORKERS = 8

_lock = threading.Lock()
_model: Optional[TextEmbedding] = None
_executor: Optional[ThreadPoolExecutor] = None


def _load_model() -> TextEmbedding:
    try:
        return TextEmbedding(PRIMARY_MODEL)
    except Exception as exc:  # a missing cache or a bad name must not be fatal
        logger.warning(
            "Could not load %s (%s); falling back to %s", PRIMARY_MODEL, exc, FALLBACK_MODEL
        )
        return TextEmbedding(FALLBACK_MODEL)


def _get_model() -> TextEmbedding:
    """Build the model once, on first use. Double-checked under a lock."""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                _model = _load_model()
    return _model


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        with _lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(
                    max_workers=MAX_WORKERS, thread_name_prefix="fastembed"
                )
    return _executor


def is_model_loaded() -> bool:
    """Whether the weights are in memory. Used by tests and startup logs."""
    return _model is not None


def generate_embedding_sync(text: str) -> List[float]:
    embeddings = list(_get_model().embed([text]))
    return embeddings[0].tolist()


async def generate_embedding(text: str) -> List[float]:
    # This is a coroutine, so it always runs inside a loop; the old
    # `except RuntimeError: asyncio.get_event_loop()` branch was dead code and
    # the deprecated API with it.
    loop = asyncio.get_running_loop()
    executor = _get_executor()
    return await loop.run_in_executor(executor, generate_embedding_sync, text)


def shutdown_embedding(wait: bool = False) -> None:
    """Release the model and its thread pool. Safe to call more than once."""
    global _model, _executor
    with _lock:
        executor, _executor = _executor, None
        _model = None
    if executor is not None:
        executor.shutdown(wait=wait)
        logger.info("Embedding model and thread pool released.")
