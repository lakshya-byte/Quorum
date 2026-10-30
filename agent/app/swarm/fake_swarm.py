"""FakeSwarm: the offline, LABELLED scripted team (PATCHLOOP_MODE=fake). Only the LLM is scripted: the planner's JSON, the
spec agents' assets, each worker's tool-call list and the critic/integrator replies come from data files
(`fake_scripts/*.json`); everything else (tools, policy gate, Workspace, builds, tests, verifiers, merge, outcome) is the
REAL code path.

Script file format (one file per demo task):
{
  "id": "inventory-feature",
  "match": {"repo": "inventory-lib", "task_type": "feature", "keywords": ["bulk", "discount"]},
  "plan": { ...a Plan as the planner would return it... },
  "spec": {"<criterion_id>": {"files": {"tests/test_x.py": "..."}, "command": "..."} | [attempt1, attempt2]},
  "workers": {"<unit_id>": [ {"variant": 0, "steps": [{"tool": "write_file", "args": {...}, "delay_ms": 0}, ...]},
                             {"variant": 1, "steps": [...]} ]},
  "critic": [ {"lesson": "...", "units": [ ... ]} ],          # one entry per failed round
  "integrator": {"<path>": "<merged file content>"}
}
A missing `finish` is appended automatically. Without a matching script, the planner reply is invalid, the plan falls
back to the deterministic single-unit plan, and workers finish at once: the run ends `failed` honestly instead of
pretending (fake mode has scripts only for the bundled demo tasks).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable

from app.swarm.workers import LLMReply, ToolCall

log = logging.getLogger(__name__)

SCRIPTS_DIR = Path(__file__).resolve().parent / "fake_scripts"
LEGACY_DEMOS = {"shop-api", "wordstats", "booking"}  # existing Python bug-fix demos -> the bugfix strategy
VAGUE = {"fix it", "make it better", "improve it", "improve", "do something", "help", "fix", "update it", "make it good",
         "fix this", "optimize it", "refactor it", "make it nicer", "clean it up"}
FAKE_QUESTIONS = [{"id": "scope", "text": "Which part of the repository should change (a file, a screen, an endpoint)?"},
                  {"id": "done", "text": "How will we know it is done (a behaviour, a metric, a screen you expect to see)?"}]


TYPE_WORDS = {
    "ui": ["ui", "ux", "interface", "mobile", "responsive", "accessib", "design", "layout", "style"],
    "refactor": ["refactor", "split", "extract", "restructure", "clean", "modular", "monolith"],
    "feature": ["add", "feature", "support", "implement", "new "],
}
STOP = {"with", "that", "this", "from", "into", "must", "same", "keep", "which", "should", "every", "after", "afterwards",
        "have", "than", "then", "their", "there", "where", "would", "about", "being", "while", "usable", "focused"}
ASSET_PARAMS = ("files", "script")


def demo_task_script(demo: Any, task: Any) -> dict[str, Any]:
    """A script derived from builder B's bundled swarm demo task (`app/swarm/demo_tasks.py`): the plan mirrors the task's
    criteria and reference units, the spec agents answer with the task's verification assets, and each unit's worker
    replays the reference solution's files for that unit with write_file. Everything is executed for real afterwards."""
    ref = task.reference
    units_src = list(ref.units) or [{"id": "u1", "title": task.title, "files": sorted(ref.files)}]
    criteria, spec = [], {}
    for c in task.criteria:
        params = dict(c.params)
        assets = {k: params.pop(k) for k in ASSET_PARAMS if k in params}
        if assets:
            spec[c.id] = assets
        criteria.append({"id": c.id, "kind": c.kind, "hard": c.hard, "description": c.description, "params": params,
                         "user_stated": c.kind in ("acceptance_tests", "characterization", "ui_smoke", "complexity_metric")})
    units, workers = [], {}
    for u in units_src:
        files = [f for f in u.get("files", []) if f in ref.files]
        units.append({"id": u["id"], "title": u.get("title", u["id"]), "scope_files": list(u.get("files", [])),
                      "depends_on": list(u.get("depends_on", [])), "variants": 1})
        workers[u["id"]] = [{"variant": 0, "summary": u.get("title", ""), "steps": [
            {"tool": "read_file", "args": {"path": f}} for f in files[:1]] + [
            {"tool": "write_file", "args": {"path": f, "content": ref.files[f]}} for f in files]}]
    words = re.findall(r"[a-z]{5,}", f"{task.title} {task.prompt}".lower())
    kws = [w for w in dict.fromkeys(words) if w not in STOP][:12] + TYPE_WORDS.get(task.task_type, [])
    return {"id": f"{demo.name}/{task.id}", "demo_task": True,
            "match": {"repo": demo.name, "task_type": task.task_type, "keywords": kws},
            "plan": {"task_type": task.task_type, "summary": task.title, "criteria": criteria, "units": units,
                     "swarm": {"max_parallel": max(1, len(units))}},
            "spec": spec, "workers": workers}


def bundled_demo_scripts() -> list[dict[str, Any]]:
    try:
        from app.swarm.demo_tasks import load_swarm_demo, swarm_demo_names
    except ImportError:  # builder B's demo loader is not present in this checkout
        return []
    out = []
    for name in swarm_demo_names():
        demo = load_swarm_demo(name)
        out.extend(demo_task_script(demo, t) for t in demo.tasks.values())
    return out


def is_vague(task: str) -> bool:
    words = re.findall(r"\w+", task.lower())
    return len(words) < 3 or " ".join(words) in VAGUE


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


class ScriptedLLM:
    """ChatLLM implementation that replays a script. Deterministic; token usage is estimated from text size."""

    def __init__(self, role: str, tier: str, state: "ScriptState") -> None:
        self.role, self.tier, self.state = role, tier, state
        self.model = f"fake-{role}-{tier}"

    async def respond(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, *,
                      key: str = "") -> LLMReply:
        st = self.state
        await asyncio.sleep(0)  # always a scheduling point so cancellation can land
        prompt = _tokens(json.dumps(messages)[:20000])
        if key.startswith("worker:"):
            reply = await self._worker(key)
        else:
            text = self._text(key)
            reply = LLMReply(content=text)
        reply.usage = {"prompt_tokens": prompt, "completion_tokens": _tokens(reply.content or json.dumps(
            [{"n": c.name, "a": c.args} for c in reply.tool_calls])[:4000])}
        return reply

    def _text(self, key: str) -> str:
        script = self.state.script
        if key == "planner" and self.state.vague and not self.state.answered:
            plan = {"task_type": ((script or {}).get("plan") or {}).get("task_type", "other"),
                    "summary": "needs clarification", "clarify": FAKE_QUESTIONS, "units": []}
            return "```json\n" + json.dumps(plan) + "\n```"
        if script is None:
            return "FAKE MODE: no script for this task"
        if key == "planner":
            return "```json\n" + json.dumps(dict(script.get("plan") or {})) + "\n```"
        if key.startswith("spec:"):
            _, cid, attempt = key.split(":")
            spec = (script.get("spec") or {}).get(cid, {"files": {}})
            if isinstance(spec, list):
                spec = spec[min(int(attempt), len(spec) - 1)]
            return "```json\n" + json.dumps(spec) + "\n```"
        if key.startswith("critic:"):
            rounds = script.get("critic") or []
            idx = min(self.state.critic_calls, len(rounds) - 1) if rounds else -1
            self.state.critic_calls += 1
            body = rounds[idx] if idx >= 0 else {"lesson": "repair the failing checks", "units": []}
            return "```json\n" + json.dumps(body) + "\n```"
        if key.startswith("integrator:"):
            path = key.split(":", 1)[1]
            content = (script.get("integrator") or {}).get(path)
            return "```json\n" + json.dumps({"content": content if content is not None else ""}) + "\n```"
        return "{}"

    async def _worker(self, key: str) -> LLMReply:
        _, unit, variant, attempt = key.split(":")
        script = self.state.script
        steps = self._steps(script, unit, int(variant), int(attempt))
        cursor = self.state.cursors.get(key, 0)
        self.state.cursors[key] = cursor + 1
        if steps is None or cursor >= len(steps):
            step: dict[str, Any] = {"tool": "finish", "args": {"summary": "no further scripted steps"}}
        else:
            step = steps[cursor]
        delay = float(step.get("delay_ms", 0)) / 1000.0 * self.state.delay_scale
        if delay:
            await asyncio.sleep(delay)
        return LLMReply(content="", tool_calls=[ToolCall(f"fake-{key}-{cursor}", step["tool"], dict(step.get("args") or {}))])

    @staticmethod
    def _steps(script: dict[str, Any] | None, unit: str, variant: int, attempt: int) -> list[dict[str, Any]] | None:
        if script is None:
            return None
        entries = (script.get("workers") or {}).get(unit)
        if entries is None:
            return None
        pick = next((e for e in entries if int(e.get("variant", 0)) == variant and int(e.get("attempt", 0)) == attempt), None) \
            or next((e for e in entries if int(e.get("variant", 0)) == variant and int(e.get("attempt", 0)) == 0), None)
        if pick is None:
            return None
        steps = list(pick.get("steps") or [])
        if not steps or steps[-1].get("tool") != "finish":
            steps.append({"tool": "finish", "args": {"summary": pick.get("summary", "scripted change applied")}})
        return steps


class ScriptState:
    def __init__(self, script: dict[str, Any] | None, delay_scale: float, vague: bool, answered: bool) -> None:
        self.script = script
        self.delay_scale = delay_scale
        self.vague = vague
        self.answered = answered
        self.cursors: dict[str, int] = {}
        self.critic_calls = 0


class FakeSwarm:
    """Script registry + strategy chooser for fake mode."""

    label = "FAKE MODE: scripted team (the LLM is replayed from fake_scripts/*.json; tools, sandbox and verifiers are real)"

    def __init__(self, scripts_dir: Path | str | None = None, delay_scale: float = 1.0) -> None:
        self.dir = Path(scripts_dir) if scripts_dir else SCRIPTS_DIR
        self.delay_scale = delay_scale
        self._scripts: list[dict[str, Any]] | None = None

    def scripts(self) -> list[dict[str, Any]]:
        if self._scripts is None:
            found = []
            for path in sorted(self.dir.glob("*.json")) if self.dir.is_dir() else []:
                try:
                    found.append(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, ValueError) as exc:
                    log.warning("fake script %s unreadable: %s", path.name, type(exc).__name__)
            if self.dir == SCRIPTS_DIR:  # the bundled team also replays B's demo tasks (inventory-lib, react-notes)
                found.extend(bundled_demo_scripts())
            self._scripts = found
        return self._scripts

    def find(self, full_name: str, task: str, requested_type: str) -> dict[str, Any] | None:
        short = full_name.split("/", 1)[-1].lower()
        text = task.lower()
        best, best_score = None, -1
        for s in self.scripts():
            m = s.get("match") or {}
            if str(m.get("repo", "")).lower() not in ("", short):
                continue
            if requested_type != "auto" and m.get("task_type") and m["task_type"] != requested_type:
                continue
            kws = [str(k).lower() for k in m.get("keywords", [])]
            hits = sum(1 for k in kws if k in text)
            if kws and not hits and requested_type == "auto":
                continue
            score = hits * 2 + (1 if requested_type != "auto" and m.get("task_type") == requested_type else 0)
            if score > best_score:
                best, best_score = s, score
        return best

    def strategy_for(self, full_name: str, task: str, requested_type: str) -> str:
        """'bugfix' (existing graph) or 'swarm'. Deterministic."""
        short = full_name.split("/", 1)[-1].lower()
        if requested_type == "bugfix":
            return "bugfix"
        if requested_type == "auto":
            if self.find(full_name, task, requested_type) is not None:
                return "swarm"
            if is_vague(task) and short not in LEGACY_DEMOS:
                return "swarm"  # a vague task on a non-legacy repo goes through the clarify path
            return "bugfix"
        return "swarm"

    def llm_factory(self, full_name: str, task: str, requested_type: str, answers: dict[str, str]) -> Callable[[str, str], Any]:
        script = self.find(full_name, task, requested_type)
        state = ScriptState(script, self.delay_scale, is_vague(task), bool(answers))
        return lambda role, tier: ScriptedLLM(role, tier, state)
