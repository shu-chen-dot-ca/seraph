"""Errors (github_searcher/crashes.py) and Problems (github_searcher/problems.py): the app's two lists of what went
wrong. Errors: the same error again is one entry, counted; new, sent, filed and skipped; one that comes back is new
again; a release the live copy took back is reported once. Problems: add, close only open ones, newest first. Both keep
MAX_KEPT at most and come back after a restart. Everything is kept in pytest's temporary folder, never in DATA_DIR."""

import json

import pytest

from github_searcher import crashes, problems
from github_searcher.crashes import Crashes
from github_searcher.problems import Problems

STACK = """Traceback (most recent call last):
  File "backend/app.py", line 120, in run
    agents.start(agent_id)
KeyError: 'agent_a1b2c3'"""


@pytest.fixture
def crash_list(tmp_path, monkeypatch):
    """Errors with crashes.json in a temporary folder, and no taken-back release waiting to be reported."""
    monkeypatch.setattr(crashes, "DATA_DIR", tmp_path)
    monkeypatch.delenv("SERAPH_HOME", raising=False)
    monkeypatch.delenv("SERAPH_CHECK", raising=False)
    return Crashes()


@pytest.fixture
def problem_list(tmp_path, monkeypatch):
    """Problems with problems.json in a temporary folder."""
    monkeypatch.setattr(problems, "DATA_DIR", tmp_path)
    return Problems()


@pytest.fixture
def taken_back(tmp_path, monkeypatch):
    """SERAPH_HOME with the failed-crashes.json deploy/switch.sh leaves when it takes a release back."""
    home = tmp_path / "seraph"
    home.mkdir()
    report = {
        "tag": "v0.4.0",
        "reason": "it stopped answering",
        "crashes": [
            {"source": "backend", "count": 3, "message": "KeyError: 'agent_a1b2c3'"},
            {"source": "browser", "count": 1, "message": "TypeError: x is undefined"},
        ],
    }
    (home / "failed-crashes.json").write_text(json.dumps(report))
    monkeypatch.setattr(crashes, "DATA_DIR", tmp_path / "data")
    monkeypatch.setenv("SERAPH_HOME", str(home))
    monkeypatch.delenv("SERAPH_CHECK", raising=False)
    return home


def test_new_error_is_new_and_counted_once(crash_list, monkeypatch):
    monkeypatch.setattr(crashes, "RUNNING", "v0.3.0")

    crash_list.add("backend", "KeyError: 'agent_a1b2c3'", STACK)

    item = crash_list.list()[0]
    assert item["id"].startswith("err_")
    assert item["source"] == "backend"
    assert item["count"] == 1
    assert item["state"] == "new"
    assert item["issue"] is None
    assert item["note"] == ""
    assert item["version"] == "v0.3.0"
    assert item["first_at"] == item["last_at"]


def test_same_error_again_is_one_entry_counted(crash_list):
    crash_list.add("backend", "KeyError: 'agent_a1b2c3'", STACK)
    crash_list.add("backend", "KeyError: 'agent_a1b2c3'", STACK)

    items = crash_list.list()
    assert len(items) == 1
    assert items[0]["count"] == 2


def test_same_first_line_and_stack_end_is_the_same_error(crash_list):
    # The key is where it came from, the message's first line and the stack's last line: the rest can change.
    crash_list.add("browser", "TypeError: x is undefined\nat page Dashboard", "at render (main.tsx:10)\nTypeError: x is undefined")
    crash_list.add("browser", "TypeError: x is undefined\nat page Issues", "at click (main.tsx:99)\nTypeError: x is undefined")

    items = crash_list.list()
    assert len(items) == 1
    assert items[0]["count"] == 2
    assert items[0]["detail"] == "at click (main.tsx:99)\nTypeError: x is undefined"


def test_another_source_or_stack_end_is_another_error(crash_list):
    crash_list.add("backend", "KeyError: 'agent_a1b2c3'", STACK)
    crash_list.add("agent", "KeyError: 'agent_a1b2c3'", STACK)
    crash_list.add("backend", "KeyError: 'agent_a1b2c3'", STACK + "\nDuring handling of the above exception")

    assert len(crash_list.list()) == 3


def test_newest_first_and_one_that_happens_again_goes_to_the_top(crash_list):
    crash_list.add("backend", "first", "")
    crash_list.add("backend", "second", "")
    crash_list.add("backend", "first", "")

    assert [item["message"] for item in crash_list.list()] == ["first", "second"]


def test_version_given_is_kept(crash_list):
    crash_list.add("release", "Release v0.2.0 failed its check", "", "v0.2.0")

    assert crash_list.list()[0]["version"] == "v0.2.0"


def test_long_message_and_detail_are_cut_keeping_the_end_of_the_stack(crash_list):
    detail = "x" * (crashes.DETAIL_CHARS + 1000) + "\nKeyError: 'agent_a1b2c3'"

    crash_list.add("backend", "m" * (crashes.MESSAGE_CHARS + 100), detail)

    item = crash_list.list()[0]
    assert len(item["message"]) == crashes.MESSAGE_CHARS
    assert len(item["detail"]) == crashes.DETAIL_CHARS
    assert item["detail"].endswith("KeyError: 'agent_a1b2c3'")


def test_empty_message_still_makes_an_entry(crash_list):
    crash_list.add("browser", "   ", "")

    assert crash_list.list()[0]["message"] == "(no message)"


def test_reporting_an_error_never_makes_another(crash_list, tmp_path):
    # Its folder can't be made (a file is in the way): add() is called from error handlers, so it must not raise.
    (tmp_path / "in-the-way").write_text("")
    crash_list.path = tmp_path / "in-the-way" / "crashes.json"

    crash_list.add("backend", "KeyError: 'agent_a1b2c3'", STACK)


def test_since_start_counts_every_report(crash_list):
    crash_list.add("backend", "KeyError: 'agent_a1b2c3'", STACK)
    crash_list.add("backend", "KeyError: 'agent_a1b2c3'", STACK)
    crash_list.add("browser", "TypeError: x is undefined", "")

    assert crash_list.since_start == 3


def test_mark_sets_what_became_of_them(crash_list):
    crash_list.add("backend", "first", "")
    crash_list.add("backend", "second", "")
    crash_list.add("backend", "third", "")
    third, second, first = [item["id"] for item in crash_list.list()]

    crash_list.mark([first], "sent")
    crash_list.mark([second], "filed", issue=42)
    crash_list.mark([third], "skipped", note="A test that failed on purpose.")

    third_item, second_item, first_item = crash_list.list()
    assert first_item["state"] == "sent"
    assert second_item["state"] == "filed"
    assert second_item["issue"] == 42
    assert third_item["state"] == "skipped"
    assert third_item["note"] == "A test that failed on purpose."


def test_mark_returns_only_the_ids_it_knew(crash_list):
    crash_list.add("backend", "first", "")
    known = crash_list.list()[0]["id"]

    assert crash_list.mark([known, "err_gone00"], "sent") == [known]
    assert crash_list.mark(["err_gone00"], "sent") == []


def test_mark_refuses_an_unknown_state(crash_list):
    crash_list.add("backend", "first", "")

    with pytest.raises(ValueError, match="Unknown state"):
        crash_list.mark([crash_list.list()[0]["id"]], "fixed")


@pytest.mark.parametrize("state", ["filed", "skipped"])
def test_error_that_comes_back_after_the_agent_dealt_with_it_is_new_again(crash_list, state):
    crash_list.add("backend", "KeyError: 'agent_a1b2c3'", STACK)
    crash_list.mark([crash_list.list()[0]["id"]], state, issue=42)

    crash_list.add("backend", "KeyError: 'agent_a1b2c3'", STACK)

    item = crash_list.list()[0]
    assert item["state"] == "new"
    assert item["count"] == 2
    assert item["issue"] == 42


def test_error_that_comes_back_while_the_agent_has_it_stays_sent(crash_list):
    crash_list.add("backend", "KeyError: 'agent_a1b2c3'", STACK)
    crash_list.mark([crash_list.list()[0]["id"]], "sent")

    crash_list.add("backend", "KeyError: 'agent_a1b2c3'", STACK)

    assert crash_list.list()[0]["state"] == "sent"


def test_only_max_kept_errors_are_kept(crash_list, monkeypatch):
    monkeypatch.setattr(crashes, "MAX_KEPT", 3)

    for number in range(5):
        crash_list.add("backend", f"error {number}", "")

    assert [item["message"] for item in crash_list.list()] == ["error 4", "error 3", "error 2"]


def test_errors_come_back_after_a_restart(crash_list):
    crash_list.add("backend", "KeyError: 'agent_a1b2c3'", STACK)
    crash_list.mark([crash_list.list()[0]["id"]], "filed", issue=42)

    restarted = Crashes()

    assert restarted.list() == crash_list.list()
    assert restarted.since_start == 0


def test_list_is_a_copy(crash_list):
    crash_list.add("backend", "first", "")

    crash_list.list()[0]["state"] = "filed"

    assert crash_list.list()[0]["state"] == "new"


def test_taken_back_release_is_reported_once_at_start(taken_back):
    errors = Crashes()

    item = errors.list()[0]
    assert item["source"] == "release"
    assert item["message"] == "Release v0.4.0 was taken back: it stopped answering"
    assert item["detail"] == "What went wrong in it:\n- backend, 3x: KeyError: 'agent_a1b2c3'\n- browser, 1x: TypeError: x is undefined"
    assert item["version"] == "v0.4.0"
    assert not (taken_back / "failed-crashes.json").exists()
    assert len(Crashes().list()) == 1


def test_taken_back_release_report_does_not_count_against_the_release_that_starts(taken_back):
    # deploy/switch.sh takes a release back when since_start climbs in its first minutes: the report about the
    # release before it must not count, or the release it went back to could be taken back for it.
    assert Crashes().since_start == 0


def test_taken_back_release_with_no_reports_says_it_stopped_answering(taken_back):
    report = {"tag": "v0.4.0", "reason": "it stopped answering", "crashes": []}
    (taken_back / "failed-crashes.json").write_text(json.dumps(report))

    item = Crashes().list()[0]

    assert item["detail"] == "What went wrong in it:\nnothing was reported; it stopped answering."


def test_new_releases_check_leaves_the_taken_back_report_for_the_live_copy(taken_back, monkeypatch):
    # A new release's check runs on a copy of data/: reporting there would lose it, the live copy must report it.
    monkeypatch.setenv("SERAPH_CHECK", "1")

    assert Crashes().list() == []
    assert (taken_back / "failed-crashes.json").exists()


def test_added_problem_is_open(problem_list):
    text = "Claimed an issue someone else's open pull request already closed; the maintainer said no second fix was needed."

    item = problem_list.add("agent_a1b2c3", "job_d4e5f6", "owner/name#12", text)

    assert item["id"].startswith("prb_")
    assert item["agent"] == "agent_a1b2c3"
    assert item["job"] == "job_d4e5f6"
    assert item["about"] == "owner/name#12"
    assert item["text"] == text
    assert item["closed_at"] is None
    assert problem_list.list() == [item]


def test_problems_are_newest_first(problem_list):
    problem_list.add("agent_a1b2c3", None, None, "first")
    problem_list.add("agent_a1b2c3", None, None, "second")

    assert [item["text"] for item in problem_list.list()] == ["second", "first"]


def test_long_problem_is_cut(problem_list):
    item = problem_list.add("agent_a1b2c3", None, None, "x" * (problems.TEXT_CHARS + 100))

    assert len(item["text"]) == problems.TEXT_CHARS


def test_close_closes_only_open_ones(problem_list):
    first = problem_list.add("agent_a1b2c3", None, None, "first")
    second = problem_list.add("agent_a1b2c3", None, None, "second")

    assert problem_list.close([first["id"]]) == [first["id"]]
    closed_at = problem_list.list()[1]["closed_at"]
    assert problem_list.close([first["id"], second["id"]]) == [second["id"]]

    # Closing again doesn't move when it was closed.
    assert problem_list.list()[1]["closed_at"] == closed_at


def test_close_ignores_unknown_ids(problem_list):
    problem_list.add("agent_a1b2c3", None, None, "first")

    assert problem_list.close(["prb_gone00"]) == []
    assert problem_list.list()[0]["closed_at"] is None


def test_closed_problems_stay(problem_list):
    item = problem_list.add("agent_a1b2c3", None, None, "first")

    problem_list.close([item["id"]])

    assert len(problem_list.list()) == 1
    assert problem_list.list()[0]["closed_at"] is not None


def test_only_max_kept_problems_are_kept(problem_list, monkeypatch):
    monkeypatch.setattr(problems, "MAX_KEPT", 3)

    for number in range(5):
        problem_list.add("agent_a1b2c3", None, None, f"problem {number}")

    assert [item["text"] for item in problem_list.list()] == ["problem 4", "problem 3", "problem 2"]


def test_problem_list_is_a_copy(problem_list):
    item = problem_list.add("agent_a1b2c3", None, None, "first")

    item["text"] = "changed"
    problem_list.list()[0]["closed_at"] = "2026-11-15T12:00:00+00:00"

    assert problem_list.list()[0]["text"] == "first"
    assert problem_list.list()[0]["closed_at"] is None


def test_every_change_goes_up_in_version(problem_list):
    item = problem_list.add("agent_a1b2c3", None, None, "first")
    after_add = problem_list.version

    problem_list.close([item["id"]])

    assert after_add == 1
    assert problem_list.version == 2


def test_problems_come_back_after_a_restart(problem_list):
    item = problem_list.add("agent_a1b2c3", None, None, "first")
    problem_list.close([item["id"]])

    assert Problems().list() == problem_list.list()
