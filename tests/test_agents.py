"""The rules that tie agents to their jobs, the VMs and the news on GitHub (github_searcher/agents.py): which VM an agent may
pick and what it is told when none takes agents.

The Agents manager is built bare (Agents.__init__ would start real stores): the real Jobs and Inbox in pytest's temporary
folder (never DATA_DIR), one agent, agent-1, and VMs as stand-ins. Nothing reaches GitHub, Claude or a VM, and no agent
runs a turn: what an agent is told stays in its pending messages."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

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
