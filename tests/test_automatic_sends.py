"""What the app does with a draft its repo's Level of automation lets go without the user (backend/repo_automation_api.py
act_on_drafts): one on GitHub already is approved, never sent again, and one that can never go as drafted goes back to
its agent.

backend/shared.py makes the app's real stores when it is imported (and asks Incus about the VMs), so a stand-in module
takes its place: the real Inbox and Jobs in pytest's temporary folder, an Agents that keeps the decisions, and a GitHub
account and issue reads that answer from the test. Nothing reaches GitHub, Claude, Incus or DATA_DIR."""

import asyncio
import json
import sys
import types
from types import SimpleNamespace

import pytest

from github_searcher import inbox as inbox_module
from github_searcher import jobs as jobs_module
from github_searcher.github_account import SendBackError
from github_searcher.inbox import Inbox
from github_searcher.jobs import Jobs

PR = "owner/proj#40"


@pytest.fixture
def automation(tmp_path, monkeypatch):
    """repo_automation_api with owner/proj's drafts let go (comments, PRs, edits), no PR of the user's open anywhere, and
    what the test puts in: decided (Agents.decide's calls), sent (the drafts send() got) and send_fails (what send()
    raises)."""
    shared = types.ModuleType("backend.shared")
    for name in ["agents", "explore", "github_account", "inbox", "issue_facts", "issue_tags", "issues", "jobs", "pr_tracking", "repo_signals", "repos"]:
        setattr(shared, name, None)
    monkeypatch.setitem(sys.modules, "backend.shared", shared)
    from backend import repo_automation_api

    monkeypatch.setattr(jobs_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(inbox_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(inbox_module, "ACTIONS_FILE", tmp_path / "actions.json")
    inbox = Inbox()
    state = SimpleNamespace(decided=[], sent=[], send_fails=None, inbox=inbox, jobs=Jobs(), module=repo_automation_api)

    def decide(draft_id, decision, reply="", answered_by="user"):
        state.decided.append((draft_id, decision, reply, answered_by))
        inbox.decide(draft_id, decision, reply, answered_by)

    def send(draft_id):
        if state.send_fails is not None:
            raise state.send_fails
        state.sent.append(draft_id)
        return inbox.mark_sent(draft_id, {"kind": "pr", "url": "https://github.com/owner/proj/pull/41"})

    settings = tmp_path / "repo_automation.json"
    settings.write_text(json.dumps({"owner/proj": {"questions": False, "comments": True, "pull_requests": True}}))
    monkeypatch.setattr(repo_automation_api, "SETTINGS_FILE", settings)
    monkeypatch.setattr(repo_automation_api, "ISSUE_SETTINGS_FILE", tmp_path / "issue_automation.json")
    monkeypatch.setattr(repo_automation_api, "DASHBOARD_AUTOMATION_FILE", tmp_path / "automation.json")
    monkeypatch.setattr(repo_automation_api, "failed_at", {})
    monkeypatch.setattr(repo_automation_api, "inbox", inbox)
    monkeypatch.setattr(repo_automation_api, "jobs", state.jobs)
    monkeypatch.setattr(repo_automation_api, "agents", SimpleNamespace(decide=decide))
    monkeypatch.setattr(repo_automation_api, "github_account", SimpleNamespace(send=send, status=lambda: {"login": "sam-example"}))
    monkeypatch.setattr(repo_automation_api, "repos", SimpleNamespace(archived=lambda: []))
    monkeypatch.setattr(repo_automation_api, "pr_tracking", SimpleNamespace(summary=lambda: {"items": []}))
    return state


def test_openclaw_204737_draft_on_github_already_is_approved_not_sent_again(automation):
    # Its send was cut off after GitHub opened the PR: every try after said "It is on GitHub already", and it stayed.
    draft = automation.inbox.create("comment", "agent-1", "Comment on owner/proj#40", "Done.", repo="owner/proj", target=PR)
    automation.inbox.mark_sent(draft["id"], {"kind": "comment", "url": "https://github.com/owner/proj/pull/40#issuecomment-1"})

    asyncio.run(automation.module.act_on_drafts())

    assert automation.decided == [(draft["id"], "approved", "", "user")]
    assert automation.sent == []


def test_amber_1199_edit_whose_text_changed_goes_back_to_its_agent(automation):
    # Tried again every ten minutes for good, while its agent never heard it had to draft it again.
    draft = automation.inbox.create("edit", "agent-1", "fix(compiler): reject builtin keywords", "New text.", repo="owner/proj", target=PR)
    automation.send_fails = SendBackError("Its title or description changed since the agent drafted this: Redraft, so the agent works on the text as it is now.")

    asyncio.run(automation.module.act_on_drafts())

    assert automation.decided == [(draft["id"], "rejected", str(automation.send_fails), "automation")]
    assert draft["id"] not in automation.module.failed_at

