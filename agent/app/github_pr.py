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


def open_pr(
    bug: Bug, node: dict[str, Any], settings: Settings | None = None, sandbox_label: str = NEBIUS_LABEL,
) -> str:
    settings = settings or load_settings()
    if not settings.github_token or not settings.github_repo:
        raise RuntimeError("GITHUB_TOKEN and GITHUB_REPO must be set to open pull requests")
    repo = Github(auth=Auth.Token(settings.github_token)).get_repo(settings.github_repo)
    base = repo.default_branch
    branch = f"patchloop/{bug['id']}-{int(time.time())}"
    repo.create_git_ref(f"refs/heads/{branch}", repo.get_branch(base).commit.sha)

    message = f"fix: {bug['title']}"
    try:
        current = repo.get_contents(bug["target"], ref=branch)
        repo.update_file(bug["target"], message, node["code"], current.sha, branch=branch)
    except UnknownObjectException:
        repo.create_file(bug["target"], message, node["code"], branch=branch)

    pr = repo.create_pull(title=message, body=pr_body(bug, node, sandbox_label), head=branch, base=base)
    return pr.html_url
