"""Nebius Token Factory chat client (OpenAI-compatible) and reply parsing."""
from __future__ import annotations

import re

from openai import AsyncOpenAI

from app.config import NEBIUS_BASE_URL

TEMPERATURE = 0.8
MAX_TOKENS = 4096

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"```[ \t]*[\w+-]*[ \t]*\n(.*?)```", re.DOTALL)
_IDEA = re.compile(r"^\s*\**Idea:\**\s*(.+)$", re.MULTILINE | re.IGNORECASE)


def make_client(api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(base_url=NEBIUS_BASE_URL, api_key=api_key)


async def chat(
    client: AsyncOpenAI,
    model: str,
    system: str,
    user: str,
    temperature: float = TEMPERATURE,
) -> tuple[str, dict[str, int]]:
    """One completion. Returns the reply text and token usage."""
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
        max_tokens=MAX_TOKENS,
    )
    text = resp.choices[0].message.content or ""
    usage = resp.usage
    return text, {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
    }


def extract(reply: str) -> tuple[str, str]:
    """(idea, code) from a model reply. Code is the first fenced block, or ''."""
    body = _THINK.sub("", reply)
    fence = _FENCE.search(body)
    code = fence.group(1).rstrip() + "\n" if fence else ""
    idea = _IDEA.search(body)
    return (idea.group(1).strip() if idea else "fix attempt"), code
