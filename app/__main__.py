"""`python -m app` — the dev server, already on the port this project uses.

`uvicorn app.main:app --reload` on its own binds **8000**, which is vLLM's
default port: coding agents (opencode) probe `127.0.0.1:8000` every 30 seconds
for a local model server (`GET /health`, `GET /v1/models`). When this API sits
on 8000 the probe answers 200/404 forever and the request log fills with
`GET /v1/models 404` lines — the reason this entry point exists.

Three equivalent ways to get the right port, in order of typing effort:

    python -m app                                   # this file, 8001 by default
    UVICORN_PORT=8001 uvicorn app.main:app --reload  # uvicorn's own CLI default
    uvicorn app.main:app --reload --port 8001        # explicit, always wins

`API_PORT` / `API_HOST` override the defaults here; nothing else reads them.
`--reload` is on because this is a development entry point only: a deploy runs
uvicorn (or gunicorn) against `app.main:app` directly with its own workers.
"""

from __future__ import annotations

import os

import uvicorn

# Loads `.env` (app.config calls load_dotenv at import) before the port is read,
# so API_PORT can live there like every other setting.
from . import config  # noqa: F401


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host=os.getenv("API_HOST", "127.0.0.1"),
        port=int(os.getenv("API_PORT", "8001")),
        reload=True,
    )


if __name__ == "__main__":
    main()
