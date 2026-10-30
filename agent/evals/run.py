"""CLI:  python -m evals.run [run|validate|list] [flags]

  python -m evals.run                         # fake mode, whole golden dataset, writes evals/results/<run_id>/
  python -m evals.run --suite safety --n 3    # one suite, 3 repetitions per case
  python -m evals.run --mode hybrid --judge nebius   # real Nemotron + Nebius judge (refuses when not reachable)
  python -m evals.run validate                # dataset schema + offline integrity proof (CI style)
Exit codes: 0 ok, 1 gate or validation failed, 2 usage error, 3 requested mode/judge cannot run here (refused).
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path

from evals.common import ENGINES, MODES, RESULTS_DIR


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m evals.run", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", nargs="?", default="run", choices=["run", "validate", "list"])
    p.add_argument("--mode", default="fake", choices=MODES, help="fake: scripted agents; hybrid: real Nemotron + local "
                   "sandbox; live: real Nemotron + Nebius Sandboxes")
    p.add_argument("--engine", default="graph", choices=ENGINES, help="engine for bundled-bug cases (repo cases always "
                   "use the graph team)")
    p.add_argument("--suite", default="all", help="all|quick|bugs|repo|multi|safety|locator|repro|unsolvable|followup|pr "
                   "or a category name; comma separated")
    p.add_argument("--cases", default="", help="comma separated case ids (overrides --suite)")
    p.add_argument("--n", type=int, default=1, help="repetitions per case")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--timeout", type=float, default=120.0, help="seconds per case run")
    p.add_argument("--judge", default="none", choices=["none", "nebius"])
    p.add_argument("--baseline", default="", help="run id | latest | path | none (default: evals/baselines/<mode>-baseline.json)")
    p.add_argument("--update-baseline", action="store_true", help="write this run as evals/baselines/<mode>-baseline.json")
    p.add_argument("--run-id", default="")
    p.add_argument("--resume", default="", help="reuse the traces of an earlier run id")
    p.add_argument("--results-dir", default=str(RESULTS_DIR))
    p.add_argument("--no-integrity", action="store_true")
    p.add_argument("--no-deepeval", action="store_true")
    p.add_argument("--no-ragas", action="store_true")
    p.add_argument("--delay-scale", type=float, default=0.05, help="fake-mode agent pacing multiplier")
    p.add_argument("--json", action="store_true", help="print the summary as JSON")
    p.add_argument("-q", "--quiet", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "list":
        from evals.dataset import load_dataset

        for c in load_dataset().cases:
            print(f"{c.id:34} {c.category:30} {c.difficulty:6} {c.input.repo}")
        return 0
    if args.command == "validate":
        from evals.build_golden import main as build_main
        from evals.integrity import format_report, run_integrity
        import asyncio

        from evals.dataset import load_dataset

        ds = load_dataset()
        print(f"dataset v{ds.dataset_version}: {len(ds.cases)} cases, schema valid, semantically consistent")
        stale = build_main(["--check"])
        result = asyncio.run(run_integrity(ds))
        print(format_report(result))
        return 0 if result["ok"] and stale == 0 else 1

    from evals.judge import JudgeUnavailable
    from evals.pipeline import RunConfig, run_pipeline
    from evals.report import fmt, headline_rows
    from evals.sut import LiveUnavailable

    cfg = RunConfig(mode=args.mode, engine=args.engine, suite=args.suite,
                    case_ids=[c for c in args.cases.split(",") if c], n=max(1, args.n), concurrency=args.concurrency,
                    timeout=args.timeout, judge=args.judge, baseline=args.baseline, update_baseline=args.update_baseline,
                    run_id=args.run_id, resume=args.resume, results_dir=Path(args.results_dir),
                    fake_delay_scale=args.delay_scale, integrity=not args.no_integrity, deepeval=not args.no_deepeval,
                    ragas=not args.no_ragas)

    def progress(stage: str, done: int, total: int, msg: str) -> None:
        if not args.quiet and not args.json and (done == total or stage in ("sut",)):
            print(f"[{stage}] {done}/{total} {msg}", flush=True)

    def on_term(signum, frame):  # noqa: ANN001
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, on_term)
    try:
        summary = run_pipeline(cfg, progress)
    except (LiveUnavailable, JudgeUnavailable) as exc:
        print(f"REFUSED: {exc}\nNo fake numbers are substituted for a mode or judge that cannot run here.", file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("aborted", file=sys.stderr)
        return 130
    if args.json:
        slim = {k: v for k, v in summary.items() if not k.startswith("_")}
        print(json.dumps(slim, indent=2, default=str))
    else:
        from evals.report import difficulty_pivot, pivot

        if summary.get("fake_banner"):
            print("\n*** FAKE MODE: scripted agents: validates the harness, not model quality ***")
        print(f"\nrun {summary['run_id']}: {summary['cases']} cases, {summary['trials']} trials, mode={summary['mode']} "
              f"engine={summary['engine']} judge={summary['judge']['mode']} dataset=v{summary['dataset_version']}")
        for row in headline_rows(summary):
            print(f"  {row[0]:34} {row[1]:>22}   {row[2]}")
        h, rows = pivot(summary)
        print("\nmetric x category (mean)")
        widths = [max(len(str(r[i])) for r in [h, *rows]) for i in range(len(h))]
        for r in [h, *rows]:
            print("  " + "  ".join(str(c).ljust(widths[i]) if i == 0 else str(c).rjust(widths[i]) for i, c in enumerate(r)))
        g = summary["gate"]
        print(f"\nGATE: {'PASSED' if g['passed'] else 'FAILED'}  (baseline: {g['baseline']})")
        for c in g["checks"]:
            if not c["ok"] or not args.quiet and not c.get("skipped"):
                print(f"  [{'ok' if c['ok'] else 'FAIL'}] {c['kind']}: {c['message']}")
        print(f"\nresults: {summary['_run_dir']}")
    return 0 if summary["gate"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
