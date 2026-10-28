"""Run `python --version` inside a Nebius Sandbox."""
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
    image = await client.images.oci(PYTHON_IMAGE)
    res = await image.run(shell="python --version 2>&1", disposable=True, timeout=60)
    print(f"exit_code={res.exit_code} uuid={res.uuid}")
    print(to_text(res.stdout).strip(), to_text(res.stderr).strip())


if __name__ == "__main__":
    asyncio.run(main())
