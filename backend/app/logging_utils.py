"""Keep API secrets out of logs.

ENTSO-E only accepts its token as the ``securityToken`` query parameter, so any logged request URL
(httpx's INFO "HTTP Request: GET <url>" line, an exception message that embeds the URL, ...) would
leak it. Two layers:

1. httpx/httpcore are held at WARNING so request URLs are not logged at all.
2. A LogRecord factory scrubs secret query parameters from every record's message and traceback,
   whichever handler or logger emits it (this also covers the handler pre-installed by the Lambda runtime).
"""

import logging
import re

_SECRET_PARAMS = ("securityToken", "api_key", "apikey", "token", "key")
_SECRET_RE = re.compile(r"(?i)\b(" + "|".join(_SECRET_PARAMS) + r")=[^&\s\"'<>]+")

_installed = False


def redact_secrets(text: str) -> str:
    """Replace the value of secret query parameters (``securityToken=...``) with ``REDACTED``."""
    return _SECRET_RE.sub(lambda m: f"{m.group(1)}=REDACTED", text)


def install_log_redaction() -> None:
    """Idempotently install the log scrubbing described in the module docstring."""
    global _installed
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    if _installed:
        return
    _installed = True

    previous_factory = logging.getLogRecordFactory()

    def factory(*args, **kwargs) -> logging.LogRecord:
        record = previous_factory(*args, **kwargs)
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001
            return record  # malformed format args: let logging report it as usual
        scrubbed = redact_secrets(message)
        if scrubbed != message:
            record.msg = scrubbed
            record.args = None
        if record.exc_info and record.exc_info[1] is not None:
            # Tracebacks are rendered later by the Formatter; pre-render them with secrets removed.
            record.exc_text = redact_secrets(logging.Formatter().formatException(record.exc_info))
        return record

    logging.setLogRecordFactory(factory)
