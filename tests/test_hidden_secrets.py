"""The user's secrets: env variables for all VMs and each VM's own (sandbox/vms.py), and what agents see of them
(sandbox/agent/tools.py, github_searcher/agent/work_tools.py).

A variable's name is checked; a VM's own value wins over the one for all VMs unless it is empty; values are quoted for
the shell; the VM list sent to the browser has names only. Agents see names and whether each is set, may add only empty
ones and remove only empty ones. Any value (HIDE_MIN_LENGTH or longer) that shows up in what an agent gets back from a VM
is replaced with [hidden], longest first, read again at that moment: a command's output, a run's result, vm_health, a
browser page, a test run and command evidence.

Nothing here runs a command: the VM's answers are stand-ins, and records, the env file for all VMs, jobs and evidence are
kept in pytest's temporary folder, never in DATA_DIR. work_tools.py is imported with tests/conftest.py's settings: the
vault and the tokens are never read."""

import asyncio
import copy
import json
import subprocess
import threading
import types

import pytest

from github_searcher import jobs as jobs_module
from github_searcher.agent import work_tools
from github_searcher.jobs import Jobs
from sandbox import vms as vms_module
from sandbox.agent.computer_use import Computer
from sandbox.agent.tools import ComputerTools
from sandbox.vm import VM
from sandbox.vm_queue import VMQueue
from sandbox.vms import VM_ENV_FILE, VMRecord, VMs, VMsError

SECRET = "sk-live-4f9a2c7e"
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
    """The VMs, with vm1 only, saved in a temporary folder, and no env variables for all VMs."""
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
def vm_calls(monkeypatch):
    """Every VM runs, and what it is asked is kept instead of done: the files it would write ({path: content}) and the
    commands it would run ([(desktop, command)]), which all succeed."""
    calls = {"files": {}, "commands": []}

    def write_file(self, path, content, mode="0644"):
        calls["files"][path] = content

    def run_command(self, command, timeout=600, input=None, tag=None):
        calls["commands"].append((self.desktop, command))
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(VM, "status", lambda self: "Running")
    monkeypatch.setattr(VM, "write_file", write_file)
    monkeypatch.setattr(VM, "exec", run_command)
    return calls


@pytest.fixture
def tools(vms):
    """agent_a's VM tools; it holds vm1's desktop 1."""
    vms.get("vm1").desktops[1]["holder"] = "agent_a"
    return ComputerTools(vms, VMQueue(vms), "agent_a", lambda: "vm1", [])


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    """The jobs, kept in a temporary folder, and the evidence files and the test runs' log work_tools writes for them too."""
    monkeypatch.setattr(jobs_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(work_tools, "EVIDENCE_DIR", tmp_path / "evidence")
    monkeypatch.setattr(work_tools, "TEST_RUNS_FILE", tmp_path / "test_runs.jsonl")
    return Jobs()


# --- Env variables -------------------------------------------------------------------------------------------------


def test_vms_own_value_wins_unless_it_is_empty(vms, vm_calls, monkeypatch):
    monkeypatch.setattr(VMRecord, "global_env", {"OPENAI_API_KEY": "sk-for-all-vms", "SENTRY_DSN": "https://all@sentry", "EMPTY": ""})
    record = vms.get("vm1")
    # SENTRY_DSN: an agent asked for it on this VM and nobody filled it in, so the one for all VMs is used.
    record.env = {"OPENAI_API_KEY": "sk-for-vm1-only", "SENTRY_DSN": "", "DB_PASSWORD": "hunter22"}

    record.write_env()

    assert vm_calls["files"][VM_ENV_FILE].splitlines()[1:] == [
        "export OPENAI_API_KEY=sk-for-vm1-only",
        "export SENTRY_DSN=https://all@sentry",
        "export EMPTY=''",
        "export DB_PASSWORD=hunter22",
    ]


def test_values_are_quoted_for_the_shell(vms, vm_calls):
    record = vms.get("vm1")
    record.env = {"PASSWORD": "it's $(reboot)"}

    record.write_env()

    assert "export PASSWORD='it'\"'\"'s $(reboot)'\n" in vm_calls["files"][VM_ENV_FILE]


def test_env_file_is_read_on_every_desktop(vms, vm_calls):
    record = vms.get("vm1")
    record.desktops = {1: {"holder": None}, 3: {"holder": None}}

    record.write_env()

    assert [desktop for desktop, command in vm_calls["commands"]] == [1, 3]
    assert f". {VM_ENV_FILE}" in vm_calls["commands"][1][1]
    assert "~/.bashrc" in vm_calls["commands"][1][1]


@pytest.mark.parametrize("name", ["1PASSWORD", "MY-KEY", "MY KEY", "KEY;reboot", ""])
def test_bad_variable_names_are_refused(vms, vm_calls, name):
    with pytest.raises(VMsError, match="Not a valid variable name"):
        vms.get("vm1").set_env({name: "value"})
    with pytest.raises(VMsError, match="Not a valid variable name"):
        vms.set_global_env({name: "value"})
    assert vm_calls["files"] == {}


def test_vm_list_has_names_never_values(vms):
    record = vms.get("vm1")
    record.env = {"DB_PASSWORD": SECRET}

    summary = vms.summary(record)

    assert summary["env_names"] == ["DB_PASSWORD"]
    assert "env" not in summary
    assert SECRET not in json.dumps(summary)


def test_agent_adds_an_empty_variable_for_all_vms(vms, vm_calls, tmp_path):
    vms.add_empty_global_env("OPENAI_API_KEY")

    assert VMRecord.global_env == {"OPENAI_API_KEY": ""}
    assert json.loads((tmp_path / "global_env.json").read_text()) == {"OPENAI_API_KEY": ""}
    # vm1 runs, so it gets it at once.
    assert "export OPENAI_API_KEY=''\n" in vm_calls["files"][VM_ENV_FILE]


def test_variable_for_all_vms_with_a_value_stays(vms, monkeypatch):
    monkeypatch.setattr(VMRecord, "global_env", {"OPENAI_API_KEY": SECRET})

    with pytest.raises(VMsError, match="OPENAI_API_KEY already exists, for all VMs"):
        vms.add_empty_global_env("OPENAI_API_KEY")
    with pytest.raises(VMsError, match="OPENAI_API_KEY has a value; only the user can remove it"):
        vms.remove_empty_global_env("OPENAI_API_KEY")
    assert VMRecord.global_env == {"OPENAI_API_KEY": SECRET}


# --- What the agent sees of them -----------------------------------------------------------------------------------


def test_agent_sees_names_never_values(vms, tools, monkeypatch):
    monkeypatch.setattr(VMRecord, "global_env", {"OPENAI_API_KEY": "sk-for-all-vms", "SENTRY_DSN": ""})
    vms.get("vm1").env = {"DB_PASSWORD": SECRET, "OPENAI_API_KEY": ""}

    text = asyncio.run(tools.env_vars({}))["content"][0]["text"]

    assert text.splitlines() == [
        "DB_PASSWORD: set",
        "OPENAI_API_KEY: empty",
        "OPENAI_API_KEY: set (for all VMs)",
        "SENTRY_DSN: empty (for all VMs)",
    ]


def test_vms_own_value_hides_the_one_for_all_vms(vms, tools, monkeypatch):
    monkeypatch.setattr(VMRecord, "global_env", {"OPENAI_API_KEY": "sk-for-all-vms"})
    vms.get("vm1").env = {"OPENAI_API_KEY": SECRET}

    text = asyncio.run(tools.env_vars({}))["content"][0]["text"]

    assert text == "OPENAI_API_KEY: set"


def test_agent_without_a_vm_sees_only_the_ones_for_all_vms(vms, monkeypatch):
    monkeypatch.setattr(VMRecord, "global_env", {"OPENAI_API_KEY": SECRET})
    vms.get("vm1").env = {"DB_PASSWORD": SECRET}
    tools = ComputerTools(vms, VMQueue(vms), "agent_b", lambda: None, [])

    text = asyncio.run(tools.env_vars({}))["content"][0]["text"]

    assert text.splitlines() == [
        "(You hold no VM, so only the ones for all VMs are listed.)",
        "OPENAI_API_KEY: set (for all VMs)",
    ]


def test_agent_can_only_add_an_empty_variable(vms, tools, vm_calls):
    asyncio.run(tools.env_var_add({"name": "OPENAI_API_KEY", "value": SECRET}))

    assert vms.get("vm1").env == {"OPENAI_API_KEY": ""}
    assert SECRET not in vm_calls["files"][VM_ENV_FILE]


def test_agent_without_a_vm_adds_one_for_all_vms(vms, vm_calls):
    tools = ComputerTools(vms, VMQueue(vms), "agent_b", lambda: None, [])

    asyncio.run(tools.env_var_add({"name": "OPENAI_API_KEY", "for_all_vms": True}))

    assert VMRecord.global_env == {"OPENAI_API_KEY": ""}


def test_agent_cannot_add_a_variable_that_is_there(vms, tools, monkeypatch):
    monkeypatch.setattr(VMRecord, "global_env", {"OPENAI_API_KEY": SECRET})
    vms.get("vm1").env = {"DB_PASSWORD": ""}

    with pytest.raises(ValueError, match="OPENAI_API_KEY is already set, for all VMs"):
        asyncio.run(tools.env_var_add({"name": "OPENAI_API_KEY"}))
    with pytest.raises(ValueError, match="DB_PASSWORD already exists"):
        asyncio.run(tools.env_var_add({"name": "DB_PASSWORD"}))


def test_agent_removes_only_empty_variables(vms, tools, vm_calls):
    vms.get("vm1").env = {"DB_PASSWORD": SECRET, "OPENAI_API_KEY": ""}

    with pytest.raises(ValueError, match="DB_PASSWORD has a value; only the user can remove it"):
        asyncio.run(tools.env_var_remove({"name": "DB_PASSWORD"}))
    asyncio.run(tools.env_var_remove({"name": "OPENAI_API_KEY"}))

    assert vms.get("vm1").env == {"DB_PASSWORD": SECRET}


# --- [hidden] in the agent's VM tools ------------------------------------------------------------------------------


def test_secrets_in_a_commands_output_are_hidden(vms, tools, monkeypatch):
    monkeypatch.setattr(VMRecord, "global_env", {"OPENAI_API_KEY": "sk-for-all-vms"})
    vms.get("vm1").env = {"DB_PASSWORD": SECRET}
    monkeypatch.setattr(Computer, "check", lambda self: None)
    monkeypatch.setattr(Computer, "bash", lambda self, command, timeout: f"DB_PASSWORD={SECRET}\nOPENAI_API_KEY=sk-for-all-vms\nexit code 0")

    text = asyncio.run(tools.bash({"command": "env"}))["content"][0]["text"]

    assert text == "DB_PASSWORD=[hidden]\nOPENAI_API_KEY=[hidden]\nexit code 0"


def test_value_holding_another_is_hidden_whole(vms, tools, monkeypatch):
    # Longest first: hiding "sk-live" first would leave the rest of the longer value showing.
    monkeypatch.setattr(VMRecord, "global_env", {"PREFIX": "sk-live"})
    vms.get("vm1").env = {"API_KEY": SECRET}
    monkeypatch.setattr(Computer, "check", lambda self: None)
    monkeypatch.setattr(Computer, "bash", lambda self, command, timeout: f"key={SECRET}")

    text = asyncio.run(tools.bash({"command": "echo key=$API_KEY"}))["content"][0]["text"]

    assert text == "key=[hidden]"


def test_short_values_are_not_hidden(vms, tools, monkeypatch):
    # Hiding "1" or "yes" would garble everything, and values that short are not secrets.
    vms.get("vm1").env = {"DEBUG": "1", "COLOR": "yes", "API_KEY": SECRET}
    monkeypatch.setattr(Computer, "check", lambda self: None)
    monkeypatch.setattr(Computer, "bash", lambda self, command, timeout: f"DEBUG=1 COLOR=yes API_KEY={SECRET}")

    text = asyncio.run(tools.bash({"command": "env"}))["content"][0]["text"]

    assert text == "DEBUG=1 COLOR=yes API_KEY=[hidden]"


def test_output_from_a_desktop_lost_meanwhile_is_not_shown(vms, tools, monkeypatch):
    record = vms.get("vm1")

    def bash(self, command, timeout):
        # The user takes the desktop over while the command runs.
        record.desktops[1]["holder"] = "user"
        return "what is in ~/.env"

    monkeypatch.setattr(Computer, "check", lambda self: None)
    monkeypatch.setattr(Computer, "bash", bash)

    with pytest.raises(ValueError, match="You lost the VM while the command ran"):
        asyncio.run(tools.bash({"command": "cat ~/.env"}))


def test_run_result_hides_values_read_when_it_ends(vms, tools):
    record = vms.get("vm1")
    run = {"id": "run_1", "log": "~/.cache/sandbox-runs/run_1.log", "stopped_by_user": False}
    result = {"ended": "exit", "exit_code": 0, "output": f"token {SECRET}\n", "seconds": 75}
    # The user set it while the run went.
    record.env = {"API_TOKEN": SECRET}

    text = tools.bash_result(record, run, result)

    assert text == "exit code 0, after 1m 15s\n--- output (stdout and stderr) ---\ntoken [hidden]\n"


def test_vm_health_hides_secrets_in_command_lines(vms, tools, monkeypatch):
    record = vms.get("vm1")
    record.env = {"API_KEY": SECRET}
    monkeypatch.setattr(record.vm, "state", lambda: {"status": "Running", "memory": {"usage": 2 * 1024**3}})
    monkeypatch.setattr(record.vm, "responds", lambda: True)
    monkeypatch.setattr(record.vm, "exec_root", lambda command, timeout: subprocess.CompletedProcess([], 0, f"python serve.py --api-key {SECRET}\n", ""))
    monkeypatch.setattr(record.vm, "console_log", lambda: f"Out of memory: Killed process 42 (node --token={SECRET})\n")

    text = asyncio.run(tools.vm_health({}))["content"][0]["text"]

    assert SECRET not in text
    assert "python serve.py --api-key [hidden]" in text
    assert "Out of memory: Killed process 42 (node --token=[hidden])" in text


def test_browser_page_hides_secrets(vms, tools, monkeypatch):
    vms.get("vm1").env = {"API_KEY": SECRET}
    answer = json.dumps({"text": f"Settings\nAPI key: {SECRET}"})
    # A login shell may print something first: the answer is the last line.
    monkeypatch.setattr(VM, "exec", lambda self, command, timeout=600, input=None, tag=None: subprocess.CompletedProcess([], 0, f"Welcome\n{answer}\n", ""))

    content = asyncio.run(tools.browser_read({}))["content"]

    assert content == [{"type": "text", "text": "Settings\nAPI key: [hidden]"}]


# --- [hidden] in the agent's work tools ----------------------------------------------------------------------------


def test_test_run_hides_secrets_in_its_command_and_output(vms, jobs, tmp_path):
    record = vms.get("vm1")
    record.env = {"API_TOKEN": SECRET}
    job = jobs.create("fix_issue", "Fix the crash", "agent_a", "user", issue="owner/name#1")
    tools = work_tools.WorkTools(types.SimpleNamespace(jobs=jobs), {"id": "agent_a", "target_vm": "vm1"})
    run = {
        "job": job["id"],
        "when": "before",
        "scope": "full",
        "command": f"API_TOKEN={SECRET} pytest",
        "base": "main",
        "path": "~/name",
        "diff_hash": "",
        "stopped_by_user": False,
    }
    ended = {"ended": "exit", "exit_code": 0, "output": f"connecting with {SECRET}\n12 passed\n", "seconds": 40}

    answer = asyncio.run(tools.finish_tests(record, run, ended))

    job = jobs.get(job["id"])
    evidence = job["evidence"][0]
    assert SECRET not in answer["content"][0]["text"]
    assert "connecting with [hidden]" in answer["content"][0]["text"]
    assert job["tests"]["before"]["command"] == "API_TOKEN=[hidden] pytest"
    assert evidence["command"] == "API_TOKEN=[hidden] pytest"
    assert SECRET not in evidence["output_tail"]
    assert SECRET not in (tmp_path / "evidence" / evidence["output_file"]).read_text()


def test_command_evidence_hides_secrets(vms, jobs, monkeypatch, tmp_path):
    record = vms.get("vm1")
    record.desktops[1]["holder"] = "agent_a"
    record.env = {"API_TOKEN": SECRET}
    job = jobs.create("fix_issue", "Fix the crash", "agent_a", "user", issue="owner/name#1")
    monkeypatch.setattr(VM, "exec", lambda self, command, timeout=600, input=None, tag=None: subprocess.CompletedProcess([], 1, f"401: bad token {SECRET}\n", ""))
    tools = work_tools.WorkTools(types.SimpleNamespace(jobs=jobs, vms=vms), {"id": "agent_a", "target_vm": "vm1"})

    answer = asyncio.run(
        tools.evidence_add({
            "job_id": job["id"],
            "kind": "command",
            "stage": "before",
            "topic": "the crash",
            "caption": "The request is refused",
            "context": "The app sends the token and the server refuses it before the fix.",
            "command": f"curl -H 'Authorization: {SECRET}' localhost:8080",
        })
    )

    evidence = jobs.get(job["id"])["evidence"][0]
    assert SECRET not in answer["content"][0]["text"]
    assert evidence["command"] == "curl -H 'Authorization: [hidden]' localhost:8080"
    assert evidence["output_tail"] == "401: bad token [hidden]"
    assert SECRET not in (tmp_path / "evidence" / evidence["output_file"]).read_text()
