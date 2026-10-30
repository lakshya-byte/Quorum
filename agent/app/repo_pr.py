"""Multi-file pull requests through the GitHub git-data API (blobs -> tree -> commit -> ref -> pull request).

Rules, enforced in code: only `patchloop/*` branches are ever created or updated; the base branch is never
written to; the token lives only inside the client object and is redacted from every error message.
The service has no call that closes the loop on a PR: a human reviews and completes it on GitHub.
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Protocol

import httpx

from app.policy import path_violation
from app.repo_eval import slugify

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
BRANCH_PREFIX = "patchloop/"
OPENED_BY = "Opened by PatchLoop — a human must review and merge."
TEST_TAIL = 1200


class PRError(Exception):
    """A PR failure safe to show to users (never contains the token)."""


class GitHubAPI(Protocol):
    async def get_default_branch(self, repo: str) -> str: ...
    async def get_ref_sha(self, repo: str, branch: str) -> str: ...
    async def get_commit_tree(self, repo: str, commit_sha: str) -> str: ...
    async def create_blob(self, repo: str, content: str) -> str: ...
    async def create_tree(self, repo: str, base_tree: str, entries: list[dict[str, str]]) -> str: ...
    async def create_commit(self, repo: str, message: str, tree: str, parents: list[str]) -> str: ...
    async def create_ref(self, repo: str, ref: str, sha: str) -> None: ...
    async def update_ref(self, repo: str, branch: str, sha: str) -> None: ...
    async def create_pull(self, repo: str, title: str, body: str, head: str, base: str) -> dict[str, Any]: ...


def redact(text: str, token: str) -> str:
    return text.replace(token, "***") if token else text


def assert_patchloop_branch(branch: str) -> None:
    if not branch.startswith(BRANCH_PREFIX) or len(branch) <= len(BRANCH_PREFIX) or ".." in branch \
            or any(c in branch for c in " ~^:?*[\\\x00"):
        raise PRError("refusing to write to a branch that does not start with patchloop/")


class HttpGitHub:
    """GitHub REST client (httpx). Endpoints follow the official git-data API docs."""

    def __init__(self, token: str, client: httpx.AsyncClient | None = None) -> None:
        self._token = token
        self._client = client
        self._own = client is None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "patchloop-agent"}

    async def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
        try:
            resp = await self._client.request(method, f"{GITHUB_API}{path}", headers=self._headers(), json=body)
        except httpx.HTTPError as exc:
            raise PRError(f"GitHub request failed: {type(exc).__name__}") from None
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = str(resp.json().get("message", ""))[:200]
            except ValueError:
                pass
            raise PRError(redact(f"GitHub {method} {path.split('?')[0]} -> HTTP {resp.status_code} {detail}".strip(),
                                 self._token))
        return resp.json() if resp.content else {}

    async def aclose(self) -> None:
        if self._client is not None and self._own:
            await self._client.aclose()

    async def get_default_branch(self, repo: str) -> str:
        return (await self._call("GET", f"/repos/{repo}"))["default_branch"]

    async def get_ref_sha(self, repo: str, branch: str) -> str:
        return (await self._call("GET", f"/repos/{repo}/git/ref/heads/{branch}"))["object"]["sha"]

    async def get_commit_tree(self, repo: str, commit_sha: str) -> str:
        return (await self._call("GET", f"/repos/{repo}/git/commits/{commit_sha}"))["tree"]["sha"]

    async def create_blob(self, repo: str, content: str) -> str:
        return (await self._call("POST", f"/repos/{repo}/git/blobs", {"content": content, "encoding": "utf-8"}))["sha"]

    async def create_tree(self, repo: str, base_tree: str, entries: list[dict[str, str]]) -> str:
        return (await self._call("POST", f"/repos/{repo}/git/trees", {"base_tree": base_tree, "tree": entries}))["sha"]

    async def create_commit(self, repo: str, message: str, tree: str, parents: list[str]) -> str:
        return (await self._call("POST", f"/repos/{repo}/git/commits",
                                 {"message": message, "tree": tree, "parents": parents}))["sha"]

    async def create_ref(self, repo: str, ref: str, sha: str) -> None:
        assert_patchloop_branch(ref.removeprefix("refs/heads/"))
        await self._call("POST", f"/repos/{repo}/git/refs", {"ref": ref, "sha": sha})

    async def update_ref(self, repo: str, branch: str, sha: str) -> None:
        assert_patchloop_branch(branch)
        await self._call("PATCH", f"/repos/{repo}/git/refs/heads/{branch}", {"sha": sha, "force": False})

    async def create_pull(self, repo: str, title: str, body: str, head: str, base: str) -> dict[str, Any]:
        return await self._call("POST", f"/repos/{repo}/pulls",
                                {"title": title, "body": body, "head": head, "base": base})


def validate_files(files: dict[str, str]) -> None:
    if not files:
        raise PRError("nothing to commit")
    for path in files:
        bad = path_violation(path)
        if bad:
            raise PRError(f"refusing unsafe path: {bad}")


def branch_name(task: str, now: int | None = None) -> str:
    return f"{BRANCH_PREFIX}{slugify(task)}-{int(now if now is not None else time.time())}"


async def _commit_files(api: GitHubAPI, repo: str, parent_sha: str, files: dict[str, str], message: str) -> str:
    base_tree = await api.get_commit_tree(repo, parent_sha)
    entries = []
    for path in sorted(files):
        entries.append({"path": path, "mode": "100644", "type": "blob", "sha": await api.create_blob(repo, files[path])})
    tree = await api.create_tree(repo, base_tree, entries)
    return await api.create_commit(repo, message, tree, [parent_sha])


async def _commit_changes(api: GitHubAPI, repo: str, parent_sha: str, files: dict[str, str | None], message: str) -> str:
    """Like _commit_files but `None` deletes the path (git-data tree entries with a null sha)."""
    base_tree = await api.get_commit_tree(repo, parent_sha)
    entries: list[dict[str, Any]] = []
    for path in sorted(files):
        text = files[path]
        sha = None if text is None else await api.create_blob(repo, text)
        entries.append({"path": path, "mode": "100644", "type": "blob", "sha": sha})
    tree = await api.create_tree(repo, base_tree, entries)  # type: ignore[arg-type]
    return await api.create_commit(repo, message, tree, [parent_sha])


async def open_repo_pr_commits(
    api: GitHubAPI, repo: str, base: str, commits: list[dict[str, Any]], title: str, body: str, task: str,
    now: int | None = None,
) -> dict[str, Any]:
    """Swarm PRs: ONE COMMIT PER UNIT (in merge order) on a single new patchloop/* branch, then the PR.
    `commits` = [{"title": str, "files": {path: text | None}}]. Never touches the base branch; no merge call exists."""
    commits = [c for c in commits if c.get("files")]
    if not commits:
        raise PRError("nothing to commit")
    for c in commits:
        validate_files({p: (t if t is not None else "") for p, t in c["files"].items()})
    branch = branch_name(task, now)
    assert_patchloop_branch(branch)
    base = base or await api.get_default_branch(repo)
    if branch == base:
        raise PRError("refusing to write to the base branch")
    parent = await api.get_ref_sha(repo, base)
    for c in commits:
        parent = await _commit_changes(api, repo, parent, c["files"], str(c.get("title") or "PatchLoop change")[:200])
    await api.create_ref(repo, f"refs/heads/{branch}", parent)
    pr = await api.create_pull(repo, title[:250], body, branch, base)
    return {"url": pr["html_url"], "number": int(pr["number"]), "branch": branch, "fake": False, "updated": False,
            "commits": len(commits)}


async def open_repo_pr(
    api: GitHubAPI, repo: str, base: str, files: dict[str, str], title: str, body: str, task: str,
    now: int | None = None,
) -> dict[str, Any]:
    """Branch from `base`, commit all files in ONE commit on a new patchloop/* branch, open the PR."""
    validate_files(files)
    branch = branch_name(task, now)
    assert_patchloop_branch(branch)
    base = base or await api.get_default_branch(repo)
    if branch == base:
        raise PRError("refusing to write to the base branch")
    base_sha = await api.get_ref_sha(repo, base)
    commit = await _commit_files(api, repo, base_sha, files, title[:200])
    await api.create_ref(repo, f"refs/heads/{branch}", commit)
    pr = await api.create_pull(repo, title[:250], body, branch, base)
    return {"url": pr["html_url"], "number": int(pr["number"]), "branch": branch, "fake": False, "updated": False}


async def push_followup(
    api: GitHubAPI, repo: str, branch: str, pr_number: int, files: dict[str, str], message: str,
    pr_url: str = "",
) -> dict[str, Any]:
    """ONE new commit on the SAME patchloop/* branch. Never a new branch, never a new PR."""
    assert_patchloop_branch(branch)
    validate_files(files)
    head = await api.get_ref_sha(repo, branch)
    commit = await _commit_files(api, repo, head, files, message[:200])
    await api.update_ref(repo, branch, commit)
    return {"url": pr_url, "number": pr_number, "branch": branch, "fake": False, "updated": True}


def fake_pr(full_name: str, task: str, run_id: str, followup: dict[str, Any] | None = None,
            now: int | None = None) -> dict[str, Any]:
    """Offline PR for demo repos: nothing leaves the machine."""
    name = full_name.split("/", 1)[-1]
    if followup:
        number = int(followup.get("pr_number") or 1)
        return {"url": f"https://github.com/demo/{name}/pull/{number}", "number": number,
                "branch": followup.get("pr_branch") or branch_name(task, now), "fake": True, "updated": True}
    number = 1 + int(hashlib.sha256(run_id.encode()).hexdigest()[:6], 16) % 98
    return {"url": f"https://github.com/demo/{name}/pull/{number}", "number": number,
            "branch": branch_name(task, now), "fake": True, "updated": False}


def _tail(text: str, n: int = TEST_TAIL) -> str:
    return (text or "")[-n:]


def repo_pr_body(
    bug: dict[str, Any], node: dict[str, Any], *, cause: str = "", draft: dict[str, Any] | None = None,
    label: str = "an isolated sandbox", run_url: str = "", issue_ref: int | None = None,
    safety: dict[str, Any] | None = None, include_untrusted: bool = True,
) -> str:
    """PR body: Cause, What changed (per file), Tests, Security, run link, risk. `include_untrusted=False` is the
    fallback when the output guard rejected the model-written/task-derived text."""
    files = node.get("files") or {}
    changed = "\n".join(f"- `{p}`" for p in sorted(files)) or "- (no files)"
    repro = bug.get("reproducer_path") or ""
    tests = (f"{node['passed']}/{node['total']} tests pass in {label} (candidate #{node['id']}, round {node['depth']}).\n"
             + (f"Reproducer: `{repro}` fails on the original code and passes now.\n" if repro
                else "No failing reproducer could be written; the existing suite was used as the judge.\n"))
    sec = node.get("security") or {}
    pol = node.get("policy") or {}
    security = (f"- Policy gate: {'pass' if pol.get('ok', True) else 'blocked'} (paths validated, tests untouched)\n"
                f"- Bandit: {'no new medium/high findings' if sec.get('ok', True) else 'new findings'}"
                f"{'' if sec.get('scanned') else ' (scanner not run for these files)'}")
    if safety:
        security += f"\n- Input guard: {safety.get('guard', {}).get('input', 'n/a')}"
    parts = []
    if include_untrusted:
        parts.append(f"## Task\n{bug['issue'][:1500]}")
    parts.append(f"## Cause\n{(cause or 'See the diff.')[:600]}")
    parts.append(f"## What changed\n{changed}\n\n{node.get('idea', '')}")
    if include_untrusted and draft:
        parts.append(f"{draft['body']}\n\n## Risk\n{draft['risk']}")
    parts.append(f"## Tests\n{tests}\n```\n{_tail(node.get('output', ''))}\n```")
    parts.append(f"## Security\n{security}")
    if run_url:
        parts.append(f"## Run\n{run_url}")
    if issue_ref:
        parts.append(f"Fixes #{int(issue_ref)}")
    parts.append(f"_{OPENED_BY}_")
    return "\n\n".join(parts) + "\n"


def _cell(text: Any, n: int = 140) -> str:
    return " ".join(str(text or "").replace("|", "/").split())[:n]


def swarm_pr_body(data: dict[str, Any], *, task: str, run_url: str = "", issue_ref: int | None = None,
                  include_untrusted: bool = True) -> str:
    """PR body of a swarm run: plan, criteria table, per-unit summary, advisory notes, honest caveats, run link.
    `data` is the run's swarm result (engine ctx.result). `include_untrusted=False` drops the user's task text."""
    plan = data.get("plan") or {}
    rows = data.get("criteria_rows") or []
    outcome = data.get("outcome", "")
    parts = []
    if include_untrusted:
        parts.append(f"## Task\n{task[:1500]}")
    parts.append(f"## Plan\nType: **{data.get('task_type', plan.get('task_type', ''))}** "
                 f"({plan.get('task_type_source', 'auto')}). Outcome: **{outcome}**.\n\n{_cell(plan.get('summary'), 600)}")
    if rows:
        table = ["| Criterion | Kind | Gate | Result | Detail |", "|---|---|---|---|---|"]
        for r in rows:
            table.append(f"| {_cell(r['criterion_id'], 40)} | {r['kind']} | {'hard' if r['hard'] else 'advisory'} | "
                         f"{r['status']} | {_cell(r.get('detail'))} |")
        parts.append("## Verification\n" + "\n".join(table))
    units = data.get("commits") or []
    summaries = data.get("unit_summaries") or {}
    if units:
        lines = [f"- **{_cell(c.get('title') or c.get('unit_id'), 80)}** (`{c.get('unit_id')}`): "
                 f"{_cell(summaries.get(c.get('unit_id'), c.get('summary')), 200)} "
                 f"[{', '.join('`' + p + '`' for p in sorted(c.get('files') or {})[:6])}]" for c in units]
        parts.append("## Changes (one commit per unit)\n" + "\n".join(lines))
    adv = data.get("advisory") or []
    if adv:
        parts.append("## Advisory notes (not gating)\n" + "\n".join(
            f"- {a['kind']} ({a['id']}): score {a.get('score')} - {_cell(a.get('rationale'), 200)}" for a in adv))
    notes = [*(data.get("reasons") or []), *(data.get("plan_notes") or [])]
    if outcome == "partial" or notes:
        parts.append("## Caveats\n" + ("\n".join(f"- {_cell(n, 220)}" for n in notes[:10]) or "- (none)")
                     + ("\n\nThis outcome is **partial**: review the caveats before merging." if outcome == "partial" else ""))
    parts.append("## Security\n- Path policy and secret scan are enforced in code on every write and on the final diff; "
                 "workers only ran in an isolated sandbox with an allow-listed command set.")
    if run_url:
        parts.append(f"## Run\n{run_url}")
    if issue_ref:
        parts.append(f"Fixes #{int(issue_ref)}")
    parts.append(f"_{OPENED_BY}_")
    return "\n\n".join(parts) + "\n"
