"""Evaluate an engine on a bug tier and print a markdown table.

Usage:
  python scripts/eval.py --engine single|loop|graph --n 5 --tier hard|easy|all [--live] [--nebius-sandbox]

- single: one proposer call (round 1, Nano, first strategy), tested once. The baseline to beat.
- loop:   the beam-search loop engine.
- graph:  the LangGraph team engine.
Without --live everything is fake (scripted agents, local sandbox): numbers only prove the harness works.
--live needs NEBIUS_API_KEY + MODEL_NANO and api.tokenfactory.nebius.com reachable; it checks first and
exits if not (it never substitutes fake numbers). Results go to evals/results/*.json. With
LANGSMITH_API_KEY set, attempts run through langsmith.aevaluate as an experiment on dataset patchloop-<tier>.
"""
import argparse
import asyncio
import dataclasses
import functools
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents import DEFAULT_STRATEGIES, FakeTeam, LiveTeam  # noqa: E402
from app.bugs import BUGS, bugs_in_tier  # noqa: E402
from app.candidate import evaluate_candidate, is_solved  # noqa: E402
from app.config import AGENT_DIR, LOCAL_TEST_TIMEOUT, NEBIUS_BASE_URL, SANDBOX_TEST_TIMEOUT, load_settings  # noqa: E402
from app.graph_engine import BudgetExceeded, GraphCtx, run_graph  # noqa: E402
from app.guard import GuardService  # noqa: E402
from app.llm import make_client  # noqa: E402
from app.proposers import model_for, new_usage, propose_fake, propose_live  # noqa: E402
from app.sandbox import LocalSandbox, NebiusSandbox  # noqa: E402
from app.search import SearchConfig, run_search  # noqa: E402
from app.telemetry import setup_langsmith  # noqa: E402

RESULTS = AGENT_DIR / "evals" / "results"


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


async def reachable(url: str, key: str) -> str | None:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{url.rstrip('/')}/models", headers={"Authorization": f"Bearer {key}"})
        return None if resp.status_code < 500 else f"HTTP {resp.status_code}"
    except Exception as exc:
        return type(exc).__name__


class Harness:
    def __init__(self, args, settings) -> None:
        self.args, self.settings = args, settings
        self.mode = ("live" if args.nebius_sandbox else "hybrid") if args.live else "fake"
        self.sandbox = NebiusSandbox() if args.nebius_sandbox else LocalSandbox()
        self.timeout = SANDBOX_TEST_TIMEOUT if args.nebius_sandbox else LOCAL_TEST_TIMEOUT
        self.guard = GuardService(settings)
        self.team = LiveTeam(settings, args.model) if args.live else FakeTeam(settings.fake_delay_scale)

    async def attempt(self, bug: dict, i: int) -> dict:
        """One attempt -> {bug_id, solved, tokens, latency_ms, guard_blocked, nodes}."""
        t0 = time.monotonic()
        guard = await self.guard.check("input", f"{bug['issue']}\n\n{bug['buggy']}", self.mode)
        if guard["verdict"] == "block":
            return {"bug_id": bug["id"], "attempt": i, "solved": False, "tokens": 0, "guard_blocked": True,
                    "latency_ms": int((time.monotonic() - t0) * 1000), "nodes": 0}
        engine = self.args.engine
        tokens, solved, nodes = 0, False, 0
        if engine == "single":
            root = {"id": 0, "depth": 0, "code": bug["buggy"], "output": ""}
            prop = await self.team.propose(bug, DEFAULT_STRATEGIES[0], root, "", "", 1, 0, None)
            node = await evaluate_candidate(bug, self.sandbox, node_id=1, parent=0, depth=1, idea=prop.idea,
                                            code=prop.code, model=prop.model, extra_files=prop.extra_files,
                                            timeout=self.timeout)
            tokens = prop.usage["prompt_tokens"] + prop.usage["completion_tokens"]
            solved, nodes = is_solved(node), 1
        elif engine == "loop":
            usage = new_usage()
            if self.args.live:
                propose = functools.partial(propose_live, settings=self.settings,
                                            client=make_client(self.settings.nebius_api_key), usage=usage)
                cfg = SearchConfig(test_timeout=self.timeout, usage=usage, model_override=self.args.model,
                                   model_for=lambda d: model_for(d, self.settings, self.args.model))
            else:
                propose, cfg = propose_fake, SearchConfig(test_timeout=self.timeout, usage=usage)
            seen: list = []

            async def emit(kind: str, data: dict) -> None:
                if kind == "node":
                    seen.append(data)

            best, solved = await run_search(bug, self.sandbox, propose, emit, cfg)
            tokens, nodes = usage["prompt_tokens"] + usage["completion_tokens"], len(seen) - 1
        else:
            async def emit(kind: str, data: dict) -> None:
                return None

            ctx = GraphCtx(run_id=f"eval-{bug['id']}-{i}", bug=bug, mode=self.mode, settings=self.settings,
                           sandbox=self.sandbox, team=self.team, guard=self.guard, emit=emit,
                           test_timeout=self.timeout)
            try:
                best = await run_graph(ctx)
                solved = bool(best and is_solved(best))
            except BudgetExceeded:
                solved = False
            tokens, nodes = ctx.tokens, ctx.next_id - 1
        return {"bug_id": bug["id"], "attempt": i, "solved": solved, "tokens": tokens, "guard_blocked": False,
                "latency_ms": int((time.monotonic() - t0) * 1000), "nodes": nodes}


async def run_plain(h: Harness, bugs: list[dict], n: int) -> list[dict]:
    out = []
    for bug in bugs:  # attempts of one bug run concurrently, bugs one after another
        out += await asyncio.gather(*(h.attempt(bug, i) for i in range(n)))
    return out


async def run_langsmith(h: Harness, bugs: list[dict], n: int, tier: str) -> list[dict]:
    from langsmith import Client
    from langsmith.evaluation import aevaluate

    client = Client()
    name = f"patchloop-{tier}"
    if not client.has_dataset(dataset_name=name):
        client.create_dataset(name, description=f"PatchLoop {tier} bugs")
        client.create_examples(dataset_name=name, examples=[{"inputs": {"bug_id": b["id"]}} for b in bugs])
    collected: list[dict] = []
    counters: dict[str, int] = {}

    async def target(inputs: dict) -> dict:
        bug = BUGS[inputs["bug_id"]]
        i = counters.get(bug["id"], 0)
        counters[bug["id"]] = i + 1
        result = await h.attempt(bug, i)
        collected.append(result)
        return result

    def solved(outputs: dict) -> dict:
        return {"key": "solved", "score": int(bool(outputs.get("solved")))}

    await aevaluate(target, data=name, evaluators=[solved], num_repetitions=n, max_concurrency=n, client=client,
                    experiment_prefix=f"{h.args.engine}-{h.mode}",
                    metadata={"engine": h.args.engine, "mode": h.mode, "tier": tier})
    wanted = {b["id"] for b in bugs}
    return [r for r in collected if r["bug_id"] in wanted]


def table(rows: list[dict], bugs: list[dict], n: int) -> str:
    lines = ["| bug | solve rate | tokens / solve | p50 latency | p95 latency | guard blocks |", "|---|---|---|---|---|---|"]

    def line(label: str, rs: list[dict]) -> str:
        solves = sum(r["solved"] for r in rs)
        tokens = sum(r["tokens"] for r in rs)
        lat = [r["latency_ms"] / 1000 for r in rs]
        blocks = sum(r["guard_blocked"] for r in rs)
        tps = f"{tokens / solves:.0f}" if solves else "n/a"
        return (f"| {label} | {solves}/{len(rs)} ({solves / max(1, len(rs)):.0%}) | {tps} | "
                f"{pct(lat, .5):.2f}s | {pct(lat, .95):.2f}s | {blocks}/{len(rs)} ({blocks / max(1, len(rs)):.0%}) |")

    for bug in bugs:
        lines.append(line(bug["id"], [r for r in rows if r["bug_id"] == bug["id"]]))
    lines.append(line("**all**", rows))
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", default="graph", choices=("single", "loop", "graph"))
    parser.add_argument("--n", type=int, default=5)
    parser.add_argument("--tier", default="hard", choices=("easy", "hard", "all"))
    parser.add_argument("--live", action="store_true", help="real Nemotron calls (needs NEBIUS_API_KEY, MODEL_NANO)")
    parser.add_argument("--nebius-sandbox", action="store_true", help="with --live: run tests in Nebius Sandboxes")
    parser.add_argument("--model", default=None, help="model override for every agent")
    args = parser.parse_args()
    settings = load_settings()

    if args.live:
        if not settings.llm_ready:
            sys.exit("--live: not verifiable here: set NEBIUS_API_KEY and MODEL_NANO")
        err = await reachable(NEBIUS_BASE_URL, settings.nebius_api_key)
        if err:
            sys.exit(f"--live: not verifiable here: allow api.tokenfactory.nebius.com ({err})")
    else:
        settings = dataclasses.replace(settings, mode="fake")

    bugs = bugs_in_tier(args.tier)
    h = Harness(args, settings)
    await h.guard.startup()
    langsmith_on = setup_langsmith(settings.langsmith_api_key, settings.langsmith_project)
    t0 = time.monotonic()
    rows = await (run_langsmith(h, bugs, args.n, args.tier) if langsmith_on else run_plain(h, bugs, args.n))
    wall = time.monotonic() - t0

    md = table(rows, bugs, args.n)
    header = (f"engine={args.engine} tier={args.tier} n={args.n} mode={h.mode} guard={h.guard.backend_for(h.mode)} "
              f"langsmith={'on' if langsmith_on else 'off'} wall={wall:.1f}s")
    print(header + "\n")
    print(md)
    if h.mode == "fake":
        print("\nFAKE MODE: scripted agents. These numbers only prove the harness; they are not model results.")
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{args.engine}-{args.tier}-{h.mode}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({"engine": args.engine, "tier": args.tier, "n": args.n, "mode": h.mode,
                               "langsmith": langsmith_on, "wall_s": round(wall, 2), "rows": rows,
                               "solve_rate": statistics.mean([r["solved"] for r in rows]) if rows else 0.0,
                               "table": md}, indent=2))
    print(f"\nwrote {out.relative_to(AGENT_DIR)}")


if __name__ == "__main__":
    asyncio.run(main())
