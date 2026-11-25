"""Our PRs on GitHub (github_searcher/pr_tracking.py): what read_all() keeps of each (each reviewer's latest review, the
PR's review verdict, its checks, who wrote last), what update_actions() says it needs from us (Needs action) or how it
waits (Waiting approval, with GitHub's status), and what needs_reply() gives its agent.

GitHub is a fake that answers with our PR acme/tool#42 as PR_STATUS_QUERY gives it; the Inbox holds the draft whose
Approve sent it. The tests named after a PR rebuild what went wrong there (opencodex#8556, openmed#5516, reticle#2221,
kibi#666, openchoreo#5419, tabularis#1542, xerj#3062). The file is kept in pytest's temporary folder, never in DATA_DIR."""

import json
from types import SimpleNamespace

import httpx
import pytest

from github_searcher import pr_tracking
from github_searcher.pr_tracking import JUDGMENT_VERSION, PRTracking

PR_ID = "acme/tool#42"
# The draft whose Approve sent the PR: agent_1 follows it.
SENT_PR = {"id": "draft_1", "kind": "pr", "status": "approved", "job": "job_1", "agent": "agent_1", "sent": {"kind": "pr", "repo": "acme/tool", "number": 42, "commit": "c0ffee1"}}
SHU = {"login": "shu", "__typename": "User"}
MAYA = {"login": "maya", "__typename": "User"}
RAJ = {"login": "raj", "__typename": "User"}
CODERABBIT = {"login": "coderabbitai", "__typename": "Bot"}
# Comments on the PR, in PR_STATUS_QUERY's shape.
MAYA_COMMENT = {"createdAt": "2026-11-11T10:00:00Z", "authorAssociation": "MEMBER", "body": "Could you add a test?", "author": MAYA}
OUR_COMMENT = {"createdAt": "2026-11-11T11:00:00Z", "authorAssociation": "CONTRIBUTOR", "body": "Added one.", "author": SHU}
COVERALLS_COMMENT = {"createdAt": "2026-11-11T09:00:00Z", "authorAssociation": "NONE", "body": "Coverage increased (+0.1%) to 91%.", "author": {"login": "coveralls", "__typename": "Bot"}}
# Claude's judgment of the PR (backend/github_api.py judge_prs), made after all of the above, on the newest commit.
NOTHING_NEEDED = {"key": "k", "needs": False, "reasons": [], "detail": "", "judged_at": "2026-11-11T12:00:00Z", "head": "c0ffee1", "failed_checks": []}
FAILED_TESTS = {"state": "FAILURE", "contexts": {"nodes": [{"__typename": "CheckRun", "name": "tests (3.12)", "status": "COMPLETED", "conclusion": "FAILURE"}]}}


@pytest.fixture
def github(monkeypatch):
    """A fake GitHub. pull is our PR acme/tool#42 as PR_STATUS_QUERY answers it: open, mergeable, one commit (commit)
    whose checks passed, nobody wrote yet. runs are its Actions runs, found what the search for PRs you opened finds.
    reads counts the PRs read. Each test changes what it needs."""
    commit = {
        "oid": "c0ffee1",
        "committedDate": "2026-11-10T09:00:00Z",
        "statusCheckRollup": {"state": "SUCCESS", "contexts": {"nodes": [{"__typename": "CheckRun", "name": "tests (3.12)", "status": "COMPLETED", "conclusion": "SUCCESS"}]}},
    }
    pull = {
        "number": 42,
        "title": "Fix the crash on empty input",
        "body": "Fixes #41.",
        "url": "https://github.com/acme/tool/pull/42",
        "state": "OPEN",
        "isDraft": False,
        "createdAt": "2026-11-10T09:00:00Z",
        "updatedAt": "2026-11-10T09:30:00Z",
        "closedAt": None,
        "mergedAt": None,
        "reviewDecision": None,
        "mergeable": "MERGEABLE",
        "baseRefName": "main",
        "additions": 12,
        "deletions": 2,
        "changedFiles": 2,
        "author": {"login": "shu"},
        "mergedBy": None,
        "headRefName": "fix-empty-input",
        "headRefOid": "c0ffee1",
        "headRepository": {"nameWithOwner": "shu/tool"},
        "headRef": {"name": "fix-empty-input"},
        "labels": {"nodes": []},
        "comments": {"totalCount": 0, "nodes": []},
        "reviews": {"nodes": []},
        "closingIssuesReferences": {
            "nodes": [{"number": 41, "title": "Crash on empty input", "url": "https://github.com/acme/tool/issues/41", "state": "OPEN", "stateReason": None, "assignees": {"nodes": [{"login": "shu"}]}}]
        },
        "commits": {"nodes": [{"commit": commit}]},
    }
    github = {"pull": pull, "commit": commit, "runs": [], "found": [], "search_fails": False, "reads": 0}

    def get_pr_status(owner, name, number):
        github["reads"] += 1
        return github["pull"]

    def search_issues(q, sort, per_page=50, page=1):
        if github["search_fails"]:
            raise httpx.ConnectError("Network is unreachable")
        items = github["found"] if q.startswith("is:pr author:") else []
        return {"items": items, "total_count": len(items)}

    monkeypatch.setattr(pr_tracking, "get_pr_status", get_pr_status)
    monkeypatch.setattr(pr_tracking, "get_action_runs", lambda owner, name, sha: github["runs"])
    monkeypatch.setattr(pr_tracking, "get_issue_status", lambda owner, name, number: None)
    monkeypatch.setattr(pr_tracking, "search_issues", search_issues)
    return github


@pytest.fixture
def tracking(github, tmp_path, monkeypatch):
    """PRTracking with its file in pytest's temporary folder. The Inbox has the draft that sent #42; the GitHub account
    (shu) isn't connected until a test connects it, so the PR's author is you."""
    monkeypatch.setattr(pr_tracking, "DATA_DIR", tmp_path)
    inbox = SimpleNamespace(drafts=[SENT_PR])
    inbox.list = lambda: inbox.drafts
    account = SimpleNamespace(connected=False)
    account.status = lambda: {"connected": account.connected, "login": "shu"}
    return PRTracking(inbox, account)


# What a read keeps.


def test_each_reviewers_latest_review_counts(github, tracking):
    github["pull"]["reviews"]["nodes"] = [
        {"state": "CHANGES_REQUESTED", "submittedAt": "2026-11-11T09:00:00Z", "authorAssociation": "MEMBER", "author": MAYA},
        {"state": "COMMENTED", "submittedAt": "2026-11-11T08:00:00Z", "authorAssociation": "NONE", "author": CODERABBIT},
        {"state": "APPROVED", "submittedAt": "2026-11-12T09:00:00Z", "authorAssociation": "MEMBER", "author": MAYA},
        # The PR's author's own review, and one not submitted yet: neither counts.
        {"state": "COMMENTED", "submittedAt": "2026-11-12T10:00:00Z", "authorAssociation": "CONTRIBUTOR", "author": SHU},
        {"state": "PENDING", "submittedAt": None, "authorAssociation": "MEMBER", "author": RAJ},
    ]

    tracking.read_all()

    pr = tracking.data["prs"][PR_ID]
    assert pr["reviewers"] == [
        {"login": "maya", "state": "approved", "at": "2026-11-12T09:00:00Z", "role": "MEMBER"},
        {"login": "coderabbitai", "state": "commented", "at": "2026-11-11T08:00:00Z", "role": "BOT"},
    ]
    assert pr["review"] == "approved"


@pytest.mark.parametrize(
    "states, decision, review",
    [
        ([], None, "none"),
        (["COMMENTED"], None, "commented"),
        (["COMMENTED"], "APPROVED", "approved"),
        (["APPROVED", "COMMENTED"], None, "approved"),
        # One reviewer asking for changes outweighs every approval, also GitHub's own decision.
        (["APPROVED", "CHANGES_REQUESTED"], "APPROVED", "changes_requested"),
    ],
)
def test_review_verdict(github, tracking, states, decision, review):
    for number, state in enumerate(states):
        github["pull"]["reviews"]["nodes"].append({"state": state, "submittedAt": f"2026-11-11T0{number}:00:00Z", "authorAssociation": "MEMBER", "author": {"login": f"reviewer{number}", "__typename": "User"}})
    github["pull"]["reviewDecision"] = decision

    tracking.read_all()

    assert tracking.data["prs"][PR_ID]["review"] == review


@pytest.mark.parametrize(
    "rollup, runs, checks",
    [
        (None, [], "none"),
        ({"state": "SUCCESS", "contexts": {"nodes": []}}, [], "passed"),
        ({"state": "FAILURE", "contexts": {"nodes": []}}, [], "failed"),
        ({"state": "ERROR", "contexts": {"nodes": []}}, [], "failed"),
        ({"state": "PENDING", "contexts": {"nodes": []}}, [], "running"),
        ({"state": "EXPECTED", "contexts": {"nodes": []}}, [], "running"),
        # A first-time contributor's runs wait for a maintainer to approve them, and the checks list shows nothing.
        (None, [{"conclusion": "action_required"}], "waiting"),
        ({"state": "SUCCESS", "contexts": {"nodes": []}}, [{"conclusion": "success"}, {"conclusion": "action_required"}], "waiting"),
    ],
)
def test_checks_of_the_newest_commit(github, tracking, rollup, runs, checks):
    github["commit"]["statusCheckRollup"] = rollup
    github["runs"] = runs

    tracking.read_all()

    assert tracking.data["prs"][PR_ID]["checks"] == checks
    assert tracking.data["prs"][PR_ID]["waiting_runs"] == len([run for run in runs if run["conclusion"] == "action_required"])


def test_failed_checks_are_named(github, tracking):
    github["commit"]["statusCheckRollup"] = {
        "state": "FAILURE",
        "contexts": {
            "nodes": [
                {"__typename": "CheckRun", "name": "tests", "status": "COMPLETED", "conclusion": "FAILURE"},
                {"__typename": "CheckRun", "name": "build", "status": "COMPLETED", "conclusion": "TIMED_OUT"},
                {"__typename": "CheckRun", "name": "docs", "status": "COMPLETED", "conclusion": "STARTUP_FAILURE"},
                {"__typename": "CheckRun", "name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {"__typename": "StatusContext", "context": "ci/circleci", "state": "ERROR"},
                {"__typename": "StatusContext", "context": "license/cla", "state": "FAILURE"},
                {"__typename": "StatusContext", "context": "codecov/patch", "state": "PENDING"},
            ]
        },
    }

    tracking.read_all()

    assert tracking.data["prs"][PR_ID]["failed_checks"] == ["tests", "build", "docs", "ci/circleci", "license/cla"]


def test_last_activity_is_someone_elses_newest_and_bots_never_count(github, tracking):
    renovate = {"createdAt": "2026-11-11T11:30:00Z", "authorAssociation": "NONE", "body": "Rebased.", "author": {"login": "renovate[bot]", "__typename": "User"}}
    github["pull"]["comments"] = {"totalCount": 4, "nodes": [COVERALLS_COMMENT, MAYA_COMMENT, OUR_COMMENT, renovate]}
    github["pull"]["reviews"]["nodes"] = [{"state": "COMMENTED", "submittedAt": "2026-11-11T08:00:00Z", "authorAssociation": "MEMBER", "author": RAJ}]

    tracking.read_all()

    pr = tracking.data["prs"][PR_ID]
    assert pr["last_activity"] == {"login": "maya", "at": "2026-11-11T10:00:00Z", "what": "comment"}
    assert pr["your_last_at"] == "2026-11-11T11:00:00Z"
    assert pr["bot_activity"] == {"login": "renovate[bot]", "at": "2026-11-11T11:30:00Z", "what": "commented"}


def test_a_merged_pr_that_did_not_change_is_not_read_again(github, tracking):
    tracking.github_account.connected = True
    github["found"] = [{"repository_url": "https://api.github.com/repos/acme/tool", "number": 42, "updated_at": "2026-11-12T09:00:00Z"}]
    github["pull"]["state"] = "MERGED"
    github["pull"]["updatedAt"] = "2026-11-12T09:00:00Z"
    github["pull"]["mergedBy"] = {"login": "maya"}

    tracking.read_all()
    tracking.read_all()

    assert github["reads"] == 1
    assert tracking.data["prs"][PR_ID]["merged_by"] == "maya"


def test_a_failed_search_keeps_what_it_follows(github, tracking):
    tracking.github_account.connected = True
    # A PR you opened by hand, which only the search finds.
    github["found"] = [{"repository_url": "https://api.github.com/repos/acme/tool", "number": 7, "updated_at": "2026-11-10T09:30:00Z"}]
    tracking.read_all()
    assert sorted(tracking.data["prs"]) == ["acme/tool#42", "acme/tool#7"]

    github["search_fails"] = True
    tracking.read_all()
    assert sorted(tracking.data["prs"]) == ["acme/tool#42", "acme/tool#7"]
    assert tracking.data["error"].startswith("Could not search GitHub for your PRs and issues")

    # The search works again and no longer finds #7: it goes.
    github["search_fails"] = False
    github["found"] = []
    tracking.read_all()
    assert sorted(tracking.data["prs"]) == ["acme/tool#42"]
    assert tracking.data["error"] is None


def test_judgments_from_older_rules_are_dropped_when_the_file_is_read(tmp_path, monkeypatch):
    monkeypatch.setattr(pr_tracking, "DATA_DIR", tmp_path)
    saved = {
        "prs": {},
        "issues": {},
        "checked_at": None,
        "error": None,
        "judgments": {"acme/tool#1": {"needs": True, "version": JUDGMENT_VERSION - 1}, "acme/tool#2": {"needs": False, "version": JUDGMENT_VERSION}},
        "agent_settings": {
            "acme/tool#1": {"action_state": ["old"], "action_version": JUDGMENT_VERSION - 1},
            "acme/tool#2": {"action_state": ["new"], "action_version": JUDGMENT_VERSION},
        },
    }
    (tmp_path / "pr_tracking.json").write_text(json.dumps(saved))

    tracking = PRTracking(SimpleNamespace(list=lambda: []), SimpleNamespace(status=lambda: {"connected": False}))

    assert list(tracking.data["judgments"]) == ["acme/tool#2"]
    assert tracking.data["agent_settings"]["acme/tool#1"]["action_state"] is None
    assert tracking.data["agent_settings"]["acme/tool#2"]["action_state"] == ["new"]


# What it needs from us: Needs action, or Waiting approval with GitHub's status.


def test_a_quiet_pr_needs_nothing_and_awaits_approval(github, tracking):
    tracking.read_all()
    tracking.update_actions([])

    action = tracking.data["prs"][PR_ID]["action"]
    assert action["needs"] is False
    assert action["reasons"] == []
    assert action["detail"] == ""
    assert action["status"] == "Awaiting approval"


@pytest.mark.parametrize(
    "rollup, reviews, mergeable, status",
    [
        ({"state": "PENDING", "contexts": {"nodes": []}}, [], "MERGEABLE", "Awaiting CI"),
        ({"state": "SUCCESS", "contexts": {"nodes": []}}, ["APPROVED"], "MERGEABLE", "Ready to merge"),
        (None, ["APPROVED"], "MERGEABLE", "Ready to merge"),
        # GitHub still works out whether it conflicts.
        ({"state": "SUCCESS", "contexts": {"nodes": []}}, ["APPROVED"], "UNKNOWN", "Awaiting approval"),
        ({"state": "SUCCESS", "contexts": {"nodes": []}}, ["COMMENTED"], "MERGEABLE", "Awaiting approval"),
    ],
)
def test_how_it_waits_in_githubs_words(github, tracking, rollup, reviews, mergeable, status):
    github["commit"]["statusCheckRollup"] = rollup
    github["pull"]["mergeable"] = mergeable
    for state in reviews:
        github["pull"]["reviews"]["nodes"].append({"state": state, "submittedAt": "2026-11-09T09:00:00Z", "authorAssociation": "MEMBER", "author": MAYA})

    tracking.read_all()
    tracking.update_actions([])

    assert tracking.data["prs"][PR_ID]["action"]["status"] == status


@pytest.mark.parametrize("mergeable, reasons", [("CONFLICTING", ["Merge conflicts"]), ("MERGEABLE", []), ("UNKNOWN", [])])
def test_merge_conflicts_only_when_github_says_so(github, tracking, mergeable, reasons):
    github["pull"]["mergeable"] = mergeable

    tracking.read_all()
    tracking.update_actions([])

    assert tracking.data["prs"][PR_ID]["action"]["reasons"] == reasons


@pytest.mark.parametrize(
    "check, reasons",
    [
        ({"__typename": "StatusContext", "context": "license/cla", "state": "FAILURE"}, ["CLA not signed"]),
        ({"__typename": "CheckRun", "name": "CLA Assistant", "status": "COMPLETED", "conclusion": "FAILURE"}, ["CLA not signed"]),
        ({"__typename": "CheckRun", "name": "cla-check", "status": "COMPLETED", "conclusion": "FAILURE"}, ["CLA not signed"]),
        ({"__typename": "CheckRun", "name": "clang-tidy", "status": "COMPLETED", "conclusion": "FAILURE"}, ["Checks failing"]),
        ({"__typename": "StatusContext", "context": "ci/tests", "state": "ERROR"}, ["Checks failing"]),
    ],
)
def test_a_failed_cla_check_is_cla_not_signed(github, tracking, check, reasons):
    github["commit"]["statusCheckRollup"] = {"state": "FAILURE", "contexts": {"nodes": [check]}}

    tracking.read_all()
    tracking.update_actions([])

    assert tracking.data["prs"][PR_ID]["action"]["reasons"] == reasons


def test_changes_requested_after_our_newest_step(github, tracking):
    github["pull"]["reviews"]["nodes"] = [{"state": "CHANGES_REQUESTED", "submittedAt": "2026-11-11T10:00:00Z", "authorAssociation": "MEMBER", "author": MAYA}]

    tracking.read_all()
    tracking.update_actions([])

    assert tracking.data["prs"][PR_ID]["action"]["reasons"] == ["Changes requested", "New review"]


def test_changes_requested_before_our_newest_commit_were_answered(github, tracking):
    github["pull"]["reviews"]["nodes"] = [{"state": "CHANGES_REQUESTED", "submittedAt": "2026-11-10T15:00:00Z", "authorAssociation": "MEMBER", "author": MAYA}]
    github["commit"]["committedDate"] = "2026-11-11T09:00:00Z"

    tracking.read_all()
    tracking.update_actions([])

    assert tracking.data["prs"][PR_ID]["action"]["needs"] is False


def test_a_review_bot_asking_for_changes_is_only_a_bot_review(github, tracking):
    github["pull"]["reviews"]["nodes"] = [{"state": "CHANGES_REQUESTED", "submittedAt": "2026-11-11T10:00:00Z", "authorAssociation": "NONE", "author": CODERABBIT}]

    tracking.read_all()
    tracking.update_actions([])

    assert tracking.data["prs"][PR_ID]["action"]["reasons"] == ["Bot review"]


@pytest.mark.parametrize("state, reasons", [("APPROVED", []), ("COMMENTED", ["New review"])])
def test_an_approval_is_no_new_review(github, tracking, state, reasons):
    github["pull"]["reviews"]["nodes"] = [{"state": state, "submittedAt": "2026-11-11T10:00:00Z", "authorAssociation": "MEMBER", "author": MAYA}]

    tracking.read_all()
    tracking.update_actions([])

    assert tracking.data["prs"][PR_ID]["action"]["reasons"] == reasons


def test_a_new_comment_needs_action_until_a_judgment_read_it(github, tracking):
    github["pull"]["comments"] = {"totalCount": 1, "nodes": [MAYA_COMMENT]}
    tracking.read_all()
    tracking.update_actions([])
    assert tracking.data["prs"][PR_ID]["action"]["reasons"] == ["New comment"]

    tracking.set_judgment(PR_ID, NOTHING_NEEDED)
    tracking.update_actions([])

    assert tracking.data["prs"][PR_ID]["action"]["needs"] is False


def test_our_reply_answers_a_comment(github, tracking):
    github["pull"]["comments"] = {"totalCount": 2, "nodes": [MAYA_COMMENT, OUR_COMMENT]}

    tracking.read_all()
    tracking.update_actions([])

    assert tracking.data["prs"][PR_ID]["action"]["needs"] is False


def test_failed_checks_need_action_until_a_judgment_saw_them(github, tracking):
    github["commit"]["statusCheckRollup"] = FAILED_TESTS
    tracking.read_all()
    tracking.update_actions([])
    assert tracking.data["prs"][PR_ID]["action"]["reasons"] == ["Checks failing"]

    tracking.set_judgment(PR_ID, {**NOTHING_NEEDED, "failed_checks": ["tests (3.12)"]})
    tracking.update_actions([])
    assert tracking.data["prs"][PR_ID]["action"]["needs"] is False

    # A check it didn't see fails too.
    lint = {"__typename": "CheckRun", "name": "lint", "status": "COMPLETED", "conclusion": "FAILURE"}
    github["commit"]["statusCheckRollup"] = {"state": "FAILURE", "contexts": {"nodes": FAILED_TESTS["contexts"]["nodes"] + [lint]}}
    tracking.read_all()
    tracking.update_actions([])
    assert tracking.data["prs"][PR_ID]["action"]["reasons"] == ["Checks failing"]


def test_an_approved_draft_not_sent_needs_action(github, tracking):
    tracking.inbox.drafts.append({"id": "draft_2", "kind": "comment", "status": "approved", "sent": None, "target": PR_ID})

    tracking.read_all()
    tracking.update_actions([])

    assert tracking.data["prs"][PR_ID]["action"]["reasons"] == ["Not sent"]


@pytest.mark.parametrize("base_sha, reasons", [("0ld5ha0", []), ("c0ffee1", ["Not sent"])])
def test_a_new_version_not_sent_counts_only_when_made_on_the_newest_commit(github, tracking, base_sha, reasons):
    tracking.inbox.drafts.append({"id": "draft_3", "kind": "pr", "status": "approved", "sent": None, "update_of": PR_ID, "base_sha": base_sha})

    tracking.read_all()
    tracking.update_actions([])

    assert tracking.data["prs"][PR_ID]["action"]["reasons"] == reasons


def test_reasons_show_in_the_order_of_action_labels(github, tracking):
    github["pull"]["mergeable"] = "CONFLICTING"
    github["pull"]["comments"] = {"totalCount": 1, "nodes": [MAYA_COMMENT]}
    github["commit"]["statusCheckRollup"] = FAILED_TESTS
    tracking.inbox.drafts.append({"id": "draft_2", "kind": "comment", "status": "approved", "sent": None, "target": PR_ID})

    tracking.read_all()
    tracking.update_actions([])

    assert tracking.data["prs"][PR_ID]["action"]["reasons"] == ["Merge conflicts", "Not sent", "Checks failing", "New comment"]


def test_only_our_open_prs_have_an_action(github, tracking):
    github["pull"]["mergeable"] = "CONFLICTING"
    tracking.read_all()
    tracking.data["prs"][PR_ID]["relation"] = "commented"
    tracking.update_actions([])
    assert tracking.data["prs"][PR_ID]["action"] is None

    github["pull"]["state"] = "MERGED"
    github["pull"]["mergedBy"] = {"login": "maya"}
    tracking.read_all()
    tracking.update_actions([])
    assert tracking.data["prs"][PR_ID]["action"] is None


def test_opencodex_8556_a_draft_held_by_the_projects_gate_needs_nothing_from_us(github, tracking):
    # opencodex's gate bot keeps a contributor's PR a draft until its runs, which wait for a maintainer's OK, pass. The
    # agents got "Draft" again and again with nothing they could do: a GitHub draft is no rule, only Claude's reading.
    github["pull"]["isDraft"] = True
    github["runs"] = [{"conclusion": "action_required"}]
    tracking.read_all()
    tracking.update_actions([])

    action = tracking.data["prs"][PR_ID]["action"]
    assert action["needs"] is False
    assert action["status"] == "Awaiting CI"

    # When reading the thread says the project waits for us to make it ready, Claude's judgment says Draft.
    tracking.set_judgment(PR_ID, {**NOTHING_NEEDED, "needs": True, "reasons": ["Draft"], "detail": "Tick the readiness boxes."})
    tracking.update_actions([])

    action = tracking.data["prs"][PR_ID]["action"]
    assert action["reasons"] == ["Draft"]
    assert action["detail"] == "Tick the readiness boxes."


def test_openmed_5516_a_comment_the_issues_own_agent_was_given_is_not_the_prs(github, tracking):
    # A maintainer's comment on openmed#5427 (assigning us) was answered by #5427's own job; the PR that fixes it got a
    # "New comment" job for it too.
    tracking.read_all()
    comment = {"login": "maya", "at": "2026-11-11T10:00:00Z", "what": "comment"}
    tracking.data["issues"]["acme/tool#41"] = {"id": "acme/tool#41", "updated_at": "2026-11-11T10:00:00Z", "last_activity": comment, "your_last_at": None}
    tracking.update_actions([])
    assert tracking.data["prs"][PR_ID]["action"]["reasons"] == ["New comment"]

    tracking.mark_answered("acme/tool#41", "2026-11-11T10:00:00Z", None)
    tracking.update_actions([])

    assert tracking.data["prs"][PR_ID]["action"]["needs"] is False


@pytest.mark.parametrize(
    "mergeable, judged, reasons, detail",
    [
        ("MERGEABLE", ["Merge conflicts"], [], ""),
        ("UNKNOWN", ["Merge conflicts"], [], ""),
        ("MERGEABLE", ["Merge conflicts", "Rebase needed"], ["Rebase needed"], "Rebase onto main."),
        ("CONFLICTING", ["Merge conflicts"], ["Merge conflicts"], "Rebase onto main."),
    ],
)
def test_reticle_2221_only_github_says_a_pr_conflicts(github, tracking, mergeable, judged, reasons, detail):
    # reticle#2221: Claude's reading asked for a rebase of a PR GitHub showed as MERGEABLE (it was only behind its base).
    # A judgment left with nothing else is no judgment, and its detail goes with it.
    github["pull"]["mergeable"] = mergeable
    tracking.read_all()
    tracking.set_judgment(PR_ID, {**NOTHING_NEEDED, "needs": True, "reasons": judged, "detail": "Rebase onto main."})

    tracking.update_actions([])

    action = tracking.data["prs"][PR_ID]["action"]
    assert action["reasons"] == reasons
    assert action["detail"] == detail


def test_kibi_666_a_bot_comment_already_judged_is_no_new_comment(github, tracking):
    # kibi's Coveralls report was judged as needing nothing; then the same report, edited, set off another job.
    github["pull"]["comments"] = {"totalCount": 1, "nodes": [COVERALLS_COMMENT]}
    tracking.read_all()
    tracking.update_actions([])

    pr = tracking.data["prs"][PR_ID]
    assert pr["last_activity"] is None
    assert pr["bot_activity"] == {"login": "coveralls", "at": "2026-11-11T09:00:00Z", "what": "commented"}
    assert pr["action"]["reasons"] == ["Bot review"]

    tracking.set_judgment(PR_ID, NOTHING_NEEDED)
    # Coveralls edits its report: the PR's updatedAt moves on, the comment's createdAt doesn't.
    github["pull"]["updatedAt"] = "2026-11-12T09:00:00Z"
    github["pull"]["comments"] = {"totalCount": 1, "nodes": [{**COVERALLS_COMMENT, "body": "Coverage increased (+0.2%) to 91%."}]}
    tracking.read_all()
    tracking.update_actions([])

    assert tracking.data["prs"][PR_ID]["action"]["needs"] is False


def test_openchoreo_5419_and_tabularis_1542_a_pr_its_agent_settled_waits_for_others(github, tracking):
    # Their agents found only a review bot's nitpick and ended; the PRs sat in Needs action for a day after.
    github["pull"]["reviews"]["nodes"] = [{"state": "COMMENTED", "submittedAt": "2026-11-11T09:00:00Z", "authorAssociation": "NONE", "author": CODERABBIT}]
    tracking.read_all()
    tracking.update_actions([])
    action = tracking.data["prs"][PR_ID]["action"]
    assert action["reasons"] == ["Bot review"]

    # Its agent is given it, and works on it: it stays in Needs action meanwhile.
    tracking.mark_action_given(PR_ID, "c0ffee1", "Bot review", action["state"])
    tracking.update_actions([{"status": "working", "thread": PR_ID, "issue": None}])
    assert tracking.data["prs"][PR_ID]["action"]["needs"] is True

    # The job ended with the PR as it was: the agent decided, and the PR waits for others.
    tracking.update_actions([{"status": "done", "thread": PR_ID, "issue": None}])
    action = tracking.data["prs"][PR_ID]["action"]
    assert action["needs"] is False
    assert action["reasons"] == []

    # Until something changes on it: a maintainer comments.
    github["pull"]["comments"] = {"totalCount": 1, "nodes": [MAYA_COMMENT]}
    tracking.read_all()
    tracking.update_actions([])
    assert tracking.data["prs"][PR_ID]["action"]["reasons"] == ["New comment", "Bot review"]


def test_xerj_3062_a_cla_its_agent_found_signed_waits_for_others(github, tracking):
    # xerj's CLA check failed although the CLA was signed in another PR: its agent found that and ended.
    github["commit"]["statusCheckRollup"] = {"state": "FAILURE", "contexts": {"nodes": [{"__typename": "StatusContext", "context": "license/cla", "state": "FAILURE"}]}}
    tracking.read_all()
    tracking.update_actions([])
    action = tracking.data["prs"][PR_ID]["action"]
    assert action["reasons"] == ["CLA not signed"]

    tracking.mark_action_given(PR_ID, "c0ffee1", "CLA not signed", action["state"])
    tracking.update_actions([{"status": "done", "thread": None, "issue": "acme/tool#41"}])

    assert tracking.data["prs"][PR_ID]["action"]["needs"] is False


def test_tries_count_the_gives_on_the_same_commit(tracking):
    tracking.mark_action_given(PR_ID, "c0ffee1", "Bot review", [])
    tracking.mark_action_given(PR_ID, "c0ffee1", "Bot review", [])
    assert tracking.data["agent_settings"][PR_ID]["action_tries"] == 2

    tracking.mark_action_given(PR_ID, "beef002", "Bot review", [])

    assert tracking.data["agent_settings"][PR_ID]["action_tries"] == 1
    assert tracking.data["agent_settings"][PR_ID]["action_version"] == JUDGMENT_VERSION


def test_a_judgment_is_made_again_once_what_it_was_made_on_changes(github, tracking):
    tracking.read_all()
    pr = tracking.data["prs"][PR_ID]
    key = tracking.judgment_key(pr, [])

    # A job still going changes nothing; one on the issue it fixes that ended does.
    assert tracking.judgment_key(pr, [{"status": "working", "thread": PR_ID, "issue": None, "updated_at": "2026-11-12T09:00:00Z"}]) == key
    assert tracking.judgment_key(pr, [{"status": "done", "thread": None, "issue": "acme/tool#41", "updated_at": "2026-11-12T09:00:00Z"}]) != key


# What its agent is told: needs_reply().


def test_someone_elses_comment_goes_to_the_agent_once(github, tracking):
    github["pull"]["comments"] = {"totalCount": 1, "nodes": [MAYA_COMMENT]}
    tracking.read_all()

    entries = tracking.needs_reply()
    assert [entry["reason"] for entry in entries] == ["@maya commented"]
    assert entries[0]["at"] == "2026-11-11T10:00:00Z"
    assert entries[0]["agent"] == "agent_1"

    tracking.mark_answered(PR_ID, entries[0]["at"], None)

    assert tracking.needs_reply() == []


def test_a_review_tells_what_the_reviewer_decided(github, tracking):
    github["pull"]["reviews"]["nodes"] = [{"state": "CHANGES_REQUESTED", "submittedAt": "2026-11-11T10:00:00Z", "authorAssociation": "MEMBER", "author": MAYA}]

    tracking.read_all()

    assert [entry["reason"] for entry in tracking.needs_reply()] == ["@maya reviewed it (changes requested)"]


def test_a_conflict_the_pr_has_at_its_first_read_is_news_to_its_agent(github, tracking):
    github["pull"]["mergeable"] = "CONFLICTING"

    tracking.read_all()

    assert [entry["reason"] for entry in tracking.needs_reply()] == ["it conflicts with main now"]


def test_github_still_working_out_a_conflict_keeps_what_the_agent_was_told(github, tracking):
    github["pull"]["mergeable"] = "CONFLICTING"
    tracking.read_all()
    tracking.mark_answered(PR_ID, None, None, tracking.needs_reply()[0]["signals"])

    # After a push GitHub works it out again for a while: unknown is no news, and doesn't wipe what the agent knows.
    github["pull"]["mergeable"] = "UNKNOWN"
    tracking.read_all()
    assert tracking.needs_reply() == []
    tracking.mark_answered(PR_ID, None, None, tracking.data["prs"][PR_ID]["signals"])
    assert tracking.data["agent_settings"][PR_ID]["told"]["mergeable"] == "conflicts"

    github["pull"]["mergeable"] = "MERGEABLE"
    tracking.read_all()

    assert [entry["reason"] for entry in tracking.needs_reply()] == ["it no longer conflicts with main"]


def test_failed_checks_go_to_the_agent_once_per_commit(github, tracking):
    tracking.read_all()
    github["commit"]["statusCheckRollup"] = FAILED_TESTS
    tracking.read_all()

    entries = tracking.needs_reply()
    assert [entry["reason"] for entry in entries] == ["its checks failed"]
    assert entries[0]["failed_sha"] == "c0ffee1"

    tracking.mark_answered(PR_ID, None, "c0ffee1", entries[0]["signals"])

    assert tracking.needs_reply() == []


def test_a_title_we_changed_ourselves_is_no_news(github, tracking):
    tracking.read_all()
    github["pull"]["title"] = "Fix the crash on empty input files"
    tracking.inbox.drafts.append(
        {"id": "draft_4", "kind": "edit", "status": "approved", "job": None, "agent": "agent_1", "sent": {"kind": "edit", "repo": "acme/tool", "number": 42, "title": "Fix the crash on empty input files"}}
    )
    tracking.read_all()
    assert tracking.needs_reply() == []

    github["pull"]["title"] = "WIP: crash fix"
    tracking.read_all()

    assert [entry["reason"] for entry in tracking.needs_reply()] == ['its title was changed to "WIP: crash fix"']


def test_a_commit_our_draft_sent_is_no_news_but_anyone_elses_is(github, tracking):
    tracking.read_all()
    # The new commit's checks haven't started: no news from them either.
    github["commit"]["statusCheckRollup"] = None
    github["pull"]["headRefOid"] = "beef002"
    tracking.inbox.drafts.append(
        {"id": "draft_5", "kind": "pr", "status": "approved", "job": "job_2", "agent": "agent_1", "update_of": PR_ID, "sent": {"kind": "pr", "repo": "acme/tool", "number": 42, "commit": "beef002"}}
    )
    tracking.read_all()
    assert tracking.needs_reply() == []

    github["pull"]["headRefOid"] = "dead003"
    tracking.read_all()

    assert [entry["reason"] for entry in tracking.needs_reply()] == ["its branch has a new commit, dead003, that no draft here made (the user or a maintainer pushed it)"]


def test_a_merged_pr_is_news_once(github, tracking):
    tracking.read_all()
    github["pull"]["state"] = "MERGED"
    github["pull"]["mergedBy"] = {"login": "maya"}
    tracking.read_all()

    entries = tracking.needs_reply()
    assert [entry["reason"] for entry in entries] == ["it was merged by @maya"]

    tracking.mark_answered(PR_ID, None, None, entries[0]["signals"])

    assert tracking.needs_reply() == []


def test_off_means_no_agent_follows_it(github, tracking):
    github["pull"]["comments"] = {"totalCount": 1, "nodes": [MAYA_COMMENT]}
    tracking.read_all()
    assert len(tracking.needs_reply()) == 1

    tracking.set_agent(PR_ID, "off", "agent_1")
    assert tracking.data["prs"][PR_ID]["agent"] is None
    assert tracking.needs_reply() == []

    # Your pick holds over the agent of the draft that sent it.
    tracking.read_all()
    assert tracking.data["prs"][PR_ID]["agent_mode"] == "off"
    assert tracking.needs_reply() == []


def test_set_agent_takes_only_drafts_or_off(tracking):
    with pytest.raises(ValueError, match="Unknown mode"):
        tracking.set_agent(PR_ID, "auto", "agent_1")
