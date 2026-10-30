"""Command allow-list for `Workspace.exec` (and the worker `run` tool). Pure string logic, fail-closed.

A command is a chain of at most 4 steps joined by `&&`; each step is `[cd <relative dir> &&] <tool> <args>`.
Everything else is denied: pipes, `;`, `||`, backticks, `$(...)`, redirects (except a trailing `2>&1`), env
assignments, absolute/home/`..` paths, `sh -c`, inline code (`python -c`, `node -e`), network tools (curl, wget,
ssh, nc ...), privilege tools (sudo), environment dumps (env, printenv), VCS/container tools, `rm`, and anything
not on the allow-list.

Allowed (project tooling only): python -m pytest|unittest|ruff|mypy|bandit|pyflakes|compileall|pip(nebius only),
python <script.py>, pytest, ruff, mypy, bandit; node <script>, npm|pnpm|yarn install|ci|test|run|build|lint|add,
npx <known tool>, vitest, jest, tsc, eslint, prettier --check; go test|build|vet|mod|fmt; cargo test|build|check|
clippy|fmt; mvn test|compile|package|verify; make test|build|lint|check|all.
"""
from __future__ import annotations

import posixpath
import re
import shlex
from dataclasses import dataclass

MAX_STEPS = 4
MAX_CMD_CHARS = 1000


class ExecDenied(Exception):
    """The command is not on the allow-list; the message says why (safe to show to the model)."""


@dataclass(frozen=True)
class Step:
    argv: list[str]
    cwd: str = "."


PY_MODULES = {"pytest", "unittest", "ruff", "mypy", "bandit", "pyflakes", "compileall", "flake8", "black", "pip"}
NODE_PM = {"npm", "pnpm", "yarn"}
PM_SUBCOMMANDS = {"install", "i", "ci", "test", "t", "run", "run-script", "build", "lint", "add", "start"}
NPX_TOOLS = {"vitest", "jest", "tsc", "eslint", "prettier", "vite", "tsx", "ts-node", "mocha"}
MAKE_TARGETS = {"test", "tests", "build", "lint", "check", "all", "typecheck", "fmt-check"}
GO_SUB = {"test", "build", "vet", "mod", "fmt"}
GO_MOD_SUB = {"tidy", "download", "verify"}
CARGO_SUB = {"test", "build", "check", "clippy", "fmt"}
MVN_SUB = {"test", "compile", "package", "verify", "test-compile"}
DIRECT_TOOLS = {"pytest", "ruff", "mypy", "bandit", "vitest", "jest", "tsc", "eslint", "prettier", "flake8"}
DENIED_FLAGS = {"-g", "--global", "--prefix", "--userconfig", "--globalconfig", "--registry", "--settings",
                "--config-settings", "--cache", "--unsafe-perm", "--eval", "--eval-file", "--exec", "--require",
                "--import", "--loader", "--experimental-loader"}
TOOL_DENIED_FLAGS = {"mvn": {"-s", "-gs", "-P"}, "mvnw": {"-s", "-gs", "-P"}, "node": {"-e", "-p", "-r"},
                     "npm": {"-C"}, "pnpm": {"-C"}, "yarn": {"--cwd"}, "go": {"-exec", "-toolexec", "-overlay"},
                     "cargo": {"--config", "--manifest-path"}}
SHELL_BAD = re.compile(r"[|;`<>\n\r\\]|\$\(|\$\{|(?<!&)&(?!&)|&&&")
BLOCKED_TOOLS = {"curl", "wget", "ssh", "scp", "sftp", "nc", "ncat", "netcat", "telnet", "ftp", "rsync",
                 "sudo", "su", "doas", "env", "printenv", "set", "export", "sh", "bash", "zsh", "dash", "eval",
                 "exec", "rm", "chmod", "chown", "dd", "mkfs", "mount", "kill", "pkill", "git", "docker", "xargs",
                 "find", "cat", "nohup", "setsid", "timeout", "time"}


def _check_arg(arg: str) -> None:
    if arg.startswith(("/", "~")) or re.match(r"^[A-Za-z]:[\\/]", arg):
        raise ExecDenied(f"absolute or home path argument not allowed: {arg[:60]!r}")
    if "=" in arg and arg.split("=", 1)[1].startswith(("/", "~")):
        raise ExecDenied(f"absolute path in option value not allowed: {arg[:60]!r}")
    if ".." in arg.split("/") or "/../" in arg or arg.endswith("/.."):
        raise ExecDenied(f"path traversal not allowed: {arg[:60]!r}")
    if "\x00" in arg:
        raise ExecDenied("NUL in argument")


def _check_flags(tool: str, args: list[str]) -> None:
    for a in args:
        if a.startswith("-") and (a.split("=", 1)[0] in DENIED_FLAGS or a.split("=", 1)[0] in TOOL_DENIED_FLAGS.get(tool, ())):
            raise ExecDenied(f"flag {a.split('=', 1)[0]} is not allowed for {tool}")


def _pip_ok(args: list[str], isolation: str) -> None:
    if isolation != "nebius":
        raise ExecDenied("pip is only allowed inside a nebius sandbox (it would modify the host)")
    if not args or args[0] not in {"install", "list", "show", "check"}:
        raise ExecDenied("only pip install|list|show|check is allowed")


def _check_step(argv: list[str], isolation: str) -> None:
    tool = argv[0]
    if posixpath.basename(tool) != tool:
        raise ExecDenied(f"tool must be a bare name, not a path: {tool[:60]!r}")
    if tool in BLOCKED_TOOLS:
        raise ExecDenied(f"{tool} is not allowed (network, shell, privilege, VCS or environment tool)")
    if "=" in tool:
        raise ExecDenied("environment assignments before a command are not allowed")
    args = argv[1:]
    for a in args:
        _check_arg(a)
    _check_flags(tool, args)
    if tool in ("python", "python3"):
        if not args:
            raise ExecDenied("interactive python is not allowed")
        if args[0] == "-m":
            mod = args[1] if len(args) > 1 else ""
            if mod not in PY_MODULES:
                raise ExecDenied(f"python -m {mod or '?'} is not on the allow-list")
            if mod == "pip":
                _pip_ok(args[2:], isolation)
        elif args[0].startswith("-"):
            raise ExecDenied(f"python option {args[0]} is not allowed (write a script file instead of inline code)")
        elif not args[0].endswith(".py"):
            raise ExecDenied("python may only run a .py file or -m <module>")
    elif tool in ("pip", "pip3"):
        _pip_ok(args, isolation)
    elif tool == "node":
        if not args or args[0].startswith("-") or not args[0].endswith((".js", ".mjs", ".cjs")):
            raise ExecDenied("node may only run a script file (no inline code, no flags first)")
    elif tool in NODE_PM:
        sub = args[0] if args else ""
        if sub not in PM_SUBCOMMANDS:
            raise ExecDenied(f"{tool} {sub or '?'} is not allowed (install|ci|test|run|build|lint|add)")
        if sub in ("run", "run-script") and (len(args) < 2 or args[1].startswith("-")):
            raise ExecDenied(f"{tool} run needs a script name")
    elif tool == "npx":
        rest = [a for a in args if not a.startswith("-")]
        if not rest or rest[0] not in NPX_TOOLS:
            raise ExecDenied(f"npx may only run: {', '.join(sorted(NPX_TOOLS))}")
        if any(a in ("-p", "--package", "--call", "-c") for a in args):
            raise ExecDenied("npx --package/--call is not allowed")
    elif tool == "go":
        sub = args[0] if args else ""
        if sub not in GO_SUB:
            raise ExecDenied(f"go {sub or '?'} is not allowed (test|build|vet|mod|fmt)")
        if sub == "mod" and (len(args) < 2 or args[1] not in GO_MOD_SUB):
            raise ExecDenied("go mod: only tidy|download|verify")
    elif tool == "cargo":
        if not args or args[0] not in CARGO_SUB:
            raise ExecDenied(f"cargo {args[0] if args else '?'} is not allowed")
    elif tool in ("mvn", "mvnw"):
        goals = [a for a in args if not a.startswith("-")]
        if not goals or any(g not in MVN_SUB for g in goals):
            raise ExecDenied("mvn: only test|compile|package|verify|test-compile")
    elif tool == "make":
        targets = [a for a in args if not a.startswith("-")]
        if not targets or any(t not in MAKE_TARGETS for t in targets):
            raise ExecDenied(f"make: only targets {sorted(MAKE_TARGETS)}")
        if any("=" in a for a in args):
            raise ExecDenied("make variable overrides are not allowed")
    elif tool == "prettier":
        if "--check" not in args:
            raise ExecDenied("prettier is only allowed with --check")
    elif tool in DIRECT_TOOLS:
        if tool == "ruff" and (not args or args[0] not in {"check", "format"}):
            raise ExecDenied("ruff: only check|format")
    else:
        raise ExecDenied(f"{tool} is not on the allow-list")


def parse_command(cmd: str, isolation: str = "local") -> list[Step]:
    """Validate `cmd` and return the steps to run in order. Raises ExecDenied."""
    if not isinstance(cmd, str) or not cmd.strip():
        raise ExecDenied("empty command")
    if len(cmd) > MAX_CMD_CHARS:
        raise ExecDenied("command too long")
    text = cmd.strip()
    if text.endswith("2>&1"):
        text = text[:-4].strip()
    if SHELL_BAD.search(text):
        raise ExecDenied("shell operators (pipes, ;, ||, redirects, backticks, $(), backslashes) are not allowed")
    steps: list[Step] = []
    cwd = "."
    parts = [p.strip() for p in text.split("&&")]
    if len(parts) > MAX_STEPS or any(not p for p in parts):
        raise ExecDenied(f"at most {MAX_STEPS} steps joined by && (no empty steps)")
    for part in parts:
        try:
            argv = shlex.split(part)
        except ValueError as exc:
            raise ExecDenied(f"unparseable command: {exc}") from None
        if not argv:
            raise ExecDenied("empty step")
        if argv[0] == "cd":
            if len(argv) != 2:
                raise ExecDenied("cd takes exactly one relative directory")
            _check_arg(argv[1])
            cwd = posixpath.normpath(posixpath.join(cwd, argv[1]))
            continue
        _check_step(argv, isolation)
        steps.append(Step(argv, cwd))
    if not steps:
        raise ExecDenied("no command to run")
    return steps


def check_command(cmd: str, isolation: str = "local") -> str | None:
    """None when allowed, otherwise the denial reason."""
    try:
        parse_command(cmd, isolation)
    except ExecDenied as exc:
        return str(exc)
    return None


def is_install(step: Step) -> bool:
    """Steps that change the environment (dependencies) rather than the repo: Nebius persists their result."""
    a = step.argv
    if a[0] in NODE_PM and len(a) > 1 and a[1] in {"install", "i", "ci", "add"}:
        return True
    if a[0] in ("pip", "pip3") or a[:3] in (["python", "-m", "pip"], ["python3", "-m", "pip"]):
        return len(a) > 1
    return a[:3] == ["go", "mod", "download"] or a[:2] == ["go", "mod"]
