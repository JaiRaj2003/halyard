"""Correlation id context and logging setup, shared by the HTTP layer and services.

One id per HTTP exchange lives in a context variable so anything logged while a
request is being served can be tied back to it. This is *transport*
correlation: it identifies a delivery, not an ask. The intake
``Idempotency-Key`` identifies a submission across retries and is unrelated.
"""

from __future__ import annotations

import logging
import os
import re
from contextvars import ContextVar
from uuid import uuid4

REQUEST_ID_HEADER = "X-Request-ID"
LOG_LEVEL_ENV_VAR = "HALYARD_LOG_LEVEL"

#: A caller-supplied id is kept when it is short, printable and has no
#: whitespace: enough to round-trip a UUID, a trace id or a ticket number,
#: while refusing anything that could smuggle a newline into a log line.
_ACCEPTABLE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")

request_id_var: ContextVar[str] = ContextVar("halyard_request_id", default="-")


def current_request_id() -> str:
    """The correlation id of the HTTP request being served, or ``-`` outside one."""
    return request_id_var.get()


def resolve_request_id(supplied: str | None) -> str:
    return supplied if supplied and _ACCEPTABLE_REQUEST_ID.match(supplied) else uuid4().hex


def configure_logging(env: dict[str, str] | None = None) -> None:
    """Attach a plain key=value handler to the root logger if nobody has yet.

    Uvicorn configures only its own loggers, so without this the request lines
    would fall through to Python's last-resort handler and only warnings would
    appear. Idempotent, and a no-op wherever logging is already set up.
    """
    environ = os.environ if env is None else env
    level = environ.get(LOG_LEVEL_ENV_VAR, "INFO").strip().upper() or "INFO"
    if not logging.getLogger().handlers:
        logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    else:
        logging.getLogger("halyard").setLevel(level)
