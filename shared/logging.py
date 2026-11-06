import contextvars
import json
import logging
import sys
from datetime import UTC, datetime

# Set per request (API) or per message (worker); added to every log line.
request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
review_id: contextvars.ContextVar[int | None] = contextvars.ContextVar("review_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id.get(),
            "review_id": review_id.get(),
        }
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
