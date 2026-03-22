"""
In-memory rolling error log for dashboard display.
Captures WARNING and ERROR from all app loggers.
"""

import logging
from collections import deque
from datetime import datetime

# ~1 entry/min for 7 days = 10080; ~150 chars/entry ≈ 1.5MB
ERROR_LOG: deque = deque(maxlen=10000)


class ErrorLogHandler(logging.Handler):
    """Append WARNING/ERROR records to ERROR_LOG for API consumption."""

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.WARNING:
            return
        # Skip third-party noise (uvicorn, httpx, etc.)
        name = record.name or ""
        if any(skip in name for skip in ("uvicorn", "httpx", "httpcore", "anyio")):
            return
        try:
            ERROR_LOG.append({
                "ts": datetime.now().isoformat(),
                "level": record.levelname,
                "msg": self.format(record),
            })
        except Exception:
            pass
