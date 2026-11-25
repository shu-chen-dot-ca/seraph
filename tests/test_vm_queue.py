"""Who uses each VM's desktops (sandbox/vm_queue.py) and the desktops themselves (sandbox/vms.py).

One holder per desktop and one waiting line per VM, in the Issues board's order: priority first, then reviews, then the
rest. A full VM takes nobody new, an overloaded one takes a desktop back and gives it to the same agent later, and the
user can take a desktop over, give it away or remove an agent. Desktops keep their numbers (a new one takes the lowest
free number) and never go past the VM's max desktops; records saved before desktops, or before agents stopped stepping
aside (2026-11-08), still load. The agent's tools (sandbox/agent/tools.py) only touch a desktop the agent holds and leave
the other agents' work alone.

Nothing here asks Incus or runs a command: VMs.__init__ would, so the fixture sets its fields itself, a VM's status is a
stand-in answer, and records are saved in pytest's temporary folder, never in DATA_DIR."""

import asyncio
import copy
import json
import subprocess
import threading

import pytest

from sandbox import vms as vms_module
from sandbox.agent import long_runs
from sandbox.agent.tools import NOT_HOLDER, ComputerTools
from sandbox.vm import MAX_DESKTOPS
from sandbox.vm_queue import VMQueue
from sandbox.vms import VMRecord, VMs, VMsError

# A VM's record as it is saved (sandbox/vms.py): running, with one desktop nobody holds.
VM1 = {
    "name": "vm1",
    "incus_name": "sandbox-vm1",
    "cpus": 8,
    "memory_gb": 8,
    "disk_gb": 128,
    "internet": True,
    "env": {},
    "status": "running",
    "created_at": "2026-11-01T00:00:00+00:00",
    "max_desktops": 5,
    "desktops": [{"number": 1, "holder": None}],
}


@pytest.fixture(autouse=True)
def no_commands(monkeypatch):
    """Nothing here may run a command (incus above all): one that tries fails the test."""
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail(f"Ran a command: {args}"))


@pytest.fixture
def vms(tmp_path, monkeypatch):
    """The VMs, with vm1 only, saved in a temporary folder."""
    monkeypatch.setattr(vms_module, "VMS_DIR", tmp_path / "vms")
    monkeypatch.setattr(vms_module, "GLOBAL_ENV_PATH", tmp_path / "global_env.json")
    monkeypatch.setattr(VMRecord, "global_env", {})
    all_vms = VMs.__new__(VMs)
    all_vms.records = {}
    all_vms.lock = threading.Lock()
    all_vms.version = 0
    all_vms.global_env_lock = threading.RLock()
    all_vms.records["vm1"] = VMRecord(copy.deepcopy(VM1), all_vms.changed)
    return all_vms


@pytest.fixture
def queue(vms):
    """The VMs' queue. What it tells Agents is kept: who got a desktop while waiting (granted) and who lost theirs
    because of the user (kicked)."""
    queue = VMQueue(vms)
    queue.granted = []
    queue.kicked = []
    queue.on_grant = lambda vm_name, agent_id: queue.granted.append(agent_id)
    queue.on_kick = lambda vm_name, agent_id, reason: queue.kicked.append(agent_id)
    return queue


# --- Joining and leaving ------------------------------------------------------------------------------------------


def test_free_desktop_is_held_at_once(vms, queue):
    place = queue.join("vm1", "agent_a")

    assert place == 0
    assert vms.get("vm1").desktop_of("agent_a") == 1
    # Granted right in join: the caller learns it from the 0, so Agents isn't told a second time.
    assert queue.granted == []


def test_holder_and_line_are_saved_with_the_vm(queue, tmp_path):
    queue.join("vm1", "agent_a")
    queue.join("vm1", "agent_b")

    saved = json.loads((tmp_path / "vms" / "vm1.json").read_text())
    assert saved["desktops"] == [{"number": 1, "holder": "agent_a"}]
    assert saved["queue"] == ["agent_b"]


def test_joining_again_gives_the_same_answer(queue):
    queue.join("vm1", "agent_a")
    queue.join("vm1", "agent_b")
    queue.join("vm1", "agent_c")

    assert queue.join("vm1", "agent_a") == 0
    assert queue.join("vm1", "agent_c") == 2
    assert queue.place("agent_c") == ("vm1", 2)
    assert queue.place("agent_d") == (None, None)


def test_next_in_line_gets_the_desktop_when_it_is_released(vms, queue):
    queue.join("vm1", "agent_a")
    queue.join("vm1", "agent_b")

    queue.release("vm1", "agent_a")

    assert vms.get("vm1").desktop_of("agent_b") == 1
    assert vms.get("vm1").queue == []
    assert queue.granted == ["agent_b"]


def test_only_the_holder_can_release(queue):
    queue.join("vm1", "agent_a")

    with pytest.raises(ValueError, match="agent_b doesn't hold vm1"):
        queue.release("vm1", "agent_b")


def test_agent_waits_for_the_desktop_it_asked_for(vms, queue):
    # Its project is set up in desktop 2's home folder, so a free desktop 1 is no use to it.
    record = vms.get("vm1")
    record.desktops = {1: {"holder": None}, 2: {"holder": "agent_a"}}

    place = queue.join("vm1", "agent_b", desktop=2)

    assert place == 1
    assert record.desktops[1]["holder"] is None
    assert record.desktop_of("agent_b") == 2


def test_free_desktop_goes_to_the_first_that_can_use_it(vms, queue):
    record = vms.get("vm1")
    record.desktops = {1: {"holder": "agent_a"}, 2: {"holder": "agent_c"}}
    queue.join("vm1", "agent_b", desktop=2)
    queue.join("vm1", "agent_d")

    queue.release("vm1", "agent_a")

    # agent_b is first, but waits for desktop 2; agent_d takes any.
    assert record.desktops[1]["holder"] == "agent_d"
    assert record.queue == ["agent_b"]
    assert record.wants == {"agent_b": 2}


def test_agent_is_in_one_vms_line_at_a_time(vms, queue):
    vms.records["vm2"] = VMRecord({**copy.deepcopy(VM1), "name": "vm2", "incus_name": "sandbox-vm2"}, vms.changed)
    queue.join("vm1", "agent_a")

    with pytest.raises(ValueError, match="Already in vm1's queue"):
        queue.join("vm2", "agent_a")
    assert vms.get("vm2").desktops[1]["holder"] is None


def test_desktop_the_vm_does_not_have_is_refused(queue):
    with pytest.raises(ValueError, match=f"There is no desktop {MAX_DESKTOPS + 1}: desktops are numbered 1 to {MAX_DESKTOPS}"):
        queue.join("vm1", "agent_a", desktop=MAX_DESKTOPS + 1)


def test_desktop_the_vm_has_not_now_is_waited_for(vms, queue):
    # Shut down while nobody used it, or taken back: the agent waits for it, and the app adds it again.
    assert queue.join("vm1", "agent_a", desktop=4) == 1
    assert vms.get("vm1").wants == {"agent_a": 4}


# --- The line's order ----------------------------------------------------------------------------------------------


def test_line_goes_in_the_issues_boards_order(vms, queue):
    queue.prioritized = {"agent_p1", "agent_p2"}
    queue.reviewing = {"agent_r1", "agent_r2"}
    queue.join("vm1", "agent_a")

    for agent_id in ["agent_b", "agent_r1", "agent_p1", "agent_c", "agent_r2", "agent_p2"]:
        queue.join("vm1", agent_id)

    # Priority first, then the reviews, then the rest; each in the order they came.
    assert vms.get("vm1").queue == ["agent_p1", "agent_p2", "agent_r1", "agent_r2", "agent_b", "agent_c"]


def test_priority_or_a_review_moves_a_waiting_agent_up(vms, queue):
    queue.join("vm1", "agent_a")
    for agent_id in ["agent_b", "agent_c", "agent_d"]:
        queue.join("vm1", agent_id)

    queue.prioritized.add("agent_d")
    queue.move_up("vm1", "agent_d")
    queue.reviewing.add("agent_c")
    queue.move_up("vm1", "agent_c")

    assert vms.get("vm1").queue == ["agent_d", "agent_c", "agent_b"]


def test_user_moves_an_agent_to_the_front(vms, queue):
    queue.prioritized = {"agent_p"}
    queue.join("vm1", "agent_a")
    queue.join("vm1", "agent_p")
    queue.join("vm1", "agent_b")

    queue.move_to_front("vm1", "agent_b")

    # The user's own choice goes ahead even of priority.
    assert vms.get("vm1").queue == ["agent_b", "agent_p"]


def test_only_a_waiting_agent_moves(queue):
    with pytest.raises(ValueError, match="agent_a is not waiting for vm1"):
        queue.move_to_front("vm1", "agent_a")
    with pytest.raises(ValueError, match="agent_a is not waiting for vm1"):
        queue.move_up("vm1", "agent_a")


# --- A VM with no room ---------------------------------------------------------------------------------------------


def test_full_vm_takes_nobody_new(vms, queue):
    queue.full = {"vm1": "a load of 17 on 16 CPUs"}

    place = queue.join("vm1", "agent_a")

    assert place == 1
    assert vms.get("vm1").desktops[1]["holder"] is None


def test_full_vm_keeps_a_released_desktop_until_there_is_room(vms, queue):
    queue.join("vm1", "agent_a")
    queue.join("vm1", "agent_b")
    queue.full = {"vm1": "9 GB of its disk free"}

    queue.release("vm1", "agent_a")

    assert vms.get("vm1").desktops[1]["holder"] is None
    assert queue.granted == []

    queue.full = {}
    queue.fill("vm1")

    assert vms.get("vm1").desktops[1]["holder"] == "agent_b"
    assert queue.granted == ["agent_b"]


def test_overloaded_vm_takes_a_desktop_back(vms, queue):
    record = vms.get("vm1")
    record.desktops = {1: {"holder": "agent_a"}, 2: {"holder": "agent_b"}}
    queue.prioritized = {"agent_p"}
    queue.reviewing = {"agent_r"}
    for agent_id in ["agent_p", "agent_r", "agent_c"]:
        queue.join("vm1", agent_id)

    number = queue.step_down("vm1", "agent_b")

    # Back in line for its own desktop, behind priority and the reviews, ahead of the rest. It isn't kicked: Agents
    # tells it, and nothing it runs is stopped.
    assert number == 2
    assert record.desktops[2]["holder"] is None
    assert record.queue == ["agent_p", "agent_r", "agent_b", "agent_c"]
    assert record.wants["agent_b"] == 2
    assert record.stepped_down_at is not None
    assert queue.kicked == []


def test_agent_with_priority_steps_down_to_the_front(vms, queue):
    queue.join("vm1", "agent_a")
    queue.prioritized = {"agent_a", "agent_p"}
    queue.join("vm1", "agent_p")

    queue.step_down("vm1", "agent_a")

    assert vms.get("vm1").queue == ["agent_a", "agent_p"]


def test_step_down_needs_a_desktop(queue):
    queue.join("vm1", "agent_a")
    queue.join("vm1", "agent_b")

    with pytest.raises(ValueError, match="agent_b doesn't hold a desktop of vm1"):
        queue.step_down("vm1", "agent_b")


def test_desktop_taken_back_comes_back_to_its_agent(vms, queue, monkeypatch):
    record = vms.get("vm1")
    monkeypatch.setattr(record.vm, "status", lambda: "Stopped")
    record.desktops = {1: {"holder": "agent_a"}, 2: {"holder": "agent_b"}}
    record.runs = [{"id": "run_1", "agent": "agent_b", "desktop": 2, "label": "pytest"}]

    number = queue.step_down("vm1", "agent_b")
    record.remove_desktop(number, queue.lock, taken_back=True)

    # Gone while agent_b waits for it, and its run goes on.
    assert list(record.desktops) == [1]
    assert record.wants == {"agent_b": 2}
    assert len(record.runs) == 1

    record.add_desktop(queue.lock, number)
    queue.fill("vm1")

    assert record.desktops[2]["holder"] == "agent_b"
    assert queue.granted == ["agent_b"]


# --- The user --------------------------------------------------------------------------------------------------------


def test_user_takes_a_desktop_over(vms, queue):
    queue.join("vm1", "agent_a")
    queue.join("vm1", "agent_b")

    queue.take_over("vm1", 1)

    record = vms.get("vm1")
    assert record.desktops[1]["holder"] == "user"
    # The agent that held it is first in line again, for that desktop.
    assert record.queue == ["agent_a", "agent_b"]
    assert record.wants == {"agent_a": 1}
    assert queue.kicked == ["agent_a"]


def test_taking_over_twice_changes_nothing(vms, queue):
    queue.take_over("vm1", 1)
    queue.take_over("vm1", 1)

    assert vms.get("vm1").desktops[1]["holder"] == "user"
    assert queue.kicked == []


def test_user_hands_the_desktop_back(vms, queue):
    queue.take_over("vm1", 1)
    queue.join("vm1", "agent_a")

    queue.release("vm1", "user", desktop=1)

    assert vms.get("vm1").desktops[1]["holder"] == "agent_a"
    assert queue.granted == ["agent_a"]


def test_user_gives_a_desktop_to_a_waiting_agent(vms, queue):
    queue.join("vm1", "agent_a")
    queue.join("vm1", "agent_b")
    queue.join("vm1", "agent_c")

    queue.give_to("vm1", "agent_c", 1)

    record = vms.get("vm1")
    assert record.desktops[1]["holder"] == "agent_c"
    assert record.queue == ["agent_a", "agent_b"]
    assert record.wants == {"agent_a": 1}
    assert queue.kicked == ["agent_a"]
    assert queue.granted == ["agent_c"]


def test_giving_away_a_desktop_the_user_holds_ends_the_users_hold(vms, queue):
    queue.take_over("vm1", 1)
    queue.join("vm1", "agent_a")

    queue.give_to("vm1", "agent_a", 1)

    assert vms.get("vm1").desktops[1]["holder"] == "agent_a"
    assert vms.get("vm1").queue == []
    assert queue.kicked == []


def test_desktop_is_given_only_to_a_waiting_agent(queue):
    with pytest.raises(ValueError, match="agent_a is not waiting for vm1"):
        queue.give_to("vm1", "agent_a", 1)


def test_removed_holder_is_told_and_the_next_one_gets_the_desktop(vms, queue):
    queue.join("vm1", "agent_a")
    queue.join("vm1", "agent_b")

    queue.remove("vm1", "agent_a")

    assert vms.get("vm1").desktops[1]["holder"] == "agent_b"
    assert queue.kicked == ["agent_a"]
    assert queue.granted == ["agent_b"]


def test_removed_from_the_line_forgets_the_desktop_it_asked_for(vms, queue):
    queue.join("vm1", "agent_a")
    queue.join("vm1", "agent_b", desktop=1)

    queue.remove("vm1", "agent_b")

    assert vms.get("vm1").queue == []
    assert vms.get("vm1").wants == {}
    assert queue.kicked == ["agent_b"]


def test_removing_an_agent_that_is_not_there_is_refused(queue):
    with pytest.raises(ValueError, match="agent_a is not holding or waiting for vm1"):
        queue.remove("vm1", "agent_a")


def test_deleted_agent_leaves_without_being_told(queue):
    queue.join("vm1", "agent_a")
    queue.join("vm1", "agent_b")

    queue.leave_all("agent_a")

    assert queue.place("agent_a") == (None, None)
    assert queue.place("agent_b") == ("vm1", 0)
    assert queue.kicked == []
    assert queue.granted == ["agent_b"]


# --- Runs ------------------------------------------------------------------------------------------------------------


def test_holder_keeps_its_desktop_while_its_run_goes(vms, queue):
    # Since 2026-11-08 agents never step aside: a run going on a desktop doesn't free it for the next one.
    queue.join("vm1", "agent_a")
    queue.add_run("vm1", {"id": "run_1", "agent": "agent_a", "desktop": 1, "background": True, "stopped_by_user": False})

    place = queue.join("vm1", "agent_b")

    assert place == 1
    assert vms.get("vm1").desktops[1]["holder"] == "agent_a"


def test_run_that_ended_is_handled_once(vms, queue):
    queue.add_run("vm1", {"id": "run_1", "agent": "agent_a", "desktop": 1, "background": True, "stopped_by_user": False})

    assert queue.claim_run("run_1") is True
    assert queue.claim_run("run_1") is False

    queue.finish_run("vm1", "run_1")

    assert vms.get("vm1").runs == []
    assert queue.ending == set()


def test_run_from_before_desktops_ends_on_desktop_1(vms, queue):
    # Runs saved before desktops had no number: they were all on desktop 1.
    record = vms.get("vm1")
    record.runs = [{"id": "run_old", "agent": "agent_a", "background": True, "stopped_by_user": False}]
    record.queue = ["agent_b"]
    record.wants = {"agent_b": 1}

    queue.finish_run("vm1", "run_old")

    assert record.desktops[1]["holder"] == "agent_b"
    assert queue.granted == ["agent_b"]


def test_runs_go_to_the_background_per_agent(vms, queue):
    queue.add_run("vm1", {"id": "run_a", "agent": "agent_a", "desktop": 1, "background": False, "stopped_by_user": False})
    queue.add_run("vm1", {"id": "run_b", "agent": "agent_b", "desktop": 2, "background": False, "stopped_by_user": False})

    queue.to_background("agent_a")
    assert [run["background"] for run in vms.get("vm1").runs] == [True, False]

    # The backend restarted: every run is collected by the app now.
    queue.to_background()
    assert [run["background"] for run in vms.get("vm1").runs] == [True, True]


def test_user_stops_a_run(queue):
    queue.add_run("vm1", {"id": "run_a", "agent": "agent_a", "desktop": 1, "background": True, "stopped_by_user": False})

    run = queue.stop_run("vm1", "run_a")

    assert run["stopped_by_user"] is True
    with pytest.raises(ValueError, match="No run run_gone in vm1"):
        queue.stop_run("vm1", "run_gone")


# --- Desktop numbers and max desktops ------------------------------------------------------------------------------


def test_new_desktop_takes_the_lowest_free_number(vms, monkeypatch):
    record = vms.get("vm1")
    monkeypatch.setattr(record.vm, "status", lambda: "Stopped")
    record.desktops = {2: {"holder": None}, 3: {"holder": None}}

    assert record.add_desktop(threading.Lock()) == 1
    assert record.add_desktop(threading.Lock()) == 4
    assert list(record.desktops) == [1, 2, 3, 4]


def test_removing_a_desktop_keeps_the_others_numbers(vms, monkeypatch):
    record = vms.get("vm1")
    monkeypatch.setattr(record.vm, "status", lambda: "Stopped")
    record.desktops = {1: {"holder": None}, 2: {"holder": None}, 3: {"holder": None}}
    record.locked_by = {2: "agent"}
    record.pointers = {2: {"agent": "agent_a", "x": 10, "y": 20, "width": 1280, "height": 800}}

    record.remove_desktop(2, threading.Lock())

    assert list(record.desktops) == [1, 3]
    assert record.locked_by == {}
    assert record.pointers == {}
    assert record.add_desktop(threading.Lock()) == 2


def test_no_more_desktops_than_its_max(vms, monkeypatch):
    record = vms.get("vm1")
    monkeypatch.setattr(record.vm, "status", lambda: "Stopped")
    record.max_desktops = 2
    record.desktops = {1: {"holder": None}, 3: {"holder": None}}

    with pytest.raises(VMsError, match="already has 2 desktops"):
        record.add_desktop(threading.Lock())
    assert list(record.desktops) == [1, 3]


def test_desktop_it_has_cannot_be_added_again(vms):
    with pytest.raises(VMsError, match="vm1 has desktop 1 already"):
        vms.get("vm1").add_desktop(threading.Lock(), 1)


def test_vm_keeps_one_desktop(vms):
    with pytest.raises(VMsError, match="Desktop 1 is the only desktop of vm1"):
        vms.get("vm1").remove_desktop(1, threading.Lock())


@pytest.mark.parametrize(
    "holder, wants, runs",
    [
        ("agent_a", {}, []),
        (None, {"agent_a": 2}, []),
        (None, {}, [{"id": "run_1", "agent": "agent_a", "desktop": 2}]),
    ],
)
def test_desktop_in_use_cannot_go(vms, holder, wants, runs):
    record = vms.get("vm1")
    record.desktops = {1: {"holder": None}, 2: {"holder": holder}}
    record.wants = wants
    record.runs = runs

    with pytest.raises(VMsError, match="Desktop 2 is in use"):
        record.remove_desktop(2, threading.Lock())
    assert list(record.desktops) == [1, 2]


def test_max_desktops_never_below_how_many_it_has(vms, tmp_path):
    record = vms.get("vm1")
    record.desktops = {1: {"holder": None}, 2: {"holder": None}}

    with pytest.raises(VMsError, match="has 2 desktops now"):
        record.set_max_desktops(1)
    with pytest.raises(VMsError, match=f"Max desktops must be 1 to {MAX_DESKTOPS}"):
        record.set_max_desktops(MAX_DESKTOPS + 1)
    record.set_max_desktops(2)

    assert json.loads((tmp_path / "vms" / "vm1.json").read_text())["max_desktops"] == 2


# --- Records ---------------------------------------------------------------------------------------------------------


def test_desktop_numbers_survive_a_restart(vms, tmp_path):
    old = copy.deepcopy(VM1)
    old["desktops"] = [{"number": 2, "holder": "agent_a"}, {"number": 3, "holder": None}]
    VMRecord(old, vms.changed).save()

    record = VMRecord(json.loads((tmp_path / "vms" / "vm1.json").read_text()), vms.changed)

    assert record.desktops == {2: {"holder": "agent_a"}, 3: {"holder": None}}


def test_record_from_before_desktops_has_desktop_1(vms):
    old = copy.deepcopy(VM1)
    del old["desktops"]
    del old["max_desktops"]
    old["holder"] = "agent_a"

    record = VMRecord(old, vms.changed)

    assert record.desktops == {1: {"holder": "agent_a"}}
    assert record.max_desktops == vms_module.MAX_DESKTOPS_DEFAULT


def test_record_from_when_agents_stepped_aside_2026_11_08(vms):
    # Before 2026-11-08 an agent stepped aside from its desktop while its run went, and waited in that desktop's
    # priority list to have it back. Loaded now, the first holds it again when nobody does, the others wait for it.
    old = copy.deepcopy(VM1)
    old["desktops"] = [
        {"number": 1, "holder": None, "priority": ["agent_a", "agent_b"]},
        {"number": 2, "holder": "agent_c", "priority": ["agent_d"]},
    ]
    old["queue"] = ["agent_e"]

    record = VMRecord(old, vms.changed)

    assert record.desktops == {1: {"holder": "agent_a"}, 2: {"holder": "agent_c"}}
    # Those that stepped aside wait ahead of the ones that were in line already, each for its own desktop.
    assert sorted(record.queue[:2]) == ["agent_b", "agent_d"]
    assert record.queue[2] == "agent_e"
    assert record.wants == {"agent_b": 1, "agent_d": 2}


def test_renamed_vm_keeps_its_incus_name_and_its_forks_follow(vms, tmp_path):
    vms.records["vm2"] = VMRecord(
        {**copy.deepcopy(VM1), "name": "vm2", "incus_name": "sandbox-vm2", "forked_from": "vm1"}, vms.changed
    )
    vms.get("vm1").save()

    vms.rename("vm1", "main")

    assert vms.get("main").incus_name == "sandbox-vm1"
    assert vms.get("vm2").forked_from == "main"
    assert (tmp_path / "vms" / "main.json").exists()
    assert not (tmp_path / "vms" / "vm1.json").exists()
    with pytest.raises(VMsError, match="There is no VM vm1"):
        vms.get("vm1")


def test_new_vm_dialog_offers_the_lowest_free_name(vms):
    vms.records["vm3"] = VMRecord({**copy.deepcopy(VM1), "name": "vm3", "incus_name": "sandbox-vm3"}, vms.changed)

    assert vms.options()["next_name"] == "vm2"


@pytest.mark.parametrize(
    "name, cpus, memory_gb, disk_gb, max_desktops, problem",
    [
        ("VM2", vms_module.CPUS_DEFAULT, vms_module.MEMORY_GB_DEFAULT, vms_module.DISK_GB_DEFAULT, 5, "The name must start"),
        ("vm-" + "x" * 30, vms_module.CPUS_DEFAULT, vms_module.MEMORY_GB_DEFAULT, vms_module.DISK_GB_DEFAULT, 5, "The name must start"),
        ("vm2", max(vms_module.CPUS_ALLOWED) + 1, vms_module.MEMORY_GB_DEFAULT, vms_module.DISK_GB_DEFAULT, 5, "cpus must be one of"),
        ("vm2", vms_module.CPUS_DEFAULT, max(vms_module.MEMORY_GB_ALLOWED) + 1, vms_module.DISK_GB_DEFAULT, 5, "memory_gb must be one of"),
        ("vm2", vms_module.CPUS_DEFAULT, vms_module.MEMORY_GB_DEFAULT, vms_module.DISK_GB_MIN - 1, 5, "The disk must be"),
        ("vm2", vms_module.CPUS_DEFAULT, vms_module.MEMORY_GB_DEFAULT, vms_module.DISK_GB_DEFAULT, 0, "Max desktops must be 1 to"),
        ("vm1", vms_module.CPUS_DEFAULT, vms_module.MEMORY_GB_DEFAULT, vms_module.DISK_GB_DEFAULT, 5, "already a VM named vm1"),
    ],
)
def test_new_vm_that_cant_be_made_is_refused_before_anything_starts(vms, name, cpus, memory_gb, disk_gb, max_desktops, problem):
    with pytest.raises(VMsError, match=problem):
        vms.create(name, "base-image", cpus, memory_gb, disk_gb, max_desktops)
    assert list(vms.records) == ["vm1"]


# --- The agent's VM tools ------------------------------------------------------------------------------------------


def test_waiting_agent_cannot_touch_the_vm(vms, queue):
    queue.join("vm1", "agent_a")
    queue.join("vm1", "agent_b")
    tools = ComputerTools(vms, queue, "agent_b", lambda: "vm1", [])

    with pytest.raises(ValueError, match=NOT_HOLDER):
        asyncio.run(tools.bash({"command": "ls"}))


def test_vm_stays_on_while_another_agent_works_on_another_desktop(vms, queue, monkeypatch):
    record = vms.get("vm1")
    record.desktops = {1: {"holder": "agent_a"}, 2: {"holder": "agent_b"}}
    monkeypatch.setattr(record.vm, "status", lambda: "Running")
    tools = ComputerTools(vms, queue, "agent_a", lambda: "vm1", [])

    with pytest.raises(ValueError, match="Someone else works on another desktop of this VM"):
        asyncio.run(tools.vm_stop({}))


def test_vm_stays_on_while_another_agents_run_goes(vms, queue, monkeypatch):
    record = vms.get("vm1")
    record.desktops = {1: {"holder": "agent_a"}, 2: {"holder": None}}
    record.runs = [{"id": "run_1", "agent": "agent_b", "desktop": 2, "label": "npm test"}]
    monkeypatch.setattr(record.vm, "status", lambda: "Running")
    tools = ComputerTools(vms, queue, "agent_a", lambda: "vm1", [])

    with pytest.raises(ValueError, match="Another agent's run is going in this VM"):
        asyncio.run(tools.vm_stop({}))


def test_vm_that_no_longer_answers_can_be_restarted_anyway(vms, queue, monkeypatch):
    record = vms.get("vm1")
    record.desktops = {1: {"holder": "agent_a"}, 2: {"holder": "agent_b"}}
    restarted = []
    monkeypatch.setattr(record, "restart", lambda: restarted.append("vm1"))
    tools = ComputerTools(vms, queue, "agent_a", lambda: "vm1", [])

    monkeypatch.setattr(record.vm, "responds", lambda: True)
    with pytest.raises(ValueError, match="a restart would end it"):
        asyncio.run(tools.vm_restart({}))

    # Frozen: the other agent's work is lost anyway.
    monkeypatch.setattr(record.vm, "responds", lambda: False)
    asyncio.run(tools.vm_restart({}))

    assert restarted == ["vm1"]
    # The runs it ended say who restarted it.
    assert record.restarted_by["by"] == "agent_a's vm_restart"


def test_agent_stops_only_its_own_runs(vms, queue, monkeypatch):
    stopped = []
    monkeypatch.setattr(long_runs, "stop", lambda record, run: stopped.append(run["id"]))
    record = vms.get("vm1")
    record.runs = [
        {"id": "run_a", "agent": "agent_a", "desktop": 1, "label": "pytest"},
        {"id": "run_b", "agent": "agent_b", "desktop": 2, "label": "cargo test"},
    ]
    tools = ComputerTools(vms, queue, "agent_a", lambda: "vm1", [])

    with pytest.raises(ValueError, match="You have no run run_b going in vm1"):
        asyncio.run(tools.run_stop({"run": "run_b"}))
    asyncio.run(tools.run_stop({"run": "run_a"}))

    assert stopped == ["run_a"]
    assert record.runs[0]["stopped_by_agent"] is True


def test_agent_locks_its_desktop_once_a_turn(vms, queue):
    queue.join("vm1", "agent_a")
    tools = ComputerTools(vms, queue, "agent_a", lambda: "vm1", [])
    asyncio.run(tools.lock_desktop({}))

    assert vms.get("vm1").locked_by == {1: "agent"}

    # The user unlocks it: it stays unlocked for the rest of the turn.
    vms.get("vm1").locked_by = {}
    with pytest.raises(ValueError, match="already locked once this turn"):
        asyncio.run(tools.lock_desktop({}))

    tools.end_turn()
    asyncio.run(tools.lock_desktop({}))

    assert vms.get("vm1").locked_by == {1: "agent"}


def test_turn_end_undoes_the_agents_lock_but_not_the_users(vms, queue):
    queue.join("vm1", "agent_a")
    tools = ComputerTools(vms, queue, "agent_a", lambda: "vm1", [])

    asyncio.run(tools.lock_desktop({}))
    tools.end_turn()
    assert vms.get("vm1").locked_by == {}

    asyncio.run(tools.lock_desktop({}))
    # The user locks it themselves meanwhile.
    vms.get("vm1").locked_by = {1: "user"}
    tools.end_turn()
    assert vms.get("vm1").locked_by == {1: "user"}
