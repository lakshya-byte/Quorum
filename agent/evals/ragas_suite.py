"""Ragas analysis of PatchLoop (ragas 0.4.3).

PatchLoop is not a RAG chatbot, so each Ragas family is mapped to the stage where it honestly applies:

  Locator              = retrieval      ContextPrecision / ContextRecall (ID based, non-LLM string based, LLM based)
  PR body / explanation = generation    Faithfulness, ResponseGroundedness, FactualCorrectness, AnswerCorrectness,
                                        AnswerRelevancy, AspectCritic, RubricsScore + non-LLM text metrics
  Agent team           = agent          ToolCallAccuracy, ToolCallF1, AgentGoalAccuracyWithReference, TopicAdherence

Offline metrics (no LLM, no embeddings) always run and produce numbers. LLM metrics run only with a judge
(`LangchainLLMWrapper(ChatOpenAI(base_url=Nebius, model=EVAL_JUDGE_MODEL))`); embedding metrics also need
EVAL_EMBED_MODEL. Otherwise they are reported SKIPPED with status needs_judge / needs_embeddings.
`COVERAGE` documents which Ragas metric families do (not) apply to a bug-fixing agent, and why.
"""
from __future__ import annotations

import asyncio
import warnings
from dataclasses import asdict, dataclass
from typing import Any

from evals.compat import ensure_ragas_importable
from evals.dataset import Case, repo_files
from evals.metrics_det import tool_prf  # noqa: F401  (documented relation: ToolCallF1 ~ tool_f1)
from evals.sut import TOLERATED_TOOLS, Trace

CTX_CAP = 4000


@dataclass
class RagasResult:
    case_id: str
    metric: str
    status: str  # ran | needs_judge | needs_embeddings | n/a | error
    score: float | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# name -> (family, kind, what it measures for PatchLoop, offline?, needs_embeddings?)
METRICS: dict[str, dict[str, Any]] = {
    "id_based_context_precision": dict(family="Retrieval (locator)", needs="none", what=(
        "Share of the files the locator returned that are ground-truth files (exact path match).")),
    "id_based_context_recall": dict(family="Retrieval (locator)", needs="none", what=(
        "Share of ground-truth files the locator found (exact path match).")),
    "non_llm_context_precision_with_reference": dict(family="Retrieval (locator)", needs="none", what=(
        "Precision of retrieved file CONTENTS vs ground-truth contents (Levenshtein ratio >= 0.5).")),
    "non_llm_context_recall": dict(family="Retrieval (locator)", needs="none", what=(
        "Recall of ground-truth file contents among the retrieved contents (Levenshtein ratio >= 0.5).")),
    "llm_context_precision_with_reference": dict(family="Retrieval (locator)", needs="judge", what=(
        "LLM judges whether each retrieved file is useful for the reference root cause (rank aware).")),
    "context_recall": dict(family="Retrieval (locator)", needs="judge", what=(
        "LLM checks that each sentence of the reference root cause is attributable to the retrieved files.")),
    "rouge_score": dict(family="Response text (non-LLM)", needs="none", what=(
        "ROUGE-L F-measure between the PR text and the reference root cause + fix summary.")),
    "bleu_score": dict(family="Response text (non-LLM)", needs="none", what=(
        "Corpus BLEU between the PR text and the reference (sacrebleu).")),
    "chrf_score": dict(family="Response text (non-LLM)", needs="none", what=(
        "Character n-gram F-score between the PR text and the reference.")),
    "non_llm_string_similarity": dict(family="Response text (non-LLM)", needs="none", what=(
        "Normalised Levenshtein similarity between the PR text and the reference.")),
    "string_presence": dict(family="Response text (non-LLM)", needs="none", what=(
        "Share of derived facts (changed files, touched functions) that the PR text mentions.")),
    "exact_match": dict(family="Response text (non-LLM)", needs="none", what=(
        "1 when the run's final stage label equals the expected stage (categorical exact match).")),
    "faithfulness": dict(family="Generation (PR body)", needs="judge", what=(
        "Fraction of the PR text's claims that are supported by the evidence (diff + test output).")),
    "nv_response_groundedness": dict(family="Generation (PR body)", needs="judge", what=(
        "NVIDIA-style 0-2 groundedness of the PR text in the evidence, normalised to 0-1.")),
    "factual_correctness": dict(family="Generation (PR body)", needs="judge", what=(
        "Claim-level F1 of the PR text against the reference root cause (NLI).")),
    "answer_correctness": dict(family="Generation (PR body)", needs="embeddings", what=(
        "Weighted factual + semantic similarity of the PR text to the reference root cause.")),
    "answer_relevancy": dict(family="Generation (PR body)", needs="embeddings", what=(
        "Whether the PR text addresses the user's task (reverse-question embeddings).")),
    "aspect_critic": dict(family="Generation (rubric)", needs="judge", what=(
        "Binary LLM critic: the output is honest, grounded and does not fabricate success or failure.")),
    "rubrics_score": dict(family="Generation (rubric)", needs="judge", what=(
        "1-5 LLM score against a rubric built from the case's own rubric criteria.")),
    "tool_call_accuracy": dict(family="Agent", needs="none", what=(
        "1 only when the set of agents/tools called equals the expected set (order free, names only).")),
    "tool_call_f1": dict(family="Agent", needs="none", what=(
        "F1 between called and expected agent/tool names (partial credit).")),
    "agent_goal_accuracy": dict(family="Agent", needs="judge", what=(
        "LLM checks whether the trajectory achieved the reference goal (fix landed, or honest stop).")),
    "topic_adherence": dict(family="Agent", needs="judge", what=(
        "LLM checks the agent conversation stayed on bug fixing / testing / review topics.")),
}

# family, ragas metric, applicable, why
COVERAGE: list[dict[str, str]] = [
    {"family": "Retrieval", "metric": "ContextPrecision / LLMContextPrecisionWithReference", "applies": "yes",
     "how": "locator output vs ground-truth files (ID based + content based + LLM variants)"},
    {"family": "Retrieval", "metric": "ContextRecall / LLMContextRecall", "applies": "yes",
     "how": "ground-truth files found by the locator"},
    {"family": "Retrieval", "metric": "NonLLMContextPrecisionWithReference / NonLLMContextRecall", "applies": "yes",
     "how": "offline string-similarity variants over file contents"},
    {"family": "Retrieval", "metric": "IDBasedContextPrecision / IDBasedContextRecall", "applies": "yes",
     "how": "exact file-path ids: the most reliable offline retrieval measure here"},
    {"family": "Retrieval", "metric": "ContextEntityRecall", "applies": "no",
     "how": "measures named-entity coverage of a reference ANSWER by the contexts; our reference is code, entities "
            "are identifiers: not meaningful"},
    {"family": "Retrieval", "metric": "NoiseSensitivity", "applies": "no",
     "how": "needs a generated answer that consumes the retrieved contexts; the locator's output feeds an agent "
            "that edits code, it does not answer from the contexts"},
    {"family": "Retrieval", "metric": "ContextRelevance (NVIDIA)", "applies": "partial",
     "how": "LLM relevance of contexts to the task; overlaps with LLMContextPrecision, not run by default"},
    {"family": "Generation", "metric": "Faithfulness / ResponseGroundedness", "applies": "yes",
     "how": "PR body claims vs diff + test output (evidence)"},
    {"family": "Generation", "metric": "FactualCorrectness / AnswerCorrectness", "applies": "yes",
     "how": "PR explanation vs the reference root cause"},
    {"family": "Generation", "metric": "AnswerRelevancy (ResponseRelevancy)", "applies": "partial",
     "how": "PR text vs the task; needs an embedding model (EVAL_EMBED_MODEL)"},
    {"family": "Generation", "metric": "SemanticSimilarity / AnswerSimilarity", "applies": "partial",
     "how": "embedding similarity to the reference; redundant with AnswerCorrectness"},
    {"family": "General purpose", "metric": "AspectCritic / SimpleCriteriaScore", "applies": "yes",
     "how": "binary / graded criteria such as honesty and no fabrication"},
    {"family": "General purpose", "metric": "RubricsScore / InstanceSpecificRubrics", "applies": "yes",
     "how": "the case rubric from the golden dataset"},
    {"family": "NLP / text", "metric": "RougeScore, BleuScore, ChrfScore", "applies": "yes",
     "how": "lexical overlap of the PR text with the reference (weak proxy; reported for completeness)"},
    {"family": "NLP / text", "metric": "NonLLMStringSimilarity, StringPresence, ExactMatch", "applies": "yes",
     "how": "similarity, derived-fact presence, categorical stage match"},
    {"family": "Agent", "metric": "ToolCallAccuracy / ToolCallF1", "applies": "yes",
     "how": "agents invoked (guard, locator, test-writer, proposer, gates, reviewer) vs expected"},
    {"family": "Agent", "metric": "AgentGoalAccuracyWithReference", "applies": "yes",
     "how": "trajectory achieved the reference goal (fix, or honest stop)"},
    {"family": "Agent", "metric": "AgentGoalAccuracyWithoutReference", "applies": "partial",
     "how": "redundant: every golden case has a reference goal"},
    {"family": "Agent", "metric": "TopicAdherence", "applies": "yes",
     "how": "stays on bug fixing; a guard-blocked injection should not drift to other topics"},
    {"family": "Summarization", "metric": "SummarizationScore", "applies": "no",
     "how": "PatchLoop does not summarise documents; the PR body is graded by Faithfulness instead"},
    {"family": "SQL", "metric": "DataCompyScore, LLMSQLEquivalence", "applies": "no",
     "how": "no SQL or tabular outputs in a bug-fixing agent"},
    {"family": "Multimodal", "metric": "MultiModalFaithfulness, MultiModalRelevance", "applies": "no",
     "how": "text and code only"},
    {"family": "Test-set generation", "metric": "TestsetGenerator", "applies": "no",
     "how": "the golden dataset is derived from bundled bugs and repos instead (evals/build_golden.py)"},
]


def available() -> dict[str, Any]:
    st = ensure_ragas_importable()
    if st["ok"]:
        import ragas

        st["version"] = getattr(ragas, "__version__", "?")
    return st


# ---- samples ----------------------------------------------------------------------------------------------

def _agent_sequence(names: list[str]) -> list[str]:
    seen: list[str] = []
    for n in names:
        if n not in TOLERATED_TOOLS and n not in seen:
            seen.append(n)
    return seen


def retrieval_applicable(case: Case, tr: Trace) -> str | None:
    if not case.expected.locate_files:
        return "no ground-truth files"
    if not tr.retrieved_files:
        return "locator returned nothing"
    if case.category != "locator_retrieval" and tr.mode == "fake":
        return "fake mode scripts the locator for end-to-end cases"
    return None


def _truth_contexts(case: Case) -> list[str]:
    files = repo_files(case.input.repo)
    return [files[p][:CTX_CAP] for p in case.expected.locate_files if p in files]


def retrieval_sample(case: Case, tr: Trace) -> Any:
    from ragas import SingleTurnSample

    return SingleTurnSample(
        user_input=case.input.full_text,
        retrieved_contexts=[tr.retrieved_contents.get(p, "")[:CTX_CAP] or p for p in tr.retrieved_files],
        reference_contexts=_truth_contexts(case),
        retrieved_context_ids=list(tr.retrieved_files), reference_context_ids=list(case.expected.locate_files),
        reference=f"{case.reference.root_cause} {case.reference.fix_summary}")


def response_sample(case: Case, tr: Trace) -> Any | None:
    from ragas import SingleTurnSample

    if tr.final.get("kind") not in ("pr", "draft") or not tr.final.get("body"):
        return None
    return SingleTurnSample(
        user_input=case.input.full_text, response=tr.final_text,
        retrieved_contexts=[tr.evidence or "(no evidence)"],
        reference=f"{case.reference.root_cause} {case.reference.fix_summary}",
        rubrics={f"score{i}_description": d for i, d in enumerate(_rubric_levels(case), 1)})


def _rubric_levels(case: Case) -> list[str]:
    crit = "; ".join(case.rubric)
    return ["Ignores or contradicts every criterion.", "Meets few criteria and makes unsupported claims.",
            "Meets about half of the criteria.", "Meets most criteria with minor gaps.",
            f"Meets all criteria: {crit}"]


def stop_sample(case: Case, tr: Trace) -> Any | None:
    from ragas import SingleTurnSample

    if tr.final.get("kind") not in ("stop", "probe") or not tr.final.get("body"):
        return None
    return SingleTurnSample(user_input=case.input.full_text, response=tr.final["body"],
                            retrieved_contexts=[tr.evidence or "(no evidence)"], reference=case.reference.root_cause)


def agent_sample(case: Case, tr: Trace) -> Any:
    from ragas import MultiTurnSample
    from ragas.messages import AIMessage, HumanMessage, ToolCall

    seq = _agent_sequence(tr.tool_names)
    reference = _agent_sequence(case.expected.expected_tools)
    goal = (f"The bug is fixed: {case.reference.fix_summary} All tests pass."
            if case.expected.solved and case.category not in ("locator_retrieval", "reproducer_quality") else
            "The agent stops without a fix or PR and says why, instead of fabricating success.")
    msgs = [HumanMessage(content=case.input.full_text),
            AIMessage(content="Working on it.", tool_calls=[ToolCall(name=n, args={}) for n in seq]),
            AIMessage(content=(tr.final_text or tr.final.get("body") or "(no output)")[:1500])]
    return MultiTurnSample(user_input=msgs, reference=goal,
                           reference_tool_calls=[ToolCall(name=n, args={}) for n in reference],
                           reference_topics=["software bug fixing", "automated testing", "code review"])


# ---- running ----------------------------------------------------------------------------------------------

def _evaluate(metric: Any, samples: list[Any], llm: Any = None, embeddings: Any = None) -> list[float | None]:
    from ragas import EvaluationDataset, evaluate

    ds = EvaluationDataset(samples=samples)
    kw: dict[str, Any] = {}
    if llm is not None:
        kw["llm"] = llm
    if embeddings is not None:
        kw["embeddings"] = embeddings
    res = evaluate(ds, metrics=[metric], show_progress=False, raise_exceptions=False, **kw)
    out: list[float | None] = []
    for row in res.scores:
        # ragas decorates some column names (e.g. "rouge_score(mode=fmeasure)"): one metric per call -> one value
        v = row.get(metric.name, next(iter(row.values()), None))
        out.append(None if v is None or v != v else float(v))
    return out


def _string_presence(case: Case, tr: Trace) -> float | None:
    """Share of derived must_mention literals that the PR text contains (ragas StringPresence per literal)."""
    from ragas import SingleTurnSample
    from ragas.metrics import StringPresence

    if tr.final.get("kind") not in ("pr", "draft") or not case.reference.must_mention:
        return None
    metric = StringPresence()
    text = tr.final_text

    async def go() -> list[float]:
        return [await metric.single_turn_ascore(SingleTurnSample(response=text, reference=lit))
                for lit in case.reference.must_mention]

    vals = asyncio.run(go())
    return sum(vals) / len(vals) if vals else None


def run_ragas(items: list[tuple[Case, Trace]], *, llm: Any = None, embeddings: Any = None,
              judge_reason: str = "") -> dict[str, Any]:
    """Run every applicable Ragas metric. Synchronous (ragas drives its own event loop)."""
    st = available()
    if not st["ok"]:
        return {"ok": False, "error": st["error"], "results": [], "table": [], "coverage": COVERAGE, "meta": st}
    warnings.filterwarnings("ignore")
    import logging

    logging.getLogger("ragas").setLevel(logging.ERROR)
    from ragas.metrics import (AgentGoalAccuracyWithReference, AspectCritic, BleuScore, ChrfScore, ExactMatch,
                               FactualCorrectness, Faithfulness, IDBasedContextPrecision, IDBasedContextRecall,
                               LLMContextPrecisionWithReference, LLMContextRecall, NonLLMContextPrecisionWithReference,
                               NonLLMContextRecall, NonLLMStringSimilarity, RougeScore, RubricsScore, ToolCallAccuracy,
                               ToolCallF1, TopicAdherenceScore)
    from ragas.metrics import AnswerCorrectness, AnswerRelevancy
    from ragas.metrics._nv_metrics import ResponseGroundedness

    items = [(c, t) for c, t in items if t.status == "ok"]
    results: list[RagasResult] = []

    def record(metric: str, pairs: list[tuple[Case, Trace]], scores: list[float | None], reason: str = "") -> None:
        for (case, _t), s in zip(pairs, scores):
            results.append(RagasResult(case.id, metric, "ran" if s is not None else "error", s,
                                       reason if s is not None else "metric returned no score"))

    def skipped(metric: str, pairs: list[tuple[Case, Trace]], status: str, why: str) -> None:
        for case, _t in pairs:
            results.append(RagasResult(case.id, metric, status, None, why))

    def not_applicable(metric: str, skip: list[tuple[Case, Trace, str]]) -> None:
        for case, _t, why in skip:
            results.append(RagasResult(case.id, metric, "n/a", None, why))

    has_judge, has_emb = llm is not None, embeddings is not None
    need_judge = judge_reason or "no judge configured (EVAL_JUDGE_MODEL / NEBIUS_API_KEY)"

    def run_group(name: str, pairs: list[tuple[Case, Trace]], samples: list[Any], factory: Any, needs: str,
                  reason: str = "") -> None:
        if not pairs:
            return
        if needs == "judge" and not has_judge:
            return skipped(name, pairs, "needs_judge", need_judge)
        if needs == "embeddings" and not (has_judge and has_emb):
            return skipped(name, pairs, "needs_embeddings" if has_judge else "needs_judge",
                           "set EVAL_EMBED_MODEL (embeddings endpoint)" if has_judge else need_judge)
        try:
            record(name, pairs, _evaluate(factory(), samples, llm, embeddings), reason)
        except Exception as exc:
            for case, _t in pairs:
                results.append(RagasResult(case.id, name, "error", None, f"{type(exc).__name__}: {exc}"[:300]))

    # retrieval
    r_pairs, r_skip = [], []
    for case, tr in items:
        why = retrieval_applicable(case, tr)
        (r_skip.append((case, tr, why)) if why else r_pairs.append((case, tr)))
    r_samples = [retrieval_sample(c, t) for c, t in r_pairs]
    for name, factory in (("id_based_context_precision", IDBasedContextPrecision),
                          ("id_based_context_recall", IDBasedContextRecall),
                          ("non_llm_context_precision_with_reference", NonLLMContextPrecisionWithReference),
                          ("non_llm_context_recall", NonLLMContextRecall),
                          ("llm_context_precision_with_reference", LLMContextPrecisionWithReference),
                          ("context_recall", LLMContextRecall)):
        run_group(name, r_pairs, r_samples, factory, METRICS[name]["needs"])
        not_applicable(name, r_skip)

    # response text
    p_pairs, p_samples, p_skip = [], [], []
    for case, tr in items:
        s = response_sample(case, tr)
        (p_pairs.append((case, tr)) if s is not None else p_skip.append((case, tr, "no PR text was produced")))
        if s is not None:
            p_samples.append(s)
    for name, factory in (("rouge_score", RougeScore), ("bleu_score", BleuScore), ("chrf_score", ChrfScore),
                          ("non_llm_string_similarity", NonLLMStringSimilarity)):
        run_group(name, p_pairs, p_samples, factory, "none")
        not_applicable(name, p_skip)
    sp = [(c, t, _string_presence(c, t)) for c, t in p_pairs]
    record("string_presence", [(c, t) for c, t, _ in sp], [v for _, _, v in sp])
    not_applicable("string_presence", p_skip)

    # exact match on the stage label (every case)
    from ragas import SingleTurnSample

    em_samples = [SingleTurnSample(response=t.final_stage,
                                   reference=t.final_stage if t.final_stage in {c.expected.expected_stage,
                                                                                *c.expected.also_acceptable_stages}
                                   else c.expected.expected_stage) for c, t in items]
    run_group("exact_match", items, em_samples, ExactMatch, "none")

    # LLM generation metrics
    for name, factory in (("faithfulness", Faithfulness), ("nv_response_groundedness", ResponseGroundedness),
                          ("factual_correctness", FactualCorrectness), ("rubrics_score", None),
                          ("answer_correctness", AnswerCorrectness), ("answer_relevancy", AnswerRelevancy)):
        if name == "rubrics_score":
            run_group(name, p_pairs, p_samples, lambda: RubricsScore(), "judge")
        else:
            run_group(name, p_pairs, p_samples, factory, METRICS[name]["needs"])
        not_applicable(name, p_skip)
    all_samples = [s for s in (response_sample(c, t) or stop_sample(c, t) for c, t in items)]
    crit_pairs = [(c, t) for (c, t), s in zip(items, all_samples) if s is not None]
    crit_samples = [s for s in all_samples if s is not None]
    run_group("aspect_critic", crit_pairs, crit_samples, lambda: AspectCritic(
        name="aspect_critic", definition="The response is honest: every claim about tests, files, root cause or a "
                                         "pull request is supported by the evidence, and a failure to fix is stated "
                                         "plainly without inventing success."), "judge")

    # agent metrics
    a_pairs = [(c, t) for c, t in items if c.expected.expected_tools]
    a_samples = [agent_sample(c, t) for c, t in a_pairs]
    run_group("tool_call_accuracy", a_pairs, a_samples, lambda: ToolCallAccuracy(strict_order=False), "none")
    run_group("tool_call_f1", a_pairs, a_samples, ToolCallF1, "none")
    run_group("agent_goal_accuracy", items and [(c, t) for c, t in items], [agent_sample(c, t) for c, t in items],
              AgentGoalAccuracyWithReference, "judge")
    run_group("topic_adherence", items and [(c, t) for c, t in items], [agent_sample(c, t) for c, t in items],
              lambda: TopicAdherenceScore(mode="precision"), "judge")

    rows = summarize([r.to_dict() for r in results], {c.id: c for c, _ in items})
    return {"ok": True, "results": [r.to_dict() for r in results], "table": rows, "coverage": coverage_matrix(rows),
            "meta": {"version": st.get("version"), "compat_stubbed": st.get("stubbed", []),
                     "llm": bool(has_judge), "embeddings": bool(has_emb)}}


# ---- analysis ---------------------------------------------------------------------------------------------

def summarize(results: list[dict[str, Any]], cases: dict[str, Case]) -> list[dict[str, Any]]:
    by: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by.setdefault(r["metric"], []).append(r)
    rows = []
    for name, spec in METRICS.items():
        rs = by.get(name, [])
        ran = [r for r in rs if r["status"] == "ran" and r["score"] is not None]
        statuses = {r["status"] for r in rs}
        status = "ran" if ran else ("needs_judge" if "needs_judge" in statuses else (
            "needs_embeddings" if "needs_embeddings" in statuses else ("error" if "error" in statuses else "n/a")))
        scores = [r["score"] for r in ran]
        cat: dict[str, list[float]] = {}
        diff: dict[str, list[float]] = {}
        for r in ran:
            c = cases.get(r["case_id"])
            if c:
                cat.setdefault(c.category, []).append(r["score"])
                diff.setdefault(c.difficulty, []).append(r["score"])
        skip_reason = next((r["reason"] for r in rs if r["status"] in ("needs_judge", "needs_embeddings", "error")), "")
        mean = sum(scores) / len(scores) if scores else None
        rows.append({
            "metric": name, "family": spec["family"], "what": spec["what"], "status": status, "n": len(scores),
            "mean": mean, "min": min(scores) if scores else None,
            "by_category": {k: sum(v) / len(v) for k, v in cat.items()},
            "by_difficulty": {k: sum(v) / len(v) for k, v in diff.items()},
            "needs": spec["needs"], "skip_reason": skip_reason if status != "ran" else "",
            "interpretation": interpret(name, mean, len(scores), status),
        })
    return rows


def interpret(name: str, mean: float | None, n: int, status: str) -> str:
    if status != "ran" or mean is None:
        return {"needs_judge": "Skipped: needs an LLM judge. Configure EVAL_JUDGE_MODEL + NEBIUS_API_KEY and re-run "
                               "with --judge nebius.",
                "needs_embeddings": "Skipped: needs an embeddings model (EVAL_EMBED_MODEL).",
                "n/a": "No applicable cases in this selection.",
                "error": "The metric raised an error; see the per-case reason."}.get(status, "")
    pct = f"{mean:.0%}"
    text = {
        "id_based_context_precision": f"{pct} of returned files are right: low means the locator pads results with "
                                       "distractors.",
        "id_based_context_recall": f"{pct} of the files that must change are found; <100% means a file is never "
                                    "shown to the proposers.",
        "non_llm_context_precision_with_reference": "Content-similarity view of precision; can over-count near-"
                                                     "identical sibling modules.",
        "non_llm_context_recall": "Content-similarity view of recall; agrees with the ID-based view when files differ.",
        "rouge_score": "Lexical overlap only: templated PR bodies score low against a prose root cause by design; do "
                       "not gate on it.",
        "bleu_score": "Very low by construction (PR text vs a paragraph); informational.",
        "chrf_score": "Character-level overlap; informational.",
        "non_llm_string_similarity": "Edit-distance similarity; informational.",
        "string_presence": f"{pct} of derived facts (files, functions) appear in the PR text: a cheap grounding check.",
        "exact_match": f"{pct} of runs end at the expected stage label.",
        "tool_call_accuracy": f"{pct} of runs called exactly the expected agent set (strict).",
        "tool_call_f1": f"Mean F1 {mean:.2f} between called and expected agents.",
    }.get(name, f"Mean {mean:.2f} over {n} cases.")
    return text


def coverage_matrix(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    status_of = {r["metric"]: r["status"] for r in rows}
    keymap = {"ContextPrecision": ["id_based_context_precision", "llm_context_precision_with_reference"],
              "ContextRecall": ["id_based_context_recall", "context_recall"],
              "NonLLMContext": ["non_llm_context_precision_with_reference", "non_llm_context_recall"],
              "IDBased": ["id_based_context_precision", "id_based_context_recall"],
              "Faithfulness": ["faithfulness", "nv_response_groundedness"],
              "FactualCorrectness": ["factual_correctness", "answer_correctness"],
              "AnswerRelevancy": ["answer_relevancy"], "AspectCritic": ["aspect_critic"],
              "RubricsScore": ["rubrics_score"], "Rouge": ["rouge_score", "bleu_score", "chrf_score"],
              "NonLLMStringSimilarity": ["non_llm_string_similarity", "string_presence", "exact_match"],
              "ToolCall": ["tool_call_accuracy", "tool_call_f1"], "AgentGoalAccuracyWithReference": ["agent_goal_accuracy"],
              "TopicAdherence": ["topic_adherence"]}
    out = []
    for row in COVERAGE:
        keys: list[str] = []
        for k, v in keymap.items():
            if k in row["metric"]:
                keys += v
        statuses = [status_of[k] for k in dict.fromkeys(keys) if k in status_of]
        if row["applies"] == "no":
            run = "n/a"
        elif not statuses:
            run = "not run"
        elif "ran" in statuses:
            run = "ran" if all(s == "ran" for s in statuses) else "ran (partly)"
        else:
            run = statuses[0]
        out.append({**row, "status": run})
    return out
