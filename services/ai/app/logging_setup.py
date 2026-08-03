"""Structured JSON logging with trace-id propagation (matches the gateway)."""
from __future__ import annotations

import contextvars
import json
import logging
import sys
import time

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "service": "ai",
            "msg": record.getMessage(),
            "logger": record.name,
        }
        tid = trace_id_var.get()
        if tid:
            entry["trace_id"] = tid
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        for key, value in getattr(record, "extra_fields", {}).items():
            entry[key] = value
        return json.dumps(entry, default=str)


def init(env: str = "dev") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.DEBUG if env == "dev" else logging.INFO)
    logging.getLogger("neo4j").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def log(name: str = "ai") -> logging.Logger:
    return logging.getLogger(name)
