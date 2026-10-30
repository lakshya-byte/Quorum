"""The swarm engine end to end with the scripted team: REAL tools, REAL workspace subprocesses, REAL (fake-registry)
verifiers, REAL scheduler / integrator / outcome. Only the LLM is replayed."""
import asyncio
import copy
import json
import time
from pathlib import Path

import pytest

from app.swarm.engine import compute_outcome, live_llm_factory, local_policy, local_secrets, run_swarm
from app.swarm.types import CriterionSpec, Plan, Unit, VerifyRow
from tests import swarm_support as sup
from tests.swarm_support import (INVENTORY, NOTES_UI, PRICING_NEW, STOCK_NEW, STOCK_REFACTORED, TmpWorkspace, feature_script,
                                 make_ctx, refactor_script, ui_script)

TOKEN = "ghs_SuperSecretInstallToken123456"


def go(ctx):
    return asyncio.run(run_swarm(ctx))


def of(events, kind):
    return [d for k, d in events if k == kind]


def feature_run(tmp_path, script=None, **kw):
    ev: list = []
    ctx = make_ctx(INVENTORY, "Add a bulk discount: orders of 10 or more units get 10% off", [script or feature_script()],
                   tmp_path, events=ev, task_type=kw.pop("task_type", "feature"), **kw)
    go(ctx)
    return ctx, ev


# ---- the happy paths ---------------------------------------------------------------------------------------

def test_feature_runs_tests_first_in_parallel_with_variants_and_lands_per_unit_commits(tmp_path: Path) -> None:
    sup.TmpWorkspace.instances.clear()
    ctx, ev = feature_run(tmp_path)
    kinds = [k for k, _ in ev]
    # contract event order: plan before any agent work, verify before done
    assert kinds.index("plan") < kinds.index("round") < kinds.index("verify") < kinds.index("done")
    assert kinds.count("done") == 1 and kinds.index("merge") < kinds.index("verify")
    plan = of(ev, "plan")[0]
    assert plan["task_type"] == "feature" and plan["task_type_source"] == "user"
    assert not any("validation" in c for c in plan["criteria"])  # the first plan event is the planner's raw proposal
    acc = next(c for c in of(ev, "plan")[-1]["criteria"] if c["kind"] == "acceptance_tests")
    assert acc["hard"] and "fails on the original" in acc["validation"]
    done = of(ev, "done")[0]
    assert done["outcome"] == "complete" and done["solved"] is True and done["task_type"] == "feature"
    assert done["criteria"]["hard_pass"] == done["criteria"]["hard_total"] >= 6
    best = done["best"]
    assert set(best["files"]) == {"tests/test_bulk.py", "inventory/pricing.py", "inventory/stock.py"}
    assert "line_price" in best["diff"] and len(best["diff"]) <= 20000
    # dependency order, and the losing variant was cancelled (not left running)
    agents = of(ev, "agent")
    order = [(a["id"], a["status"]) for a in agents if a["role"] == "worker"]
    assert order.index(("r1.pricing.v0", "done")) < order.index(("r1.stock.v0", "spawned"))
    assert ("r1.stock.v1", "cancelled") in order and ("r1.stock.v0", "done") in order
    units = {u["id"]: u for u in of(ev, "unit") if u["status"] == "passed"}
    assert units["stock"]["winner_variant"] == 0 and units["stock"]["files"] == ["inventory/stock.py"]
    assert {u["id"] for u in of(ev, "unit") if u["status"] == "merged"} == {"pricing", "stock"}
    assert of(ev, "merge")[-1] == {"status": "ok", "units": ["pricing", "stock"], "conflicts": []}
    # one commit per unit, verification tests first (what the PR will contain)
    assert [c["unit_id"] for c in ctx.result["commits"]] == ["pricing", "stock"]
    assert ctx.result["spec_files"].keys() == {"tests/test_bulk.py"}
    assert done["agents"]["spawned"] >= 4 and 1 <= done["agents"]["peak_parallel"] <= 4
    # every sandbox fork and checkpoint was released, including the cancelled variant's
    assert sup.TmpWorkspace.instances and all(w.released for w in sup.TmpWorkspace.instances)
    # artifacts from the verifier store were announced
    assert of(ev, "artifact") and {"id", "kind", "label", "phase", "mime"} <= set(of(ev, "artifact")[0])


def test_verify_event_carries_every_criterion_with_status_and_summary(tmp_path: Path) -> None:
    _, ev = feature_run(tmp_path)
    v = of(ev, "verify")[-1]
    assert v["round"] == 1 and v["hard_pass"] is True
    assert {r["kind"] for r in v["results"]} >= {"build", "no_regression", "policy", "security", "secrets", "acceptance_tests"}
    assert all(r["status"] in ("pass", "fail", "skip", "advisory") and len(r["detail"]) <= 500 for r in v["results"])
    assert sum(v["summary"].values()) == len(v["results"])


def test_refactor_uses_characterization_tests_and_the_api_surface_gate(tmp_path: Path) -> None:
    ev: list = []
    ctx = make_ctx(INVENTORY, "Extract the quantity validation in stock.py into a helper", [refactor_script()], tmp_path,
                   events=ev, task_type="refactor")
    go(ctx)
    done = of(ev, "done")[0]
    assert done["outcome"] == "complete" and done["task_type"] == "refactor"
    kinds = {r["kind"]: r["status"] for r in of(ev, "verify")[-1]["results"]}
    assert kinds["characterization"] == kinds["api_surface"] == kinds["lint_typecheck"] == "pass"
    spec_agent = [a for a in of(ev, "agent") if a["role"] == "spec" and a["status"] == "done"][0]
    assert "passes on the original" in spec_agent["summary"]
    assert "_positive" in done["best"]["files"]["inventory/stock.py"]


def test_ui_task_gets_ui_gates_plus_non_gating_advisory_notes(tmp_path: Path) -> None:
    ev: list = []
    script = ui_script()
    ctx = make_ctx(NOTES_UI, "Improve the UI of the notes page on mobile", [script], tmp_path, events=ev, task_type="ui",
                   repo="demo/react-notes")
    go(ctx)
    done = of(ev, "done")[0]
    assert done["outcome"] == "complete"
    rows = {r["kind"]: r for r in of(ev, "verify")[-1]["results"]}
    assert {"ui_build_console", "ui_overflow", "ui_axe", "ui_smoke"} <= {k for k, r in rows.items() if r["hard"]}
    assert rows["advisory_vision"]["status"] == "advisory" and rows["advisory_vision"]["score"] == 0.8
    assert {a["kind"] for a in done["criteria"]["advisory"]} == {"advisory_vision", "advisory_rubric"}
    assert rows["ui_overflow"]["artifacts"]  # screenshot artifact referenced by the gate
    assert [a for a in of(ev, "artifact") if a["kind"] == "screenshot"]


# ---- failure, repair rounds, honesty about gaps ------------------------------------------------------------------

def test_failed_hard_gate_triggers_critic_repair_units_in_the_next_round(tmp_path: Path) -> None:
    script = feature_script()
    script["workers"]["stock"] = [{"variant": 0, "steps": [  # first attempt forgets to use line_price
        {"tool": "write_file", "args": {"path": "inventory/stock.py", "content": INVENTORY["inventory/stock.py"] + "\n# touched\n"}}]},
        {"variant": 1, "steps": [
            {"tool": "write_file", "args": {"path": "inventory/stock.py", "content": INVENTORY["inventory/stock.py"] + "\n# touched\n"}}]}]
    script["critic"] = [{"lesson": "Inventory.value must use line_price", "units": [
        {"id": "fix1", "title": "Use line_price", "scope_files": ["inventory/stock.py"], "instructions": "use line_price",
         "criterion_ids": ["bulk_acceptance"]}]}]
    script["workers"]["r2-fix1"] = [{"variant": 0, "steps": [
        {"tool": "write_file", "args": {"path": "inventory/stock.py", "content": STOCK_NEW}}]}]
    ctx, ev = feature_run(tmp_path, script)
    rounds = of(ev, "round")
    assert [r["depth"] for r in rounds] == [1, 2] and rounds[1]["units"] == ["r2-fix1"]
    verifies = of(ev, "verify")
    assert verifies[0]["hard_pass"] is False and verifies[1]["hard_pass"] is True
    failed = [r for r in verifies[0]["results"] if r["status"] == "fail"]
    assert [r["kind"] for r in failed] == ["acceptance_tests"]
    assert of(ev, "critic")[0]["lesson"].startswith("Inventory.value")
    done = of(ev, "done")[0]
    assert done["outcome"] == "complete" and done["rounds"] == 2
    assert [c["unit_id"] for c in ctx.result["commits"]] == ["pricing", "stock", "r2-fix1"]


def test_rounds_are_capped_by_the_env_cap_and_an_unfixed_run_is_failed_not_declared_done(tmp_path: Path) -> None:
    script = feature_script()
    script["workers"]["stock"] = [{"variant": 0, "steps": [
        {"tool": "write_file", "args": {"path": "inventory/stock.py", "content": INVENTORY["inventory/stock.py"] + "\n# x\n"}}]},
        {"variant": 1, "steps": [{"tool": "finish", "args": {"summary": "x"}}]}]
    ctx, ev = feature_run(tmp_path, script, swarm_max_rounds=2)
    done = of(ev, "done")[0]
    assert done["outcome"] == "failed" and done["solved"] is False and done["rounds"] == 2
    assert len(of(ev, "round")) == 2 and "acceptance" in " ".join(done["reasons"]).lower() or done["reasons"]
    assert done["best"]["files"].keys() >= {"inventory/pricing.py"}  # the work is reported, but no PR-able success


def test_unit_whose_workers_all_fail_is_retried_then_reported(tmp_path: Path) -> None:
    script = feature_script()
    script["workers"]["pricing"] = [{"variant": 0, "steps": [{"tool": "finish", "args": {"summary": "no idea"}}]}]
    ctx, ev = feature_run(tmp_path, script, swarm_max_rounds=1)
    pricing = [u for u in of(ev, "unit") if u["id"] == "pricing"]
    assert [u["status"] for u in pricing][-1] == "failed"
    assert [u["status"] for u in of(ev, "unit") if u["id"] == "stock"][-1] == "cancelled"  # dependency did not land
    assert any(a["id"].endswith(".a1") for a in of(ev, "agent"))  # one retry with the stronger model
    assert of(ev, "done")[0]["outcome"] == "failed"


def test_unverifiable_criterion_is_downgraded_and_the_outcome_is_partial_not_complete(tmp_path: Path) -> None:
    script = feature_script()
    script["spec"]["bulk_acceptance"] = {"files": {"tests/test_bulk.py": "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertTrue(True)\n"}}
    ctx, ev = feature_run(tmp_path, script)
    plan = of(ev, "plan")[-1]
    c = next(c for c in plan["criteria"] if c["id"] == "bulk_acceptance")
    assert c["hard"] is False and c["downgraded"]
    done = of(ev, "done")[0]
    assert done["outcome"] == "partial" and done["solved"] is False
    assert any("bulk_acceptance" in r for r in done["reasons"])
    assert any(n for n in plan["notes"] if "downgraded" in n)


def test_task_types_without_any_executable_verifier_end_partial_with_the_reason(tmp_path: Path) -> None:
    script = {"id": "docs", "match": {"repo": "inventory-lib", "task_type": "docs"},
              "plan": {"task_type": "docs", "summary": "write a README", "units": [{"id": "readme", "scope_files": ["README.md"]}]},
              "workers": {"readme": [{"variant": 0, "steps": [
                  {"tool": "write_file", "args": {"path": "README.md", "content": "# Inventory\n"}}]}]}}
    ev: list = []
    go(make_ctx(INVENTORY, "Document the inventory package in a README", [script], tmp_path, events=ev, task_type="docs"))
    done = of(ev, "done")[0]
    assert done["outcome"] == "partial" and any("no executable task-specific verifier" in r for r in done["reasons"])
    assert any("NO_EXECUTABLE_TASK_VERIFIER" in n for n in of(ev, "plan")[-1]["notes"])


def test_strict_promotes_an_advisory_criterion_to_a_real_gate(tmp_path: Path) -> None:
    real = sup.run_verifier

    async def harsh(c, ws, baseline, store):  # the vision reviewer scores 0.3
        res = await real(c, ws, baseline, store)
        if c.kind == "advisory_vision":
            res.score = 0.3
        return res

    ev: list = []
    ctx = make_ctx(NOTES_UI, "Improve the UI of the notes page on mobile", [ui_script()], tmp_path, events=ev, task_type="ui",
                   repo="demo/react-notes", strict=["advisory_vision"])
    ctx.deps.run_verifier = harsh
    go(ctx)
    row = next(r for r in of(ev, "verify")[-1]["results"] if r["kind"] == "advisory_vision")
    assert row["hard"] is True and row["status"] == "fail" and "strict" in row["detail"]
    assert of(ev, "done")[0]["outcome"] == "failed"
    # without strict the same low score is only reported
    ev2: list = []
    ctx2 = make_ctx(NOTES_UI, "Improve the UI of the notes page on mobile", [ui_script()], tmp_path / "b", events=ev2,
                    task_type="ui", repo="demo/react-notes")
    ctx2.deps.run_verifier = harsh
    go(ctx2)
    assert of(ev2, "done")[0]["outcome"] == "complete"


def test_policy_failure_is_a_block_and_cannot_be_overridden_by_the_verifier(tmp_path: Path) -> None:
    real = sup.run_verifier

    async def lying(c, ws, baseline, store):  # a buggy verifier says everything passes
        res = await real(c, ws, baseline, store)
        res.status = "pass" if c.kind in ("policy", "secrets") else res.status
        return res

    script = feature_script()
    script["workers"]["pricing"][0]["steps"].insert(1, {"tool": "write_file", "args": {"path": "tests/test_stock.py", "content": "x"}})
    ev: list = []
    ctx = make_ctx(INVENTORY, "Add a bulk discount", [script], tmp_path, events=ev, task_type="feature")
    ctx.deps.run_verifier = lying
    go(ctx)
    # the worker's attempt to touch an existing test was refused by the tool gate, so the run is still clean
    assert of(ev, "done")[0]["outcome"] == "complete"
    assert any(t for t in of(ev, "tool") if t["note"] == "policy denied")
    # and the independent code gate catches tampering that bypassed the tools
    ok, why = local_policy({"tests/test_stock.py": "x", ".github/ci.yml": "y"}, INVENTORY, "feature", "local")
    assert not ok and "test file" in why or not ok
    assert not local_secrets({"a.py": "k = 'ghp_" + "b" * 30 + "'"})[0]


# ---- caps, budgets, locks, cancellation -------------------------------------------------------------------------------

def parallel_script(n=4, variants=2, overlap=False, delay=200):
    units = [{"id": f"u{i}", "scope_files": ["inventory/shared.py" if overlap else f"inventory/m{i}.py"], "variants": variants}
             for i in range(n)]
    workers = {f"u{i}": [{"variant": v, "steps": [
        {"tool": "search", "args": {"regex": "x"}, "delay_ms": delay * (v + 1)},
        {"tool": "write_file", "args": {"path": "inventory/shared.py" if overlap else f"inventory/m{i}.py",
                                         "content": f"V{i} = {i}\n"}}]} for v in range(variants)] for i in range(n)}
    return {"id": "par", "match": {"repo": "inventory-lib", "task_type": "other"},
            "plan": {"task_type": "other", "summary": "parallel", "units": units, "swarm": {"max_parallel": 99}},
            "workers": workers}


def spans(ev, unit_ids):
    """(first running, last done/failed/cancelled index) per unit from the worker agent events."""
    out = {}
    for u in unit_ids:
        idx = [i for i, (k, d) in enumerate(ev) if k == "agent" and d.get("unit_id") == u]
        out[u] = (idx[0], idx[-1])
    return out


def test_parallelism_never_exceeds_the_worker_cap_even_if_the_plan_and_user_ask_for_more(tmp_path: Path) -> None:
    ev: list = []
    ctx = make_ctx({**INVENTORY, **{f"inventory/m{i}.py": "x = 1\n" for i in range(4)}}, "do four independent things",
                   [parallel_script()], tmp_path, events=ev, task_type="other", limits={"max_workers": 1000}, swarm_max_workers=3)
    go(ctx)
    plan = of(ev, "plan")[0]
    assert plan["swarm"]["max_parallel"] <= 3 and plan["swarm"]["limits"]["max_workers"] == 3
    peak = ctx.result["budget"].peak_parallel
    assert 2 <= peak <= 3
    # replay agent events: simultaneously running workers never exceed 3
    live: set[str] = set()
    peak_seen = 0
    for k, d in ev:
        if k == "agent" and d["role"] == "worker":
            if d["status"] == "running":
                live.add(d["id"])
            elif d["status"] in ("done", "failed", "cancelled"):
                live.discard(d["id"])
            peak_seen = max(peak_seen, len(live))
    assert peak_seen <= 3
    assert of(ev, "done")[0]["agents"]["peak_parallel"] == peak


def test_user_limits_lower_the_caps(tmp_path: Path) -> None:
    ev: list = []
    ctx = make_ctx({**INVENTORY, **{f"inventory/m{i}.py": "x = 1\n" for i in range(4)}}, "four independent things",
                   [parallel_script(variants=1)], tmp_path, events=ev, task_type="other", limits={"max_workers": 1})
    go(ctx)
    assert ctx.result["budget"].peak_parallel == 1
    assert of(ev, "plan")[0]["swarm"]["limits"]["max_workers"] == 1


def test_units_with_overlapping_file_scopes_never_run_at_the_same_time(tmp_path: Path) -> None:
    ev: list = []
    ctx = make_ctx({**INVENTORY, "inventory/shared.py": "x = 0\n"}, "touch the shared module twice",
                   [parallel_script(n=3, variants=1, overlap=True, delay=50)], tmp_path, events=ev, task_type="other",
                   swarm_max_workers=8)
    go(ctx)
    sp = spans(ev, ["u0", "u1", "u2"])
    ordered = sorted(sp.values())
    assert all(a[1] < b[0] for a, b in zip(ordered, ordered[1:])), sp  # strictly serial
    assert ctx.result["budget"].peak_parallel == 1


def test_independent_units_do_run_in_parallel(tmp_path: Path) -> None:
    ev: list = []
    ctx = make_ctx({**INVENTORY, **{f"inventory/m{i}.py": "x = 1\n" for i in range(3)}}, "three independent things",
                   [parallel_script(n=3, variants=1, delay=100)], tmp_path, events=ev, task_type="other", swarm_max_workers=8)
    go(ctx)
    assert ctx.result["budget"].peak_parallel == 3


def test_token_budget_stops_the_run_and_reports_failure(tmp_path: Path) -> None:
    ev: list = []
    ctx = make_ctx(INVENTORY, "Add a bulk discount", [feature_script()], tmp_path, events=ev, task_type="feature",
                   limits={"max_tokens": 1000})
    go(ctx)
    done = of(ev, "done")[0]
    assert done["outcome"] == "failed" and done["usage"]["prompt_tokens"] + done["usage"]["completion_tokens"] < 6000
    assert done["stopped"] == "budget" or done["rounds"] >= 1


def test_wall_budget_cuts_a_slow_worker_off(tmp_path: Path) -> None:
    script = feature_script()
    script["workers"]["pricing"] = [{"variant": 0, "steps": [{"tool": "search", "args": {"regex": "x"}, "delay_ms": 30000}]}]
    ev: list = []
    ctx = make_ctx(INVENTORY, "Add a bulk discount", [script], tmp_path, events=ev, task_type="feature", limits={"max_wall_s": 2})
    t0 = time.monotonic()
    go(ctx)
    assert time.monotonic() - t0 < 12
    assert of(ev, "done")[0]["outcome"] == "failed"


def test_budget_events_flow_while_running_at_most_two_seconds_apart(tmp_path: Path) -> None:
    script = feature_script()
    script["workers"]["pricing"][0]["steps"].insert(0, {"tool": "search", "args": {"regex": "x"}, "delay_ms": 900})
    ev: list = []
    ctx = make_ctx(INVENTORY, "Add a bulk discount", [script], tmp_path, events=ev, task_type="feature")
    go(ctx)
    budgets = of(ev, "budget")
    assert len(budgets) >= 3
    b = budgets[-1]
    assert set(b) == {"tokens_used", "tokens_limit", "wall_s", "wall_limit_s", "workers_active"}
    assert b["tokens_used"] > 0 and b["tokens_limit"] == ctx.settings.swarm_max_tokens
    assert max(x["workers_active"] for x in budgets) >= 1


def test_cancelling_the_run_stops_workers_and_releases_every_sandbox(tmp_path: Path) -> None:
    sup.TmpWorkspace.instances.clear()
    script = feature_script()
    script["workers"]["pricing"][0]["steps"].insert(0, {"tool": "search", "args": {"regex": "x"}, "delay_ms": 20000})

    async def main():
        ctx = make_ctx(INVENTORY, "Add a bulk discount", [script], tmp_path, task_type="feature")
        t = asyncio.create_task(run_swarm(ctx))
        await asyncio.sleep(1.2)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t

    asyncio.run(main())
    assert sup.TmpWorkspace.instances and all(w.released for w in sup.TmpWorkspace.instances)


# ---- merge conflicts --------------------------------------------------------------------------------------------------

def conflict_script(resolution: str | None):
    s = {"id": "conf", "match": {"repo": "inventory-lib", "task_type": "other"},
         "plan": {"task_type": "other", "summary": "two units add the same helper", "units": [
             {"id": "a", "scope_files": ["inventory/pricing.py"]}, {"id": "b", "scope_files": ["inventory/stock.py"]}]},
         "workers": {
             "a": [{"variant": 0, "steps": [
                 {"tool": "write_file", "args": {"path": "inventory/util.py", "content": "def helper():\n    return 'a'\n"}},
                 {"tool": "write_file", "args": {"path": "inventory/pricing.py", "content": PRICING_NEW}}]}],
             "b": [{"variant": 0, "steps": [
                 {"tool": "write_file", "args": {"path": "inventory/util.py", "content": "def helper():\n    return 'b'\n"}},
                 {"tool": "write_file", "args": {"path": "inventory/stock.py", "content": STOCK_REFACTORED}}]}]}}
    if resolution is not None:
        s["integrator"] = {"inventory/util.py": resolution}
    return s


def test_real_conflicts_go_to_the_integrator_agent_and_resolution_is_validated(tmp_path: Path) -> None:
    ev: list = []
    both = "def helper():\n    return ('a', 'b')\n"
    ctx = make_ctx(INVENTORY, "two units both add the same helper module", [conflict_script(both)], tmp_path, events=ev, task_type="other")
    go(ctx)
    merges = of(ev, "merge")
    assert [m["status"] for m in merges] == ["conflict", "resolved"] and merges[-1]["conflicts"] == ["inventory/util.py"]
    assert any(a["role"] == "integrator" and a["status"] == "done" for a in of(ev, "agent"))
    assert ctx.result["final_files"]["inventory/util.py"] == both


def test_an_unresolved_or_invalid_integrator_answer_fails_the_merge_without_corrupting_files(tmp_path: Path) -> None:
    ev: list = []
    bad = "<<<<<<< ours\n=======\n>>>>>>> theirs\n"
    ctx = make_ctx(INVENTORY, "two units both add the same helper module", [conflict_script(bad)], tmp_path, events=ev, task_type="other")
    go(ctx)
    assert of(ev, "merge")[-1]["status"] == "failed"
    assert "<<<<<<<" not in json.dumps(ctx.result["final_files"])
    assert any(a["role"] == "integrator" and a["status"] == "failed" for a in of(ev, "agent"))


def test_three_way_merge_combines_disjoint_edits_and_flags_overlaps() -> None:
    from app.swarm.integrator import merge3

    base = "a\nb\nc\nd\ne\n"
    merged, conflict = merge3(base, "a\nB\nc\nd\ne\n", "a\nb\nc\nd\nE\n")
    assert (merged, conflict) == ("a\nB\nc\nd\nE\n", False)
    assert merge3(base, "a\nX\nc\nd\ne\n", "a\nY\nc\nd\ne\n")[1] is True
    assert merge3(base, "a\nX\nc\nd\ne\n", "a\nX\nc\nd\ne\n") == ("a\nX\nc\nd\ne\n", False)
    assert merge3("", "n\n", "n\n") == ("n\n", False)


# ---- clarify / needs_input / resume --------------------------------------------------------------------------------------

def test_vague_tasks_ask_at_most_three_questions_and_end_needs_input_and_resume_with_answers(tmp_path: Path) -> None:
    ev: list = []
    ctx = make_ctx(INVENTORY, "improve it", [refactor_script()], tmp_path, events=ev, task_type="refactor")
    go(ctx)
    clarify = of(ev, "clarify")[0]
    assert 1 <= len(clarify["questions"]) <= 3 and all(q["id"] and q["text"] for q in clarify["questions"])
    done = of(ev, "done")[0]
    assert done["outcome"] == "needs_input" and done["solved"] is False and not of(ev, "round")
    assert not [a for a in of(ev, "agent") if a["role"] == "worker"]
    # resumed with answers: same task text + answers => the run proceeds
    ev2: list = []
    ctx2 = make_ctx(INVENTORY, "improve it", [refactor_script()], tmp_path / "r2", events=ev2, task_type="refactor",
                    answers={"scope": "extract validation in stock.py", "done": "tests still pass"})
    go(ctx2)
    assert not of(ev2, "clarify") and of(ev2, "done")[0]["outcome"] == "complete"


# ---- outcome table (pure) --------------------------------------------------------------------------------------------------

def row(cid, kind, hard, status, detail=""):
    return VerifyRow(cid, kind, hard, status, None, detail)


def plan_with(ttype="feature", **kw):
    from app.swarm.planner import finalize_plan
    from tests.swarm_support import settings
    from app.swarm.budget import resolve_limits

    return finalize_plan(Plan(task_type=ttype, units=[Unit(id="u")]), requested_type=ttype, strict=[],
                         limits=resolve_limits(settings()), files={}, answers={})


def hard_rows(plan, **status):
    return [row(c.id, c.kind, c.hard, status.get(c.id, status.get(c.kind, "pass" if c.hard else "advisory")))
            for c in plan.criteria]


def test_outcome_table() -> None:
    plan = plan_with()
    ok = hard_rows(plan)
    assert compute_outcome(rows=ok, plan=plan, units_total=2, units_landed=2, changed=True)[0] == "complete"
    assert compute_outcome(rows=ok, plan=plan, units_total=2, units_landed=1, changed=True)[0] == "partial"
    assert compute_outcome(rows=ok, plan=plan, units_total=2, units_landed=2, changed=False)[0] == "failed"
    assert compute_outcome(rows=hard_rows(plan, build="fail"), plan=plan, units_total=1, units_landed=1, changed=True)[0] == "failed"
    assert compute_outcome(rows=ok, plan=plan, units_total=1, units_landed=1, changed=True, needs_input=True)[0] == "needs_input"
    assert compute_outcome(rows=ok, plan=plan, units_total=1, units_landed=1, changed=True, blocked=True)[0] == "blocked"
    assert compute_outcome(rows=[], plan=plan, units_total=1, units_landed=1, changed=True)[0] == "failed"
    # a skipped task-specific gate verified nothing: partial; a skipped baseline gate (no build system) is fine
    assert compute_outcome(rows=hard_rows(plan, acceptance_tests="skip"), plan=plan, units_total=1, units_landed=1,
                           changed=True)[0] == "partial"
    assert compute_outcome(rows=hard_rows(plan, build="skip"), plan=plan, units_total=1, units_landed=1, changed=True)[0] == "complete"
    # advisory failures never gate
    adv = hard_rows(plan) + [row("v", "advisory_vision", False, "advisory")]
    assert compute_outcome(rows=adv, plan=plan, units_total=1, units_landed=1, changed=True)[0] == "complete"


def test_live_llm_factory_uses_super_for_planning_and_nano_first_for_workers(tmp_path: Path) -> None:
    ctx = make_ctx(INVENTORY, "t", [], tmp_path, model_nano="nano-x", model_super="super-y", nebius_api_key="k")
    f = live_llm_factory(ctx)
    assert f("planner", "nano").model == "super-y" and f("worker", "nano").model == "nano-x"
    assert f("worker", "super").model == "super-y" and f("critic", "nano").model == "super-y"
    assert f("worker", "nano") is f("worker", "nano")
