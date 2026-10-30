"""Run every swarm demo task against the REAL workspace + verifiers on: the original repo, the reference solution
and each deliberately bad solution; write a proof table (markdown + json) and the react-notes before/after
screenshots.

    cd agent && python scripts/swarm_demo_proof.py [--out ../docs/swarm-proof]

Needs node + npm registry access for react-notes (npm ci) and chromium for the UI criteria; anything missing is
reported as `skip` with its reason, never as pass."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.swarm.demo_tasks import load_swarm_demo, swarm_demo_names  # noqa: E402
from app.swarm.verifiers import ArtifactStore, collect_baseline, run_verifier  # noqa: E402
from app.swarm.workspace import LocalWorkspaceFactory  # noqa: E402


async def prove(repo: str, only: str | None) -> list[dict]:
    demo = load_swarm_demo(repo)
    rows: list[dict] = []
    factory = LocalWorkspaceFactory()
    root = await factory.open(demo.files, language_hint=demo.language_hint)
    shots: list[dict] = []
    try:
        base = await collect_baseline(root, None, ArtifactStore())
        for task in demo.tasks.values():
            if only and task.id != only:
                continue
            variants = {"original": None, "reference": task.reference, **{f"bad:{k}": v for k, v in task.bad.items()}}
            for name, sol in variants.items():
                ws = await root.fork()
                store = ArtifactStore()
                if sol:
                    ws.allow_tests = True  # the bad solutions delete tests; the VERIFIERS must catch that, not the write hook
                    await sol.apply(ws)
                for c in task.criteria:
                    t0 = time.time()
                    r = await run_verifier(c, ws, base, store)
                    rows.append({"repo": repo, "task": task.id, "variant": name, "criterion": c.id, "kind": c.kind,
                                 "hard": c.hard, "status": r.status, "detail": r.detail[:300], "s": round(time.time() - t0, 1)})
                for a in store.list():
                    if a.kind == "screenshot":
                        shots.append({"name": f"{repo}-{name.replace(':', '-')}-{a.phase}-{a.viewport}px.png",
                                      "data": store.bytes_of(a.id)})
                await ws.release()
    finally:
        await root.release()
    return rows + [{"repo": repo, "shots": shots}]


def table(rows: list[dict]) -> str:
    out = []
    for repo_task in sorted({(r["repo"], r["task"]) for r in rows if "task" in r}):
        sub = [r for r in rows if r.get("task") == repo_task[1] and r["repo"] == repo_task[0]]
        variants = list(dict.fromkeys(r["variant"] for r in sub))
        out.append(f"### {repo_task[0]} / {repo_task[1]}\n")
        out.append("| criterion | kind | hard | " + " | ".join(variants) + " |")
        out.append("|---|---|---|" + "---|" * len(variants))
        for crit in dict.fromkeys(r["criterion"] for r in sub):
            line = [r for r in sub if r["criterion"] == crit]
            cells = {r["variant"]: r["status"].upper() for r in line}
            out.append(f"| {crit} | {line[0]['kind']} | {'yes' if line[0]['hard'] else 'advisory'} | " +
                       " | ".join(cells.get(v, "-") for v in variants) + " |")
        out.append("")
    return "\n".join(out)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "docs" / "swarm-proof"))
    ap.add_argument("--repo", default="")
    ap.add_argument("--task", default="")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for repo in swarm_demo_names():
        if args.repo and repo != args.repo:
            continue
        got = await prove(repo, args.task or None)
        for r in got:
            if "shots" in r:
                for sh in r["shots"]:
                    if "-original-after-" in sh["name"] or ("-before-" in sh["name"] and "-original-" not in sh["name"]):
                        continue  # the original's "after" and every other variant's "before" are duplicates
                    (out / sh["name"].replace("-original-before-", "-before-")).write_bytes(sh["data"])
            else:
                rows.append(r)
    (out / "proof.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    md = table(rows)
    (out / "PROOF.md").write_text("# Verifier proof matrix (real runs)\n\n" + md + "\n", encoding="utf-8")
    print(md)
    for r in rows:
        if r["status"] == "skip":
            print(f"skip: {r['repo']}/{r['task']}/{r['variant']}/{r['criterion']}: {r['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
