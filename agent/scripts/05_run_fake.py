"""Run one bug end to end in fake mode and print the event log and the tree.

Usage: python scripts/05_run_fake.py [bug] [--engine graph|loop]   (default: cart, graph)
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents import FakeTeam  # noqa: E402
from app.bugs import BUGS  # noqa: E402
from app.candidate import is_solved  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.graph_engine import GraphCtx, run_graph  # noqa: E402
from app.guard import GuardService  # noqa: E402
from app.proposers import propose_fake  # noqa: E402
from app.sandbox import LocalSandbox  # noqa: E402
from app.search import SearchConfig, run_search  # noqa: E402


def print_tree(nodes: list[dict], best_id: int) -> None:
    children: dict[int | None, list[dict]] = {}
    for node in nodes:
        children.setdefault(node["parent"], []).append(node)

    def walk(node: dict, indent: str) -> None:
        mark = "  <== best" if node["id"] == best_id else ""
        gate = "" if node.get("policy", {}).get("ok", True) else "  [POLICY BLOCKED]"
        if not node.get("security", {}).get("ok", True):
            gate += "  [SECURITY BLOCKED]"
        print(f"{indent}#{node['id']} [{node['passed']}/{node['total']} score={node['score']:.3f}] "
              f"{node['idea']}{gate}{mark}")
        for child in sorted(children.get(node["id"], []), key=lambda n: n["id"]):
            walk(child, indent + "    ")

    for root in children.get(None, []):
        walk(root, "")


async def main(bug_id: str, engine: str) -> None:
    settings = load_settings()
    bug = BUGS.get(bug_id) or sys.exit(f"unknown bug {bug_id!r}; choose from {', '.join(BUGS)}")
    nodes: list[dict] = []
    t0 = time.monotonic()
    done: dict = {}

    async def emit(kind: str, data: dict) -> None:
        nonlocal done
        ms = int((time.monotonic() - t0) * 1000)
        if kind == "node":
            nodes.append(data)
            print(f"{ms:>6}ms node #{data['id']} r{data['depth']} {data['passed']}/{data['total']} "
                  f"policy={data['policy']['ok']} security={data['security']['ok']} {data['idea']}")
        elif kind == "done":
            done = data
            print(f"{ms:>6}ms done solved={data['solved']} best=#{data['best']['id']}")
        elif kind == "guard":
            print(f"{ms:>6}ms guard {data['stage']} {data['verdict']} ({data['backend']}, {data['latency_ms']}ms)")
        elif kind == "triage":
            print(f"{ms:>6}ms triage: {data['cause']} strategies={len(data['strategies'])}")
        elif kind == "critic":
            print(f"{ms:>6}ms critic #{data['node_id']}: {data['lesson']}")
        else:
            print(f"{ms:>6}ms {kind} {data}")

    sandbox = LocalSandbox()
    if engine == "graph":
        guard = GuardService(settings)
        await guard.startup()
        ctx = GraphCtx(run_id="script05", bug=bug, mode="fake", settings=settings, sandbox=sandbox,
                       team=FakeTeam(settings.fake_delay_scale), guard=guard, emit=emit)
        await run_graph(ctx)
        best = done["best"]
        print(f"\ncancelled by early exit: {ctx.cancelled}")
        if ctx.pr_draft:
            print(f"PR draft: {ctx.pr_draft['title']!r} (output guard: {ctx.pr_draft['guard']})")
    else:
        best, _ = await run_search(bug, sandbox, propose_fake, emit, SearchConfig())
    print(f"\nTree for {bug['id']} (engine={engine}):")
    print_tree(nodes, best["id"])
    print(f"\nbest: #{best['id']} (round {best['depth']}) {best['passed']}/{best['total']}")
    print(f"solved: {is_solved(best)}  wall: {int((time.monotonic() - t0) * 1000)}ms")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("bug", nargs="?", default="cart")
    parser.add_argument("--engine", default="graph", choices=("graph", "loop"))
    args = parser.parse_args()
    asyncio.run(main(args.bug, args.engine))
