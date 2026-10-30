"""Static scans on changed files: security (bandit for Python, regex rules for JS/TS) and added-line secrets."""
from __future__ import annotations

import difflib
import math
import re
from collections import Counter
from pathlib import PurePosixPath

from app.swarm.artifacts import _SECRET_PATTERNS
from app.security import bandit_available, bandit_local, new_findings

SKIP_SECRET_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock", "go.sum"}
SKIP_SECRET_SUFFIX = (".svg", ".png", ".jpg", ".lock", ".map", ".min.js", ".min.css")
PLACEHOLDER = re.compile(r"(?i)(example|changeme|change_me|placeholder|your[_-]|xxx+|<[^>]+>|\$\{|process\.env|os\.environ|getenv|"
                         r"\.\.\.|dummy|sample|test|fake|redacted|\*{3,})")
SECRETISH = re.compile(r"""(?i)\b([\w.-]*(?:secret|token|passw(?:or)?d|passwd|api[_-]?key|private[_-]?key|auth[_-]?key|access[_-]?key)[\w.-]*)\b"""
                       r"""\s*[:=]\s*['"]([^'"\s]{8,})['"]""")
QUOTED = re.compile(r"""['"]([A-Za-z0-9+/=_\-]{32,})['"]""")

# (rule id, severity, regex, message)
JS_RULES = [
    ("js-eval", "HIGH", re.compile(r"\beval\s*\("), "eval() call"),
    ("js-new-function", "HIGH", re.compile(r"\bnew\s+Function\s*\("), "new Function() call"),
    ("js-child-process", "HIGH", re.compile(r"child_process|\bexecSync\s*\(|\bspawnSync\s*\("), "process execution"),
    ("js-document-write", "MEDIUM", re.compile(r"document\.write\s*\("), "document.write"),
    ("js-innerhtml", "MEDIUM", re.compile(r"\.innerHTML\s*=(?!=)|dangerouslySetInnerHTML"), "raw HTML injection"),
    ("js-insecure-random-token", "MEDIUM", re.compile(r"(?i)(token|secret|password)\w*\s*=\s*Math\.random"), "Math.random for a secret"),
    ("js-tls-off", "HIGH", re.compile(r"rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED"), "TLS verification disabled"),
]
GO_RULES = [
    ("go-exec", "MEDIUM", re.compile(r"exec\.Command\("), "exec.Command"),
    ("go-tls-off", "HIGH", re.compile(r"InsecureSkipVerify:\s*true"), "TLS verification disabled"),
]


def entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    return -sum(c / len(s) * math.log2(c / len(s)) for c in counts.values())


def added_lines(old: str | None, new: str) -> list[str]:
    if old is None:
        return new.splitlines()
    return [ln[1:] for ln in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
            if ln.startswith("+") and not ln.startswith("+++")]


def secret_hits(path: str, old: str | None, new: str) -> list[str]:
    name = PurePosixPath(path).name
    if name in SKIP_SECRET_FILES or path.endswith(SKIP_SECRET_SUFFIX):
        return []
    hits: list[str] = []
    for line in added_lines(old, new):
        if "integrity" in line and "sha" in line or len(line) > 2000:
            continue
        found = None
        for rx, _repl in _SECRET_PATTERNS[:7]:
            if rx.search(line):
                found = "known token format"
                break
        if not found:
            m = SECRETISH.search(line)
            if m and not PLACEHOLDER.search(m.group(2)) and not PLACEHOLDER.search(line[:m.start()][-30:]):
                found = f"hard-coded value assigned to `{m.group(1)}`"
        if not found:
            for q in QUOTED.findall(line):
                if q.lower().startswith(("data", "http")) or "/" in q[:3]:
                    continue
                digits = sum(c.isdigit() for c in q)
                if entropy(q) >= 4.4 and len(set(q)) >= 18 and 0.1 < digits / len(q) < 0.7 and not PLACEHOLDER.search(q):
                    found = "high-entropy string literal"
                    break
        if found:
            hits.append(f"{path}: {found}")
    return hits


def regex_findings(path: str, text: str) -> list[dict]:
    rules = JS_RULES if path.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")) else GO_RULES if path.endswith(".go") else []
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        for rid, sev, rx, msg in rules:
            if rx.search(line):
                out.append({"test_id": rid, "severity": sev, "confidence": "MEDIUM", "line": n, "text": msg})
    return out


async def security_scan(path: str, old: str | None, new: str) -> tuple[list[dict], bool]:
    """New medium+ findings in one changed file and whether a scanner actually ran."""
    if path.endswith(".py"):
        if not bandit_available():
            return [], False
        before = await bandit_local(PurePosixPath(path).name, old) if old is not None else []
        after = await bandit_local(PurePosixPath(path).name, new)
        if after is None:
            return [], False
        return [{**f, "file": path} for f in new_findings(before, after)], True
    if path.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go")):
        before = regex_findings(path, old or "")
        after = regex_findings(path, new)
        return [{**f, "file": path} for f in new_findings(before, after)], True
    return [], False
