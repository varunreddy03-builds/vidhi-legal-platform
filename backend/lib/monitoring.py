"""Error tracking with Sentry, switched on only when SENTRY_DSN is set, and set up so that no client text leaves.

  - no request bodies, cookies, headers, query strings, user, tags, breadcrumbs or local variables are attached;
  - an exception's MESSAGE is never sent (a database, validation or provider message can repeat a name, an address or part of a document): only the error's class, the file,
    function and line numbers of OUR code, the route template and the status remain;
  - a log record that becomes an event keeps its fixed wording and loses its values;
  - the same `error_label` / `where` helpers keep messages out of our own logs and stored job errors.
Sentry runs on someone else's servers (see docs/ARCHITECTURE_DECISIONS.md, section 5): leave SENTRY_DSN empty if you do not want that. What to do when an alert fires: docs/ALERT_RUNBOOK.md."""

import logging
import os
import re
import traceback

logger = logging.getLogger(__name__)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DIGITS = re.compile(r"\d[\d\s-]{6,}\d")
_MAX_MESSAGE = 200


def redact(text: str) -> str:
    text = _EMAIL.sub("[email]", text or "")
    text = _DIGITS.sub("[number]", text)
    return text[:_MAX_MESSAGE] + ("…" if len(text) > _MAX_MESSAGE else "")


def error_label(exc: BaseException) -> str:
    """What may be written to a log, an error report or a database row about a failure: the error's class and, when it has one, its numeric HTTP status. Never its message:
    a provider's or a database's message can repeat an address, a name or part of a document."""
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    return type(exc).__name__ + (f" (HTTP {status})" if isinstance(status, int) else "")


def where(exc: BaseException, depth: int = 4) -> str:
    """The last few places in OUR code the failure passed through (file name, line, function), so it can be found without the message."""
    frames = traceback.extract_tb(exc.__traceback__)[-depth:]
    return " <- ".join(f"{os.path.basename(f.filename)}:{f.lineno} {f.name}" for f in reversed(frames)) or "unknown"


def scrub(event: dict, hint: dict | None = None) -> dict | None:
    """before_send hook: send where and what KIND of failure, never any text. Exception messages are dropped (only the class is kept), log records keep their fixed wording
    but not their values, and local variables, source lines, paths and request data are removed. The earlier version kept a scrubbed 200-character message, which could still
    hold a name."""
    for key in ("request", "user", "extra", "contexts_user", "breadcrumbs", "server_name", "message", "tags", "modules"):
        event.pop(key, None)
    for exc in (event.get("exception") or {}).get("values", []) or []:
        exc["value"] = ""
        for frame in (exc.get("stacktrace") or {}).get("frames", []) or []:
            for k in ("vars", "context_line", "pre_context", "post_context", "abs_path"):
                frame.pop(k, None)  # local variables and source lines can hold document text; the absolute path names the server
    log = event.get("logentry")
    if isinstance(log, dict):
        event["logentry"] = {"message": redact(str(log.get("message") or ""))}  # the fixed wording only: the values (params, formatted text) are dropped
    return event


def init_sentry() -> bool:
    """True if error tracking was switched on."""
    dsn = (os.environ.get("SENTRY_DSN") or "").strip()
    if not dsn:
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        release=os.environ.get("APP_VERSION") or None,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        traces_sample_rate=0.0,
        before_send=scrub,
        before_breadcrumb=lambda crumb, hint: None,
    )
    logger.info("error tracking is on (Sentry): messages are scrubbed before sending")
    return True


def enabled() -> bool:
    return bool((os.environ.get("SENTRY_DSN") or "").strip())