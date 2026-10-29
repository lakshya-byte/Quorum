"""Observability: New Relic spans + custom events, LangSmith switch, JSON logs, W3C traceparent.

Everything is a no-op when NEW_RELIC_LICENSE_KEY / LANGSMITH_API_KEY are unset.
Our LangGraph StateGraph is not auto-instrumented by New Relic (only create_agent() agents are),
so graph nodes and sandbox calls get manual FunctionTrace spans via `span()`.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import re
import secrets
import time
from typing import Any, Iterator

run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="")
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")

_TRACEPARENT = re.compile(r"^[0-9a-f]{2}-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")
_nr_enabled = False
_SECRET_ENV = ("NEBIUS_API_KEY", "GITHUB_TOKEN", "NEW_RELIC_LICENSE_KEY", "LANGSMITH_API_KEY",
               "NVIDIA_API_KEY", "AGENT_SHARED_SECRET")


# ---- W3C trace context ------------------------------------------------------

def parse_traceparent(value: str | None) -> str | None:
    """Trace id from a W3C traceparent header, or None if absent/invalid."""
    m = _TRACEPARENT.match((value or "").strip().lower())
    if not m or m.group(1) == "0" * 32:
        return None
    return m.group(1)


def new_trace_id() -> str:
    return secrets.token_hex(16)


def traceparent_for(trace_id: str) -> str:
    return f"00-{trace_id}-{secrets.token_hex(8)}-01"


# ---- JSON logs ----------------------------------------------------------------

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        for name in _SECRET_ENV:  # never log secrets, even by accident
            val = os.environ.get(name)
            if val and len(val) > 4 and val in msg:
                msg = msg.replace(val, "***")
        out = {
            "ts": round(time.time(), 3), "level": record.levelname, "logger": record.name, "msg": msg,
            "run_id": getattr(record, "run_id", None) or run_id_var.get() or None,
            "trace_id": getattr(record, "trace_id", None) or trace_id_var.get() or None,
        }
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    root.setLevel(os.environ.get("LOG_LEVEL", level).upper())
    for noisy in ("httpx", "httpcore", "nemoguardrails", "langsmith"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ---- LangSmith ------------------------------------------------------------------

def setup_langsmith(api_key: str, project: str) -> bool:
    """LangSmith traces every LangChain runnable when LANGSMITH_TRACING=true; only with a key."""
    if api_key:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ.setdefault("LANGSMITH_PROJECT", project)
        return True
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    return False


# ---- New Relic ------------------------------------------------------------------

def setup_newrelic(license_key: str) -> bool:
    """Enable NR helpers. The agent itself is started by `newrelic-admin run-program`
    (preferred) or initialised here if the key is set and it is not running yet."""
    global _nr_enabled
    if not license_key:
        _nr_enabled = False
        return False
    try:
        import newrelic.agent as nr

        os.environ.setdefault("NEW_RELIC_APP_NAME", "patchloop-agent")
        # AI monitoring: NR auto-instruments the openai SDK and langchain_core runnables.
        os.environ.setdefault("NEW_RELIC_AI_MONITORING_ENABLED", "true")
        if not nr.global_settings().license_key:
            nr.initialize()
        _nr_enabled = True
    except Exception as exc:  # observability must never break the service
        logging.getLogger(__name__).warning("new relic setup failed: %s", type(exc).__name__)
        _nr_enabled = False
    return _nr_enabled


def nr_enabled() -> bool:
    return _nr_enabled


@contextlib.contextmanager
def span(name: str, group: str = "PatchLoop") -> Iterator[None]:
    if not _nr_enabled:
        yield
        return
    import newrelic.agent as nr

    with nr.FunctionTrace(name=name, group=group):
        yield


@contextlib.contextmanager
def background_run(name: str, headers: dict[str, str] | None = None) -> Iterator[None]:
    """A New Relic background transaction for one run, joined to the caller's W3C trace."""
    if not _nr_enabled:
        yield
        return
    import newrelic.agent as nr

    app = nr.application()
    with nr.BackgroundTask(app, name=name, group="PatchLoop"):
        if headers:
            try:
                nr.accept_distributed_trace_headers(headers, transport_type="HTTP")
            except Exception:
                pass
        yield


def record_event(event_type: str, params: dict[str, Any]) -> None:
    """Custom event (PatchLoopRun / PatchLoopAgentStep / PatchLoopGuard). No-op without NR."""
    if not _nr_enabled:
        return
    try:
        import newrelic.agent as nr

        clean = {k: v for k, v in params.items() if isinstance(v, (str, int, float, bool)) and v is not None}
        txn = nr.current_transaction()
        if txn:
            nr.record_custom_event(event_type, clean)
        else:
            nr.record_custom_event(event_type, clean, application=nr.application())
    except Exception:
        pass
