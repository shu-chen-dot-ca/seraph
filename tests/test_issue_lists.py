"""The issue stores around the tags: the Issues list (github_searcher/issue_list.py) with its undo/redo, dismissed
issues and board, the Tracked page's issues (github_searcher/tracked_issues.py), and what GitHub says about each listed
issue (github_searcher/issue_facts.py).

An issue an agent is working on is never taken out of the Issues list, by remove, dismiss, undo or redo; a dismissed
one is never added again except by the user by hand. GitHub is a fake that sends what the test says, the agents' jobs
are a plain list, and every file is kept in pytest's temporary folder, never in DATA_DIR."""

import copy
import json
import types

import pytest

from github_searcher import issue_facts, issue_list, tracked_issues
from github_searcher.issue_facts import IssueFacts
from github_searcher.issue_list import IssueList
from github_searcher.tracked_issues import GOOD_FIRST, TrackedIssues

ONE = {"id": "owner/repo#1", "title": "Crash on empty input", "note": "", "added_by": "user"}
TWO = {"id": "owner/repo#2", "title": "Add a dark theme", "note": "", "added_by": "agent_1"}
THREE = {"id": "owner/repo#3", "title": "Update install docs", "note": "", "added_by": "user"}


@pytest.fixture
def jobs():
    """The agents' jobs as Jobs.list() gives them; a test adds {"issue", "status"}."""
    return []


@pytest.fixture
def issues(tmp_path, monkeypatch, jobs):
    """An empty Issues list, its issues.json in a temporary folder."""
    monkeypatch.setattr(issue_list, "DATA_DIR", tmp_path)
    return IssueList(types.SimpleNamespace(list=lambda: copy.deepcopy(jobs)))


# The Issues list.


def test_add_keeps_order_and_skips_repeats(issues):
    assert issues.add([ONE, TWO, ONE]) == ["owner/repo#1", "owner/repo#2"]
    assert issues.add([TWO, THREE]) == ["owner/repo#3"]
    assert [item["id"] for item in issues.items()] == ["owner/repo#1", "owner/repo#2", "owner/repo#3"]


def test_adding_nothing_new_is_no_undo_step(issues):
    issues.add([ONE])

    assert issues.add([ONE]) == []
    assert issues.undo() is True
    assert issues.items() == []
    assert issues.can_undo() is False


@pytest.mark.parametrize(
    "status, result",
    [
        ("queued", {"removed": ["owner/repo#2"], "working": ["owner/repo#1"]}),
        ("working", {"removed": ["owner/repo#2"], "working": ["owner/repo#1"]}),
        ("waiting_on_user", {"removed": ["owner/repo#2"], "working": ["owner/repo#1"]}),
        ("waiting_on_maintainers", {"removed": ["owner/repo#2"], "working": ["owner/repo#1"]}),
        ("paused", {"removed": ["owner/repo#2"], "working": ["owner/repo#1"]}),
        ("done", {"removed": ["owner/repo#1", "owner/repo#2"], "working": []}),
        ("cancelled", {"removed": ["owner/repo#1", "owner/repo#2"], "working": []}),
    ],
)
def test_remove_skips_issues_an_agent_works_on(issues, jobs, status, result):
    issues.add([ONE, TWO])
    jobs.append({"issue": "owner/repo#1", "status": status})

    assert issues.remove(["owner/repo#1", "owner/repo#2", "owner/repo#99"]) == result


def test_removing_only_working_issues_is_no_undo_step(issues, jobs):
    issues.add([ONE])
    jobs.append({"issue": "owner/repo#1", "status": "working"})

    assert issues.remove(["owner/repo#1"]) == {"removed": [], "working": ["owner/repo#1"]}
    assert issues.undo() is True
    assert issues.can_undo() is False


def test_undo_keeps_an_issue_an_agent_works_on(issues, jobs):
    # The step undone is the one that added it.
    issues.add([ONE])
    issues.add([TWO])
    jobs.append({"issue": "owner/repo#2", "status": "working"})

    assert issues.undo() is True
    assert [item["id"] for item in issues.items()] == ["owner/repo#1", "owner/repo#2"]


def test_redo_keeps_an_issue_an_agent_works_on(issues, jobs):
    # The step redone is the one that removed it, before an agent took it up.
    issues.add([ONE, TWO])
    issues.remove(["owner/repo#2"])
    issues.undo()
    jobs.append({"issue": "owner/repo#2", "status": "queued"})

    assert issues.redo() is True
    assert [item["id"] for item in issues.items()] == ["owner/repo#1", "owner/repo#2"]


def test_undo_and_redo(issues):
    issues.add([ONE])
    issues.add([TWO])

    assert issues.undo() is True
    assert [item["id"] for item in issues.items()] == ["owner/repo#1"]
    assert issues.redo() is True
    assert [item["id"] for item in issues.items()] == ["owner/repo#1", "owner/repo#2"]

    # A new change after an undo clears redo.
    issues.undo()
    issues.add([THREE])
    assert issues.can_redo() is False
    assert issues.redo() is False
    assert [item["id"] for item in issues.items()] == ["owner/repo#1", "owner/repo#3"]


def test_undo_goes_back_at_most_undo_limit_steps(issues, monkeypatch, tmp_path):
    monkeypatch.setattr(issue_list, "UNDO_LIMIT", 4)
    monkeypatch.setattr(issue_list, "SAVED_STEPS", 2)
    for number in range(1, 7):
        issues.add([{"id": f"owner/repo#{number}", "note": ""}])

    saved = json.loads((tmp_path / "issues.json").read_text())
    assert len(saved["items"]) == 6
    assert len(saved["undo"]) == 2
    for step in range(4):
        assert issues.undo() is True
    assert issues.undo() is False
    assert [item["id"] for item in issues.items()] == ["owner/repo#1", "owner/repo#2"]


def test_set_note_is_an_undo_step(issues):
    issues.add([ONE])
    issues.set_note("owner/repo#1", "Check the parser first")

    assert issues.items()[0]["note"] == "Check the parser first"
    issues.undo()
    assert issues.items()[0]["note"] == ""
    with pytest.raises(KeyError):
        issues.set_note("owner/repo#99", "Nothing here")


def test_dismissed_issue_is_never_added_again(issues):
    issues.add([ONE, TWO])

    assert issues.dismiss(["owner/repo#1"]) == {"removed": ["owner/repo#1"], "working": []}
    assert issues.dismissed() == ["owner/repo#1"]
    assert issues.add([ONE, THREE]) == ["owner/repo#3"]
    assert [item["id"] for item in issues.items()] == ["owner/repo#2", "owner/repo#3"]


def test_adding_a_dismissed_issue_by_hand_takes_it_off_dismissed(issues):
    issues.add([ONE])
    issues.dismiss(["owner/repo#1"])

    assert issues.add([ONE], allow_dismissed=True) == ["owner/repo#1"]
    assert issues.dismissed() == []


def test_dismiss_keeps_an_issue_an_agent_works_on(issues, jobs):
    issues.add([ONE])
    jobs.append({"issue": "owner/repo#1", "status": "working"})

    assert issues.dismiss(["owner/repo#1"]) == {"removed": [], "working": ["owner/repo#1"]}
    assert issues.dismissed() == []
    assert [item["id"] for item in issues.items()] == ["owner/repo#1"]


def test_restore_puts_a_dismissed_issue_back_as_it_was(issues):
    issues.add([ONE])
    issues.set_note("owner/repo#1", "Check the parser first")
    issues.dismiss(["owner/repo#1"])

    assert issues.restore(["owner/repo#1", "owner/repo#99"]) == ["owner/repo#1"]
    assert issues.items()[0]["note"] == "Check the parser first"
    assert issues.dismissed() == []


def test_undo_after_dismiss_brings_it_back_still_dismissed(issues):
    issues.add([ONE])
    issues.dismiss(["owner/repo#1"])

    assert issues.undo() is True
    assert [item["id"] for item in issues.items()] == ["owner/repo#1"]
    assert issues.dismissed() == ["owner/repo#1"]


def test_board_is_not_an_undo_step(issues):
    issues.add([ONE])
    issues.set_board(["owner/repo#1"], ["owner/repo#1", "owner/repo#2"], ["owner/repo#2"])

    assert issues.board() == {"catalog": ["owner/repo#1"], "order": ["owner/repo#1", "owner/repo#2"], "held": ["owner/repo#2"]}
    issues.undo()
    assert issues.can_undo() is False
    assert issues.board()["catalog"] == ["owner/repo#1"]


def test_saved_list_comes_back_after_a_restart(issues, jobs):
    issues.add([ONE, TWO])
    issues.dismiss(["owner/repo#2"])
    issues.set_board(["owner/repo#1"], ["owner/repo#1"], [])

    restarted = IssueList(types.SimpleNamespace(list=lambda: jobs))

    assert restarted.items() == issues.items()
    assert restarted.dismissed() == ["owner/repo#2"]
    assert restarted.board() == {"catalog": ["owner/repo#1"], "order": ["owner/repo#1"], "held": []}
    assert restarted.can_undo() is True


def test_list_from_before_dismissed_and_the_board_still_loads(tmp_path, monkeypatch, jobs):
    monkeypatch.setattr(issue_list, "DATA_DIR", tmp_path)
    (tmp_path / "issues.json").write_text(json.dumps({"items": [ONE], "undo": [], "redo": []}))

    issues = IssueList(types.SimpleNamespace(list=lambda: jobs))

    assert issues.dismissed() == []
    assert issues.board() == {"catalog": [], "order": [], "held": []}
    assert issues.add([ONE, TWO]) == ["owner/repo#2"]


# The Tracked page's issues.


@pytest.fixture
def github():
    """What GitHub sends for owner/repo's open issues: the newest (#5, #3), and the issues under labels GitHub's loose
    label search found: "good first issue" (#3 again, #1), "Difficulty: Hard" (#2, found by "first") and "helm" (#4,
    found by "help")."""
    return {
        "stargazerCount": 120,
        "description": "A command line tool",
        "newest": {
            "nodes": [
                {"number": 5, "title": "Add a dark theme", "url": "https://github.com/owner/repo/issues/5", "createdAt": "2026-11-05T10:00:00Z",
                 "updatedAt": "2026-11-06T10:00:00Z", "author": {"login": "alice"}, "labels": {"nodes": []},
                 "comments": {"totalCount": 0}, "assignees": {"totalCount": 0}},
                {"number": 3, "title": "Update install docs", "url": "https://github.com/owner/repo/issues/3", "createdAt": "2026-11-03T10:00:00Z",
                 "updatedAt": "2026-11-03T10:00:00Z", "author": {"login": "bob"}, "labels": {"nodes": [{"name": "good first issue"}]},
                 "comments": {"totalCount": 2}, "assignees": {"totalCount": 1}},
            ]
        },
        "firstLabels": {
            "nodes": [
                {"name": "good first issue", "issues": {"nodes": [
                    {"number": 3, "title": "Update install docs", "url": "https://github.com/owner/repo/issues/3", "createdAt": "2026-11-03T10:00:00Z",
                     "updatedAt": "2026-11-03T10:00:00Z", "author": {"login": "bob"}, "labels": {"nodes": [{"name": "good first issue"}]},
                     "comments": {"totalCount": 2}, "assignees": {"totalCount": 1}},
                    {"number": 1, "title": "Crash on empty input", "url": "https://github.com/owner/repo/issues/1", "createdAt": "2026-10-01T10:00:00Z",
                     "updatedAt": "2026-10-02T10:00:00Z", "author": None, "labels": {"nodes": [{"name": "good first issue"}, {"name": "bug"}]},
                     "comments": {"totalCount": 5}, "assignees": {"totalCount": 0}},
                ]}},
                {"name": "Difficulty: Hard", "issues": {"nodes": [
                    {"number": 2, "title": "Rewrite the parser", "url": "https://github.com/owner/repo/issues/2", "createdAt": "2026-10-02T10:00:00Z",
                     "updatedAt": "2026-10-02T10:00:00Z", "author": {"login": "lead"}, "labels": {"nodes": [{"name": "Difficulty: Hard"}]},
                     "comments": {"totalCount": 0}, "assignees": {"totalCount": 0}},
                ]}},
            ]
        },
        "beginnerLabels": {"nodes": []},
        "easyLabels": {"nodes": []},
        "helpLabels": {
            "nodes": [
                {"name": "helm", "issues": {"nodes": [
                    {"number": 4, "title": "Bump the chart", "url": "https://github.com/owner/repo/issues/4", "createdAt": "2026-10-04T10:00:00Z",
                     "updatedAt": "2026-10-04T10:00:00Z", "author": {"login": "lead"}, "labels": {"nodes": [{"name": "helm"}]},
                     "comments": {"totalCount": 0}, "assignees": {"totalCount": 0}},
                ]}},
            ]
        },
        "grabsLabels": {"nodes": []},
    }


@pytest.fixture
def tracked(tmp_path, monkeypatch, github):
    """TrackedIssues with its files in a temporary folder. GitHub sends github, read at the time of the call."""
    monkeypatch.setattr(tracked_issues, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tracked_issues, "get_tracked_issues", lambda owner, repo: copy.deepcopy(github))
    return TrackedIssues()


@pytest.mark.parametrize(
    "label, anyone",
    [
        ("good first issue", True),
        ("🌱 Good first issue", True),
        ("good-first-issue", True),
        ("first-timers-only", True),
        ("beginner-friendly", True),
        ("Difficulty: Easy", True),
        ("help wanted", True),
        ("up-for-grabs", True),
        ("Difficulty: Hard", False),
        ("helm", False),
        ("help: question", False),
        ("first-party", False),
    ],
)
def test_good_first_labels(label, anyone):
    assert bool(GOOD_FIRST.search(label)) is anyone


def test_check_keeps_the_newest_and_good_first_issues_once(tracked):
    tracked.check("owner/repo")
    check = tracked.all()["owner/repo"]

    assert [issue["number"] for issue in check["issues"]] == [5, 3, 1]
    assert check["stars"] == 120
    assert check["description"] == "A command line tool"
    assert check["error"] is None
    assert check["read"] == []
    assert check["checked_at"].endswith("Z")
    assert check["issues"][2] == {
        "number": 1,
        "title": "Crash on empty input",
        "url": "https://github.com/owner/repo/issues/1",
        "created_at": "2026-10-01T10:00:00Z",
        "updated_at": "2026-10-02T10:00:00Z",
        "author": "ghost",
        "labels": ["good first issue", "bug"],
        "comments": 5,
        "assignees": 0,
    }


def test_issues_marked_read_stay_read_while_open(tracked, github):
    tracked.check("owner/repo")
    tracked.mark_read()
    assert tracked.all()["owner/repo"]["read"] == [5, 3, 1]

    # #5 was closed and #6 opened since.
    github["newest"]["nodes"][0]["number"] = 6
    tracked.check("owner/repo")

    assert [issue["number"] for issue in tracked.all()["owner/repo"]["issues"]] == [6, 3, 1]
    assert tracked.all()["owner/repo"]["read"] == [3, 1]


def test_failed_check_keeps_the_issues_and_says_why(tracked, monkeypatch):
    tracked.check("owner/repo")
    tracked.mark_read()

    def broken(owner, repo):
        raise ValueError("GitHub has no repo owner/repo")

    monkeypatch.setattr(tracked_issues, "get_tracked_issues", broken)
    with pytest.raises(ValueError):
        tracked.check("owner/repo")
    check = tracked.all()["owner/repo"]

    assert check["error"] == "GitHub has no repo owner/repo"
    assert [issue["number"] for issue in check["issues"]] == [5, 3, 1]
    assert check["read"] == [5, 3, 1]
    assert check["stars"] == 120


def test_first_check_that_fails_without_a_message_names_the_error(tracked, monkeypatch):
    def broken(owner, repo):
        raise TimeoutError()

    monkeypatch.setattr(tracked_issues, "get_tracked_issues", broken)
    with pytest.raises(TimeoutError):
        tracked.check("owner/new")
    check = tracked.all()["owner/new"]

    assert check["error"] == "TimeoutError"
    assert check["issues"] == []
    assert check["stars"] is None


def test_issues_taken_up_are_noted_once_and_come_back(tracked):
    tracked.note_added(["owner/repo#1"])
    tracked.note_added(["owner/repo#3"])
    tracked.check("owner/repo")

    restarted = TrackedIssues()

    assert restarted.added() == ["owner/repo#1", "owner/repo#3"]
    assert restarted.all() == tracked.all()


# What GitHub says about each listed issue.


@pytest.fixture
def facts_github():
    """What GitHub sends about owner/repo#7: opened by a bot, last comment by a maintainer, and pull request #9 both
    closing it and cross-referencing it (once in the facts), #12 linked by a deleted account, and an issue that
    mentions it (not a pull request)."""
    pull = {"number": 9, "state": "OPEN", "url": "https://github.com/owner/repo/pull/9", "author": {"login": "alice"}, "repository": {"nameWithOwner": "owner/repo"}}
    return {
        "stargazerCount": 120,
        "pushedAt": "2026-11-14T10:00:00Z",
        "issue": {
            "title": "Crash on empty input",
            "state": "OPEN",
            "createdAt": "2026-11-01T10:00:00Z",
            "updatedAt": "2026-11-10T10:00:00Z",
            "authorAssociation": "NONE",
            "author": {"login": "dependabot", "__typename": "Bot"},
            "labels": {"nodes": [{"name": "bug"}]},
            "assignees": {"nodes": [{"login": "alice"}]},
            "participants": {"totalCount": 3},
            "reactions": {"totalCount": 4},
            "comments": {"totalCount": 2, "nodes": [{"createdAt": "2026-11-09T10:00:00Z", "authorAssociation": "MEMBER", "author": {"login": "lead", "__typename": "User"}}]},
            "closedByPullRequestsReferences": {"nodes": [pull]},
            "timelineItems": {
                "nodes": [
                    {"__typename": "CrossReferencedEvent", "source": dict(pull, __typename="PullRequest")},
                    {"__typename": "CrossReferencedEvent", "source": {"__typename": "Issue"}},
                    {"__typename": "ConnectedEvent", "subject": {"__typename": "PullRequest", "number": 12, "state": "CLOSED", "url": "https://github.com/owner/repo/pull/12", "author": None, "repository": {"nameWithOwner": "owner/repo"}}},
                ]
            },
        },
    }


@pytest.fixture
def facts(tmp_path, monkeypatch, facts_github):
    """IssueFacts with issue_facts.json in a temporary folder. GitHub sends facts_github, read at the time of the call."""
    monkeypatch.setattr(issue_facts, "DATA_DIR", tmp_path)
    monkeypatch.setattr(issue_facts, "get_issue_facts", lambda owner, repo, number: copy.deepcopy(facts_github))
    return IssueFacts()


def test_refresh_keeps_what_github_says(facts):
    kept = facts.refresh("owner/repo#7")

    assert kept["fetched_at"] != ""
    del kept["fetched_at"]
    assert kept == {
        "state": "OPEN",
        "title": "Crash on empty input",
        "labels": ["bug"],
        "created_at": "2026-11-01T10:00:00Z",
        "updated_at": "2026-11-10T10:00:00Z",
        "author": "dependabot",
        "author_role": "BOT",
        "assignees": ["alice"],
        "participants": 3,
        "thumbs_up": 4,
        "comments": 2,
        "last_comment_at": "2026-11-09T10:00:00Z",
        "last_comment_by": "lead",
        "last_comment_role": "MEMBER",
        "linked_prs": [
            {"number": 9, "repo": "owner/repo", "state": "OPEN", "url": "https://github.com/owner/repo/pull/9", "author": "alice"},
            {"number": 12, "repo": "owner/repo", "state": "CLOSED", "url": "https://github.com/owner/repo/pull/12", "author": "ghost"},
        ],
        "repo_stars": 120,
        "repo_pushed_at": "2026-11-14T10:00:00Z",
    }


def test_deleted_author_and_bot_comment(facts, facts_github):
    facts_github["issue"]["author"] = None
    facts_github["issue"]["comments"]["nodes"][0]["author"] = {"login": "github-actions", "__typename": "Bot"}

    kept = facts.refresh("owner/repo#7")

    assert kept["author"] == "ghost"
    assert kept["author_role"] == "NONE"
    assert kept["last_comment_by"] == "github-actions"
    assert kept["last_comment_role"] == "BOT"


def test_issue_without_comments(facts, facts_github):
    facts_github["issue"]["comments"] = {"totalCount": 0, "nodes": []}

    kept = facts.refresh("owner/repo#7")

    assert kept["comments"] == 0
    assert kept["last_comment_at"] is None
    assert kept["last_comment_by"] is None
    assert kept["last_comment_role"] is None


def test_missing_issue_is_an_error_and_keeps_nothing(facts, facts_github):
    facts_github["issue"] = None

    with pytest.raises(ValueError, match="GitHub has no issue owner/repo#7"):
        facts.refresh("owner/repo#7")
    assert facts.all() == {}


def test_forget_drops_the_issues_no_longer_listed(facts):
    facts.refresh("owner/repo#7")
    facts.refresh("owner/repo#8")

    facts.forget(["owner/repo#8"])
    assert list(facts.all()) == ["owner/repo#8"]

    # Nothing to drop: nothing written.
    version = facts.version
    facts.forget(["owner/repo#8"])
    assert facts.version == version


def test_facts_come_back_after_a_restart(facts):
    facts.refresh("owner/repo#7")

    assert IssueFacts().all() == facts.all()
