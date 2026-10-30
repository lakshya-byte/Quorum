"""Each deterministic verifier: positive and negative cases, parsers, artifact store, error handling."""
import asyncio
import json

import pytest

from app.swarm.artifacts import ArtifactStore, redact_text
from app.swarm.repo_map import build_repo_map
from app.swarm.verifiers import Baseline, Criterion, collect_baseline, run_verifier, validate_on_original
from app.swarm.verifiers import testparse
from app.swarm.workspace import LocalWorkspaceFactory


def run(coro):
    return asyncio.run(coro)


PKG = {
    "pkg/__init__.py": "from .core import add, Calc\n__all__ = ['add', 'Calc']\n",
    "pkg/core.py": "def add(a, b):\n    return a + b\n\n\nclass Calc:\n    def mul(self, a, b):\n        return a * b\n",
    "tests/__init__.py": "",
    "tests/test_core.py": "import unittest\nfrom pkg import add, Calc\n\n\nclass T(unittest.TestCase):\n"
                         "    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n\n"
                         "    def test_mul(self):\n        self.assertEqual(Calc().mul(2, 3), 6)\n",
}


class Env:
    """Open a demo-flagged local workspace + baseline for `files`; fork() gives a fresh editable copy."""

    def __init__(self, files=None, ui=False):
        self.files = dict(files or PKG)
        self.store = ArtifactStore()
        self.root = run(LocalWorkspaceFactory(demo=True).open(self.files, language_hint="python"))
        self.base = run(collect_baseline(self.root, None, self.store, ui_checks=ui))

    def fork(self):
        return run(self.root.fork())

    def verify(self, ws, kind, hard=True, **params):
        return run(run_verifier(Criterion(kind, kind, hard, "", params), ws, self.base, self.store))


@pytest.fixture(scope="module")
def env():
    e = Env()
    yield e
    run(e.root.release())


def edit(ws, path, text, tests=False):
    ws.allow_tests = tests
    run(ws.write(path, text))


# ---- parsers ------------------------------------------------------------------------------------------------------

def test_parse_unittest_pytest_go_and_json():
    ut = ("test_a (tests.test_x.T.test_a) ... ok\ntest_b (tests.test_x.T.test_b)\nDoc line ... FAIL\n"
          "test_c (tests.test_x.T.test_c) ... skipped 'no'\nERROR: test_y (unittest.loader._FailedTest.test_y)\n")
    got = testparse.parse_unittest(ut)
    assert got["tests.test_x.T.test_a"] == "pass" and got["tests.test_x.T.test_b"] == "fail"
    assert got["tests.test_x.T.test_c"] == "skip" and got["test_y (import)"] == "fail"
    pt = "tests/test_a.py::test_one PASSED [ 50%]\ntests/test_a.py::TestX::test_two FAILED [100%]\n"
    assert testparse.parse_pytest(pt) == {"tests/test_a.py::test_one": "pass", "tests/test_a.py::TestX::test_two": "fail"}
    go = "=== RUN   TestA\n--- PASS: TestA (0.00s)\n--- FAIL: TestB (0.00s)\nFAIL\texample.com/app/store\t0.01s\n"
    assert testparse.parse_go(go) == {"example.com/app/store::TestA": "pass", "example.com/app/store::TestB": "fail"}
    blob = json.dumps({"numTotalTestSuites": 1, "testResults": [{"name": "/tmp/x/src/a.test.js", "status": "passed", "assertionResults": [
        {"fullName": "suite one", "title": "one", "status": "passed"}, {"fullName": "suite two", "status": "failed"}]}]})
    got = testparse.parse_jest_json("noise\n" + blob + "\ntrailing", {"src/a.test.js"})
    assert got == {"src/a.test.js::suite one": "pass", "src/a.test.js::suite two": "fail"}
    assert testparse.test_file_of("tests.test_core.T.test_add", {"tests/test_core.py"}) == "tests/test_core.py"


# ---- build / tests / no_regression -------------------------------------------------------------------------------------

def test_build_pass_fail_skip(env):
    assert env.verify(env.fork(), "build").status == "pass"
    ws = env.fork()
    edit(ws, "pkg/broken.py", "def (:\n")
    r = env.verify(ws, "build")
    assert r.status == "fail" and "compileall" in r.detail
    empty = Env({"notes.txt": "hello"})
    r = empty.verify(empty.fork(), "build")
    assert r.status == "skip" and "no build" in r.detail
    run(empty.root.release())


def test_tests_and_no_regression(env):
    ws = env.fork()
    assert env.verify(ws, "tests").status == "pass"
    assert env.verify(ws, "no_regression").status == "pass"
    edit(ws, "pkg/core.py", "def add(a, b):\n    return a - b\n\n\nclass Calc:\n    def mul(self, a, b):\n        return a * b\n")
    r = env.verify(ws, "no_regression")
    assert r.status == "fail" and "test_add" in r.detail and env.verify(ws, "tests").status == "fail"
    # deleting the tests is also a regression (missing, not failing)
    ws2 = env.fork()
    ws2.allow_tests = True
    run(ws2.delete("tests/test_core.py"))
    r = env.verify(ws2, "no_regression")
    assert r.status == "fail" and "missing/deleted" in r.detail


def test_no_regression_is_relative_to_a_failing_baseline():
    files = dict(PKG)
    files["tests/test_core.py"] += "\n    def test_known_bad(self):\n        self.assertEqual(add(1, 1), 3)\n"
    e = Env(files)
    assert e.base.tests["status"] == "fail" and len(e.base.passing_tests) == 2
    ws = e.fork()
    assert e.verify(ws, "no_regression").status == "pass"  # the pre-existing failure is not our problem
    assert e.verify(ws, "tests").status == "fail"
    edit(ws, "pkg/core.py", "def add(a, b):\n    return 0\n\n\nclass Calc:\n    pass\n")
    assert e.verify(ws, "no_regression").status == "fail"
    run(e.root.release())


def test_no_tests_means_skip():
    e = Env({"a.py": "x = 1\n"})
    assert e.base.tests["status"] == "none"
    assert e.verify(e.fork(), "no_regression").status == "skip"
    assert e.verify(e.fork(), "tests").status == "skip"
    run(e.root.release())


# ---- spec tests -------------------------------------------------------------------------------------------------------

ACCEPT = {"tests/test_neg.py": "import unittest\nfrom pkg import add\n\n\nclass N(unittest.TestCase):\n"
                               "    def test_neg(self):\n        self.assertEqual(add(-1, -2), -3)\n\n"
                               "    def test_missing_feature(self):\n        from pkg import sub\n        self.assertEqual(sub(3, 1), 2)\n"}


def test_acceptance_fails_on_original_passes_with_feature(env):
    ws = env.fork()
    c = Criterion("acc", "acceptance_tests", True, "", {"files": ACCEPT})
    ok, why = run(validate_on_original(c, ws, env.base, env.store))
    assert ok and "fails on the original" in why
    ws2 = env.fork()
    edit(ws2, "pkg/core.py", PKG["pkg/core.py"] + "\n\ndef sub(a, b):\n    return a - b\n")
    edit(ws2, "pkg/__init__.py", "from .core import add, sub, Calc\n__all__ = ['add', 'sub', 'Calc']\n")
    r = env.verify(ws2, "acceptance_tests", files=ACCEPT)
    assert r.status == "pass" and r.meta["total"] == 2
    ok, why = run(validate_on_original(c, ws2, env.base, env.store))
    assert not ok and "does not test the requested change" in why


def test_characterization_must_pass_on_original(env):
    good = {"tests/test_char.py": "import unittest\nfrom pkg import add\n\n\nclass C(unittest.TestCase):\n    def test_x(self):\n        self.assertEqual(add(2, 2), 4)\n"}
    bad = {"tests/test_char.py": good["tests/test_char.py"].replace("4)", "5)")}
    ws = env.fork()
    assert run(validate_on_original(Criterion("c", "characterization", True, "", {"files": good}), ws, env.base, env.store))[0]
    ws = env.fork()
    assert not run(validate_on_original(Criterion("c", "characterization", True, "", {"files": bad}), ws, env.base, env.store))[0]
    r = env.verify(env.fork(), "repro", files=good)
    assert r.status == "pass"
    assert env.verify(env.fork(), "acceptance_tests").status == "skip"


# ---- policy / security / secrets (fake workspaces return the diff we want to judge) -----------------------------------------

class FakeWS:
    isolation = "local"

    def __init__(self, changed):
        self._changed = changed

    async def changed(self):
        return self._changed

    async def exec(self, cmd, timeout=1):
        raise AssertionError("not used")


def judge(env, kind, changed, **params):
    return run(run_verifier(Criterion(kind, kind, True, "", params), FakeWS(changed), env.base, env.store))


def test_policy(env):
    assert judge(env, "policy", {"pkg/core.py": "x = 1\n"}).status == "pass"
    assert judge(env, "policy", {}).status == "fail"
    assert "existing test file modified" in judge(env, "policy", {"tests/test_core.py": "# gutted\n"}).detail
    assert "deleted" in judge(env, "policy", {"tests/test_core.py": None}).detail
    assert judge(env, "policy", {"tests/test_core.py": "# ok\n"}, task_type="tests").status == "pass"
    assert judge(env, "policy", {"tests/test_new.py": "def test_n():\n    pass\n"}).status == "pass"  # new tests are fine
    assert judge(env, "policy", {".github/workflows/ci.yml": "x"}).status == "fail"
    assert judge(env, "policy", {"../escape.py": "x"}).status == "fail"
    assert judge(env, "policy", {f"f{i}.py": "x" for i in range(5)}, max_files=3).status == "fail"
    assert judge(env, "policy", {"big.py": "x" * 1_100_000}).status == "fail"
    assert judge(env, "policy", {"a.py": "x"}, protected_globs=["a.*"]).status == "fail"


def test_policy_package_json_test_script_weakening():
    e = Env({"package.json": json.dumps({"scripts": {"test": "vitest run"}}), "a.js": "1"}, ui=False)
    weak = json.dumps({"scripts": {"test": "echo skipped"}})
    assert "test script changed" in judge(e, "policy", {"package.json": weak}).detail
    ok = json.dumps({"scripts": {"test": "vitest run", "lint": "x"}})
    assert judge(e, "policy", {"package.json": ok}).status == "pass"
    run(e.root.release())


def test_secrets(env):
    aws = "KEY = 'AKIAIOSFODNN7EXAMPLE'\n"
    assert judge(env, "secrets", {"c.py": aws}).status == "fail"
    assert judge(env, "secrets", {"c.py": "GH = 'ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8" + "'\n"}).status == "fail"
    assert judge(env, "secrets", {"c.py": "db_password = 'hunter2hunter2'\n"}).status == "fail"
    assert judge(env, "secrets", {"c.js": "const apiKey = \"" + "x9Zk3Qw8Lm2Vb7Nc4Rt6Yp1Hs5Dg0Fj" + "\"\n"}).status == "fail"
    assert judge(env, "secrets", {"c.py": "tok = '" + "Zx8Qw3Lm9Vb2Nc7Rt4Yp6Hs1Dg5Fj0KaP8uE3mW" + "'\n"}).status == "fail"  # entropy
    assert judge(env, "secrets", {"k.pem": "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----\n"}).status == "fail"
    for ok in ("password = os.environ['PASSWORD']\n", "api_key = 'changeme-example-key'\n", "token = process.env.TOKEN\n",
               "name = 'a perfectly normal long string with spaces in it'\n", "url = 'https://example.com/a/b/c'\n"):
        assert judge(env, "secrets", {"ok.py": ok}).status == "pass", ok
    lock = '    "integrity": "sha512-' + "Ab3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5bC7dE9fG1hJ3kL5mN7pQ9rS1tU3vW5xY7zA9bC1dE3fG5hJ7kL9mN1p==" + '"\n'
    assert judge(env, "secrets", {"package-lock.json": lock}).status == "pass"
    # only ADDED lines count: a pre-existing secret that is not touched is not flagged
    e2 = Env({"c.py": aws, "ok.py": "x = 1\n"})
    assert judge(e2, "secrets", {"c.py": aws + "y = 1\n"}).status == "pass"
    run(e2.root.release())


def test_security_python_and_js(env):
    bad = "import subprocess\n\n\ndef go(cmd):\n    subprocess.call(cmd, shell=True)\n"
    r = judge(env, "security", {"pkg/danger.py": bad})
    from app.security import bandit_available
    if bandit_available():
        assert r.status == "fail" and "B602" in r.detail
        assert judge(env, "security", {"pkg/core.py": PKG["pkg/core.py"] + "\n\ndef z():\n    return 1\n"}).status == "pass"
    else:
        assert r.status == "skip"
    js = judge(env, "security", {"src/x.js": "export const run = (s) => eval(s)\n"})
    assert js.status == "fail" and "js-eval" in js.detail
    assert judge(env, "security", {"src/y.js": "el.innerHTML = html\n"}).status == "fail"
    assert judge(env, "security", {"src/z.js": "export const ok = 1\n"}).status == "pass"
    e2 = Env({"src/x.js": "export const run = (s) => eval(s)\n", "a.py": "x = 1\n"})
    assert judge(e2, "security", {"src/x.js": "export const run = (s) => eval(s)\n// touched\n"}).status == "pass"  # not new
    run(e2.root.release())


# ---- api surface ---------------------------------------------------------------------------------------------------------------

def test_api_surface_python(env):
    ws = env.fork()
    assert env.verify(ws, "api_surface", modules=["pkg/__init__.py", "pkg/core.py"]).status == "pass"
    # additions are fine
    edit(ws, "pkg/core.py", PKG["pkg/core.py"] + "\n\ndef extra():\n    return 1\n")
    assert env.verify(ws, "api_surface", modules=["pkg/core.py"]).status == "pass"
    # removal, signature change, method removal
    for new, expect in (("def add(a, b, c):\n    return 0\n\n\nclass Calc:\n    def mul(self, a, b):\n        return 1\n", "changed signature"),
                        ("class Calc:\n    def mul(self, a, b):\n        return 1\n", "removed `add`"),
                        ("def add(a, b):\n    return 0\n\n\nclass Calc:\n    pass\n", "removed method `Calc.mul`")):
        w = env.fork()
        edit(w, "pkg/core.py", new)
        r = env.verify(w, "api_surface", modules=["pkg/core.py"])
        assert r.status == "fail" and expect in r.detail, r.detail
    w = env.fork()
    w.allow_tests = True
    run(w.delete("pkg/core.py"))
    assert "module removed" in env.verify(w, "api_surface", modules=["pkg/core.py"]).detail


def test_api_surface_follows_moves_and_reexports(env):
    w = env.fork()
    edit(w, "pkg/impl.py", PKG["pkg/core.py"])
    edit(w, "pkg/core.py", "from .impl import add, Calc\n")  # moved: same names, same signatures
    assert env.verify(w, "api_surface", modules=["pkg/__init__.py", "pkg/core.py"]).status == "pass"
    edit(w, "pkg/impl.py", PKG["pkg/core.py"].replace("def add(a, b):", "def add(a, b, c=0):"))
    assert env.verify(w, "api_surface", modules=["pkg/__init__.py"]).status == "fail"


def test_api_surface_typescript_and_default_modules():
    ts = {"src/index.ts": "export function a(x: number): number { return x }\nexport const B = 1\nexport interface I { y: string }\n",
          "package.json": json.dumps({"main": "src/index.ts"})}
    e = Env(ts)
    w = e.fork()
    assert e.verify(w, "api_surface").status == "pass"
    edit(w, "src/index.ts", "export function a(x: string): number { return 1 }\nexport const B = 1\n")
    r = e.verify(w, "api_surface")
    assert r.status == "fail" and "`a`" in r.detail and "removed `I`" in r.detail
    run(e.root.release())
    assert Env({"x.txt": "1"}).verify(None, "api_surface").status == "skip"


# ---- lint / complexity / command / benchmark -----------------------------------------------------------------------------------

def test_lint_no_worse_than_baseline():
    from app.swarm.verifiers.gates import lint_tools
    if not __import__("importlib").util.find_spec("ruff"):
        pytest.skip("ruff not installed")
    e = Env({"a.py": "import os\nx = 1\n", "tests/test_a.py": "def test_a():\n    assert True\n"})
    assert e.base.lint["ruff"]["count"] == 2  # F401 unused import + I001
    w = e.fork()
    edit(w, "a.py", "x = 1\n")
    r = e.verify(w, "lint_typecheck")
    assert r.status == "pass" and "ruff 2->0" in r.detail
    edit(w, "a.py", "import os\nimport sys\nx = 1\n")
    assert e.verify(w, "lint_typecheck").status == "fail"
    assert Env({"notes.txt": "x"}).verify(None, "lint_typecheck").status == "skip"
    assert lint_tools(build_repo_map({"a.py": "x=1"}))
    run(e.root.release())


def test_complexity_metric(env):
    big = "def f(x):\n" + "".join(f"    if x == {i}:\n        return {i}\n" for i in range(8)) + "    return 0\n"
    e = Env({"m.py": big, "tests/test_m.py": "from m import f\n\n\ndef test_f():\n    assert f(1) == 1\n"})
    w = e.fork()
    r = e.verify(w, "complexity_metric", metric="max_function_complexity", paths=["m.py"], target={"op": "<=", "value": 3})
    assert r.status == "fail" and "no improvement" in r.detail
    edit(w, "m.py", "TABLE = {i: i for i in range(8)}\n\n\ndef f(x):\n    return TABLE.get(x, 0)\n")
    r = e.verify(w, "complexity_metric", metric="max_function_complexity", paths=["m.py"], target={"op": "<=", "value": 3})
    assert r.status == "pass" and r.meta["before"] == 9 and r.meta["after"] == 1
    assert e.verify(w, "complexity_metric", metric="bogus").status == "skip"
    run(e.root.release())


def test_command_and_benchmark(env):
    ws = env.fork()
    edit(ws, "bench.py", "print('elapsed_ms=42.5')\n")
    assert env.verify(ws, "command", cmd="python -m pytest -q tests").status in ("pass", "fail")
    assert env.verify(ws, "command", cmd="python bench.py").status == "pass"
    assert env.verify(ws, "command", cmd="python bench.py", expect_code=1).status == "fail"
    r = env.verify(ws, "command", cmd="curl http://x")
    assert r.status == "fail" and "COMMAND_DENIED" in r.detail
    assert env.verify(ws, "benchmark", cmd="python bench.py", regex=r"elapsed_ms=([0-9.]+)", threshold=50).status == "pass"
    assert env.verify(ws, "benchmark", cmd="python bench.py", regex=r"elapsed_ms=([0-9.]+)", threshold=40).status == "fail"
    assert env.verify(ws, "benchmark", cmd="python bench.py", regex=r"elapsed_ms=([0-9.]+)", threshold=40, direction="min").status == "pass"
    assert env.verify(ws, "benchmark", cmd="python bench.py").status == "skip"
    assert env.verify(ws, "command").status == "skip"


# ---- advisory / robustness ---------------------------------------------------------------------------------------------------------

def test_advisory_needs_judge_and_with_judge(env):
    ws = env.fork()
    r = env.verify(ws, "advisory_rubric", hard=False, rubric="readable?")
    assert r.status == "skip" and r.detail == "needs_judge"

    async def judge_fn(kind, crit, context):
        assert kind == "advisory_rubric" and "changed_files" in context
        return {"score": 0.8, "rationale": "reads fine"}

    r = run(run_verifier(Criterion("r", "advisory_rubric", False, "", {}), ws, env.base, env.store, judge=judge_fn))
    assert r.status == "advisory" and r.score == 0.8 and r.detail == "reads fine" and not r.hard

    async def broken(kind, crit, context):
        raise RuntimeError("x")

    r = run(run_verifier(Criterion("r", "advisory_rubric", False, "", {}), ws, env.base, env.store, judge=broken))
    assert r.status == "skip" and "judge failed" in r.detail
    # vision without a web app: explicit reason, not a crash
    r = run(run_verifier(Criterion("v", "advisory_vision", False, "", {}), ws, env.base, env.store, judge=judge_fn))
    assert r.status == "skip"


def test_unknown_kind_and_crash_are_skip_not_pass(env):
    r = run(run_verifier(Criterion("x", "nonsense", True), env.fork(), env.base, env.store))
    assert r.status == "skip" and "unknown verifier kind" in r.detail
    r = run(run_verifier(Criterion("x", "policy", True), object(), env.base, env.store))
    assert r.status == "skip" and r.detail.startswith("verifier error")
    ev = r.event()
    assert set(ev) == {"criterion_id", "kind", "hard", "status", "score", "detail", "artifacts"}


def test_ui_criteria_skip_with_reason_on_non_web_repo(env):
    for kind in ("ui_build_console", "ui_overflow", "ui_axe"):
        r = env.verify(env.fork(), kind)
        assert r.status == "skip" and "not a static web app" in r.detail
    assert env.base.ui["status"] == "skip"


# ---- artifacts --------------------------------------------------------------------------------------------------------------------

def test_artifact_store_caps_and_redaction():
    s = ArtifactStore(max_artifacts=3, max_bytes=100)
    a = s.add("log", "run", "after", None, "text/plain", "token=abcdef123456 and sk-" + "A" * 30 + " ok")
    text = s.bytes_of(a.id).decode()
    assert "abcdef123456" not in text and "sk-" not in text and "[REDACTED]" in text
    assert s.add("screenshot", "big", "after", 375, "image/png", b"x" * 101) is None  # binary over the cap is dropped
    assert s.add("log", "long", "n/a", None, "text/plain", "y" * 500) is not None  # text is tail-truncated instead
    assert s.add("weird", "k", "n/a", None, "text/plain", "x") is None and s.add("log", "m", "n/a", None, "application/zip", b"x") is None
    s.add("report", "r", "n/a", None, "application/json", "{}")
    assert s.add("log", "overflow", "n/a", None, "text/plain", "z") is None  # 3 max
    art, data = s.get(a.id)
    assert art.meta()["mime"] == "text/plain" and set(art.meta()) == {"id", "kind", "label", "phase", "viewport", "mime", "size"}
    assert redact_text("Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123") == "Authorization: Bearer [REDACTED]"
