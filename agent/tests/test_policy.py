import asyncio

import pytest

from app.bugs import BUGS
from app.bugs import test_filename as harness_tests_file
from app.candidate import evaluate_candidate, is_solved
from app.policy import check_candidate
from app.sandbox import LocalSandbox
from app.security import bandit_available

BUG = BUGS["average"]
OK_CODE = BUG["correct"]


def blocked(code: str, extra: dict | None = None) -> list[str]:
    res = check_candidate(BUG, {BUG["target"]: code, **(extra or {})})
    assert not res.ok
    return res.reasons


@pytest.mark.parametrize("snippet", [
    "import os\nos.system('ls')\n",
    "from os import system\nsystem('ls')\n",
    "import os as o\no.popen('ls')\n",
    "import subprocess\nsubprocess.run(['ls'])\n",
    "from subprocess import run\n",
    "import socket\n",
    "import requests\n",
    "import httpx\n",
    "import urllib.request\n",
    "from urllib import request\n",
    "x = eval('1+1')\n",
    "exec('x = 1')\n",
    "m = __import__('os')\n",
    "import ctypes\n",
    "open('/etc/passwd').read()\n",
    "open('../secrets.txt').read()\n",
    "p = 'x'\nopen(p).read()\n",
    "import io\nio.open('/tmp/x')\n",
    "().__class__.__base__.__subclasses__()\n",
])
def test_denylist_is_blocked(snippet: str) -> None:
    reasons = blocked(OK_CODE + "\n" + snippet)
    assert reasons, snippet


def test_relative_open_inside_workdir_is_allowed() -> None:
    assert check_candidate(BUG, {BUG["target"]: OK_CODE + "\nDATA = open('data.txt')\n"}).ok


def test_correct_fix_passes_policy() -> None:
    assert check_candidate(BUG, {BUG["target"]: OK_CODE}).ok


def test_test_file_edit_is_blocked() -> None:
    reasons = blocked(OK_CODE, {harness_tests_file(BUG): "import unittest\n"})
    assert any("test file" in r for r in reasons)


def test_identical_test_file_is_fine() -> None:
    assert check_candidate(BUG, {BUG["target"]: OK_CODE, harness_tests_file(BUG): BUG["tests"]}).ok


def test_other_files_are_blocked() -> None:
    reasons = blocked(OK_CODE, {"conftest.py": "x = 1\n"})
    assert any("outside the target" in r for r in reasons)


def test_large_diff_is_blocked() -> None:
    big = OK_CODE + "".join(f"\nX{i} = {i}" for i in range(70)) + "\n"
    assert any("diff too large" in r for r in blocked(big))


def test_syntax_error_is_blocked() -> None:
    assert any("does not parse" in r for r in blocked("def broken(:\n"))


def test_policy_violation_scores_zero_and_never_runs() -> None:
    node = asyncio.run(evaluate_candidate(
        BUG, LocalSandbox(), node_id=1, parent=0, depth=1, idea="x", model="m",
        code=OK_CODE + "\nimport subprocess\n",
    ))
    assert node["policy"]["ok"] is False and node["score"] == 0.0
    assert node["output"].startswith("POLICY_BLOCKED") and node["total"] == 0
    assert not is_solved(node)


@pytest.mark.skipif(not bandit_available(), reason="bandit not installed")
def test_security_scan_blocks_new_medium_findings() -> None:
    # passes every test and the policy gate, but adds pickle (bandit B403/B301, medium+)
    code = "import pickle\n\n\n" + OK_CODE + "\n\ndef load(blob):\n    return pickle.loads(blob)\n"
    node = asyncio.run(evaluate_candidate(
        BUG, LocalSandbox(), node_id=1, parent=0, depth=1, idea="x", model="m", code=code,
    ))
    assert node["policy"]["ok"] is True
    assert node["passed"] == node["total"] > 0
    assert node["security"]["ok"] is False and node["security"]["new_findings"]
    assert node["score"] == 0.0 and not is_solved(node)
