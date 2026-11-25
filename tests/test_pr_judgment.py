"""What Claude is told when it reads the user's open PRs for what each needs from us (backend/github_api.py judge_prs),
whose detail goes to the PR's agent as its task.

backend/shared.py makes the app's real stores when it is imported (and asks Incus about the VMs), so a stand-in module
takes its place, with stand-ins for what judge_prs reads. Claude and GitHub are fakes: nothing reaches them, Incus or
DATA_DIR."""

import asyncio
import sys
import types
from types import SimpleNamespace

import pytest

# The user's open PR as pr_tracking has it, and its thread as the pop-up reads it.
PR = {
    "id": "owner/proj#40", "repo": "owner/proj", "mergeable": "yes", "checks": "passed", "failed_checks": [], "waiting_runs": 0,
    "labels": [], "head": {"sha": "c" * 40}, "head_at": "2026-11-20T10:00:00Z", "your_last_at": "2026-11-20T10:00:00Z", "issues": [],
}
THREAD = {
    "title": "Add the endpoint", "url": "https://github.com/owner/proj/pull/40", "draft": False, "base": "trunk",
    "body": "Adds it.", "hidden": 0,
    "timeline": [{"type": "comment", "at": "2026-11-21T10:00:00Z", "login": "lead", "role": "MEMBER", "body": "Please run make signoff."}],
}


@pytest.fixture
def github_api(monkeypatch):
    """backend/github_api.py with its stores stood in for, Claude's prompts kept in prompts."""
    shared = types.ModuleType("backend.shared")
    for name in ["agents", "explore", "github_account", "inbox", "issue_facts", "issue_tags", "issues", "jobs", "pr_tracking", "repo_signals", "repos", "your_repositories"]:
        setattr(shared, name, None)
    monkeypatch.setitem(sys.modules, "backend.shared", shared)
    from backend import github_api

    prompts = []

    async def judge(prompt, schema, effort, what=""):
        prompts.append(prompt)
        return {"prs": []}

    async def thread_details(thread_id):
        return THREAD

    monkeypatch.setattr(github_api, "judge", judge)
    monkeypatch.setattr(github_api, "thread_details", thread_details)
    monkeypatch.setattr(github_api, "github_account", SimpleNamespace(status=lambda: {"login": "sam-example"}))
    monkeypatch.setattr(github_api, "pr_tracking", SimpleNamespace(judgment_key=lambda pr, jobs: "key"))
    return SimpleNamespace(module=github_api, prompts=prompts)


def test_spiceai_16306_task_says_what_was_asked_in_the_projects_own_words(github_api):
    # "Run make signoff" (the project's own attestation script) went to the agent as a DCO sign-off on every commit,
    # which would have meant rewriting the maintainer's merge commits.
    asyncio.run(github_api.module.judge_prs([PR], [], {}))

    assert "Say what was asked in the words of whoever asked and of the project's own rules" in github_api.prompts[0]
    assert "a project's own sign-off (a script or check it runs) is no DCO Signed-off-by line" in github_api.prompts[0]
