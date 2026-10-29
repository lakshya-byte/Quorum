"""Check every bug (easy + hard): buggy < partial < correct pass counts, and correct passes all.

Usage: python scripts/04_check_bugs.py [--tier easy|hard|all]
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bugs import bugs_in_tier, files_for  # noqa: E402
from app.config import load_env  # noqa: E402
from app.sandbox import LocalSandbox  # noqa: E402
from app.scoring import parse_unittest  # noqa: E402

STAGES = ("buggy", "partial", "correct")


async def check(sandbox: LocalSandbox, bug: dict) -> bool:
    counts = []
    for stage in (*STAGES, "wrong"):
        _, output = await sandbox.run_tests(files_for(bug, bug[stage]))
        counts.append(parse_unittest(output))
    (b, total), (p, _), (c, _), (w, _) = counts
    ok = b < p < c == total and w < total
    stairs = "  <  ".join(f"{stage} {passed}/{t}" for stage, (passed, t) in zip(STAGES, counts))
    print(f"{'OK  ' if ok else 'FAIL'} {bug.get('tier', 'easy'):<4} {bug['id']:<16} {stairs}   (wrong {w}/{total})")
    return ok


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", default="all", choices=("easy", "hard", "all"))
    args = parser.parse_args()
    load_env()
    sandbox = LocalSandbox()
    results = [await check(sandbox, bug) for bug in bugs_in_tier(args.tier)]
    if not all(results):
        sys.exit(1)
    print("all bugs form a rising staircase")


if __name__ == "__main__":
    asyncio.run(main())
