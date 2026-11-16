"""An agent's artifacts folder (github_searcher/artifacts.py): every path must stay inside the agent's own folder (no ..,
no absolute path, no link that points out), nothing is overwritten, and what comes out of a VM is cleaned of links.

The VM is faked (its exec answers the size, and the copy out of it is a function of the test that writes into the
hidden folder), and the artifacts are kept in pytest's temporary folder, never in DATA_DIR."""

import os
import shlex
from types import SimpleNamespace

import pytest

from github_searcher import artifacts
from github_searcher.artifacts import FROM_VM_LIMIT, Artifacts, ArtifactsError

AGENT = "agent_a1b2c3"
OTHER = "agent_d4e5f6"


class FakeVM:
    """A VM, faked: exec answers `du` with `size` (returncode `found` 0 or 1). The fake copies note their sources."""

    def __init__(self, size):
        self.size = size
        self.found = 0
        self.commands = []
        self.copied = []

    def exec(self, command, timeout):
        self.commands.append(command)
        return SimpleNamespace(returncode=self.found, stdout=f"{self.size}\n")


def copy_logs_with_links(vm, source, folder):
    """The copy of a logs folder whose VM user left links in it: one to a file of the computer, one to a folder."""
    vm.copied.append(source)
    logs = os.path.join(folder, "logs")
    os.mkdir(logs)
    with open(os.path.join(logs, "app.log"), "w") as file:
        file.write("started\n")
    os.symlink("/etc/passwd", os.path.join(logs, "passwd"))
    os.symlink("/home", os.path.join(logs, "home"))


def copy_a_link(vm, source, folder):
    """The copy of a path that is itself a link in the VM."""
    vm.copied.append(source)
    os.symlink("/etc", os.path.join(folder, "logs"))


@pytest.fixture
def agent_files(tmp_path, monkeypatch):
    """Artifacts kept in a temporary folder's artifacts/."""
    monkeypatch.setattr(artifacts, "ROOT", tmp_path / "artifacts")
    return Artifacts()


@pytest.fixture
def base(agent_files, tmp_path):
    """The agent's own folder."""
    return agent_files.resolve(AGENT, "")


def test_empty_path_is_the_agents_folder(agent_files, tmp_path):
    folder = agent_files.resolve(AGENT, "")

    assert folder == (tmp_path / "artifacts" / AGENT).resolve()
    assert folder.is_dir()


def test_path_in_the_folder(agent_files, base):
    assert agent_files.resolve(AGENT, "screenshots/before.png") == base / "screenshots" / "before.png"
    assert agent_files.resolve(AGENT, " screenshots/./before.png ") == base / "screenshots" / "before.png"


@pytest.mark.parametrize(
    "path",
    [
        "..",
        "../",
        f"../{OTHER}/notes.txt",
        "../../.env",
        f"screenshots/../../{OTHER}",
        "a/b/../../../x",
        " ../x ",
        "/../../x",
    ],
)
def test_path_out_of_the_folder_is_refused(agent_files, path):
    with pytest.raises(ArtifactsError, match="is not in the artifacts"):
        agent_files.resolve(AGENT, path)


def test_folder_whose_name_starts_the_same_is_not_inside(agent_files):
    # agent_a1b2c3-copy starts with agent_a1b2c3 as text, but it is another folder.
    with pytest.raises(ArtifactsError, match="is not in the artifacts"):
        agent_files.resolve(AGENT, f"../{AGENT}-copy/notes.txt")


def test_absolute_path_counts_from_the_agents_folder(agent_files, base):
    assert agent_files.resolve(AGENT, "/etc/passwd") == base / "etc" / "passwd"
    assert agent_files.resolve(AGENT, "//etc/passwd") == base / "etc" / "passwd"


def test_link_that_points_out_is_refused(agent_files, base, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    os.symlink(outside, base / "out")
    os.symlink("/etc", base / "etc")

    with pytest.raises(ArtifactsError):
        agent_files.resolve(AGENT, "out/secret.txt")
    with pytest.raises(ArtifactsError):
        agent_files.resolve(AGENT, "out")
    with pytest.raises(ArtifactsError):
        agent_files.resolve(AGENT, "etc/passwd")


def test_link_to_another_agents_folder_is_refused(agent_files, base):
    other = agent_files.resolve(OTHER, "")
    (other / "notes.txt").write_text("not yours")
    os.symlink(other, base / "theirs")

    with pytest.raises(ArtifactsError):
        agent_files.resolve(AGENT, "theirs/notes.txt")


def test_link_that_stays_inside_is_followed(agent_files, base):
    (base / "screenshots").mkdir()
    os.symlink(base / "screenshots", base / "latest")

    assert agent_files.resolve(AGENT, "latest/before.png") == base / "screenshots" / "before.png"


def test_save_makes_a_new_file_and_says_where(agent_files, base):
    changes = []
    agent_files.on_change = lambda: changes.append(1)

    name = agent_files.save(AGENT, "screenshots/before.png", b"png")

    assert name == "screenshots/before.png"
    assert (base / "screenshots" / "before.png").read_bytes() == b"png"
    assert agent_files.stamps[AGENT] == 1
    assert changes == [1]


def test_nothing_is_overwritten(agent_files, base):
    agent_files.save(AGENT, "notes.txt", b"first")

    with pytest.raises(ArtifactsError, match="already in the artifacts"):
        agent_files.save(AGENT, "notes.txt", b"second")
    assert (base / "notes.txt").read_bytes() == b"first"


def test_save_out_of_the_folder_is_refused(agent_files, tmp_path):
    with pytest.raises(ArtifactsError):
        agent_files.save(AGENT, f"../{OTHER}/evil.txt", b"x")

    assert not (tmp_path / "artifacts" / OTHER / "evil.txt").exists()


def test_new_file_refuses_a_link_that_points_out_at_nothing_yet(agent_files, base, tmp_path):
    # Writing through it would make a file out of the folder.
    os.symlink(tmp_path / "outside" / "evil.txt", base / "notes.txt")

    with pytest.raises(ArtifactsError, match="is not in the artifacts"):
        agent_files.save(AGENT, "notes.txt", b"x")
    assert not (tmp_path / "outside").exists()


def test_make_folder(agent_files, base):
    agent_files.make_folder(AGENT, "screenshots/day 1")

    assert (base / "screenshots" / "day 1").is_dir()
    with pytest.raises(ArtifactsError, match="already in the artifacts"):
        agent_files.make_folder(AGENT, "screenshots/day 1")


def test_rename_keeps_it_in_the_same_folder(agent_files, base):
    agent_files.save(AGENT, "screenshots/before.png", b"png")

    agent_files.rename(AGENT, "screenshots/before.png", " after.png ")

    assert (base / "screenshots" / "after.png").read_bytes() == b"png"
    assert not (base / "screenshots" / "before.png").exists()


@pytest.mark.parametrize("new_name", ["", "  ", "a/b", f"../{OTHER}", "..", "."])
def test_rename_refuses_a_name_that_could_move_it(agent_files, base, new_name):
    agent_files.save(AGENT, "notes.txt", b"x")

    with pytest.raises(ArtifactsError, match="can't be empty or have a /"):
        agent_files.rename(AGENT, "notes.txt", new_name)
    assert (base / "notes.txt").exists()


@pytest.mark.parametrize("path", ["", "/", "screenshots/.."])
def test_the_folder_itself_cannot_be_renamed_or_deleted(agent_files, base, path):
    (base / "screenshots").mkdir()

    with pytest.raises(ArtifactsError, match="can't be renamed"):
        agent_files.rename(AGENT, path, "mine")
    with pytest.raises(ArtifactsError, match="can't be deleted"):
        agent_files.delete(AGENT, path)
    assert base.is_dir()


def test_rename_refuses_a_name_that_is_taken(agent_files, base):
    agent_files.save(AGENT, "a.txt", b"a")
    agent_files.save(AGENT, "b.txt", b"b")

    with pytest.raises(ArtifactsError, match="already in that folder"):
        agent_files.rename(AGENT, "a.txt", "b.txt")
    assert (base / "b.txt").read_bytes() == b"b"


def test_rename_of_something_gone_is_refused(agent_files):
    with pytest.raises(ArtifactsError, match="not in the artifacts anymore"):
        agent_files.rename(AGENT, "gone.txt", "new.txt")


def test_delete_a_file_and_a_folder_with_everything_in_it(agent_files, base):
    agent_files.save(AGENT, "notes.txt", b"x")
    agent_files.save(AGENT, "screenshots/day 1/before.png", b"png")

    agent_files.delete(AGENT, "notes.txt")
    agent_files.delete(AGENT, "screenshots")

    assert list(base.iterdir()) == []


def test_delete_of_something_gone_is_refused(agent_files):
    with pytest.raises(ArtifactsError, match="not in the artifacts anymore"):
        agent_files.delete(AGENT, "gone.txt")


def test_delete_cannot_reach_another_agents_folder(agent_files):
    agent_files.save(OTHER, "notes.txt", b"not yours")

    with pytest.raises(ArtifactsError):
        agent_files.delete(AGENT, f"../{OTHER}")
    with pytest.raises(ArtifactsError):
        agent_files.delete(AGENT, f"../{OTHER}/notes.txt")
    assert agent_files.resolve(OTHER, "notes.txt").read_bytes() == b"not yours"


def test_delete_all_takes_the_agents_folder(agent_files, tmp_path):
    agent_files.save(AGENT, "screenshots/before.png", b"png")
    agent_files.save(OTHER, "notes.txt", b"x")

    agent_files.delete_all(AGENT)

    assert not (tmp_path / "artifacts" / AGENT).exists()
    assert (tmp_path / "artifacts" / OTHER / "notes.txt").exists()


def test_list_has_folders_first_then_names_and_leaves_copies_coming_in_out(agent_files, base):
    agent_files.save(AGENT, "b.txt", b"bb")
    agent_files.save(AGENT, "A.txt", b"a")
    agent_files.make_folder(AGENT, "screenshots")
    agent_files.make_folder(AGENT, "Logs")
    (base / ".incoming-a1b2c3").mkdir()

    listing = agent_files.list(AGENT, "")

    assert listing["path"] == ""
    assert listing["parent"] is None
    assert [entry["name"] for entry in listing["entries"]] == ["Logs", "screenshots", "A.txt", "b.txt"]
    assert [entry["kind"] for entry in listing["entries"]] == ["folder", "folder", "file", "file"]
    assert listing["entries"][0]["size"] == 0
    assert listing["entries"][3]["size"] == 2


def test_list_gives_the_parent_of_a_folder(agent_files):
    agent_files.make_folder(AGENT, "screenshots/day 1")

    assert agent_files.list(AGENT, "screenshots")["parent"] == ""
    assert agent_files.list(AGENT, "screenshots/day 1")["path"] == "screenshots/day 1"
    assert agent_files.list(AGENT, "screenshots/day 1")["parent"] == "screenshots"


def test_list_of_a_file_is_refused(agent_files):
    agent_files.save(AGENT, "notes.txt", b"x")

    with pytest.raises(ArtifactsError, match="is not a folder"):
        agent_files.list(AGENT, "notes.txt")


def test_has_links_finds_a_link_anywhere_in_it(agent_files, base):
    agent_files.save(AGENT, "plain/notes.txt", b"x")
    agent_files.save(AGENT, "linked/deep/notes.txt", b"x")
    os.symlink(base / "plain" / "notes.txt", base / "linked" / "deep" / "link.txt")
    os.symlink(base / "plain", base / "shortcut")

    assert agent_files.has_links(AGENT, "plain") is False
    assert agent_files.has_links(AGENT, "plain/notes.txt") is False
    assert agent_files.has_links(AGENT, "linked") is True
    assert agent_files.has_links(AGENT, "") is True


def test_link_made_in_the_vm_never_comes_out_as_a_link(agent_files, base, monkeypatch):
    # A link made in the VM, copied out as it is, would point a later copy at a file of this computer: links are
    # taken out of what comes from the VM before it is put in its place.
    monkeypatch.setattr(artifacts, "to_computer", copy_logs_with_links)
    vm = FakeVM(1234)

    name = agent_files.from_vm(AGENT, vm, "/home/agent/logs", "")

    assert name == "logs"
    assert (base / "logs" / "app.log").read_text() == "started\n"
    assert not os.path.lexists(base / "logs" / "passwd")
    assert not os.path.lexists(base / "logs" / "home")
    assert agent_files.has_links(AGENT, "") is False
    assert [entry.name for entry in base.iterdir()] == ["logs"]


def test_copy_out_of_the_vm_goes_in_the_folder_asked(agent_files, base, monkeypatch):
    monkeypatch.setattr(artifacts, "to_computer", copy_logs_with_links)

    name = agent_files.from_vm(AGENT, FakeVM(1234), "/home/agent/logs", "from vm")

    assert name == "from vm/logs"
    assert (base / "from vm" / "logs" / "app.log").exists()


def test_vm_path_that_is_a_link_is_refused(agent_files, base, monkeypatch):
    monkeypatch.setattr(artifacts, "to_computer", copy_a_link)

    with pytest.raises(ArtifactsError, match="is a link or a special file"):
        agent_files.from_vm(AGENT, FakeVM(4096), "/home/agent/logs", "")

    assert list(base.iterdir()) == []


def test_too_big_a_copy_out_of_the_vm_is_refused_before_copying(agent_files, base, monkeypatch):
    monkeypatch.setattr(artifacts, "to_computer", copy_logs_with_links)
    vm = FakeVM(FROM_VM_LIMIT + 1)

    with pytest.raises(ArtifactsError, match="is over 200 MB"):
        agent_files.from_vm(AGENT, vm, "/home/agent/logs", "")

    assert vm.copied == []
    assert list(base.iterdir()) == []


def test_path_not_in_the_vm_is_refused(agent_files, monkeypatch):
    monkeypatch.setattr(artifacts, "to_computer", copy_logs_with_links)
    vm = FakeVM("")
    vm.found = 1

    with pytest.raises(ArtifactsError, match="is not in the VM"):
        agent_files.from_vm(AGENT, vm, "/home/agent/gone", "")

    assert vm.copied == []


def test_copy_out_of_the_vm_never_overwrites(agent_files, base, monkeypatch):
    monkeypatch.setattr(artifacts, "to_computer", copy_logs_with_links)
    agent_files.save(AGENT, "logs/mine.txt", b"mine")
    vm = FakeVM(1234)

    with pytest.raises(ArtifactsError, match="already in the artifacts"):
        agent_files.from_vm(AGENT, vm, "/home/agent/logs", "")

    assert vm.commands == []
    assert [entry.name for entry in (base / "logs").iterdir()] == ["mine.txt"]


def test_copy_out_of_the_vm_into_a_folder_out_of_the_artifacts_is_refused(agent_files, monkeypatch):
    monkeypatch.setattr(artifacts, "to_computer", copy_logs_with_links)
    vm = FakeVM(1234)

    with pytest.raises(ArtifactsError, match="is not in the artifacts"):
        agent_files.from_vm(AGENT, vm, "/home/agent/logs", f"../{OTHER}")

    assert vm.commands == []


def test_vm_path_is_quoted_for_the_shell(agent_files, monkeypatch):
    monkeypatch.setattr(artifacts, "to_computer", copy_logs_with_links)
    vm = FakeVM(1234)
    source = "/home/agent/my logs; rm -rf ~"

    with pytest.raises(ArtifactsError):
        agent_files.from_vm(AGENT, vm, source, "")

    assert vm.commands == [f"du -sb {shlex.quote(source)} | cut -f1"]
