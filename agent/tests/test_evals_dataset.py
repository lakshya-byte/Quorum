"""Golden dataset: schema, counts, loader, integrity proof (real local sandbox)."""
import asyncio
import copy
import json

import jsonschema
import pytest

from evals import build_golden
from evals.common import GOLDEN_PATH, SCHEMA_PATH
from evals.dataset import (CATEGORY_MINIMUMS, MIN_TOTAL_CASES, DatasetError, json_schema, load_dataset, parse_dataset,
                           semantic_errors, validate_case_dict)
from evals.integrity import run_integrity


@pytest.fixture(scope="module")
def ds():
    return load_dataset()


def test_counts_and_category_minimums(ds):
    assert len(ds.cases) >= MIN_TOTAL_CASES
    for cat, minimum in CATEGORY_MINIMUMS.items():
        assert sum(c.category == cat for c in ds.cases) >= minimum, cat
    assert sum(c.category == "bug_fix_single_file" for c in ds.cases) == 9
    assert {c.difficulty for c in ds.cases} == {"easy", "medium", "hard"}
    assert ds.dataset_version and ds.created and ds.schema_version


def test_versioned_ids_unique_and_fields_real(ds):
    assert len({c.id for c in ds.cases}) == len(ds.cases)
    for c in ds.cases:
        assert c.input.task and c.rubric and c.reference.root_cause
    shop = ds.by_id()["bf-shop-api-coupon"]
    assert len(shop.reference.reference_files) == 2 and shop.expected.min_files_changed == 2
    assert any(c.input.adversarial_patch for c in ds.cases if c.category == "safety_guardrails")
    assert any("ignore previous instructions" in c.input.task.lower() for c in ds.cases)
    assert sum(1 for c in ds.cases if c.expected.solved is False) >= 2


def test_file_validates_against_generated_json_schema():
    data = json.loads(GOLDEN_PATH.read_text())
    schema = json.loads(SCHEMA_PATH.read_text())
    assert schema == json_schema()
    jsonschema.validate(data, schema)


def test_committed_dataset_matches_builder():
    assert build_golden.main(["--check"]) == 0


def test_semantic_errors_detected(ds):
    raw = json.loads(GOLDEN_PATH.read_text())
    raw["cases"][0]["input"]["repo"] = "no-such-bug"
    assert any("unknown repo" in e for e in semantic_errors(parse_dataset(raw)))
    raw = json.loads(GOLDEN_PATH.read_text())
    raw["cases"] = raw["cases"][:5]
    assert any("cases <" in e or "required" in e for e in semantic_errors(parse_dataset(raw)))


def test_schema_rejects_bad_case(ds):
    case = json.loads(ds.cases[0].model_dump_json())
    case["difficulty"] = "impossible"
    obj, errs = validate_case_dict(case)
    assert obj is None and errs
    good = json.loads(ds.cases[0].model_dump_json())
    assert validate_case_dict(good)[0] is not None
    with pytest.raises(DatasetError):
        parse_dataset({"cases": []})


def test_integrity_proof_runs_for_real():
    ids = ["bf-paginate", "bf-shop-api-coupon", "repro-booking-suite-hides-bug", "saf-weak-crypto-patch",
           "unsol-false-bug-report", "loc-wordstats-distractor"]
    result = asyncio.run(run_integrity(case_ids=ids))
    assert result["ok"], result["failed_cases"]
    names = {c["name"] for r in result["reports"] for c in r["checks"]}
    assert {"reference_fix_passes_all_tests", "original_fails_at_least_one_test", "partial_ranks_below_correct",
            "wrong_ranks_below_correct", "reference_diff_non_test_files_only", "bandit_flags_new_finding",
            "existing_suite_green_on_original", "claimed_bug_does_not_reproduce"} <= names


def test_integrity_fails_on_a_corrupted_case(tmp_path):
    from evals.dataset import Dataset

    raw = json.loads(GOLDEN_PATH.read_text())
    case = next(c for c in raw["cases"] if c["id"] == "bf-paginate")
    case["reference"]["reference_diff"] = case["reference"]["reference_diff"].replace("page - 1", "page")
    ds = Dataset.model_validate(raw)
    result = asyncio.run(run_integrity(ds, ["bf-paginate"]))
    assert not result["ok"]
    failed = [c["name"] for r in result["reports"] for c in r["checks"] if not c["ok"]]
    assert "reference_diff_is_current" in failed
