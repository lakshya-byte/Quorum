"""Language and test-command detection. Python is solid; Node and Go are best-effort."""
from __future__ import annotations

import json
import re
from pathlib import PurePosixPath

PY_UNITTEST = 'python -m unittest discover -s . -t . -p "test*.py"'
PY_PYTEST = "python -m pytest -q -x --no-header -p no:cacheprovider"
TEST_DIRS = {"tests", "test", "__tests__", "spec", "specs", "testdata"}
TEST_CONFIGS = {"conftest.py", "pytest.ini", "tox.ini", "setup.cfg", ".coveragerc", "jest.config.js",
                "jest.config.ts", "karma.conf.js"}
TEST_SUFFIXES = ("_test.py", "_test.go", ".test.js", ".test.ts", ".spec.js", ".spec.ts", ".test.jsx", ".test.tsx")


def is_test_path(path: str) -> bool:
    """True for files that hold tests (or test configuration) and must never be edited by a candidate."""
    p = PurePosixPath(path)
    name = p.name.lower()
    if any(part.lower() in TEST_DIRS for part in p.parts[:-1]):
        return True
    return name.startswith("test_") or name.endswith(TEST_SUFFIXES) or name in TEST_CONFIGS


def _py_test_files(files: dict[str, str]) -> list[str]:
    return [f for f in files if f.endswith(".py") and is_test_path(f)
            and (PurePosixPath(f).name.startswith("test") or f.endswith("_test.py"))]


def _is_package_chain(path: str, files: dict[str, str]) -> bool:
    parent = PurePosixPath(path).parent
    while str(parent) not in (".", ""):
        if f"{parent}/__init__.py" not in files:
            return False
        parent = parent.parent
    return True


def detect(files: dict[str, str]) -> dict[str, str]:
    py_tests = _py_test_files(files)
    has_py_project = any(f in files for f in ("setup.py", "pyproject.toml", "requirements.txt"))
    if py_tests or (has_py_project and any(f.endswith(".py") for f in files)):
        uses_pytest = (
            "conftest.py" in files or "pytest.ini" in files
            or "[tool.pytest" in files.get("pyproject.toml", "") or "[pytest]" in files.get("tox.ini", "")
            or any(re.search(r"^\s*(import pytest|from pytest)", files[t], re.MULTILINE) for t in py_tests)
        )
        if py_tests and not uses_pytest and all(_is_package_chain(t, files) for t in py_tests):
            return {"language": "python", "framework": "unittest", "test_command": PY_UNITTEST, "support": "full"}
        if py_tests or uses_pytest:
            return {"language": "python", "framework": "pytest", "test_command": PY_PYTEST, "support": "full"}
    pkg = files.get("package.json")
    if pkg:
        try:
            scripts = json.loads(pkg).get("scripts", {})
        except ValueError:
            scripts = {}
        if isinstance(scripts, dict) and "test" in scripts:
            return {"language": "node", "framework": "npm", "test_command": "npm test", "support": "best-effort"}
    if "go.mod" in files:
        return {"language": "go", "framework": "go test", "test_command": "go test ./...", "support": "best-effort"}
    return {"language": "unknown", "framework": "", "test_command": "", "support": "none"}
