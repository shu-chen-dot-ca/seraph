"""The rules that tie agents to their jobs, the VMs and the news on GitHub (github_searcher/agents.py): which VM an agent may
pick and what it is told when none takes agents.

The Agents manager is built bare (Agents.__init__ would start real stores): the real Jobs and Inbox in pytest's temporary
folder (never DATA_DIR), one agent, agent-1, and VMs as stand-ins. Nothing reaches GitHub, Claude or a VM, and no agent
runs a turn: what an agent is told stays in its pending messages."""

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from github_searcher import agents as agents_module
from github_searcher import inbox as inbox_module
from github_searcher import jobs as jobs_module
from github_searcher.agents import Agents
from github_searcher.inbox import Inbox
from github_searcher.jobs import Jobs


def vm(name, status="running", suspended=False, graceful_shutdown=False):
    """A VM as Agents reads it from sandbox/vms.py."""
    return SimpleNamespace(name=name, status=status, suspended=suspended, graceful_shutdown=graceful_shutdown, runs=[], desktops={})


@pytest.fixture
def agents(tmp_path, monkeypatch):
    """Agents with agent-1 (no target VM, in no VM's line) and vm1, which takes agents; the test changes vms. Records are
    never written."""
    monkeypatch.setattr(jobs_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(jobs_module, "EVIDENCE_DIR", tmp_path / "evidence")
    monkeypatch.setattr(inbox_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(inbox_module, "ACTIONS_FILE", tmp_path / "actions.json")
    manager = Agents.__new__(Agents)
    manager.jobs = Jobs()
    manager.inbox = Inbox()
    manager.vms_list = [vm("vm1")]
    manager.vms = SimpleNamespace(list=lambda: list(manager.vms_list))
    manager.queue = SimpleNamespace(place=lambda agent_id: (None, None))
    record = {"id": "agent-1", "name": "agent-1", "target_vm": None, "archived_at": None, "role": None}
    manager.agents = {"agent-1": SimpleNamespace(id="agent-1", name="agent-1", record=record, busy=False, stopped=False, history=[])}
    manager.pending = {"agent-1": []}
    manager.wake = {"agent-1": asyncio.Event()}
    manager.loop_thread = threading.get_ident()
    manager.version = 0
    manager.waiting_for_vm = set()
    manager.waiting_for_run = {}
    manager.save = lambda agent: None
    return manager


# Picking a VM


def test_lance_11091_suspended_vm_with_no_other_says_to_wait_for_one(agents):
    # vm1 was the only VM and suspended: "pick another VM" had none to pick, and both rebase jobs were cancelled.
    agents.vms_list = [vm("vm1", suspended=True)]

    with pytest.raises(ValueError) as error:
        agents.set_target_vm("agent-1", "vm1", by_agent=True)

    assert "vm1 is suspended and takes nobody new: no VM takes agents now, so there is none to pick: queue_for_vm" in str(error.value)
    assert "Don't cancel jobs for this." in str(error.value)


def test_vm_shutting_down_with_another_running_says_to_pick_that(agents):
    agents.vms_list = [vm("vm1", graceful_shutdown=True), vm("vm2")]

    with pytest.raises(ValueError) as error:
        agents.set_target_vm("agent-1", "vm1", by_agent=True)

    assert str(error.value) == "vm1 shuts down once the agents on it are done and takes nobody new: pick another VM."


# Decisions on drafts


def test_opencodex_8598_draft_the_app_sent_back_tells_its_agent_to_draft_it_again(agents):
    # Its text changed since it was drafted, so it could never go; its agent never heard, and it waited for good.
    job = agents.jobs.create("follow_up", "Follow up on owner/proj#40", "agent-1", "user", thread="owner/proj#40")
    draft = agents.inbox.create("edit", "agent-1", "feat(codex): add a login policy", "New text.", job=job["id"], repo="owner/proj", target="owner/proj#40")
    agents.jobs.update(job["id"], status="waiting_on_user", drafts=[draft["id"]])
    why = "Its title or description changed since the agent drafted this: Redraft, so the agent works on the text as it is now."

    agents.decide(draft["id"], "rejected", why, answered_by="automation")

    text = agents.pending["agent-1"][-1]["text"]
    assert text.startswith(f"The app didn't send your title and description draft {draft['id']} (feat(codex): add a login policy): {why}")
    assert agents.jobs.get(job["id"])["status"] == "queued"


# News on a job's issue


def test_bulwarkmail_1760_issue_closed_on_github_is_told_at_once_and_once(agents):
    # A maintainer fixed and closed it, and our agent ran eight more hours of checks before its last read found out.
    job = agents.jobs.create("fix_issue", "Fix the folder list", "agent-1", "user", issue="owner/proj#1760")
    agents.jobs.update(job["id"], status="working")

    agents.issue_fixed("owner/proj#1760", "was closed")
    agents.issue_fixed("owner/proj#1760", "was closed")

    assert len(agents.pending["agent-1"]) == 1
    text = agents.pending["agent-1"][0]["text"]
    assert text.startswith(f"owner/proj#1760 was closed on GitHub now. You have {job['id']} (Fix the folder list) on it.")
    assert "close_issue with the link that shows it" in text
    notices = [entry for entry in agents.jobs.get(job["id"])["timeline"] if entry["kind"] == "notice"]
    assert len(notices) == 1


def test_issue_fixed_leaves_a_finished_job_alone(agents):
    job = agents.jobs.create("fix_issue", "Fix the folder list", "agent-1", "user", issue="owner/proj#1760")
    agents.jobs.update(job["id"], status="done")

    agents.issue_fixed("owner/proj#1760", "was closed")

    assert agents.pending["agent-1"] == []


# The heartbeat


class RoundOver(Exception):
    pass


def heartbeat_round(agents, monkeypatch):
    """One round of keep_going: its first sleep returns at once, its next one ends it."""
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) > 1:
            raise RoundOver()

    async def archive(agent_id):
        pass

    monkeypatch.setattr(agents_module.asyncio, "sleep", sleep)
    agents.archive = archive
    with pytest.raises(RoundOver):
        asyncio.run(agents.keep_going())


def test_phoenix_cla_blocker_is_tried_again_once_a_day_not_every_hour(agents, monkeypatch):
    # A CLA signed on the user's first PR there, which waits for the user's decision: every hourly check found nothing new.
    job = agents.jobs.create("fix_issue", "Fix the trace view", "agent-1", "user", issue="owner/proj#17537")
    two_hours_ago = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    cla = agents.inbox.create("approval", "agent-1", "Sign the project's CLA", "...", job=job["id"], repo="owner/proj", overview={"kind": "cla", "link": ""})
    other = agents.inbox.create("approval", "agent-1", "Pay for the API", "...", job=job["id"], repo="owner/proj", overview={"kind": "other", "link": ""})
    agents.inbox.drafts[cla["id"]]["created_at"] = two_hours_ago
    agents.inbox.drafts[other["id"]]["created_at"] = two_hours_ago
    agents.jobs.update(job["id"], status="waiting_on_user", drafts=[cla["id"], other["id"]])

    heartbeat_round(agents, monkeypatch)

    told = [message["text"] for message in agents.pending["agent-1"]]
    assert len(told) == 1
    assert told[0].startswith(f"Blocker check: {other['id']} (Pay for the API)")


def test_lance_10997_agent_waiting_for_another_run_of_its_project_is_woken_once_it_ended(agents, monkeypatch):
    agents.waiting_for_run = {"agent-1": "run_b2c3d4"}

    heartbeat_round(agents, monkeypatch)

    assert agents.waiting_for_run == {}
    assert agents.pending["agent-1"][0]["text"] == "The other agent's test run you waited for has ended: run your tests now (run_tests)."
