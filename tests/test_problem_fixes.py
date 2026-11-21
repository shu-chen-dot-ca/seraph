"""Fix all (github_searcher/problem_fixes.py): what a run keeps when it fails or is cut off, the items it closes instead
of trying again, the scope its fixes must keep to, and the release it makes (the next version from the commit titles
since the last release, and its notes).

Nothing here runs Claude Code, starts a VM or reaches GitHub: VMs are fakes, GitHub is an httpx.MockTransport, the scope
is checked in a git repo made in pytest's temporary folder, and everything is kept there, never in DATA_DIR."""

import json
import subprocess

import httpx
import pytest

from github_searcher import problem_fixes
from github_searcher.problem_fixes import LOCKED, MAX_TRIES, PROMPT, FixError, ProblemFixes
from sandbox.vms import FIX_VM, VMsError


class FakeProblems:
    def __init__(self, items):
        self.items = items
        self.closed = []

    def list(self):
        return self.items

    def close(self, ids):
        self.closed = self.closed + ids
        return ids


class FakeUpdates:
    asked = False


class FakeVMs:
    """No VM at all; the ones asked to stop are kept in stopped."""

    def __init__(self):
        self.stopped = []

    def get(self, name):
        raise VMsError(f"There is no VM {name}")

    def stop_in_background(self, name):
        self.stopped.append(name)


class FakeImages:
    default = "dev-vm"


@pytest.fixture
def fixes(tmp_path, monkeypatch):
    """Fix all with no runs yet."""
    monkeypatch.setattr(problem_fixes, "DATA_DIR", tmp_path)
    monkeypatch.setattr(problem_fixes, "SELF_REPO", "owner/seraph")
    return ProblemFixes(FakeProblems([]), None, FakeUpdates(), FakeVMs(), FakeImages())


def test_a_run_the_restart_cut_off_is_failed_at_start_and_the_vm_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(problem_fixes, "DATA_DIR", tmp_path)
    run = {"started_at": "2026-11-15T01:00:00+00:00", "ended_at": None, "state": "running", "error": ""}
    (tmp_path / "problem_fixes.json").write_text(json.dumps({"runs": [run]}))
    vms = FakeVMs()

    fixes = ProblemFixes(FakeProblems([]), None, FakeUpdates(), vms, FakeImages())

    assert fixes.data["runs"][0]["state"] == "failed"
    assert fixes.data["runs"][0]["error"] == "Cut off: the app restarted during the run."
    assert fixes.data["runs"][0]["ended_at"] is not None
    assert vms.stopped == [FIX_VM]


def test_a_failed_run_keeps_why_and_the_output(fixes):
    problem = {"id": "prb_a1b2c3", "at": "2026-11-15T10:00:00+00:00", "about": None, "text": "x", "closed_at": None}
    fixes.problems = FakeProblems([problem])

    def fail(run, open_problems):
        raise FixError("uv run pytest -q fails on main, so nothing was released.", "1 failed")

    fixes.fix = fail
    fixes.run()

    run = fixes.data["runs"][0]
    assert run["state"] == "failed"
    assert run["problems"] == ["prb_a1b2c3"]
    assert run["error"] == "uv run pytest -q fails on main, so nothing was released."
    assert run["output"] == "1 failed"
    assert run["ended_at"] is not None


def test_no_second_run_while_one_runs(fixes):
    fixes.data["runs"] = [{"started_at": "2026-11-15T20:00:00+00:00", "state": "running"}]

    def never(run, open_problems):
        raise AssertionError("a second run started")

    fixes.fix = never
    fixes.run()

    assert len(fixes.data["runs"]) == 1


def test_closed_problems_are_not_given_to_a_run(fixes):
    open_one = {"id": "prb_open01", "at": "2026-11-15T10:00:00+00:00", "about": None, "text": "x", "closed_at": None}
    closed_one = {"id": "prb_done01", "at": "2026-11-14T10:00:00+00:00", "about": None, "text": "y", "closed_at": "2026-11-14T12:00:00+00:00"}
    fixes.problems = FakeProblems([open_one, closed_one])
    given = []

    def remember(run, open_problems):
        given.extend(item["id"] for item in open_problems)

    fixes.fix = remember
    fixes.run()

    assert given == ["prb_open01"]
    assert fixes.data["runs"][0]["state"] == "done"


def test_an_item_tried_in_max_tries_runs_is_closed_not_given_again(fixes):
    item = {"id": "prb_stuck1", "at": "2026-11-15T10:00:00+00:00", "about": None, "text": "x", "closed_at": None}
    fixes.problems = FakeProblems([item])
    fixes.data["runs"] = [{"started_at": f"2026-11-1{n}T20:00:00+00:00", "state": "done", "tried": ["prb_stuck1"]} for n in range(MAX_TRIES)]
    given = []

    def remember(run, open_problems):
        given.extend(each["id"] for each in open_problems)

    fixes.fix = remember
    fixes.run()

    assert given == []
    assert fixes.problems.closed == ["prb_stuck1"]
    assert fixes.data["runs"][0]["given_up"] == [{"id": "prb_stuck1", "why": f"Not fixed in {MAX_TRIES} runs."}]


def test_an_item_tried_fewer_times_is_given_again(fixes):
    item = {"id": "prb_again1", "at": "2026-11-15T10:00:00+00:00", "about": None, "text": "x", "closed_at": None}
    fixes.problems = FakeProblems([item])
    fixes.data["runs"] = [{"started_at": "2026-11-15T20:00:00+00:00", "state": "done", "tried": ["prb_again1"]}]
    given = []

    def remember(run, open_problems):
        given.extend(each["id"] for each in open_problems)

    fixes.fix = remember
    fixes.run()

    assert given == ["prb_again1"]
    assert fixes.problems.closed == []


def test_the_prompt_names_what_may_never_change_and_the_tries():
    text = PROMPT.format(locked=", ".join(LOCKED), tries=MAX_TRIES)

    for path in LOCKED:
        assert path in text
    assert f"after {MAX_TRIES} runs it is closed too" in text


def git(repo, *args):
    done = subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args], cwd=repo, capture_output=True, text=True, check=True)
    return done.stdout.strip()


@pytest.fixture
def clone(tmp_path, monkeypatch):
    """The run's clone with one commit (its base): an app file, a locked file and a test file with two tests."""
    repo = tmp_path / "clone"
    (repo / "tests").mkdir(parents=True)
    (repo / "github_searcher").mkdir()
    (repo / "deploy").mkdir()
    (repo / "github_searcher" / "agents.py").write_text("RULE = 1\n")
    (repo / "deploy" / "switch.sh").write_text("echo switch\n")
    (repo / "tests" / "test_agents.py").write_text("def test_one():\n    pass\n\n\ndef test_two():\n    pass\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "chore(app): start")
    monkeypatch.setattr(problem_fixes, "FIX_DIR", repo)
    return repo


def commit(repo):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "fix(agents): change")


def test_a_fix_with_its_test_keeps_to_the_scope(fixes, clone):
    base = git(clone, "rev-parse", "HEAD")
    (clone / "github_searcher" / "agents.py").write_text("RULE = 2\n")
    (clone / "tests" / "test_agents.py").write_text("def test_one():\n    pass\n\n\ndef test_two():\n    pass\n\n\ndef test_pallets_click_812():\n    pass\n")
    commit(clone)

    assert fixes.out_of_scope(base, ["pallets/click#812"]) == ""


def test_a_locked_file_changed_is_out_of_scope(fixes, clone):
    base = git(clone, "rev-parse", "HEAD")
    (clone / "deploy" / "switch.sh").write_text("echo never take back\n")
    commit(clone)

    assert fixes.out_of_scope(base, []) == "deploy/switch.sh may not be changed."


def test_a_deleted_test_file_is_out_of_scope(fixes, clone):
    base = git(clone, "rev-parse", "HEAD")
    (clone / "tests" / "test_agents.py").unlink()
    commit(clone)

    assert fixes.out_of_scope(base, []) == "tests/test_agents.py was deleted: tests may not be."


def test_fewer_tests_than_before_is_out_of_scope(fixes, clone):
    base = git(clone, "rev-parse", "HEAD")
    (clone / "tests" / "test_agents.py").write_text("def test_one():\n    pass\n")
    commit(clone)

    assert fixes.out_of_scope(base, []) == "there are fewer tests than before (2, now 1)."


def test_a_fix_for_only_the_repo_of_the_report_is_out_of_scope(fixes, clone):
    base = git(clone, "rev-parse", "HEAD")
    (clone / "github_searcher" / "agents.py").write_text('RULE = 1\nif repo == "Pallets/Click":\n    RULE = 2\n')
    commit(clone)

    why = fixes.out_of_scope(base, ["pallets/click#812"])

    assert why == "they name pallets/click outside tests/: a fix is for every case of its kind, not one repo."


def github(latest, titles, made):
    """A GitHub with release latest (None: no release yet) and these commit titles on main since it. Releases it makes
    go in made."""

    def answer(request):
        path = request.url.path
        if path == "/repos/owner/seraph/releases/latest" and latest is None:
            return httpx.Response(404, json={"message": "Not Found"})
        if path == "/repos/owner/seraph/releases/latest":
            return httpx.Response(200, json={"tag_name": latest})
        if path == f"/repos/owner/seraph/compare/{latest}...main":
            return httpx.Response(200, json={"commits": [{"commit": {"message": title + "\n"}} for title in titles]})
        if path == "/repos/owner/seraph/commits":
            return httpx.Response(200, json=[{"commit": {"message": title}} for title in titles])
        if path == "/repos/owner/seraph/releases" and request.method == "POST":
            made.append(json.loads(request.content))
            return httpx.Response(201, json={"html_url": "https://github.com/owner/seraph/releases/x"})
        return httpx.Response(500, json={"message": f"unexpected {request.method} {path}"})

    return httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(answer))


def test_a_feature_since_the_last_release_is_the_next_minor(fixes):
    made = []
    titles = ["fix(agents): stop claiming a taken issue", "feat(settings): add fix problems", "docs(readme): say so"]

    tag = fixes.release(github("v0.1.0", titles, made))

    assert tag == "v0.2.0"
    assert made[0]["tag_name"] == "v0.2.0"
    assert made[0]["target_commitish"] == "main"
    assert made[0]["body"] == (
        "## Features\n\n- feat(settings): add fix problems\n\n"
        "## Fixes\n\n- fix(agents): stop claiming a taken issue\n\n"
        "## Other changes\n\n- docs(readme): say so"
    )


def test_only_fixes_since_the_last_release_is_the_next_patch(fixes):
    made = []

    tag = fixes.release(github("v0.3.4", ["fix(search): skip archived repos", "test(search): cover archived repos"], made))

    assert tag == "v0.3.5"


def test_nothing_new_since_the_last_release_makes_none(fixes):
    made = []

    tag = fixes.release(github("v0.2.0", [], made))

    assert tag is None
    assert made == []


def test_the_first_release_is_v0_1_0(fixes):
    made = []

    tag = fixes.release(github(None, ["feat(app): first"], made))

    assert tag == "v0.1.0"


def test_github_refusing_the_release_says_so(fixes):
    def answer(request):
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(200, json={"tag_name": "v0.1.0"})
        if "/compare/" in request.url.path:
            return httpx.Response(200, json={"commits": [{"commit": {"message": "fix(app): x"}}]})
        return httpx.Response(422, json={"message": "Validation Failed"})

    client = httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(answer))

    with pytest.raises(FixError, match="GitHub answered 422 for the release v0.1.1"):
        fixes.release(client)
