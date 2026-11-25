"""What the app watches on the issues agents work on (backend/issues_api.py keep_facts): an issue closed on GitHub while
an agent works on it is told to that agent at once.

backend/shared.py makes the app's real stores when it is imported (and asks Incus about the VMs), so a stand-in module
takes its place, and the stores are stand-ins with what each test puts in. Nothing reaches GitHub, Claude, Incus or
DATA_DIR. keep_facts runs as long as the backend; one round of it runs here, ended at its sleep."""

import asyncio
import sys
import types
from types import SimpleNamespace

import pytest


class RoundOver(Exception):
    pass


@pytest.fixture
def watch(monkeypatch):
    """issues_api with one issue on the board, owner/proj#1760, open when last read; an agent has a job on it. What
    GitHub says of it now is in state.now; Agents.issue_fixed's calls are kept in state.told."""
    shared = types.ModuleType("backend.shared")
    for name in ["agents", "explore", "github_account", "inbox", "issue_facts", "issue_tags", "issues", "jobs", "pr_tracking", "repo_signals", "repos"]:
        setattr(shared, name, None)
    monkeypatch.setitem(sys.modules, "backend.shared", shared)
    from backend import issues_api

    state = SimpleNamespace(told=[], now="OPEN", module=issues_api)
    facts = {"owner/proj#1760": {"state": "OPEN"}}

    def refresh(issue_id):
        facts[issue_id] = {"state": state.now}
        return facts[issue_id]

    async def sleep(seconds):
        raise RoundOver()

    job = {"id": "job_a1b2c3", "issue": "owner/proj#1760", "status": "working"}
    monkeypatch.setattr(issues_api, "issues", SimpleNamespace(items=lambda: [{"id": "owner/proj#1760"}]))
    monkeypatch.setattr(issues_api, "issue_facts", SimpleNamespace(all=lambda: dict(facts), forget=lambda ids: None, refresh=refresh))
    monkeypatch.setattr(issues_api, "jobs", SimpleNamespace(list=lambda: [job]))
    monkeypatch.setattr(issues_api, "agents", SimpleNamespace(issue_fixed=lambda issue_id, why: state.told.append((issue_id, why))))
    monkeypatch.setattr(issues_api.asyncio, "sleep", sleep)
    return state


def test_bulwarkmail_1760_issue_closed_while_an_agent_works_on_it_is_told(watch):
    watch.now = "CLOSED"

    with pytest.raises(RoundOver):
        asyncio.run(watch.module.keep_facts())

    assert watch.told == [("owner/proj#1760", "was closed")]


def test_issue_still_open_is_no_news(watch):
    with pytest.raises(RoundOver):
        asyncio.run(watch.module.keep_facts())

    assert watch.told == []
