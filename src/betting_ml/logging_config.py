"""Process logging (spec 003, US7).

One handler on the root logger: JSON in prod (``LOG_FORMAT``, text in dev), the request id on
every line, and every line redacted before it is written, whatever logger it comes from:
``name=value`` pairs whose name looks like a credential (password, token, cookie, API key,
authorization), Argon2 hashes and the literal value of every secret of the configuration.

uvicorn's access log is replaced by ``betting_ml.access`` (method, path without the query
string, status, duration) and security events go to ``betting_ml.security``.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Iterable
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import IO, Any

from pydantic import SecretStr

REDACTED = "[REDACTED]"
REQUEST_ID: ContextVar[str] = ContextVar("request_id", default="-")
MIN_SECRET_LENGTH = 8  # shorter values would redact ordinary words

_NAME = r"[\w-]*(?:password|passwd|secret|token|cookie|api[-_]?key|authorization|bml_session)[\w-]*"
# "password": "a b", ('x-api-key', b'k'), password='k'
_QUOTED = re.compile(rf"""(?i)(["']?{_NAME}["']?\s*[:=,]\s*b?)(["'])(.*?)(?<!\\)\2""")
# password=k, X-API-Key: k, ?apiKey=k&, Authorization: Bearer k
_BARE = re.compile(rf"""(?i)({_NAME}\s*[:=]\s*)((?:bearer|basic)\s+[^\s"'&,;]+|[^\s"'&,;)}}\]]+)""")
_ARGON2 = re.compile(r"\$argon2(?:id|i|d)\$[^\s\"';]+")  # parameters have commas

SECURITY = logging.getLogger("betting_ml.security")
_MARK = "_betting_ml_handler"


class Redactor:
    def __init__(self, secrets: Iterable[str] = ()) -> None:
        values = {s for s in secrets if len(s) >= MIN_SECRET_LENGTH}
        self.secrets = sorted(values, key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, REDACTED)
        text = _ARGON2.sub(REDACTED, text)
        text = _QUOTED.sub(lambda m: f"{m[1]}{m[2]}{REDACTED}{m[2]}", text)
        return _BARE.sub(lambda m: f"{m[1]}{REDACTED}", text)

    def value(self, value: Any) -> Any:
        """Redact every string inside a JSON-like value (before it is serialized)."""
        if isinstance(value, str):
            return self(value)
        if isinstance(value, dict):
            return {k: self.value(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [self.value(v) for v in value]
        return value


def secret_values(settings: Any) -> list[str]:
    """The values of every ``SecretStr`` setting (API keys, session secret, password hash)."""
    return [v.get_secret_value() for _, v in settings if isinstance(v, SecretStr)]


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = REQUEST_ID.get()
        return True


class TextFormatter(logging.Formatter):
    def __init__(self, redactor: Redactor) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s")
        self.redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        return self.redactor(super().format(record))


class JsonFormatter(logging.Formatter):
    def __init__(self, redactor: Redactor) -> None:
        super().__init__()
        self.redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", REQUEST_ID.get()),
            "message": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            entry.update({k: v for k, v in fields.items() if k not in entry})
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(self.redactor.value(entry), ensure_ascii=False, default=str)


def configure_logging(
    settings: Any, stream: IO[str] | None = None, verbose: bool = False
) -> logging.Handler:
    """Install (or replace) the application handler on the root logger. Called at startup,
    after uvicorn has set up its own loggers, so it also takes them over."""
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, _MARK, False)]:
        root.removeHandler(handler)
    redactor = Redactor(secret_values(settings))
    handler = logging.StreamHandler(stream or sys.stderr)
    setattr(handler, _MARK, True)
    handler.addFilter(ContextFilter())
    json_format = settings.effective_log_format == "json"
    handler.setFormatter(JsonFormatter(redactor) if json_format else TextFormatter(redactor))
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    access = logging.getLogger("uvicorn.access")  # full URL with the query string, no id
    access.handlers.clear()
    access.disabled = True
    return handler


def security_event(event: str, level: int = logging.WARNING, /, **fields: Any) -> None:
    """One line per security event (login, lockout, 401/403, limits, integrity)."""
    text = " ".join(f"{key}={value}" for key, value in fields.items())
    SECURITY.log(level, "%s %s", event, text, extra={"fields": {"event": event, **fields}})
