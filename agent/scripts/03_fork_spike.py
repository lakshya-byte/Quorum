"""Prove branching: two parallel forks of one checkpoint never see each other's writes."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import PYTHON_IMAGE, load_env  # noqa: E402
from app.sandbox import to_text  # noqa: E402


async def main() -> None:
    load_env()
    from contree_sdk import Contree

    client = Contree()
    base = await client.images.oci(PYTHON_IMAGE)
    checkpoint = await base.run(
        shell="cat /work/state.txt", files={"/work/state.txt": b"original\n"}, disposable=False, timeout=60,
    )
    print(f"checkpoint {checkpoint.uuid}: {to_text(checkpoint.stdout).strip()}")

    async def fork(label: str):
        return await checkpoint.run(
            shell=f"echo {label} > /work/state.txt && cat /work/state.txt", disposable=True, timeout=60,
        )

    fork_a, fork_b = await asyncio.gather(fork("FIX-A"), fork("FIX-B"))
    print(f"fork A: {to_text(fork_a.stdout).strip()}")
    print(f"fork B: {to_text(fork_b.stdout).strip()}")

    check = await checkpoint.run(shell="cat /work/state.txt", disposable=True, timeout=60)
    print(f"checkpoint after forks: {to_text(check.stdout).strip()}")


if __name__ == "__main__":
    asyncio.run(main())
