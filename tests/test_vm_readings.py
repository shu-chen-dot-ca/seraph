"""What the app reads from Incus, from inside the VMs and from this computer, and the paths it accepts.

A VM's status is what Incus says once no stop or start goes on anymore (vm1 showed as stopping while it ran on,
2026-11-11), and a stop that hangs is forced, then reported (prb_3e5cac). A long run (sandbox/agent/long_runs.py) only
counts as ended when Incus says the VM is off (prb_7b8fd5), and why it ended is read from what the VM shows: a reboot, a
full disk (vm1, 2026-11-11), its log deleted. Internet use is counted once, across backend restarts and VM reboots.
Copying files (sandbox/file_transfer.py) never overwrites and refuses relative paths and the whole disk. GPU readings
(sandbox/resource_usage.py) never wake a sleeping NVIDIA card. Image names, task ids and fingerprints that come from a
URL (sandbox/images.py) can't reach outside their folders, and an image a VM was made from stays.

Nothing here runs a command or touches Incus: every answer is a stand-in, and every folder is pytest's temporary one,
never DATA_DIR."""

import copy
import json
import subprocess
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from sandbox import file_transfer
from sandbox import images as images_module
from sandbox import vms as vms_module
from sandbox.agent import long_runs
from sandbox.file_transfer import FileTransferError
from sandbox.images import Images, ImagesError
from sandbox.resource_usage import ResourceUsage
from sandbox.vm import VM, VMError
from sandbox.vms import VMRecord, VMs

# A VM's record as it is saved (sandbox/vms.py): running, with one desktop nobody holds.
VM1 = {
    "name": "vm1",
    "incus_name": "sandbox-vm1",
    "cpus": 8,
    "memory_gb": 8,
    "disk_gb": 128,
    "internet": True,
    "env": {},
    "autostart": False,
    "status": "running",
    "created_at": "2026-11-01T00:00:00+00:00",
    "max_desktops": 5,
    "desktops": [{"number": 1, "holder": None}],
}
# What read_usage gives for a VM that is on, and one that is off.
USAGE_ON = {"on": True, "responding": True, "cpu_percent": 5.0, "memory_used_gb": 2.0, "disk_used_gb": 20.0, "net_down_rate": None, "net_up_rate": None}
USAGE_OFF = {"on": False, "responding": False, "cpu_percent": None, "memory_used_gb": None, "disk_used_gb": None, "net_down_rate": None, "net_up_rate": None}
# Above the largest process id Linux gives (2^22), so no process has it: a task with it has ended.
GONE_PID = 4_194_305


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
def run():
    """agent_a's run on desktop 2 of vm1, started an hour ago."""
    started_at = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    return {"id": "run_1", "agent": "agent_a", "desktop": 2, "log": "~/.cache/sandbox-runs/run_1.log", "started_at": started_at, "stopped_by_user": False}


@pytest.fixture
def usage():
    """This computer's use, without its start: that reads the real /proc and /sys and starts a thread."""
    usage = ResourceUsage.__new__(ResourceUsage)
    usage.watchers = 0
    return usage


@pytest.fixture
def gpu(tmp_path):
    """An NVIDIA card as /sys shows it, awake, with no driver linked yet. The drivers it can be linked to are made."""
    device = tmp_path / "0000:01:00.0"
    (device / "power").mkdir(parents=True)
    (device / "power" / "runtime_status").write_text("active\n")
    for driver in ["nvidia", "vfio-pci", "amdgpu"]:
        (tmp_path / "drivers" / driver).mkdir(parents=True)
    return {"device": device, "vendor": "nvidia", "name": "NVIDIA GeForce RTX 4060"}


@pytest.fixture
def images(vms, tmp_path, monkeypatch):
    """The images, without asking Incus (Images.__init__ would), their folders in a temporary folder."""
    monkeypatch.setattr(images_module, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(images_module, "INVENTORY_DIR", tmp_path / "images" / "inventory")
    monkeypatch.setattr(images_module, "DEFINITIONS_DIR", tmp_path / "images" / "definitions")
    (tmp_path / "images").mkdir()
    images = Images.__new__(Images)
    images.vms = vms
    images.lock = threading.Lock()
    images.version = 0
    images.images = []
    images.default = "base-image"
    images.highlights_by_fingerprint = {}
    images.tasks = []
    return images


# --- A VM's status ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status, usage_now, expected",
    [
        ("stopping", USAGE_ON, "running"),
        ("starting", USAGE_ON, "running"),
        ("stopping", USAGE_OFF, "stopped"),
        ("starting", USAGE_OFF, "stopped"),
    ],
)
def test_status_left_behind_is_what_incus_says_vm1_2026_11_11(vms, monkeypatch, status, usage_now, expected):
    # vm1's stop hung on 2026-11-11: it showed as stopping to the agents while it ran on and answered commands.
    record = vms.get("vm1")
    record.status = status
    monkeypatch.setattr(record, "read_usage", lambda: dict(usage_now))
    # One round of the watcher, then it ends, as it does for a deleted VM.
    monkeypatch.setattr(time, "sleep", lambda seconds: setattr(record, "deleted", True))

    vms.watch(record)

    assert record.status == expected


def test_status_of_a_stop_still_going_on_stays(vms, monkeypatch):
    record = vms.get("vm1")
    record.status = "stopping"
    monkeypatch.setattr(record, "read_usage", lambda: dict(USAGE_ON))
    monkeypatch.setattr(time, "sleep", lambda seconds: setattr(record, "deleted", True))
    record.lock.acquire()

    vms.watch(record)

    assert record.status == "stopping"


def test_vm_shut_down_from_inside_shows_as_stopped(vms, monkeypatch):
    # The desktop's power menu or `sudo poweroff`: the page offers Start instead of waiting for a desktop.
    record = vms.get("vm1")
    record.samples = [{"cpu_percent": 5.0, "memory_used_gb": 2.0, "net_down_rate": None, "net_up_rate": None}]
    monkeypatch.setattr(record, "read_usage", lambda: dict(USAGE_OFF))
    monkeypatch.setattr(time, "sleep", lambda seconds: setattr(record, "deleted", True))

    vms.watch(record)

    assert record.status == "stopped"
    assert record.samples == []


def test_hung_stop_is_forced_then_reported_prb_3e5cac(monkeypatch):
    # vm1 on 2026-11-11, its disk full: incus stop hung and the VM sat in "stopping" for good while it ran on. Each
    # incus stop has a time limit now; still running after both, the stop says so.
    ran = []

    def run(command, **kwargs):
        ran.append(command)
        if command[1] == "query":
            return subprocess.CompletedProcess(command, 0, json.dumps({"status": "Running"}), "")
        if command[1] == "exec":
            return subprocess.CompletedProcess(command, 0, "", "")
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(VMError, match="Could not stop sandbox-vm1"):
        VM("sandbox-vm1").stop()

    stops = [command for command in ran if command[1] == "stop"]
    assert stops == [["incus", "stop", "sandbox-vm1", "--timeout", "60"], ["incus", "stop", "sandbox-vm1", "--force"]]


def test_vm_that_does_not_answer_is_forced_off_at_once(monkeypatch):
    ran = []
    statuses = ["Running", "Stopped"]

    def run(command, **kwargs):
        ran.append(command)
        if command[1] == "query":
            return subprocess.CompletedProcess(command, 0, json.dumps({"status": statuses.pop(0)}), "")
        if command[1] == "exec":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)

    VM("sandbox-vm1").stop()

    stops = [command for command in ran if command[1] == "stop"]
    assert stops == [["incus", "stop", "sandbox-vm1", "--force"]]


# --- Long runs -------------------------------------------------------------------------------------------------------


def test_run_in_a_vm_stuck_in_stopping_still_goes_prb_7b8fd5(vms, run, monkeypatch):
    # vm1 sat in "stopping" for a quarter of an hour on 2026-11-11 while it ran on, and every run in it was reported
    # ended. Only Incus saying the VM is off ends a run.
    record = vms.get("vm1")
    record.status = "stopping"
    monkeypatch.setattr(record.vm, "status", lambda: "Running")
    monkeypatch.setattr(VM, "exec", lambda self, command, timeout=600, input=None, tag=None: subprocess.CompletedProcess([], 0, "running\n", ""))

    assert long_runs.check(record, run) is None


def test_run_in_a_vm_that_is_off_has_ended(vms, run, monkeypatch):
    record = vms.get("vm1")
    record.status = "stopped"
    monkeypatch.setattr(record.vm, "status", lambda: "Stopped")

    result = long_runs.check(record, run)

    assert result["ended"] == "gone"
    assert result["why"] == "the VM stopped or restarted"


def test_finished_run_gives_its_exit_code_and_output(vms, run, monkeypatch):
    asked = []

    def run_command(self, command, timeout=600, input=None, tag=None):
        asked.append(self.desktop)
        return subprocess.CompletedProcess([], 0, "exit 1\nFAILED tests/test_app.py::test_login\n", "")

    monkeypatch.setattr(VM, "exec", run_command)

    result = long_runs.check(vms.get("vm1"), run)

    assert result["ended"] == "exit"
    assert result["exit_code"] == 1
    assert result["output"] == "FAILED tests/test_app.py::test_login\n"
    # Checked as the user of the run's own desktop, where its output is.
    assert asked == [2]


def test_full_disk_is_named_as_why_a_run_ended_vm1_2026_11_11(vms, run, monkeypatch):
    # ENOSPC and SQLITE_FULL on vm1, 2026-11-11: the run couldn't even write its exit code. 500,000 KB free in its home.
    monkeypatch.setattr(VM, "exec", lambda self, command, timeout=600, input=None, tag=None: subprocess.CompletedProcess([], 0, "gone 99999 500000 kept\ndatabase or disk is full\n", ""))

    result = long_runs.check(vms.get("vm1"), run)

    assert result["ended"] == "gone"
    assert result["why"].startswith("the disk is full (0.5 GB free)")
    assert result["output"] == "database or disk is full\n"


@pytest.mark.parametrize(
    "answer, why",
    [
        # The VM has been up for 2 minutes, but the run started an hour ago.
        ("gone 120 9000000 kept", "the VM restarted"),
        ("gone 99999 9000000 deleted", "its log and result were deleted"),
        ("gone 99999 9000000 kept", "something ended its processes"),
    ],
)
def test_why_a_run_ended_without_its_exit_code(vms, run, monkeypatch, answer, why):
    monkeypatch.setattr(VM, "exec", lambda self, command, timeout=600, input=None, tag=None: subprocess.CompletedProcess([], 0, answer + "\n", ""))

    result = long_runs.check(vms.get("vm1"), run)

    assert result["ended"] == "gone"
    assert result["why"].startswith(why)


# --- Internet use and what a VM uses ---------------------------------------------------------------------------------


def test_internet_use_is_counted_once(vms, monkeypatch):
    record = vms.get("vm1")
    answers = ["boot-1\ndown 1000\nup 200\n", "boot-1\ndown 1500\nup 300\n", "boot-2\ndown 50\nup 10\n"]
    monkeypatch.setattr(record.vm, "exec_root", lambda command, timeout: subprocess.CompletedProcess([], 0, answers.pop(0), ""))

    record.count_traffic()
    record.count_traffic()
    # The VM booted again: its counters started from zero.
    record.count_traffic()

    assert record.traffic["down"] == 1550
    assert record.traffic["up"] == 310


def test_backend_restart_counts_nothing_twice(vms, monkeypatch):
    saved = copy.deepcopy(VM1)
    saved["traffic"] = {"down": 1000, "up": 200, "since": "2026-11-01T00:00:00+00:00", "boot_id": "boot-1", "last_down": 1000, "last_up": 200}
    record = VMRecord(saved, vms.changed)
    monkeypatch.setattr(record.vm, "exec_root", lambda command, timeout: subprocess.CompletedProcess([], 0, "boot-1\ndown 1000\nup 200\n", ""))

    record.count_traffic()

    assert record.traffic["down"] == 1000
    assert record.traffic["up"] == 200


def test_failed_read_gives_no_speed_and_counts_nothing(vms, monkeypatch):
    record = vms.get("vm1")
    record.net_down_rate = 1000.0
    record.net_up_rate = 100.0
    monkeypatch.setattr(record.vm, "exec_root", lambda command, timeout: subprocess.CompletedProcess([], 3, "", "No network yet"))

    record.count_traffic()

    assert record.net_down_rate is None
    assert record.net_up_rate is None
    assert record.traffic["down"] == 0


def test_vm_that_is_off_uses_nothing(vms, monkeypatch):
    record = vms.get("vm1")
    record.last_cpu = (10**9, 1.0)
    record.last_disk = (20.0, 1.0)
    monkeypatch.setattr(record.vm, "state", lambda: {"status": "Stopped"})

    assert record.read_usage() == USAGE_OFF
    # The next start measures from scratch.
    assert record.last_cpu is None
    assert record.last_disk is None


def test_frozen_vm_is_not_asked_inside(vms, monkeypatch):
    # Incus still says Running, but its agent doesn't answer (processes -1): no df and no internet counters, which
    # would hang. Asking would run a command, and no_commands fails the test then.
    record = vms.get("vm1")
    monkeypatch.setattr(record.vm, "state", lambda: {"status": "Running", "processes": -1, "cpu": {"usage": 10**9}, "memory": {"usage": 2 * 1024**3}})

    reading = record.read_usage()

    assert reading["on"] is True
    assert reading["responding"] is False
    assert reading["memory_used_gb"] == 2.0
    assert reading["disk_used_gb"] is None


# --- Copying files ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source, target, problem",
    [
        ("notes.txt", "/home/ubuntu", "Paths must be absolute"),
        ("/home/admin/notes.txt", "home/ubuntu", "Paths must be absolute"),
        ("/", "/home/ubuntu", "The whole disk can't be copied"),
    ],
)
def test_copy_into_the_vm_refuses(source, target, problem):
    with pytest.raises(FileTransferError, match=problem):
        file_transfer.to_vm(VM("sandbox-vm1"), source, target)


def test_copy_into_the_vm_needs_the_file_here(tmp_path):
    with pytest.raises(FileTransferError, match="is not on this computer anymore"):
        file_transfer.to_vm(VM("sandbox-vm1"), str(tmp_path / "gone.txt"), "/home/ubuntu")


def test_copy_into_the_vm_never_overwrites(tmp_path, monkeypatch):
    (tmp_path / "notes.txt").write_text("mine")
    vm = VM("sandbox-vm1")
    # The VM's own check: the folder is there and nothing in it has that name. Here something has.
    monkeypatch.setattr(vm, "exec", lambda command, timeout: subprocess.CompletedProcess([], 1, "", ""))

    with pytest.raises(FileTransferError, match="notes.txt is already in /home/ubuntu in the VM"):
        file_transfer.to_vm(vm, str(tmp_path / "notes.txt"), "/home/ubuntu")


def test_folder_is_copied_into_the_vm_whole_and_given_to_its_user(tmp_path, monkeypatch):
    (tmp_path / "project").mkdir()
    vm = VM("sandbox-vm1")
    owners = []
    pushed = []
    monkeypatch.setattr(vm, "exec", lambda command, timeout: subprocess.CompletedProcess([], 0, "ubuntu\n", ""))

    def exec_root(command, timeout):
        owners.append(command)
        return subprocess.CompletedProcess([], 0, "", "")

    def run(command, **kwargs):
        pushed.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(vm, "exec_root", exec_root)
    monkeypatch.setattr(subprocess, "run", run)

    file_transfer.to_vm(vm, str(tmp_path / "project"), "/home/ubuntu/")

    assert pushed == [["incus", "file", "push", "-r", str(tmp_path / "project"), "sandbox-vm1/home/ubuntu/"]]
    # incus file push writes as root.
    assert owners == ["chown -R ubuntu: /home/ubuntu/project"]


@pytest.mark.parametrize(
    "source, target, problem",
    [
        ("home/ubuntu/report.txt", "/tmp", "Paths must be absolute"),
        ("/home/ubuntu/report.txt", "tmp", "Paths must be absolute"),
        ("/", "/tmp", "The whole disk can't be copied"),
        ("/home/ubuntu/report.txt", "/no/such/folder", "is not a folder on this computer anymore"),
    ],
)
def test_copy_to_this_computer_refuses(source, target, problem):
    with pytest.raises(FileTransferError, match=problem):
        file_transfer.to_computer(VM("sandbox-vm1"), source, target)


def test_copy_to_this_computer_never_overwrites(tmp_path):
    (tmp_path / "report.txt").write_text("mine")

    with pytest.raises(FileTransferError, match="report.txt is already in"):
        file_transfer.to_computer(VM("sandbox-vm1"), "/home/ubuntu/report.txt", str(tmp_path))


def test_broken_link_counts_as_already_there(tmp_path):
    # Copying onto it would write wherever it points.
    (tmp_path / "report.txt").symlink_to(tmp_path / "somewhere-else.txt")

    with pytest.raises(FileTransferError, match="report.txt is already in"):
        file_transfer.to_computer(VM("sandbox-vm1"), "/home/ubuntu/report.txt", str(tmp_path))


def test_copy_of_what_is_gone_from_the_vm_is_refused(tmp_path, monkeypatch):
    vm = VM("sandbox-vm1")
    monkeypatch.setattr(vm, "exec", lambda command, timeout: subprocess.CompletedProcess([], 3, "", ""))

    with pytest.raises(FileTransferError, match="/home/ubuntu/report.txt is not in the VM anymore"):
        file_transfer.to_computer(vm, "/home/ubuntu/report.txt", str(tmp_path))


@pytest.mark.parametrize("returncode, recursive", [(0, ["-r"]), (1, [])])
def test_folder_from_the_vm_is_copied_whole(tmp_path, monkeypatch, returncode, recursive):
    # The VM's check exits 0 for a folder (test -d), 1 for a file.
    vm = VM("sandbox-vm1")
    pulled = []
    monkeypatch.setattr(vm, "exec", lambda command, timeout: subprocess.CompletedProcess([], returncode, "", ""))

    def run(command, **kwargs):
        pulled.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)

    file_transfer.to_computer(vm, "/home/ubuntu/project", str(tmp_path))

    assert pulled == [["incus", "file", "pull"] + recursive + ["sandbox-vm1/home/ubuntu/project", f"{tmp_path}/"]]


def test_vm_folder_listing(monkeypatch):
    vm = VM("sandbox-vm1")
    # pwd first, then one entry per \0: type, size, modified, name. A name may hold tabs.
    listing = "/home/ubuntu\nf\t12\t1700000000.5\tREADME.md\0d\t4096\t1700000000\tsrc\0f\t3\t1\tname\twith\ttabs\0d\t4096\t1\tDocs\0"
    monkeypatch.setattr(vm, "exec", lambda command, timeout: subprocess.CompletedProcess([], 0, listing, ""))

    folder = file_transfer.list_vm(vm, "")

    assert folder["path"] == "/home/ubuntu"
    assert folder["parent"] == "/home"
    # Folders first, then by name whatever its capitals.
    assert [entry["name"] for entry in folder["entries"]] == ["Docs", "src", "name\twith\ttabs", "README.md"]
    assert folder["entries"][3] == {"name": "README.md", "kind": "file", "size": 12, "modified": 1700000000.5}


def test_vm_root_folder_has_no_parent(monkeypatch):
    vm = VM("sandbox-vm1")
    monkeypatch.setattr(vm, "exec", lambda command, timeout: subprocess.CompletedProcess([], 0, "/\nd\t4096\t1\thome\0", ""))

    folder = file_transfer.list_vm(vm, "/")

    assert folder["parent"] is None
    assert folder["entries"] == [{"name": "home", "kind": "folder", "size": 4096, "modified": 1.0}]


def test_vm_folder_that_cant_be_opened(monkeypatch):
    vm = VM("sandbox-vm1")
    monkeypatch.setattr(vm, "exec", lambda command, timeout: subprocess.CompletedProcess([], 3, "", "bash: cd: /root: Permission denied\n"))

    with pytest.raises(FileTransferError, match="Permission denied"):
        file_transfer.list_vm(vm, "/root")


def test_computer_folder_listing(tmp_path):
    (tmp_path / "b.txt").write_text("hi")
    (tmp_path / "A.txt").write_text("hello")
    (tmp_path / "zdir").mkdir()
    (tmp_path / "broken").symlink_to(tmp_path / "gone")

    folder = file_transfer.list_computer(str(tmp_path))

    assert folder["path"] == str(tmp_path)
    assert [entry["name"] for entry in folder["entries"]] == ["zdir", "A.txt", "b.txt", "broken"]
    # A broken link is still listed, as a file of size 0.
    assert folder["entries"][3] == {"name": "broken", "kind": "file", "size": 0, "modified": 0}


def test_computer_listing_needs_a_folder(tmp_path):
    (tmp_path / "notes.txt").write_text("hi")

    with pytest.raises(FileTransferError, match="is not a folder on this computer"):
        file_transfer.list_computer(str(tmp_path / "notes.txt"))


# --- This computer's GPUs --------------------------------------------------------------------------------------------


def test_gpu_given_to_a_vm(usage, gpu, tmp_path):
    (gpu["device"] / "driver").symlink_to(tmp_path / "drivers" / "vfio-pci")

    assert usage.read_gpu(gpu)["state"] == "in_vm"


def test_nvidia_gpu_without_its_driver(usage, gpu):
    assert usage.read_gpu(gpu)["state"] == "no_driver"


def test_sleeping_nvidia_gpu_is_never_woken(usage, gpu, tmp_path):
    # nvidia-smi wakes it and keeps it awake, draining the battery. Running it fails the test (no_commands).
    (gpu["device"] / "driver").symlink_to(tmp_path / "drivers" / "nvidia")
    (gpu["device"] / "power" / "runtime_status").write_text("suspended\n")
    usage.watchers = 1

    assert usage.read_gpu(gpu)["state"] == "asleep"


def test_nvidia_gpu_is_asked_only_while_a_resource_page_is_open(usage, gpu, tmp_path):
    (gpu["device"] / "driver").symlink_to(tmp_path / "drivers" / "nvidia")

    assert usage.read_gpu(gpu)["state"] == "not_watched"


def test_nvidia_gpu_numbers(usage, gpu, tmp_path, monkeypatch):
    (gpu["device"] / "driver").symlink_to(tmp_path / "drivers" / "nvidia")
    usage.watchers = 1
    answer = "NVIDIA GeForce RTX 4060 Laptop GPU, 37, 1024, 8192, 52, [N/A], 2100\n"
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0, answer, ""))

    reading = usage.read_gpu(gpu)

    assert reading["state"] == "on"
    assert reading["percent"] == 37.0
    assert reading["memory_used_gb"] == 1.0
    assert reading["memory_total_gb"] == 8.0
    assert reading["temp_c"] == 52.0
    # What this GPU doesn't report is None, not an error.
    assert reading["power_w"] is None
    assert reading["mhz"] == 2100.0
    # The driver's name is kept for when it sleeps.
    assert gpu["name"] == "NVIDIA GeForce RTX 4060 Laptop GPU"


def test_nvidia_answer_that_cant_be_read(usage, gpu, tmp_path, monkeypatch):
    (gpu["device"] / "driver").symlink_to(tmp_path / "drivers" / "nvidia")
    usage.watchers = 1
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 9, "", "No devices were found"))

    assert usage.read_gpu(gpu)["state"] == "error"


def test_built_in_amd_graphics_leave_out_the_whole_chips_power(usage, gpu, tmp_path):
    device = gpu["device"]
    gpu["vendor"] = "amd"
    (device / "driver").symlink_to(tmp_path / "drivers" / "amdgpu")
    (device / "gpu_busy_percent").write_text("12\n")
    (device / "mem_info_vram_used").write_text(f"{512 * 1024**2}\n")
    (device / "mem_info_vram_total").write_text(f"{2 * 1024**3}\n")
    (device / "mem_info_gtt_used").write_text(f"{1024**3}\n")
    (device / "mem_info_gtt_total").write_text(f"{8 * 1024**3}\n")
    hwmon = device / "hwmon" / "hwmon3"
    hwmon.mkdir(parents=True)
    (hwmon / "temp1_input").write_text("45000\n")
    (hwmon / "freq1_input").write_text("800000000\n")
    # PPT is the whole chip's power, CPU too.
    (hwmon / "power1_input").write_text("15000000\n")
    (hwmon / "power1_label").write_text("PPT\n")

    reading = usage.read_gpu(gpu)

    assert reading["state"] == "on"
    assert reading["percent"] == 12
    assert reading["memory_used_gb"] == 0.5
    assert reading["shared_total_gb"] == 8.0
    assert reading["temp_c"] == 45.0
    assert reading["mhz"] == 800.0
    assert reading["power_w"] is None


# --- Images ----------------------------------------------------------------------------------------------------------


def test_incus_image_list_is_read(images, monkeypatch):
    listed = [
        # A download a build started from: not ours, so not listed.
        {"aliases": [], "fingerprint": "a" * 64, "size": 1024**3, "created_at": "2026-11-01T00:00:00Z"},
        {"aliases": [{"name": "dev-vm"}, {"name": "dev"}], "fingerprint": "b" * 64, "size": 3 * 1024**3, "created_at": "2026-11-02T00:00:00Z"},
        {"aliases": [{"name": "base-image"}], "fingerprint": "c" * 64, "size": 2 * 1024**3, "created_at": "2026-11-03T00:00:00Z"},
    ]
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0, json.dumps(listed), ""))

    images.refresh()
    images.refresh()

    assert images.names() == ["base-image", "dev"]
    assert images.find("dev-vm")["aliases"] == ["dev", "dev-vm"]
    assert images.find("dev-vm")["size_gb"] == 3.0
    # The second read found nothing new.
    assert images.version == 1


def test_image_names_are_the_same_whatever_their_capitals(images, tmp_path):
    images.images = [{"name": "Ubuntu-1", "aliases": ["Ubuntu-1"], "fingerprint": "a" * 64, "size_gb": 1.0, "created_at": ""}]
    (tmp_path / "images" / "definitions" / "never-built").mkdir(parents=True)
    (tmp_path / "images" / "definitions" / "never-built" / "image.yaml").write_text("system: ubuntu-24.04\ndesktop: none\n")

    assert images.name_taken("ubuntu-1") is True
    assert images.name_taken("NEVER-BUILT") is True
    assert images.name_taken("other") is False


@pytest.mark.parametrize("name", ["../vms", "a/b", ".hidden", "1-image", "", "-x"])
def test_image_name_from_a_url_stays_in_its_folder(images, tmp_path, name):
    with pytest.raises(ImagesError, match="can't have a definition"):
        images.image_dir(name)
    assert not (tmp_path / "images" / "definitions").exists()


def test_image_folder_is_made_under_the_definitions(images, tmp_path):
    folder = images.image_dir("Dev-VM")

    assert folder == tmp_path / "images" / "definitions" / "Dev-VM"
    assert folder.is_dir()


def test_task_log_from_a_url_stays_in_its_folder(images, tmp_path):
    (tmp_path / "images" / "task_a1b2c3.log").write_text("==> Done\n")
    (tmp_path / "vms").mkdir()
    (tmp_path / "vms" / "vm1.log").write_text("not a task's")

    assert images.read_log("task_a1b2c3") == "==> Done\n"
    assert images.read_log("../vms/vm1") == ""
    assert images.read_log("task_A1B2C3") == ""
    assert images.read_log("task_ffffff") == ""


def test_inventory_is_found_only_by_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr(images_module, "INVENTORY_DIR", tmp_path / "inventory")
    (tmp_path / "inventory").mkdir()
    (tmp_path / "inventory" / f"{'d' * 64}.json").write_text(json.dumps({"image": "dev-vm"}))
    (tmp_path / "secret.json").write_text(json.dumps({"token": "not an inventory"}))

    assert images_module.load_inventory("d" * 64) == {"image": "dev-vm"}
    assert images_module.load_inventory("e" * 64) is None
    assert images_module.load_inventory("../secret") is None


def test_inventory_highlights_count_the_packages(images, tmp_path):
    inventory = {
        "image": "dev-vm",
        "inspected_at": "2026-11-02T00:00:00Z",
        "system": "Ubuntu 24.04",
        "languages": [{"name": "Python", "version": "3.12"}],
        "tools": [{"name": "git", "version": "2.43"}],
        "packages": [
            {"kind": "apt", "name": "ripgrep"},
            {"kind": "apt", "name": "fd-find"},
            {"kind": "docker", "name": "postgres:17"},
            {"kind": "pip", "name": "pydantic"},
        ],
        "models": [],
        "caches": [],
    }
    (tmp_path / "images" / "inventory").mkdir()
    (tmp_path / "images" / "inventory" / f"{'d' * 64}.json").write_text(json.dumps(inventory))

    highlights = images.highlights("d" * 64)

    assert highlights["counts"] == {"apt": 2, "docker": 1, "pip": 1}
    assert highlights["docker_images"] == ["postgres:17"]
    assert "packages" not in highlights


def test_task_that_ended_with_done_is_dropped(images, tmp_path, monkeypatch):
    monkeypatch.setattr(images, "refresh", lambda: None)
    images.tasks = [{"id": "task_a1b2c3", "kind": "build", "name": "dev-vm", "vm": None, "pid": GONE_PID, "status": "running", "error": None}]
    (tmp_path / "images" / "task_a1b2c3.log").write_text("==> Base layer\n==> Done\n")

    images.check_tasks()

    assert images.tasks == []
    assert images.task_state("task_a1b2c3") == ("done", None)
    assert not (tmp_path / "images" / "task_a1b2c3.log").exists()


@pytest.mark.parametrize(
    "log, stopped, error",
    [
        ("==> Packages\nE: Unable to locate package fd\n", False, "E: Unable to locate package fd"),
        ("", False, "It stopped without a word."),
        ("==> Packages\nTerminated\n", True, "Stopped by you."),
    ],
)
def test_task_that_ended_without_done_failed(images, tmp_path, monkeypatch, log, stopped, error):
    monkeypatch.setattr(images, "refresh", lambda: None)
    images.tasks = [{"id": "task_a1b2c3", "kind": "build", "name": "dev-vm", "vm": None, "pid": GONE_PID, "status": "running", "error": None, "stopped": stopped}]
    (tmp_path / "images" / "task_a1b2c3.log").write_text(log)

    images.check_tasks()

    assert images.task_state("task_a1b2c3") == ("failed", error)
    # Failed ones stay, with their log, until the user dismisses them.
    assert json.loads((tmp_path / "images" / "tasks.json").read_text())[0]["status"] == "failed"
    assert (tmp_path / "images" / "task_a1b2c3.log").exists()


def test_image_a_vm_was_made_from_stays(images, vms):
    images.images = [{"name": "dev-vm", "aliases": ["dev-vm"], "fingerprint": "f" * 64, "size_gb": 3.0, "created_at": ""}]
    # Stopped VMs count too.
    vms.get("vm1").image_fingerprint = "f" * 64
    vms.get("vm1").status = "stopped"

    with pytest.raises(ImagesError, match=r"VMs were made from dev-vm \(vm1\)"):
        images.delete("dev-vm")
    assert images.names() == ["dev-vm"]
