import asyncio

import pytest

from app.bugs import BUGS
from app.proposers import propose_fake
from app.sandbox import LocalSandbox
from app.search import SearchConfig, run_search


@pytest.mark.parametrize("bug_id", list(BUGS))
def test_fake_search_solves_every_bug(bug_id: str) -> None:
    events: list[tuple[str, dict]] = []

    async def emit(kind: str, data: dict) -> None:
        events.append((kind, data))

    best, solved = asyncio.run(run_search(BUGS[bug_id], LocalSandbox(), propose_fake, emit, SearchConfig()))

    assert solved
    assert best["passed"] == best["total"] > 0
    assert best["depth"] <= 2
    assert best["code"] == BUGS[bug_id]["correct"]
    kinds = [kind for kind, _ in events]
    assert kinds.count("node") >= 4
    assert kinds[-1] == "done"
    assert events[-1][1]["best"]["id"] == best["id"]


def test_search_survives_a_crashing_proposer() -> None:
    async def explode(bug, parent, i, model_override=None):
        raise RuntimeError("boom")

    async def emit(kind: str, data: dict) -> None:
        return None

    bug = BUGS["average"]
    cfg = SearchConfig(max_depth=1)
    best, solved = asyncio.run(run_search(bug, LocalSandbox(), explode, emit, cfg))
    assert not solved
    assert best["id"] == 0
