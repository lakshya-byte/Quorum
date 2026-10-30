"""Parse test-runner output into {test_id: "pass"|"fail"|"skip"}. Supports unittest -v, pytest -v, jest/vitest
JSON reporters and `go test -v`. Pure functions, no I/O."""
from __future__ import annotations

import json
import re

_UNITTEST = re.compile(r"^(?P<name>\S+) \((?P<cls>[\w.]+)\)(?:\n?.*?)? \.\.\. (?P<st>ok|FAIL|ERROR|skipped.*|expected failure|unexpected success)\s*$",
                       re.M)
_UNITTEST_FAILED_IMPORT = re.compile(r"^(?:ERROR|FAIL): (\S+) \((unittest\.loader\._FailedTest[\w.]*)\)", re.M)
_PYTEST = re.compile(r"^(?P<id>[^\s:]+(?:/[^\s:]+)*\.py::\S.*?)\s+(?P<st>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b", re.M)
_PYTEST_SUMMARY = re.compile(r"^(?P<st>PASSED|FAILED|ERROR|SKIPPED) (?P<id>\S+\.py::\S+)", re.M)
_GO = re.compile(r"^\s*--- (?P<st>PASS|FAIL|SKIP): (?P<name>\S+)", re.M)
_GO_PKG = re.compile(r"^(?:ok|FAIL)[ \t]+(\S+)[ \t]", re.M)


def _status(word: str) -> str:
    w = word.lower()
    if w in ("ok", "pass", "passed", "xfail", "expected failure", "xpass", "passed"):
        return "pass"
    if w.startswith("skip") or w in ("pending", "todo", "disabled"):
        return "skip"
    return "fail"


def parse_unittest(output: str) -> dict[str, str]:
    results: dict[str, str] = {}
    for m in _UNITTEST.finditer(output):
        cls, name = m.group("cls"), m.group("name")
        ident = cls if cls.endswith("." + name) or cls == name else f"{cls}.{name}"
        results[ident] = _status(m.group("st"))
    for m in _UNITTEST_FAILED_IMPORT.finditer(output):
        results[f"{m.group(1)} (import)"] = "fail"
    return results


def parse_pytest(output: str) -> dict[str, str]:
    results: dict[str, str] = {}
    for m in _PYTEST.finditer(output):
        results[m.group("id").strip()] = _status(m.group("st"))
    for m in _PYTEST_SUMMARY.finditer(output):
        results.setdefault(m.group("id"), _status(m.group("st")))
    return results


def _json_blob(output: str) -> dict | None:
    for marker in ('{"numTotalTestSuites"', '{"numFailedTestSuites"', '{"success"', '{"testResults"'):
        i = output.find(marker)
        if i >= 0:
            depth, j = 0, i
            in_str = esc = False
            for j in range(i, len(output)):
                ch = output[j]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        break
            try:
                return json.loads(output[i:j + 1])
            except ValueError:
                return None
    return None


def parse_jest_json(output: str, known_paths: set[str] | None = None) -> dict[str, str]:
    """jest `--json` and vitest `--reporter=json` share this shape."""
    data = _json_blob(output)
    results: dict[str, str] = {}
    if not data:
        return results
    for suite in data.get("testResults", []):
        raw = str(suite.get("name", ""))
        path = _relativise(raw, known_paths)
        asserts = suite.get("assertionResults") or []
        for a in asserts:
            name = a.get("fullName") or " ".join([*(a.get("ancestorTitles") or []), a.get("title", "")]).strip()
            results[f"{path}::{name}"] = _status(str(a.get("status", "failed")))
        if not asserts and str(suite.get("status", "")).lower() in ("failed", "fail"):
            results[f"{path}::(suite failed to run)"] = "fail"
    return results


def _relativise(raw: str, known: set[str] | None) -> str:
    raw = raw.replace("\\", "/")
    if known:
        parts = raw.split("/")
        for i in range(len(parts)):
            cand = "/".join(parts[i:])
            if cand in known:
                return cand
    return raw.rsplit("/", 2)[-2] + "/" + raw.rsplit("/", 1)[-1] if raw.count("/") >= 2 else raw


def parse_go(output: str) -> dict[str, str]:
    pkgs = _GO_PKG.findall(output)
    pkg = pkgs[0] if len(pkgs) == 1 else ""
    return {f"{pkg}::{m.group('name')}" if pkg else m.group("name"): _status(m.group("st")) for m in _GO.finditer(output)}


def parse_any(output: str, framework: str, known_paths: set[str] | None = None) -> dict[str, str]:
    """Pick the parser from the framework name; unknown frameworks try every parser."""
    fw = framework.lower()
    if fw == "unittest":
        return parse_unittest(output)
    if fw == "pytest":
        return parse_pytest(output)
    if fw in ("vitest", "jest"):
        return parse_jest_json(output, known_paths)
    if fw in ("go", "go test"):
        return parse_go(output)
    for fn in (lambda o: parse_jest_json(o, known_paths), parse_pytest, parse_unittest, parse_go):
        got = fn(output)
        if got:
            return got
    return {}


def test_file_of(test_id: str, known_paths: set[str]) -> str | None:
    """Best-effort: which source file does this test id belong to."""
    if "::" in test_id:
        head = test_id.split("::", 1)[0]
        return head if head in known_paths or not known_paths else head
    parts = test_id.split(".")  # unittest dotted id: tests.test_stock.StockTests.test_x
    for i in range(len(parts), 0, -1):
        cand = "/".join(parts[:i]) + ".py"
        if cand in known_paths:
            return cand
    return None
