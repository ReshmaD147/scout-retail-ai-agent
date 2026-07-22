"""Structured (JSON) logging setup.

This module configures the root logger once, at application startup,
so every log line across the app is emitted as a single JSON object.
That makes logs greppable and machine-parseable, which is the
foundation the later observability step will build on.
"""

import json
import logging
from datetime import datetime, timezone

# Attribute names that exist on every LogRecord by default. Anything
# beyond this set was added via logger.info(..., extra={...}) and is
# treated as extra context to include in the JSON output.
_DEFAULT_RECORD_ATTRS = set(vars(logging.makeLogRecord({})).keys())


class JSONLogFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        extra_context = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _DEFAULT_RECORD_ATTRS
        }
        if extra_context:
            payload["context"] = extra_context

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(log_level: str = "INFO") -> None:
    """Attach a single JSON-formatted handler to the root logger.

    Called once from the application factory (scout.api.app.create_app)
    before anything else logs, so all subsequent log calls - from
    FastAPI, uvicorn, or our own code - share the same format.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JSONLogFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(log_level.upper())
