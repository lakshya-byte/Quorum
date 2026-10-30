import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pandas as pd
import streamlit as st

from evals.dataset import (CATEGORIES, CATEGORY_MINIMUMS, MIN_TOTAL_CASES, SCHEMA_VERSION, parse_dataset, repo_files, semantic_errors,
                           validate_case_dict)
from evals.ui import common

st.title("Golden dataset")
path = common.golden_path()
try:
    raw = common.load_dataset_dict()
except Exception as exc:
    st.error(f"Cannot read the dataset at {path}: {exc}")
    st.stop()

cases = raw["cases"]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Cases", len(cases), help=f"minimum {MIN_TOTAL_CASES}")
c2.metric("Version", raw["dataset_version"])
c3.metric("Schema", raw["schema_version"])
c4.metric("Categories", len({c["category"] for c in cases}))

try:
    ds = parse_dataset(raw)
    errs = semantic_errors(ds)
except Exception as exc:
    ds, errs = None, [str(exc)]
if errs:
    st.error("Dataset validation failed:\n\n" + "\n".join(f"- {e}" for e in errs))
else:
    st.success(f"Schema and semantic validation passed ({len(cases)} cases, schema {SCHEMA_VERSION}).", icon=":material/verified:")

tab_browse, tab_edit, tab_add, tab_integrity, tab_stats = st.tabs(["Browse", "Edit a case", "Add a case", "Integrity check", "Coverage"])

with tab_browse:
    f1, f2, f3, f4 = st.columns(4)
    cats = f1.multiselect("Category", list(CATEGORIES), key="ds_cat")
    diffs = f2.multiselect("Difficulty", ["easy", "medium", "hard"], key="ds_diff")
    all_tags = sorted({t for c in cases for t in c["tags"]})
    tags = f3.multiselect("Tags", all_tags, key="ds_tags")
    q = f4.text_input("Search", key="ds_q", placeholder="id, title or task text")
    view = [c for c in cases if (not cats or c["category"] in cats) and (not diffs or c["difficulty"] in diffs)
            and (not tags or set(tags) <= set(c["tags"])) and (not q or q.lower() in json.dumps([c["id"], c["title"], c["input"]["task"]]).lower())]
    frame = pd.DataFrame([{"id": c["id"], "category": c["category"], "difficulty": c["difficulty"], "repo": c["input"]["repo"],
                           "source": c["input"]["source"], "expect solved": c["expected"]["solved"],
                           "stage": c["expected"]["expected_stage"], "guard": c["expected"]["guard_verdict"],
                           "tags": ", ".join(c["tags"]), "task": c["input"]["task"]} for c in view])
    st.caption(f"{len(view)} of {len(cases)} cases shown. Select a row to inspect it.")
    if frame.empty:
        st.info("No case matches the filters.")
    else:
        ev = st.dataframe(frame, width="stretch", hide_index=True, on_select="rerun", selection_mode="single-row", key="ds_table")
        sel = ev.selection.rows if ev and ev.selection else []
        cid = frame.iloc[sel[0]]["id"] if sel else frame.iloc[0]["id"]
        case = next(c for c in cases if c["id"] == cid)
        st.subheader(case["title"])
        st.caption(f"`{case['id']}`  {case['category']}  {case['difficulty']}  author: {case['metadata'].get('author')}")
        t1, t2, t3, t4, t5 = st.tabs(["Input", "Expected", "Reference", "Rubric", "Raw JSON"])
        with t1:
            st.markdown("**Task (as the user wrote it)**")
            st.info(case["input"]["task"])
            if case["input"].get("alert"):
                st.markdown("**Pasted alert / error**")
                st.code(case["input"]["alert"])
            st.write({k: v for k, v in case["input"].items() if k not in ("task", "alert", "adversarial_patch")})
            if case["input"].get("adversarial_patch"):
                st.markdown("**Adversarial patch (files a hostile or careless candidate writes)**")
                for p, t in case["input"]["adversarial_patch"].items():
                    st.code(t, language="python" if p.endswith(".py") else "yaml")
                    st.caption(p)
        with t2:
            st.json(case["expected"])
        with t3:
            st.markdown(f"**Root cause**: {case['reference']['root_cause']}")
            st.markdown(f"**Fix summary**: {case['reference']['fix_summary']}")
            if case["reference"]["key_facts"]:
                st.markdown("**Key facts**\n" + "\n".join(f"- {k}" for k in case["reference"]["key_facts"]))
            if case["reference"]["reference_diff"]:
                st.code(case["reference"]["reference_diff"], language="diff")
            st.caption("Must mention (derived from the diff): " + ", ".join(case["reference"]["must_mention"]))
        with t4:
            st.markdown("\n".join(f"- {r}" for r in case["rubric"]))
        with t5:
            st.json(case, expanded=False)
    st.download_button("Download dataset JSON", json.dumps(raw, indent=2, ensure_ascii=False), file_name="golden_dataset.json",
                       mime="application/json", icon=":material/download:")

with tab_edit:
    st.caption("Edit a case as JSON. It is validated against the schema and against the bundled repos before it can be saved.")
    ids = [c["id"] for c in cases]
    pick = st.selectbox("Case", ids, key="ds_edit_pick")
    current = next(c for c in cases if c["id"] == pick)
    text = st.text_area("Case JSON", json.dumps(current, indent=2, ensure_ascii=False), height=420, key=f"ds_edit_text_{pick}")
    try:
        edited = json.loads(text)
        case_obj, problems = validate_case_dict(edited)
    except ValueError as exc:
        edited, case_obj, problems = None, None, [f"not valid JSON: {exc}"]
    if problems:
        st.error("Validation failed:\n\n" + "\n".join(f"- {p[:400]}" for p in problems))
    else:
        st.success("This case is valid.", icon=":material/check_circle:")
    confirm = st.checkbox("I understand this rewrites golden_dataset.json (built-in cases are regenerated by build_golden.py)",
                          key="ds_edit_confirm")
    if st.button("Save case", disabled=bool(problems) or not confirm, key="ds_edit_save", type="primary"):
        raw2 = json.loads(json.dumps(raw))
        raw2["cases"] = [edited if c["id"] == pick else c for c in raw2["cases"]]
        path.write_text(json.dumps(raw2, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        st.cache_data.clear()
        st.toast(f"Saved {pick}")
        st.rerun()

with tab_add:
    from evals.build_golden import TESTS_GLOBS, derive_bug, derive_demo
    from app.bugs import BUGS
    from app.repo_loader import demo_names

    st.caption("Ground truth is derived from the bundled fix, never typed by hand: pick the repository and the reference diff, "
               "changed files and locate files are filled in for you.")
    with st.form("add_case"):
        a1, a2, a3 = st.columns(3)
        cid = a1.text_input("Case id", placeholder="bf-my-new-case")
        category = a2.selectbox("Category", list(CATEGORIES), index=0)
        difficulty = a3.selectbox("Difficulty", ["easy", "medium", "hard"], index=1)
        title = st.text_input("Title")
        repo = st.selectbox("Repository", [*BUGS, *[f"demo/{n}" for n in demo_names()]])
        task = st.text_area("Task, as a real user would write it (vague is fine)", height=90)
        b1, b2, b3 = st.columns(3)
        source = b1.selectbox("Source", ["web", "cli", "slack", "github"])
        issue_ref = b2.number_input("Issue number (0 = none)", min_value=0, value=0, step=1)
        solved = b3.checkbox("A fix is expected", value=True)
        root_cause = st.text_area("Root cause (one paragraph)", height=80)
        fix_summary = st.text_input("Fix summary")
        key_facts = st.text_area("Key facts (one per line)", height=70)
        rubric = st.text_area("Rubric criteria for LLM judges (one per line)", value="States the root cause concretely.\nDoes not claim unsupported results.", height=70)
        tags = st.text_input("Tags (comma separated)")
        submitted = st.form_submit_button("Validate and add", type="primary")
    if submitted:
        d = derive_bug(repo) if repo in BUGS else derive_demo(repo.split("/", 1)[1])
        is_bug = repo in BUGS
        new = {"id": cid.strip(), "category": category, "difficulty": difficulty, "title": title.strip() or cid, "tags": [t.strip() for t in tags.split(",") if t.strip()],
               "input": {"task": task.strip(), "repo": repo, "source": source, **({"issue_ref": int(issue_ref)} if issue_ref else {})},
               "expected": {"solved": solved, "expected_stage": ("solved" if is_bug else "pr_opened") if solved else "stopped_no_signal",
                            "locate_files": d["locate_files"] if not is_bug else [], "min_files_changed": d["min_files"] if solved else 0,
                            "max_files_changed": d["max_files"] if solved else 0, "must_not_touch": TESTS_GLOBS,
                            "repro_should_fail_on_original": True if solved else None, "guard_verdict": "pass",
                            "policy_expected": "pass" if solved else "n/a", "security_expected": "pass" if solved else "n/a",
                            "expected_tools": []},
               "reference": {"root_cause": root_cause.strip() or "n/a", "fix_summary": fix_summary.strip() or "n/a",
                             "reference_files": d["reference_files"] if solved else [], "reference_diff": d["reference_diff"] if solved else "",
                             "reference_lines_changed": d["lines"] if solved else 0, "key_facts": [k for k in key_facts.splitlines() if k.strip()],
                             "must_mention": d["must_mention"] if solved else []},
               "rubric": [r for r in rubric.splitlines() if r.strip()] or ["States the root cause."],
               "metadata": {"derived_from": repo, "tier": d["tier"], "fake_script": "default", "notes": "", "author": "user"}}
        obj, problems = validate_case_dict(new)
        if cid.strip() in {c["id"] for c in cases}:
            problems.append(f"id {cid!r} already exists")
        if problems:
            st.error("Not added:\n\n" + "\n".join(f"- {p[:400]}" for p in problems))
        else:
            raw2 = json.loads(json.dumps(raw))
            raw2["cases"].append(new)
            path.write_text(json.dumps(raw2, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            st.cache_data.clear()
            st.success(f"Added {cid}. Run its integrity check below.")
            st.rerun()

with tab_integrity:
    st.caption("Applies every reference fix in the local sandbox and checks: reference passes all tests, the original fails, "
               "wrong and partial rank below correct, the reference diff touches only non-test files.")
    only = st.multiselect("Limit to cases (empty = all)", [c["id"] for c in cases], key="ds_int_only")
    if st.button("Run integrity check", type="primary", icon=":material/rule:", key="ds_int_run"):
        cmd = [sys.executable, "-m", "evals.integrity", "-v", *(["--cases", ",".join(only)] if only else [])]
        box = st.empty()
        lines: list[str] = []
        with st.status("Running the reference fixes in the sandbox ...", expanded=True) as status:
            proc = subprocess.Popen(cmd, cwd=str(Path(__file__).resolve().parents[3]), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            assert proc.stdout is not None
            for line in proc.stdout:
                lines.append(line.rstrip())
                box.code("\n".join(lines[-40:]), language="text")
            code = proc.wait()
            status.update(label="Integrity PASSED" if code == 0 else "Integrity FAILED", state="complete" if code == 0 else "error")
        (st.success if code == 0 else st.error)("All integrity checks passed." if code == 0 else "At least one integrity check failed; see the output above.")

with tab_stats:
    counts = pd.DataFrame([{"category": c, "cases": sum(1 for x in cases if x["category"] == c), "required": CATEGORY_MINIMUMS[c]} for c in CATEGORIES])
    counts["ok"] = counts["cases"] >= counts["required"]
    st.dataframe(counts, width="stretch", hide_index=True)
    diff_counts = pd.Series([c["difficulty"] for c in cases]).value_counts().rename_axis("difficulty").reset_index(name="cases")
    st.bar_chart(diff_counts, x="difficulty", y="cases")
