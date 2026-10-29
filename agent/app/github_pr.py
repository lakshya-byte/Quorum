"""Open a pull request with the winning fix."""
from __future__ import annotations

import time
from typing import Any

from github import Auth, Github
from github.GithubException import UnknownObjectException

from app.bugs import Bug
from app.config import Settings, load_settings

OUTPUT_TAIL = 1200
NEBIUS_LABEL = "an isolated Nebius Sandbox"


def pr_body(bug: Bug, node: dict[str, Any], sandbox_label: str = NEBIUS_LABEL) -> str:
    proof = (
        f"{node['passed']}/{node['total']} tests pass in {sandbox_label} "
        f"(candidate #{node['id']}, round {node['depth']})"
    )
    tail = node.get("output", "")[-OUTPUT_TAIL:]
    return (
        f"## Issue\n{bug['issue']}\n\n"
        f"## Winning idea\n{node['idea']}\n\n"
        f"## Proof\n{proof}\n\n"
        f"## Test output\n```\n{tail}\n```\n\n"
        "_Opened by PatchLoop._\n"
    )


def draft_body(bug: Bug, node: dict[str, Any], draft: dict[str, Any], sandbox_label: str) -> str:
    """Reviewer-written body (already through the output guard) + the deterministic proof section."""
    return (
        f"{draft['body']}\n\n## Risk\n{draft['risk']}\n\n---\n{pr_body(bug, node, sandbox_label)}"
    )


def open_pr(
    bug: Bug, node: dict[str, Any], settings: Settings | None = None, sandbox_label: str = NEBIUS_LABEL,
    draft: dict[str, Any] | None = None,
) -> str:
    """Open a PR from a fresh patchloop/* branch. Agents never push to the default branch; a human closes the loop."""
    settings = settings or load_settings()
    if not settings.github_token or not settings.github_repo:
        raise RuntimeError("GITHUB_TOKEN and GITHUB_REPO must be set to open pull requests")
    repo = Github(auth=Auth.Token(settings.github_token)).get_repo(settings.github_repo)
    base = repo.default_branch
    branch = f"patchloop/{bug['id']}-{int(time.time())}"
    if branch == base or not branch.startswith("patchloop/"):
        raise RuntimeError("refusing to write to the default branch")
    repo.create_git_ref(f"refs/heads/{branch}", repo.get_branch(base).commit.sha)

    message = f"fix: {bug['title']}"
    title = (draft or {}).get("title") or message
    try:
        current = repo.get_contents(bug["target"], ref=branch)
        repo.update_file(bug["target"], message, node["code"], current.sha, branch=branch)
    except UnknownObjectException:
        repo.create_file(bug["target"], message, node["code"], branch=branch)

    body = draft_body(bug, node, draft, sandbox_label) if draft else pr_body(bug, node, sandbox_label)
    pr = repo.create_pull(title=title, body=body, head=branch, base=base)
    return pr.html_url
