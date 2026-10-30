"""LLM-judge plumbing: configuration, honest availability status, DeepEval judge and Ragas wrappers.

The judge is the Nebius Token Factory OpenAI-compatible endpoint:
  base url   EVAL_JUDGE_BASE_URL (default: app.config.NEBIUS_BASE_URL)
  model      EVAL_JUDGE_MODEL      (required: a chat model id from your Nebius account)
  key        NEBIUS_API_KEY
  embeddings EVAL_EMBED_MODEL      (optional: only needed by embedding based Ragas metrics)
With no judge configured every LLM-based metric is reported as SKIPPED (status "needs_judge"); no score is invented.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from evals.common import NEBIUS_BASE_URL


def config() -> dict[str, str]:
    from app.config import load_env

    load_env()
    return {
        "base_url": (os.environ.get("EVAL_JUDGE_BASE_URL") or NEBIUS_BASE_URL).strip(),
        "model": os.environ.get("EVAL_JUDGE_MODEL", "").split("#", 1)[0].strip(),
        "api_key": os.environ.get("NEBIUS_API_KEY", "").split("#", 1)[0].strip(),
        "embed_model": os.environ.get("EVAL_EMBED_MODEL", "").split("#", 1)[0].strip(),
    }


def status(check_reachable: bool = False) -> dict[str, Any]:
    """{available, reason, model, base_url, embeddings}. Never raises."""
    cfg = config()
    missing = [n for n, k in (("NEBIUS_API_KEY", "api_key"), ("EVAL_JUDGE_MODEL", "model")) if not cfg[k]]
    if missing:
        return {"available": False, "reason": f"not configured: set {' and '.join(missing)}", "model": cfg["model"],
                "base_url": cfg["base_url"], "embeddings": bool(cfg["embed_model"])}
    if check_reachable:
        import httpx

        try:
            r = httpx.get(cfg["base_url"].rstrip("/") + "/models", headers={"Authorization": f"Bearer {cfg['api_key']}"},
                          timeout=5)
            if r.status_code >= 500:
                return {"available": False, "reason": f"endpoint answered HTTP {r.status_code}", "model": cfg["model"],
                        "base_url": cfg["base_url"], "embeddings": bool(cfg["embed_model"])}
            if r.status_code in (401, 403):
                return {"available": False, "reason": f"endpoint rejected the key (HTTP {r.status_code})",
                        "model": cfg["model"], "base_url": cfg["base_url"], "embeddings": bool(cfg["embed_model"])}
        except Exception as exc:
            return {"available": False, "reason": f"{cfg['base_url']} unreachable ({type(exc).__name__})",
                    "model": cfg["model"], "base_url": cfg["base_url"], "embeddings": bool(cfg["embed_model"])}
    return {"available": True, "reason": "configured", "model": cfg["model"], "base_url": cfg["base_url"],
            "embeddings": bool(cfg["embed_model"])}


class JudgeUnavailable(RuntimeError):
    pass


def require_judge(check_reachable: bool = True) -> dict[str, Any]:
    st = status(check_reachable)
    if not st["available"]:
        raise JudgeUnavailable(f"--judge nebius: {st['reason']}")
    return st


_JSON = re.compile(r"\{.*\}", re.DOTALL)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def _extract_json(text: str) -> str:
    text = _THINK.sub("", text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1)
    m = _JSON.search(text)
    return m.group(0) if m else text


def _build_deepeval_judge() -> type:
    from deepeval.models import DeepEvalBaseLLM

    class NebiusJudge(DeepEvalBaseLLM):
        """DeepEval judge on the Nebius Token Factory (OpenAI-compatible) endpoint."""

        def __init__(self, model: str | None = None, base_url: str | None = None, api_key: str | None = None,
                     timeout: float = 90.0, temperature: float = 0.0, max_tokens: int = 1500) -> None:
            cfg = config()
            self._model = model or cfg["model"]
            self._base_url = base_url or cfg["base_url"]
            self._api_key = api_key or cfg["api_key"]
            self._timeout, self._temperature, self._max_tokens = timeout, temperature, max_tokens
            if not (self._model and self._api_key):
                raise JudgeUnavailable("NebiusJudge needs EVAL_JUDGE_MODEL and NEBIUS_API_KEY")
            super().__init__(self._model)

        def load_model(self) -> Any:
            from openai import AsyncOpenAI, OpenAI

            self._async = AsyncOpenAI(base_url=self._base_url, api_key=self._api_key, timeout=self._timeout)
            return OpenAI(base_url=self._base_url, api_key=self._api_key, timeout=self._timeout)

        def _messages(self, prompt: str, schema: Any) -> list[dict[str, str]]:
            if schema is not None:
                prompt += ("\n\nReply with ONE JSON object only (no prose, no markdown fence) that matches this JSON "
                           "schema:\n" + json.dumps(schema.model_json_schema()))
            return [{"role": "user", "content": prompt}]

        def _finish(self, text: str, schema: Any) -> Any:
            if schema is None:
                return text
            try:
                return schema.model_validate_json(_extract_json(text))
            except Exception:
                return _extract_json(text)  # DeepEval parses JSON strings itself

        def generate(self, prompt: str, schema: Any = None) -> Any:
            resp = self.model.chat.completions.create(
                model=self._model, messages=self._messages(prompt, schema), temperature=self._temperature,
                max_tokens=self._max_tokens)
            return self._finish(resp.choices[0].message.content or "", schema)

        async def a_generate(self, prompt: str, schema: Any = None) -> Any:
            resp = await self._async.chat.completions.create(
                model=self._model, messages=self._messages(prompt, schema), temperature=self._temperature,
                max_tokens=self._max_tokens)
            return self._finish(resp.choices[0].message.content or "", schema)

        def get_model_name(self) -> str:
            return f"nebius:{self._model}"

    return NebiusJudge


_JUDGE_CLS: type | None = None


def nebius_judge_class() -> type:
    global _JUDGE_CLS
    if _JUDGE_CLS is None:
        _JUDGE_CLS = _build_deepeval_judge()
    return _JUDGE_CLS


def NebiusJudge(*args: Any, **kwargs: Any) -> Any:  # noqa: N802  (class-like factory so importing stays cheap)
    return nebius_judge_class()(*args, **kwargs)


def offline_guard_model() -> Any:
    """A DeepEval model that raises if it is ever called. Name-based metrics need *some* model object at construction
    time; passing this proves that they never reach an LLM."""
    from deepeval.models import DeepEvalBaseLLM

    class NoJudge(DeepEvalBaseLLM):
        def __init__(self) -> None:
            self.name = "no-judge"

        def load_model(self) -> None:
            return None

        def generate(self, *a: Any, **k: Any) -> str:
            raise RuntimeError("no judge configured: this metric must not call an LLM")

        async def a_generate(self, *a: Any, **k: Any) -> str:
            raise RuntimeError("no judge configured: this metric must not call an LLM")

        def get_model_name(self) -> str:
            return "no-judge"

    return NoJudge()


def ragas_llm() -> Any:
    """LangchainLLMWrapper(ChatOpenAI(...)) on the Nebius endpoint."""
    from evals.compat import ensure_ragas_importable

    st = ensure_ragas_importable()
    if not st["ok"]:
        raise RuntimeError(f"ragas not importable: {st['error']}")
    from langchain_openai import ChatOpenAI
    from ragas.llms import LangchainLLMWrapper

    cfg = config()
    if not (cfg["model"] and cfg["api_key"]):
        raise JudgeUnavailable("set EVAL_JUDGE_MODEL and NEBIUS_API_KEY")
    return LangchainLLMWrapper(ChatOpenAI(model=cfg["model"], base_url=cfg["base_url"], api_key=cfg["api_key"],
                                          temperature=0, max_tokens=1500, timeout=90, max_retries=1))


def ragas_embeddings() -> Any | None:
    """Embeddings wrapper only when EVAL_EMBED_MODEL is set; None otherwise (embedding metrics then skip)."""
    cfg = config()
    if not cfg["embed_model"]:
        return None
    from evals.compat import ensure_ragas_importable

    ensure_ragas_importable()
    from langchain_openai import OpenAIEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper

    return LangchainEmbeddingsWrapper(OpenAIEmbeddings(model=cfg["embed_model"], base_url=cfg["base_url"],
                                                       api_key=cfg["api_key"], check_embedding_ctx_length=False))
