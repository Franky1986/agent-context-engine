from __future__ import annotations

from ...adapters.sqlite.request_db import RetryingConnection, begin_request, close_request
from ...adapters.sqlite.request_db import _LOCK_RETRY_DELAYS as _LOCK_RETRY_DELAYS
from ...infrastructure.db import connect as db_connect


def connect(*args, **kwargs):
    kwargs.setdefault("init", False)
    return RetryingConnection(db_connect(*args, **kwargs))


__all__ = ["begin_request", "close_request", "connect", "db_connect", "_LOCK_RETRY_DELAYS"]
