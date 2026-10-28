"""Run the whole search in fake mode for one bug (default: cart) and print the tree."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bugs import BUGS  # noqa: E402
from app.config import load_env  # noqa: E402
from app.proposers import propose_fake  # noqa: E402
from app.sandbox import LocalSandbox  # noqa: E402
from app.search import SearchConfig, run_search  # noqa: E402


def print_tree(nodes: list[dict], best_id: int) -> None:
    children: dict[int | None, list[dict]] = {}
    for node in nodes:
        children.setdefault(node["parent"], []).append(node)

    def walk(node: dict, indent: str) -> None:
        mark = "  <== best" if node["id"] == best_id else ""
        print(f"{indent}#{node['id']} [{node['passed']}/{node['total']} score={node['score']:.3f}] {node['idea']}{mark}")
        for child in sorted(children.get(node["id"], []), key=lambda n: n["id"]):
            walk(child, indent + "    ")

    for root in children.get(None, []):
        walk(root, "")


async def main(bug_id: str) -> None:
    load_env()
    bug = BUGS.get(bug_id) or sys.exit(f"unknown bug {bug_id!r}; choose from {', '.join(BUGS)}")
    nodes: list[dict] = []

    async def emit(kind: str, data: dict) -> None:
        if kind == "node":
            nodes.append(data)
        elif kind == "round":
            print(f"-- round {data['depth']}")

    best, solved = await run_search(bug, LocalSandbox(), propose_fake, emit, SearchConfig())
    print(f"\nTree for {bug['id']}:")
    print_tree(nodes, best["id"])
    print(f"\nbest: #{best['id']} (round {best['depth']}) {best['passed']}/{best['total']}")
    print(f"solved: {solved}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "cart"))
