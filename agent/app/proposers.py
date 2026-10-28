"""Fix proposers. Both share the signature `propose(bug, parent_node, i, model_override=None)`."""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from openai import AsyncOpenAI

from app.bugs import Bug
from app.config import Settings
from app.llm import chat, extract
from app.prompts import SYSTEM_PROMPT, build_user_prompt

log = logging.getLogger(__name__)

Node = dict
Propose = Callable[..., Awaitable[tuple[str, str]]]

FAKE_DELAY = 0.4
BROKEN_CODE = "def broken(:\n"


def new_usage() -> dict[str, int]:
    return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


def model_for(depth: int, settings: Settings, model_override: str | None = None) -> str:
    """Model for a child at `depth`: nano for the first round, super afterwards."""
    if model_override:
        return model_override
    if depth <= 1:
        return settings.model_nano
    return settings.model_super or settings.model_nano


async def propose_fake(bug: Bug, parent_node: Node, i: int, model_override: str | None = None) -> tuple[str, str]:
    await asyncio.sleep(FAKE_DELAY)
    if parent_node["code"] == bug["partial"] and i == 0:
        return "also validate the edge case the tests still reject", bug["correct"]
    scripted = [
        ("scripted wrong fix", bug["wrong"]),
        ("scripted obvious fix", bug["partial"]),
        ("scripted fix with a syntax error", BROKEN_CODE),
    ]
    return scripted[i % len(scripted)]


async def propose_live(
    bug: Bug,
    parent_node: Node,
    i: int,
    model_override: str | None = None,
    *,
    settings: Settings,
    client: AsyncOpenAI,
    usage: dict[str, int] | None = None,
) -> tuple[str, str]:
    model = model_for(parent_node["depth"] + 1, settings, model_override)
    prompt = build_user_prompt(bug, parent_node["code"], parent_node.get("output", ""), i)
    try:
        reply, used = await chat(client, model, SYSTEM_PROMPT, prompt)
    except Exception as exc:
        log.warning("LLM call failed: %s", type(exc).__name__)
        return "LLM error", ""
    if usage is not None:
        usage["calls"] += 1
        usage["prompt_tokens"] += used["prompt_tokens"]
        usage["completion_tokens"] += used["completion_tokens"]
    return extract(reply)
