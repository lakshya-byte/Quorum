# PatchLoop eval pipeline

Golden dataset, system-under-test adapter, deterministic metrics, DeepEval, Ragas, regression gate, reports and a
Streamlit UI. **Tests are the judge**: a fix counts only when the sandbox tests pass and the policy gate and bandit scan
are clean.

> **Fake mode does not measure model quality.** `--mode fake` (the default) runs the real LangGraph team, policy gate,
> sandbox, bandit scan, guard and repo flow with *scripted agents*. It validates the harness (dataset integrity,
> adapters, metrics, gate, reports, UI). Every report carries a FAKE MODE banner. Model results need
> `--mode hybrid|live` plus keys.

## Architecture

```
 golden/golden_dataset.json  (30 cases, schema-validated, ground truth derived from bundled bugs/repos)
        |  dataset.py (pydantic + semantic checks)        build_golden.py (generator)   integrity.py (reference fix proof)
        v
 pipeline.py ── 1 load+validate ─ 2 integrity ─ 3 SUT ─ 4 det. metrics ─ 5 DeepEval ─ 6 Ragas ─ 7 aggregate ─ 8 gate ─ 9 report
                                                    |
                              sut.py  ──► RunRegistry.start()/start_repo()  (guard → locate → repro → graph team
                                          → policy gate → sandbox tests → bandit → score → critic → reviewer → output guard → PR)
                                          + probes: locator, reproducer, adversarial patch (guard + policy + bandit)
                                          returns a normalized Trace
        metrics_det.py (offline)   deepeval_suite.py (offline + judge)   ragas_suite.py (offline + judge)   judge.py (Nebius)
        results/<run_id>/{run.json,cases.jsonl,summary.json,report.md,report.html,traces/}   results/index.json
        baselines/<mode>-baseline.json + thresholds.yaml  →  gate (exit 1 on failure)
        app.py + ui/pages/*  (Streamlit)         run.py (CLI)       test_deepeval_golden.py (pytest / deepeval test run)
```

## Golden dataset

`golden/golden_dataset.json` (+ `golden.schema.json`, generated from the pydantic models). Top level:
`schema_version`, `dataset_version`, `created`, `cases[]`. A case:

| field | content |
|---|---|
| `id`, `category`, `difficulty` (easy/medium/hard), `title`, `tags` | |
| `input` | `task` (as a user wrote it, often vague), `repo` (bundled bug id or `demo/<repo>`), `source` (web/cli/slack/github), optional `alert`, `issue_ref`, `followup`, `adversarial_patch` |
| `expected` | `solved`, `expected_stage` (+ `also_acceptable_stages`), `locate_files`, `min/max_files_changed`, `must_not_touch`, `repro_should_fail_on_original`, `guard_verdict`, `policy_expected`, `security_expected`, `expected_tools`, `pr`, |
| `reference` | `root_cause`, `fix_summary`, `reference_files`, `reference_diff` (original → bundled `correct`), `reference_lines_changed`, `key_facts` (concepts for LLM grading), `must_mention` (paths/functions derived from the diff) |
| `rubric` | criteria for LLM judges |
| `metadata` | `derived_from`, `tier`, `fake_script` (default / no_reproducer / no_locator_hint: how fake mode scripts an unsolvable case), `notes`, `author` |

Categories (counts): bug_fix_single_file 9, bug_fix_multi_file 3, locator_retrieval 3, reproducer_quality 2,
safety_guardrails 7, unsolvable_or_underspecified 2, followup_change_request 2, pr_quality 2 = **30**.
Cases tagged `known-gap-heuristic` (paraphrased injection, benign text the regex guard blocks, a locator distractor) are
real weaknesses of the offline heuristics, kept on purpose; the gate thresholds account for them.

**Integrity** (`python -m evals.integrity`, also `python -m evals.run validate`): for each fixable case the reference fix
makes all tests pass in the local sandbox, the original fails, `wrong`/`partial` rank below `correct`, the reference diff is
current and touches only non-test files; plus reproducer-fails-on-original, existing-suite-green (booking), no-source-matches-task,
adversarial-patch checks, bandit flags the weak-hash patch.

**Add a case**: Streamlit *Golden dataset → Add a case* (ground truth is derived for you), or add it to `build_golden.py`, or
append JSON with `metadata.author` ≠ `patchloop-evals` (survives a rebuild). Then `python -m evals.run validate`.

## Metrics and how they map to the system

Deterministic (`metrics_det.py`, offline, typed `MetricResult(score, passed, threshold, reason)`): solved/pass@1, pass@k (unbiased),
tests_passed_ratio, regression_rate (count based: originally-passing tests broken), patch_minimality, files precision/recall/F1,
scope_respected, locator precision@k / recall@3 / MRR / hit@1, repro_valid, policy_accuracy / violation_detected,
guard_accuracy (+ TPR/FPR in the aggregate), security_accuracy / security_clean, test_tampering_blocked, honest_failure,
blocked_before_proposal, claim_supported, followup_same_branch, pr_body_completeness (sections, `Fixes #n` iff issue_ref, no secrets),
tool precision/recall/F1, latency p50/p95, time-to-first-event, tokens, cost per solve (needs `PRICE_IN_PER_MTOK`/`PRICE_OUT_PER_MTOK`).

**DeepEval** (`deepeval_suite.py`): `LLMTestCase` per trace (input = task, actual_output = PR text or stop reason, expected_output =
reference root cause, retrieval_context = diff + test output, tools_called/expected_tools). Offline: a `BaseMetric` subclass wrapping
the deterministic metrics, and `ToolCorrectnessMetric`. Judge: GEval (root-cause correctness, PR body quality, honesty/no fabrication,
rubric adherence), FaithfulnessMetric, AnswerRelevancyMetric, TaskCompletionMetric. Judge = `NebiusJudge(DeepEvalBaseLLM)`.

**Ragas 0.4.3** (`ragas_suite.py`): locator = retrieval (ID-based and Non-LLM context precision/recall offline, LLM variants with a judge);
PR body = generation (Rouge, BLEU, chrF, string similarity, derived-fact `StringPresence`, stage `ExactMatch` offline; Faithfulness,
ResponseGroundedness, FactualCorrectness, AnswerCorrectness, AnswerRelevancy, AspectCritic, RubricsScore with a judge); agent team
(`ToolCallAccuracy` strict set equality, `ToolCallF1` offline; `AgentGoalAccuracyWithReference`, `TopicAdherence` with a judge).
`import ragas` fails against langchain-community 0.4.x, so `compat.py` injects inert Vertex placeholders only when the real import fails.
The coverage matrix (in every report and the Ragas page) states why NoiseSensitivity, ContextEntityRecall, SummarizationScore, SQL and
multimodal metrics are not applicable.

## Running

```bash
pip install -r requirements.txt -r requirements-evals.txt
python -m evals.run                                  # fake mode, all 30 cases
python -m evals.run --suite safety --n 3             # suite (all|quick|bugs|repo|multi|safety|locator|repro|unsolvable|followup|pr|<category>)
python -m evals.run --cases bf-paginate,loc-booking-vague --engine loop
python -m evals.run --baseline latest | <run_id> | none --update-baseline
python -m evals.run --resume <run_id>                # reuse traces
python -m evals.run validate                         # dataset + integrity (CI)
streamlit run evals/app.py        # or scripts/eval-app.sh
pytest evals/test_deepeval_golden.py                 # or: deepeval test run evals/test_deepeval_golden.py
```
Exit codes: 0 ok, 1 gate/validation failed, 2 usage, 3 mode or judge cannot run here (refused; nothing is faked).

**Live / judge** (needs keys and network to `api.tokenfactory.nebius.com`):
```bash
export NEBIUS_API_KEY=... MODEL_NANO=... MODEL_SUPER=... NEBIUS_PROJECT_ID=...   # agents (live also uses Nebius Sandboxes)
export EVAL_JUDGE_MODEL=<chat model id>  EVAL_EMBED_MODEL=<optional embeddings model>
python -m evals.run --mode hybrid --judge nebius --n 3
```
Bundled-bug cases honour `--engine single|loop|graph`; repo cases always use the graph team. Live mode never downgrades to fake. LangSmith
tracing follows the app (`LANGSMITH_API_KEY`); it was not exercised here.

## Reading a report

`report.md` / `report.html`: gate verdict and each check; headline (solve rate, guard TPR/FPR, honest-failure rate, latency, tokens);
metric × category and by difficulty; cases needing attention; DeepEval; Ragas table + coverage matrix; skipped metrics with reasons;
per-case table. `traces/<case>__<trial>.json` holds events, candidates (diff, test output, policy/security) and the final text.
Gate: `thresholds.yaml` (absolute floors per mode, regression tolerance vs `baselines/<mode>-baseline.json`, case flips).

## What fake mode proves, and what it does not

Proves: the dataset is internally consistent (reference fixes really pass), the adapters drive the real engine/flow/guard/policy/
bandit, metrics and reports compute, the gate trips on regressions, the UI renders. The offline guard/locator numbers are real
measurements of those heuristics. Does **not** prove: anything about Nemotron's fixing, locating, test-writing, explaining or honesty;
the scripted team always finds the bundled fix (so solve rate is ~100% by construction), the reproducer and locator hints are scripted
for end-to-end cases, and the "unsolvable" cases are driven by scripted agent failures (what is measured is the flow's honest-stop logic).
Needs keys: judge metrics (DeepEval GEval/Faithfulness/..., Ragas LLM metrics), hybrid/live runs, embeddings metrics, LangSmith.
