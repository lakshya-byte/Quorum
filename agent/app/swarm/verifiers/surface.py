"""Public API surface extraction and diff (refactor safety net).

Python: via `ast`, re-exports are resolved through the repo's own modules so moving a class into another module
keeps the same surface (class methods are merged across internal base classes/mixins). TypeScript/JavaScript:
regex over `export` statements (best-effort: signature text of the declaration line). Go: exported identifiers."""
from __future__ import annotations

import ast
import posixpath
import re
from typing import Any

Surface = dict[str, Any]


def _sig(node: ast.AST) -> str:
    try:
        ret = f" -> {ast.unparse(node.returns)}" if getattr(node, "returns", None) else ""  # type: ignore[attr-defined]
        return f"({ast.unparse(node.args)}){ret}"  # type: ignore[attr-defined]
    except Exception:
        return "(?)"


class PySurface:
    def __init__(self, files: dict[str, str]) -> None:
        self.files = files
        self._trees: dict[str, ast.Module | None] = {}
        self.modules: dict[str, str] = {}
        for p in files:
            if p.endswith(".py"):
                parts = p[:-3].split("/")
                if parts[-1] == "__init__":
                    parts = parts[:-1]
                for i in range(min(3, len(parts))):
                    self.modules.setdefault(".".join(parts[i:]), p)

    def tree(self, path: str) -> ast.Module | None:
        if path not in self._trees:
            try:
                self._trees[path] = ast.parse(self.files[path])
            except (SyntaxError, ValueError, KeyError):
                self._trees[path] = None
        return self._trees[path]

    def resolve_module(self, src: str, level: int, module: str | None) -> str | None:
        if level:
            base = src.split("/")[:-1]
            if src.endswith("/__init__.py"):
                pass
            base = base[: len(base) - (level - 1)] if level > 1 else base
            cand = ".".join(base + ([module] if module else []))
            for k in (cand, ".".join(cand.split(".")[1:])):
                if k in self.modules:
                    return self.modules[k]
            # fall through to suffix match for src/ layouts
            for k, v in self.modules.items():
                if module and k.endswith(module) and v.startswith("/".join(base)):
                    return v
            return None
        return self.modules.get(module or "")

    def _defs(self, path: str) -> dict[str, ast.AST]:
        tree = self.tree(path)
        out: dict[str, ast.AST] = {}
        if tree:
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    out[node.name] = node
                elif isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            out[t.id] = node
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    out[node.target.id] = node
        return out

    def _imports(self, path: str) -> dict[str, tuple[str, str]]:
        """local name -> (module path, original name) for internal `from x import y [as z]`."""
        tree = self.tree(path)
        out: dict[str, tuple[str, str]] = {}
        if not tree:
            return out
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                target = self.resolve_module(path, node.level, node.module)
                for alias in node.names:
                    if target:
                        out[alias.asname or alias.name] = (target, alias.name)
                    elif node.level == 0 and alias.name != "*":
                        pass
                    if not target and node.level:
                        # `from . import mod`
                        sub = self.resolve_module(path, node.level, ((node.module + ".") if node.module else "") + alias.name)
                        if sub:
                            out[alias.asname or alias.name] = (sub, "*module*")
        return out

    def exported_names(self, path: str) -> list[str]:
        tree = self.tree(path)
        if not tree:
            return []
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
                try:
                    return [str(x) for x in ast.literal_eval(node.value)]
                except Exception:
                    break
        names = [n for n in self._defs(path) if not n.startswith("_")]
        names += [n for n in self._imports(path) if not n.startswith("_") and n not in names]
        return names

    def describe(self, path: str, name: str, depth: int = 0) -> Any:
        if depth > 8:
            return {"kind": "unresolved"}
        defs = self._defs(path)
        if name in defs:
            node = defs[name]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return {"kind": "function", "sig": _sig(node)}
            if isinstance(node, ast.ClassDef):
                return self._class(path, node, depth)
            return {"kind": "const"}
        imp = self._imports(path).get(name)
        if imp:
            target, orig = imp
            if orig == "*module*":
                return {"kind": "module"}
            return self.describe(target, orig, depth + 1)
        return {"kind": "unresolved"}

    def _class(self, path: str, node: ast.ClassDef, depth: int) -> Any:
        methods: dict[str, str] = {}
        fields: set[str] = set()
        externals: list[str] = []
        for sub in node.body:
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and (not sub.name.startswith("_") or
                                                                           sub.name in ("__init__", "__call__", "__enter__", "__exit__")):
                methods.setdefault(sub.name, _sig(sub))
            elif isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name):
                fields.add(sub.target.id)
            elif isinstance(sub, ast.Assign):
                fields.update(t.id for t in sub.targets if isinstance(t, ast.Name) and not t.id.startswith("_"))
        imports = self._imports(path)
        defs = self._defs(path)
        for base in node.bases:
            bname = base.id if isinstance(base, ast.Name) else ast.unparse(base)
            sub_desc = None
            if isinstance(base, ast.Name):
                if bname in defs and isinstance(defs[bname], ast.ClassDef) and defs[bname] is not node:
                    sub_desc = self._class(path, defs[bname], depth + 1)  # type: ignore[arg-type]
                elif bname in imports and imports[bname][1] != "*module*":
                    d = self.describe(imports[bname][0], imports[bname][1], depth + 1)
                    sub_desc = d if d.get("kind") == "class" else None
            if sub_desc:
                for m, s in sub_desc["methods"].items():
                    methods.setdefault(m, s)
                fields |= set(sub_desc["fields"])
                externals += sub_desc["external_bases"]
            else:
                externals.append(bname)
        return {"kind": "class", "methods": methods, "fields": sorted(fields), "external_bases": sorted(set(externals))}

    def surface(self, path: str) -> Surface:
        return {n: self.describe(path, n) for n in self.exported_names(path)}


_TS_EXPORT = re.compile(
    r"^\s*export\s+(?P<default>default\s+)?(?:declare\s+)?(?P<decl>(?:async\s+)?function\*?\s+(?P<fn>[A-Za-z_$][\w$]*)[^{;]*"
    r"|(?:abstract\s+)?class\s+(?P<cls>[A-Za-z_$][\w$]*)[^{]*"
    r"|interface\s+(?P<iface>[A-Za-z_$][\w$]*)[^{]*"
    r"|type\s+(?P<type>[A-Za-z_$][\w$]*)[^=]*=[^;\n]*"
    r"|enum\s+(?P<enum>[A-Za-z_$][\w$]*)"
    r"|(?:const|let|var)\s+(?P<var>[A-Za-z_$][\w$]*)[^=\n]*)",
    re.M)
_TS_LIST = re.compile(r"export\s*\{([^}]*)\}(?:\s*from\s*['\"]([^'\"]+)['\"])?")
_TS_STAR = re.compile(r"export\s*\*\s*(?:as\s+(\w+)\s*)?from\s*['\"]([^'\"]+)['\"]")


def ts_surface(files: dict[str, str], path: str, depth: int = 0) -> Surface:
    text = files.get(path, "")
    out: Surface = {}
    for m in _TS_EXPORT.finditer(text):
        name = next((m.group(g) for g in ("fn", "cls", "iface", "type", "enum", "var") if m.group(g)), None)
        if m.group("default"):
            name = "default"
        if name:
            kind = ("function" if m.group("fn") else "class" if m.group("cls") else "type" if (m.group("type") or m.group("iface")) else "const")
            out[name] = {"kind": kind, "sig": re.sub(r"\s+", " ", m.group("decl")).strip()[:200]}
    for m in _TS_LIST.finditer(text):
        for part in m.group(1).split(","):
            part = part.strip()
            if not part:
                continue
            src, _, alias = part.partition(" as ")
            exported = (alias or src).strip()
            out.setdefault(exported, {"kind": "reexport", "sig": src.strip()})
    for m in _TS_STAR.finditer(text):
        target = _resolve_ts(files, path, m.group(2))
        if target and depth < 6 and not m.group(1):
            for k, v in ts_surface(files, target, depth + 1).items():
                out.setdefault(k, v)
    return out


def _resolve_ts(files: dict[str, str], src: str, raw: str) -> str | None:
    if not raw.startswith("."):
        return None
    cand = posixpath.normpath(posixpath.join(posixpath.dirname(src), raw))
    for opt in [cand] + [cand + e for e in (".ts", ".tsx", ".js", ".jsx")] + [f"{cand}/index{e}" for e in (".ts", ".tsx", ".js", ".jsx")]:
        if opt in files:
            return opt
    return None


def go_surface(files: dict[str, str], path: str) -> Surface:
    text = files.get(path, "")
    out: Surface = {}
    for m in re.finditer(r"^func\s+(?:\(([^)]*)\)\s*)?([A-Z]\w*)\s*(\([^{]*)", text, re.M):
        recv = (m.group(1) or "").split()
        key = f"{recv[-1].lstrip('*')}.{m.group(2)}" if recv else m.group(2)
        out[key] = {"kind": "function", "sig": re.sub(r"\s+", " ", m.group(3)).strip()}
    for m in re.finditer(r"^type\s+([A-Z]\w*)\s+(\w+)", text, re.M):
        out[m.group(1)] = {"kind": "type", "sig": m.group(2)}
    return out


def surface_of(files: dict[str, str], path: str) -> Surface | None:
    if path not in files:
        return None
    if path.endswith(".py"):
        return PySurface(files).surface(path)
    if path.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs")):
        return ts_surface(files, path)
    if path.endswith(".go"):
        return go_surface(files, path)
    return {}


def diff_surface(before: Surface, after: Surface | None) -> list[str]:
    """Human-readable breaking changes; additions are allowed."""
    if after is None:
        return ["module removed"]
    problems: list[str] = []
    for name, old in before.items():
        new = after.get(name)
        if new is None:
            problems.append(f"removed `{name}`")
        elif old != new:
            if old.get("kind") == "class" and new.get("kind") == "class":
                for m, sig in old["methods"].items():
                    if m not in new["methods"]:
                        problems.append(f"removed method `{name}.{m}`")
                    elif new["methods"][m] != sig:
                        problems.append(f"changed signature `{name}.{m}{sig}` -> `{name}.{m}{new['methods'][m]}`")
                for f in old["fields"]:
                    if f not in new["fields"]:
                        problems.append(f"removed field `{name}.{f}`")
                if old["external_bases"] != new["external_bases"]:
                    problems.append(f"changed bases of `{name}`")
            elif old.get("kind") == "function" and new.get("kind") == "function":
                problems.append(f"changed signature of `{name}`: {old['sig']} -> {new['sig']}")
            else:
                problems.append(f"changed `{name}`: {old.get('sig') or old.get('kind')} -> {new.get('sig') or new.get('kind')}")
    return problems
