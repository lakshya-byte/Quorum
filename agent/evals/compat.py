"""Import shim for ragas 0.4.3 against langchain-community >= 0.4.

ragas/llms/base.py does `from langchain_community.chat_models.vertexai import ChatVertexAI` and
`from langchain_community.llms import VertexAI`; both were removed from langchain-community 0.4.x, so
`import ragas.metrics` raises ModuleNotFoundError. `ensure_ragas_importable()` injects inert placeholder
classes ONLY when the real import genuinely fails, then verifies `import ragas.metrics` works.
The placeholders are never usable as Vertex clients; they exist so ragas can import.
"""
from __future__ import annotations

import importlib
import sys
import types

_STUBBED: list[str] = []


class _VertexStub:
    """Placeholder for a removed langchain-community Vertex class (never instantiated by PatchLoop)."""

    def __init__(self, *args, **kwargs) -> None:
        raise RuntimeError("Vertex AI is not supported in the PatchLoop eval pipeline (compat placeholder)")


def stubs_installed() -> list[str]:
    return list(_STUBBED)


def _real_import_works(name: str, attr: str) -> bool:
    try:
        mod = importlib.import_module(name)
        return hasattr(mod, attr) if attr else True
    except Exception:
        return False


def install_vertex_stubs() -> list[str]:
    """Inject the placeholders that are missing. Returns the names that were stubbed."""
    added: list[str] = []
    try:
        import langchain_community.chat_models as chat_models
        import langchain_community.llms as llms
    except Exception:  # langchain_community absent: ragas will report its own error
        return added
    if not _real_import_works("langchain_community.chat_models.vertexai", "ChatVertexAI"):
        mod = types.ModuleType("langchain_community.chat_models.vertexai")
        mod.ChatVertexAI = _VertexStub  # type: ignore[attr-defined]
        mod.__patchloop_stub__ = True  # type: ignore[attr-defined]
        sys.modules["langchain_community.chat_models.vertexai"] = mod
        chat_models.vertexai = mod  # type: ignore[attr-defined]
        added.append("langchain_community.chat_models.vertexai.ChatVertexAI")
    if not hasattr(llms, "VertexAI"):
        try:
            llms.VertexAI = _VertexStub  # type: ignore[attr-defined]
        except Exception:
            pass
        else:
            added.append("langchain_community.llms.VertexAI")
    _STUBBED.extend(a for a in added if a not in _STUBBED)
    return added


def ensure_ragas_importable() -> dict:
    """Make `import ragas.metrics` work. Idempotent. Returns {ok, stubbed, error}."""
    try:
        import ragas.metrics  # noqa: F401
        return {"ok": True, "stubbed": stubs_installed(), "error": ""}
    except ModuleNotFoundError as first:
        if "vertexai" not in str(first) and "VertexAI" not in str(first):
            return {"ok": False, "stubbed": [], "error": f"{type(first).__name__}: {first}"}
    except ImportError as first:
        if "VertexAI" not in str(first):
            return {"ok": False, "stubbed": [], "error": f"{type(first).__name__}: {first}"}
    for name in [m for m in sys.modules if m == "ragas" or m.startswith("ragas.")]:
        del sys.modules[name]  # drop the half-imported package before retrying
    stubbed = install_vertex_stubs()
    try:
        import ragas.metrics  # noqa: F401
        return {"ok": True, "stubbed": stubbed, "error": ""}
    except Exception as exc:
        return {"ok": False, "stubbed": stubbed, "error": f"{type(exc).__name__}: {exc}"}
