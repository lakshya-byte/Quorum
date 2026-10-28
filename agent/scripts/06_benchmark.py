"""Benchmark single-shot fixing vs the full beam search on every bug.

Usage: python scripts/06_benchmark.py [N] [--live] [--model MODEL_ID]
Default sandbox is local (hybrid); --live uses Nebius Sandboxes. Without LLM credentials it runs fake mode.
"""
import argparse
import asyncio
import functools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bugs import BUGS  # noqa: E402
from app.config import LOCAL_TEST_TIMEOUT, SANDBOX_TEST_TIMEOUT, load_settings  # noqa: E402
from app.llm import make_client  # noqa: E402
from app.proposers import model_for, new_usage, propose_fake, propose_live  # noqa: E402
from app.sandbox import LocalSandbox, NebiusSandbox  # noqa: E402
from app.search import SearchConfig, evaluate, is_solved, run_search  # noqa: E402


async def ignore(kind: str, data: dict) -> None:
    return None


def tokens(usage: dict) -> int:
    return usage["prompt_tokens"] + usage["completion_tokens"]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("n", nargs="?", type=int, default=3)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--model", default=None, help="model override, e.g. MODEL_ULTRA's id")
    args = parser.parse_args()

    settings = load_settings()
    fake = not settings.llm_ready
    model_override = args.model or None
    sandbox = NebiusSandbox() if args.live else LocalSandbox()
    timeout = SANDBOX_TEST_TIMEOUT if args.live else LOCAL_TEST_TIMEOUT
    client = None if fake else make_client(settings.nebius_api_key)
    print(f"mode={'fake' if fake else ('live' if args.live else 'hybrid')} n={args.n}\n")

    def proposer(usage: dict):
        if fake:
            return propose_fake
        return functools.partial(propose_live, settings=settings, client=client, usage=usage)

    def config(usage: dict) -> SearchConfig:
        return SearchConfig(
            test_timeout=timeout, usage=usage, model_override=model_override,
            model_for=lambda d: "fake" if fake else model_for(d, settings, model_override),
        )

    rows = []
    for bug in BUGS.values():
        single_usage, search_usage = new_usage(), new_usage()
        root = await evaluate(bug, sandbox, config(single_usage), node_id=0, parent=None, depth=0,
                              idea="original", code=bug["buggy"], model="-")

        async def single_shot(i: int) -> bool:
            idea, code = await proposer(single_usage)(bug, root, i, model_override)
            node = await evaluate(bug, sandbox, config(single_usage), node_id=i + 1, parent=0, depth=1,
                                  idea=idea, code=code, model="")
            return is_solved(node)

        async def full_search() -> bool:
            _, solved = await run_search(bug, sandbox, proposer(search_usage), ignore, config(search_usage))
            return solved

        singles = await asyncio.gather(*(single_shot(i) for i in range(args.n)))
        searches = await asyncio.gather(*(full_search() for _ in range(args.n)))
        rows.append((bug["id"], sum(singles), sum(searches), tokens(single_usage), tokens(search_usage)))

    print("| bug | single-shot solved | search solved | single-shot tokens | search tokens |")
    print("|---|---|---|---|---|")
    for bug_id, single, search, t1, t2 in rows:
        print(f"| {bug_id} | {single}/{args.n} | {search}/{args.n} | {t1} | {t2} |")
    print(f"| **total** | {sum(r[1] for r in rows)}/{args.n * len(rows)} | "
          f"{sum(r[2] for r in rows)}/{args.n * len(rows)} | {sum(r[3] for r in rows)} | {sum(r[4] for r in rows)} |")


if __name__ == "__main__":
    asyncio.run(main())
