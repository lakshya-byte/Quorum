"""Check every demo bug: buggy < partial < correct pass counts, and correct passes all."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bugs import BUGS, files_for  # noqa: E402
from app.config import load_env  # noqa: E402
from app.sandbox import LocalSandbox  # noqa: E402
from app.scoring import parse_unittest  # noqa: E402

STAGES = ("buggy", "partial", "correct")


async def check(sandbox: LocalSandbox, bug: dict) -> bool:
    counts = []
    for stage in STAGES:
        _, output = await sandbox.run_tests(files_for(bug, bug[stage]))
        counts.append(parse_unittest(output))
    (b, total), (p, _), (c, _) = counts
    ok = b < p < c == total
    stairs = "  <  ".join(f"{stage} {passed}/{t}" for stage, (passed, t) in zip(STAGES, counts))
    print(f"{'OK  ' if ok else 'FAIL'} {bug['id']:<9} {stairs}")
    return ok


async def main() -> None:
    load_env()
    sandbox = LocalSandbox()
    results = [await check(sandbox, bug) for bug in BUGS.values()]
    if not all(results):
        sys.exit(1)
    print("all bugs form a rising staircase")


if __name__ == "__main__":
    asyncio.run(main())
