"""Issue tags (github_searcher/issue_tags.py): the merge verdict's fixed rule, when an issue is taken without asking
Claude, which answers stay from one read to the next, and what Claude is shown about an issue.

The merge is the first rule that holds: Fixed, Out of scope, Claimed, Maintainers only, Waiting, No outside PRs, Large
feature, Big change, Can't validate, else Likely. Most rules are there because of a real issue an agent was wrongly
given; each of those is rebuilt here with small hand-made data and named after it. GitHub and Claude are fakes that
send what the test says, and the tags are kept in pytest's temporary folder, never in DATA_DIR. The tags file is written
at most every SAVE_SECONDS, and the tags of closed issues and of repos no longer in Repos go."""

import asyncio
import copy
import json
import types
from datetime import UTC, datetime, timedelta

import pytest

from github_searcher import issue_tags
from github_searcher.issue_tags import (
    BIG_LINES,
    BODY_CHARS,
    BOT_CHARS,
    NAME_CHARS,
    NAME_VERSION,
    REASON_CHARS,
    RULES_VERSION,
    TAKEN_PR_DAYS,
    TRIAGE,
    WILLING,
    IssueTags,
)
from github_searcher.repo_signals import MIN_SAMPLE

# Times in GitHub's format, which compare as text: touched two days ago, and untouched for longer than TAKEN_PR_DAYS.
RECENT = (datetime.now(UTC) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
STALE = (datetime.now(UTC) - timedelta(days=TAKEN_PR_DAYS + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def github():
    """What GitHub sends for owner/repo: one open issue, #7, nobody on it, nothing tied to it, no comments, and none
    of the user's pull requests merged there yet."""
    return {
        "nameWithOwner": "owner/repo",
        "description": "A command line tool",
        "stargazerCount": 120,
        "primaryLanguage": {"name": "Python"},
        "yourMerged": 0,
        "mentioned": {},
        "named": {},
        "i7": {
            "number": 7,
            "title": "Crash on empty input",
            "body": "Running it on an empty file crashes.",
            "state": "OPEN",
            "createdAt": "2026-11-01T10:00:00Z",
            "updatedAt": "2026-11-10T10:00:00Z",
            "authorAssociation": "NONE",
            "author": {"login": "reporter"},
            "labels": {"nodes": [{"name": "bug"}]},
            "assignees": {"nodes": []},
            "earliest": {"nodes": []},
            "latest": {"totalCount": 0, "nodes": []},
            "closedByPullRequestsReferences": {"nodes": []},
            "timelineItems": {"nodes": []},
        },
    }


@pytest.fixture
def answer():
    """Claude's answer for #7: free, every check yes, a 20-line bug fix."""
    return {
        "number": 7,
        "status": "free",
        "kind": "bug",
        "lines": 20,
        "name": "Fix crash on empty input",
        "complexity": "easy",
        "scope_clear": True,
        "reason": "Nobody is on it.",
        "belongs": True,
        "linux": True,
        "apolitical": True,
        "not_game": True,
        "open": True,
        "any_contributor": True,
        "ai_ok": True,
        "modest": True,
        "validatable": True,
    }


@pytest.fixture
def signals():
    """The repo's numbers (repo_signals.py), by repo: owner/repo merges outsiders' pull requests."""
    return {
        "owner/repo": {
            "ai_policy": {"tag": "welcome"},
            "newcomers": {"tag": "welcomes"},
            "outside_merged_90d": 6,
            "outside_closed_90d": 2,
            "newcomer_verdict": {"verdict": "welcome"},
        }
    }


@pytest.fixture
def prompts():
    """Every prompt Claude was sent."""
    return []


@pytest.fixture
def tags(tmp_path, monkeypatch, github, answer, signals, prompts):
    """IssueTags for the user Shu, with issue_tags.json in a temporary folder. GitHub sends github, Claude answers
    with answer: both read at the time of the call, so a test can change them first."""
    monkeypatch.setattr(issue_tags, "DATA_DIR", tmp_path)
    monkeypatch.setattr(issue_tags, "get_issues_for_tags", lambda owner, repo, numbers, login: copy.deepcopy(github))

    async def fake_judge(prompt, schema, effort):
        prompts.append(prompt)
        return {"issues": [copy.deepcopy(answer)]}

    monkeypatch.setattr(issue_tags, "judge", fake_judge)
    account = types.SimpleNamespace(status=lambda: {"login": "Shu"})
    return IssueTags(signals, account)


@pytest.fixture
def pull():
    """Someone else's (alice's) pull request #9 in owner/repo, open and touched two days ago, with no comments."""
    return {
        "__typename": "PullRequest",
        "number": 9,
        "title": "Fix crash on empty input",
        "state": "OPEN",
        "createdAt": RECENT,
        "updatedAt": RECENT,
        "closedAt": None,
        "author": {"login": "alice"},
        "repository": {"nameWithOwner": "owner/repo"},
        "comments": {"nodes": []},
    }


# The merge rule, top to bottom. Each rule's test also trips the rule below it, so the order is checked too.


def test_nothing_in_the_way_is_likely(tags, prompts):
    assert asyncio.run(tags.tag_batch("owner/repo", [7])) == ["owner/repo#7"]
    tag = tags.all()["owner/repo#7"]

    assert tag["status"] == "free"
    assert tag["merge"] == "likely"
    assert tag["reason"] == "Nobody is on it. Merge: Likely, nothing stands in the way."
    assert tag["kind"] == "bug"
    assert tag["lines"] == 20
    assert tag["name"] == "Fix crash on empty input"
    assert tag["rules_version"] == RULES_VERSION
    assert tag["name_version"] == NAME_VERSION
    assert tag["updated_at"] == "2026-11-10T10:00:00Z"
    assert all(tag["checks"].values())
    assert len(prompts) == 1


def test_runanywhere_sdks_1181_already_fixed_is_fixed_before_anything_else(tags, answer):
    # #1181's fix and tests were already on main; it should have been tagged fixed, whatever else is true of it.
    answer["status"] = "fixed"
    answer["lines"] = 900
    for key in ["belongs", "linux", "apolitical", "not_game", "open", "any_contributor", "ai_ok", "modest", "validatable"]:
        answer[key] = False

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.all()["owner/repo#7"]["merge"] == "fixed"


@pytest.mark.parametrize(
    "check, why",
    [
        ("apolitical", "it touches politics"),
        ("not_game", "it is about a game"),
        ("belongs", "it isn't a pull request to this repo for its own users"),
        ("linux", "it can only be seen on Windows, macOS, a phone or other hardware"),
    ],
)
def test_out_of_scope_comes_before_claimed(tags, answer, check, why):
    answer["status"] = "assigned"
    answer[check] = False

    asyncio.run(tags.tag_batch("owner/repo", [7]))
    tag = tags.all()["owner/repo#7"]

    assert tag["merge"] == "out of scope"
    assert f"Merge: Out of scope, {why}" in tag["reason"]


def test_bambuddy_3524_fix_in_an_image_built_elsewhere_is_out_of_scope(tags, github, answer, prompts):
    # The bug was in a prebuilt image the repo only pulls in, built from another repo by the maintainer's own script.
    github["i7"]["body"] = "The bambu-studio-api container can't write to /data: permission denied."
    answer["belongs"] = False

    asyncio.run(tags.tag_batch("owner/repo", [7]))
    tag = tags.all()["owner/repo#7"]

    assert tag["merge"] == "out of scope"
    assert "its fix lives outside this repo's code" in tag["reason"]
    assert "in a prebuilt image, package or binary the repo only pulls in" in prompts[0]


def test_mcp_memory_service_1910_author_sending_the_pr_is_claimed(tags, github, answer, prompts):
    # The author posted the whole fix and its test, and said they would send the PR once a maintainer confirmed.
    github["i7"]["latest"] = {
        "totalCount": 1,
        "nodes": [
            {
                "body": "Here is the fix and a test. I'd like to send the PR myself, I'll /claim once a maintainer confirms.",
                "createdAt": "2026-11-07T18:00:00Z",
                "authorAssociation": "NONE",
                "author": {"login": "reporter", "__typename": "User"},
            }
        ],
    }
    answer["status"] = "assigned"
    answer["open"] = False

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.all()["owner/repo#7"]["merge"] == "claimed"
    assert "I'll /claim once a maintainer confirms." in prompts[0]
    assert "A fix posted in the issue's description or in a comment counts too" in prompts[0]


def test_kestra_14059_internal_team_is_maintainers_only(tags, github, answer, prompts):
    # A triager whose role shows only CONTRIBUTOR said the internal team would handle it.
    github["i7"]["latest"] = {
        "totalCount": 1,
        "nodes": [
            {
                "body": "This one will be handled by the internal Kestra team.",
                "createdAt": "2026-10-27T09:00:00Z",
                "authorAssociation": "CONTRIBUTOR",
                "author": {"login": "marco-comi", "__typename": "User"},
            }
        ],
    }
    answer["status"] = "waiting"
    answer["open"] = False

    asyncio.run(tags.tag_batch("owner/repo", [7]))
    tag = tags.all()["owner/repo#7"]

    assert tag["merge"] == "maintainers only"
    assert "the maintainers keep it for themselves" in tag["reason"]
    assert "--- marco-comi (CONTRIBUTOR), 2026-10-27:\nThis one will be handled by the internal Kestra team." in prompts[0]


def test_deskcommcrm_4410_newcomers_only_is_maintainers_only_once_you_have_a_merged_pr(tags, github, answer):
    # "se você já contribui, deixe esta para um estreante", and the user already had merged pull requests there.
    github["yourMerged"] = 2
    answer["any_contributor"] = False
    answer["status"] = "waiting"

    asyncio.run(tags.tag_batch("owner/repo", [7]))
    tag = tags.all()["owner/repo#7"]

    assert tag["merge"] == "maintainers only"
    assert "kept for first-time contributors, and you already have a merged pull request" in tag["reason"]


@pytest.mark.parametrize("merged", [0, None])
def test_newcomers_only_is_open_to_you_before_your_first_merged_pr(tags, github, answer, merged):
    # None: without a GitHub account nobody knows of a merged pull request of the user's.
    github["yourMerged"] = merged
    answer["any_contributor"] = False

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.all()["owner/repo#7"]["merge"] == "likely"


def test_dioxus_6063_waiting_on_an_upstream_release_is_waiting(tags, answer, signals, prompts):
    # The change was merged upstream, but the release this project uses doesn't have it yet.
    answer["status"] = "waiting"
    signals["owner/repo"]["ai_policy"]["tag"] = "no_ai"

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.all()["owner/repo#7"]["merge"] == "waiting"
    assert "So is one whose fix needs a release that isn't out yet" in prompts[0]


def test_mastra_28528_triage_label_is_waiting_whatever_claude_says(tags, github, signals):
    # The triage bot said to open no pull request until "status: needs triage" is removed. Claude said free.
    github["i7"]["labels"]["nodes"].append({"name": "status: needs triage"})
    signals["owner/repo"]["newcomer_verdict"] = {"verdict": "closed"}

    asyncio.run(tags.tag_batch("owner/repo", [7]))
    tag = tags.all()["owner/repo#7"]

    assert tag["status"] == "waiting"
    assert tag["merge"] == "waiting"
    assert tag["reason"] == (
        "It still waits for the maintainers' triage or approval (its label status: needs triage). "
        "Merge: Waiting, it isn't ready to pick up."
    )


def test_triage_label_leaves_a_fixed_issue_fixed(tags, github, answer):
    github["i7"]["labels"]["nodes"].append({"name": "needs-triage"})
    answer["status"] = "fixed"

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.all()["owner/repo#7"]["status"] == "fixed"
    assert tags.all()["owner/repo#7"]["merge"] == "fixed"


@pytest.mark.parametrize(
    "label, waits",
    [
        ("status: needs triage", True),
        ("needs-triage", True),
        ("Needs Triage", True),
        ("needs-approval", True),
        ("awaiting triage", True),
        ("pending_approval", True),
        ("untriaged", True),
        ("triage needed", True),
        ("triaged", False),
        ("approved", False),
        ("needs-review", False),
        ("bug", False),
    ],
)
def test_triage_labels(label, waits):
    assert bool(TRIAGE.search(label)) is waits


@pytest.mark.parametrize(
    "repo, why",
    [
        ({"ai_policy": {"tag": "no_ai"}}, "the project doesn't accept AI-made contributions"),
        ({"newcomers": {"tag": "turned_away"}}, "most newcomers' first pull requests are closed or left waiting"),
        ({"newcomers": {"tag": "left_waiting"}}, "most newcomers' first pull requests are closed or left waiting"),
        ({"outside_merged_90d": 0, "outside_closed_90d": MIN_SAMPLE}, "none of the outside pull requests that ended"),
        # mastra#28528 and DeepSeek-Reasonix#14665: pull requests disabled for outside contributors.
        ({"newcomer_verdict": {"verdict": "closed"}}, "the project isn't open to outside contributors' pull requests"),
    ],
)
def test_repo_that_doesnt_merge_outsiders_is_no_outside_prs(tags, answer, signals, repo, why):
    signals["owner/repo"].update(repo)
    answer["modest"] = False

    asyncio.run(tags.tag_batch("owner/repo", [7]))
    tag = tags.all()["owner/repo#7"]

    assert tag["merge"] == "no outside prs"
    assert f"Merge: No outside PRs, {why}" in tag["reason"]


@pytest.mark.parametrize(
    "repo",
    [
        {"outside_merged_90d": 0, "outside_closed_90d": MIN_SAMPLE - 1},
        {"newcomer_verdict": None},
        {"newcomers": {"tag": "few"}},
    ],
)
def test_repo_numbers_that_say_nothing_leave_it_likely(tags, signals, repo):
    signals["owner/repo"].update(repo)

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.all()["owner/repo#7"]["merge"] == "likely"


def test_repo_numbers_not_in_yet_leave_it_likely(tags, signals):
    signals.clear()

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.all()["owner/repo#7"]["merge"] == "likely"


def test_hydro_3281_pr_closed_as_ai_made_is_no_outside_prs(tags, github, answer, pull, prompts):
    # A maintainer closed the fix for this exact issue as "an autonomously generated PR": ours would go the same way.
    pull["number"] = 3295
    pull["state"] = "CLOSED"
    pull["closedAt"] = "2026-11-09T12:00:00Z"
    pull["comments"]["nodes"].append(
        {
            "body": "Closing, this appears to be an autonomously generated PR.",
            "createdAt": "2026-11-09T12:00:00Z",
            "authorAssociation": "MEMBER",
            "author": {"login": "shadaj", "__typename": "User"},
        }
    )
    github["i7"]["closedByPullRequestsReferences"]["nodes"].append(pull)
    answer["ai_ok"] = False
    answer["modest"] = False

    asyncio.run(tags.tag_batch("owner/repo", [7]))
    tag = tags.all()["owner/repo#7"]

    assert tag["merge"] == "no outside prs"
    assert "looked AI-made" in tag["reason"]
    assert "closed without merging 2026-11-09." in prompts[0]
    assert "Its last comment, by shadaj (MEMBER): Closing, this appears to be an autonomously generated PR." in prompts[0]


def test_large_feature_comes_before_big_change(tags, answer):
    answer["modest"] = False
    answer["lines"] = 900

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.all()["owner/repo#7"]["merge"] == "large feature"


def test_openchoreo_5371_big_change_without_a_merged_pr_is_big_change(tags, answer):
    # Three CRDs, new webhooks and four clients in a repo where the user had no merged pull request.
    answer["lines"] = BIG_LINES + 1
    answer["validatable"] = False

    asyncio.run(tags.tag_batch("owner/repo", [7]))
    tag = tags.all()["owner/repo#7"]

    assert tag["merge"] == "big change"
    assert f"about {BIG_LINES + 1} lines, and you have no merged pull request in this repo yet" in tag["reason"]


def test_exactly_big_lines_is_not_a_big_change(tags, answer):
    answer["lines"] = BIG_LINES

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.all()["owner/repo#7"]["merge"] == "likely"


def test_big_change_is_fine_once_you_have_a_merged_pr(tags, github, answer):
    github["yourMerged"] = 1
    answer["lines"] = 900

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.all()["owner/repo#7"]["merge"] == "likely"


def test_openchoreo_5129_bug_behind_a_host_firewall_cant_validate(tags, answer, prompts):
    # It only showed with a default-deny host firewall, which an agent may not set up in a VM others share.
    answer["validatable"] = False

    asyncio.run(tags.tag_batch("owner/repo", [7]))
    tag = tags.all()["owner/repo#7"]

    assert tag["merge"] == "can't validate"
    assert tag["reason"].endswith("Merge: Can't validate, our agent can't prove the fix works in its VM.")
    assert "a default-deny host firewall" in prompts[0]


# Taken without asking Claude: an assignee, or someone else's live pull request that says it closes it.


def test_assignee_on_github_is_claimed_without_asking_claude(tags, github, prompts):
    github["i7"]["assignees"]["nodes"].append({"login": "alice"})

    assert asyncio.run(tags.tag_batch("owner/repo", [7])) == ["owner/repo#7"]
    tag = tags.all()["owner/repo#7"]

    assert prompts == []
    assert tag["status"] == "assigned"
    assert tag["merge"] == "claimed"
    assert tag["reason"] == "Assigned on GitHub to alice."
    assert tag["checks"] is None
    assert tag["kind"] is None
    assert tag["lines"] is None
    assert tag["name"] is None
    assert tag["complexity"] is None
    assert tag["scope_clear"] is None


def test_assigned_only_to_you_is_read_by_claude(tags, github, prompts):
    # The login's case doesn't matter: GitHub's logins don't have one.
    github["i7"]["assignees"]["nodes"].append({"login": "shu"})

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert len(prompts) == 1
    assert tags.all()["owner/repo#7"]["status"] == "free"


def test_assigned_to_you_and_someone_else_names_only_them(tags, github):
    github["i7"]["assignees"]["nodes"].append({"login": "Shu"})
    github["i7"]["assignees"]["nodes"].append({"login": "alice"})

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.all()["owner/repo#7"]["reason"] == "Assigned on GitHub to alice."


def test_repowise_5369_open_pr_that_closes_it_is_claimed(tags, github, pull, prompts):
    # A newcomer's pull request said it closes the issue, and our agent still worked it to a draft.
    pull["number"] = 5389
    pull["author"] = {"login": "newcomer"}
    github["i7"]["closedByPullRequestsReferences"]["nodes"].append(pull)

    asyncio.run(tags.tag_batch("owner/repo", [7]))
    tag = tags.all()["owner/repo#7"]

    assert prompts == []
    assert tag["merge"] == "claimed"
    assert tag["reason"] == "Open pull request #5389 by newcomer says it closes it."
    assert tags.open_prs["owner/repo#7"] == ["owner/repo#5389 by newcomer"]


def test_closing_pr_by_a_deleted_account_is_claimed(tags, github, pull):
    pull["author"] = None
    github["i7"]["closedByPullRequestsReferences"]["nodes"].append(pull)

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.all()["owner/repo#7"]["reason"] == "Open pull request #9 by ghost says it closes it."


def test_closing_pr_untouched_for_taken_pr_days_is_read_by_claude(tags, github, pull, prompts):
    # It may be abandoned: Claude weighs that.
    pull["updatedAt"] = STALE
    github["i7"]["closedByPullRequestsReferences"]["nodes"].append(pull)

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert len(prompts) == 1
    assert tags.all()["owner/repo#7"]["merge"] == "likely"
    assert tags.open_prs["owner/repo#7"] == []
    assert f"by alice says it closes it: opened {RECENT[:10]}, still open, last updated {STALE[:10]}." in prompts[0]


@pytest.mark.parametrize("state", ["CLOSED", "MERGED"])
def test_closing_pr_that_ended_is_read_by_claude(tags, github, pull, prompts, state):
    pull["state"] = state
    pull["closedAt"] = RECENT
    github["i7"]["closedByPullRequestsReferences"]["nodes"].append(pull)

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert len(prompts) == 1
    assert tags.all()["owner/repo#7"]["status"] == "free"


def test_qwenpaw_8698_your_own_work_is_never_someone_on_it(tags, github, pull, prompts):
    # The user's own claim was once taken for someone else's. Their open pull request doesn't take the issue either.
    pull["author"] = {"login": "shu"}
    github["i7"]["closedByPullRequestsReferences"]["nodes"].append(pull)

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.all()["owner/repo#7"]["status"] == "free"
    assert tags.open_prs["owner/repo#7"] == []
    assert "We work for the GitHub user Shu. Their own claims, assignment and pull requests" in prompts[0]


def test_without_a_github_account_every_assignee_counts(tags, github, prompts):
    tags.github_account = types.SimpleNamespace(status=lambda: {})
    github["yourMerged"] = None
    github["i7"]["assignees"]["nodes"].append({"login": "shu"})

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert prompts == []
    assert tags.all()["owner/repo#7"]["merge"] == "claimed"


def test_deskcommcrm_4511_open_pr_that_only_mentions_it_is_heard(tags, github, pull, prompts):
    # #4511 only said "Refs #4495": the issue stayed free, and an agent ran five more hours on a fix nobody wanted.
    pull["number"] = 4511
    pull["author"] = {"login": "bob"}
    github["i7"]["timelineItems"]["nodes"].append({"__typename": "CrossReferencedEvent", "source": pull})

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.all()["owner/repo#7"]["status"] == "free"
    assert tags.open_prs["owner/repo#7"] == ["owner/repo#4511 by bob"]
    assert "Pull request #4511 (\"Fix crash on empty input\") by bob mentions it" in prompts[0]


def test_open_prs_leave_out_yours_old_ended_and_repeats(tags, github, pull):
    closed = dict(pull, number=10, state="CLOSED", closedAt=RECENT)
    yours = dict(pull, number=11, author={"login": "Shu"})
    old = dict(pull, number=12, author={"login": "carol"}, updatedAt=STALE)
    linked = dict(pull, number=13, author={"login": "bob"})
    elsewhere = dict(pull, number=14, author={"login": "dan"}, repository={"nameWithOwner": "other/repo"})
    github["i7"]["closedByPullRequestsReferences"]["nodes"].append(closed)
    github["i7"]["timelineItems"]["nodes"] = [
        {"__typename": "CrossReferencedEvent", "source": yours},
        {"__typename": "CrossReferencedEvent", "source": old},
        {"__typename": "CrossReferencedEvent", "source": linked},
        {"__typename": "ConnectedEvent", "subject": linked},
        {"__typename": "CrossReferencedEvent", "source": {"__typename": "Issue"}},
        {"__typename": "ReferencedEvent", "createdAt": RECENT, "commitRepository": {"nameWithOwner": "other/repo"}, "commit": None},
        {
            "__typename": "ReferencedEvent",
            "createdAt": RECENT,
            "commitRepository": {"nameWithOwner": "other/repo"},
            "commit": {"abbreviatedOid": "abc1234", "messageHeadline": "Handle empty input", "associatedPullRequests": {"nodes": [elsewhere]}},
        },
    ]

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.open_prs["owner/repo#7"] == ["owner/repo#13 by bob", "other/repo#14 by dan"]


# Which answers stay from one read to the next.


def test_answers_stay_while_the_issue_is_unchanged(tags, answer, prompts):
    asyncio.run(tags.tag_batch("owner/repo", [7]))
    answer.update({"validatable": False, "kind": "feature", "lines": 500, "complexity": "hard", "scope_clear": False, "name": "Add something else"})

    asyncio.run(tags.tag_batch("owner/repo", [7]))
    tag = tags.all()["owner/repo#7"]

    assert tag["checks"]["validatable"] is True
    assert tag["kind"] == "bug"
    assert tag["lines"] == 20
    assert tag["complexity"] == "easy"
    assert tag["scope_clear"] is True
    assert tag["name"] == "Fix crash on empty input"
    assert tag["merge"] == "likely"
    assert "Nothing changed since: give the same answers." in prompts[1]
    assert "Read before: belongs yes, linux yes," in prompts[1]


def test_status_is_judged_afresh_every_read(tags, answer):
    asyncio.run(tags.tag_batch("owner/repo", [7]))
    answer["status"] = "assigned"

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.all()["owner/repo#7"]["merge"] == "claimed"


def test_changed_issue_takes_the_new_answers_but_keeps_its_name(tags, github, answer, prompts):
    asyncio.run(tags.tag_batch("owner/repo", [7]))
    github["i7"]["updatedAt"] = "2026-11-12T10:00:00Z"
    answer.update({"validatable": False, "kind": "feature", "complexity": "hard", "name": "Add something else"})

    asyncio.run(tags.tag_batch("owner/repo", [7]))
    tag = tags.all()["owner/repo#7"]

    assert tag["merge"] == "can't validate"
    assert tag["kind"] == "feature"
    assert tag["complexity"] == "hard"
    assert tag["name"] == "Fix crash on empty input"
    assert tag["updated_at"] == "2026-11-12T10:00:00Z"
    assert "It changed since: keep those answers unless what is new shows otherwise." in prompts[1]


def test_forced_read_keeps_nothing(tags, answer, prompts):
    asyncio.run(tags.tag_batch("owner/repo", [7]))
    answer.update({"validatable": False, "complexity": "hard", "name": "Add something else"})

    asyncio.run(tags.tag_batch("owner/repo", [7], force=True))
    tag = tags.all()["owner/repo#7"]

    assert tag["merge"] == "can't validate"
    assert tag["complexity"] == "hard"
    assert tag["name"] == "Add something else"
    assert "Read before" not in prompts[1]


def test_bambuddy_3524_answers_from_older_rules_are_asked_afresh(tags, answer, prompts):
    # Read under the old rules, belongs was yes: the old answer would have kept the old mistake.
    tags.tags["owner/repo#7"] = {
        "status": "free",
        "merge": "likely",
        "checks": {"belongs": True, "linux": True, "apolitical": True, "not_game": True, "open": True, "modest": True, "validatable": True},
        "kind": "bug",
        "lines": 20,
        "name": "Fix image permissions",
        "name_version": NAME_VERSION,
        "rules_version": RULES_VERSION - 1,
        "complexity": "easy",
        "scope_clear": True,
        "reason": "",
        "updated_at": "2026-11-10T10:00:00Z",
        "judged_at": "2026-11-10T11:00:00Z",
    }
    answer["belongs"] = False

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.all()["owner/repo#7"]["merge"] == "out of scope"
    assert "Read before" not in prompts[0]


def test_check_added_since_takes_the_new_answer(tags, answer):
    # Read before ai_ok was a check, and with one ("easy") that is gone since.
    tags.tags["owner/repo#7"] = {
        "status": "free",
        "merge": "likely",
        "checks": {"belongs": True, "linux": True, "apolitical": True, "not_game": True, "open": True, "any_contributor": True, "modest": True, "validatable": True, "easy": True},
        "kind": "bug",
        "lines": None,
        "name": "Fix crash on empty input",
        "name_version": NAME_VERSION,
        "rules_version": RULES_VERSION,
        "complexity": None,
        "scope_clear": None,
        "reason": "",
        "updated_at": "2026-11-10T10:00:00Z",
        "judged_at": "2026-11-10T11:00:00Z",
    }
    answer["ai_ok"] = False
    answer["lines"] = 30

    asyncio.run(tags.tag_batch("owner/repo", [7]))
    tag = tags.all()["owner/repo#7"]

    assert tag["merge"] == "no outside prs"
    assert "easy" not in tag["checks"]
    assert tag["lines"] == 30
    assert tag["complexity"] == "easy"


def test_name_from_older_naming_rules_is_made_again(tags, answer):
    tags.tags["owner/repo#7"] = {"name": "Bug: crash", "name_version": NAME_VERSION - 1, "updated_at": "2026-11-10T10:00:00Z"}

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.all()["owner/repo#7"]["name"] == "Fix crash on empty input"


def test_name_and_reason_are_kept_short(tags, answer):
    answer["name"] = "  Fix   crash\n on empty input.  "
    answer["reason"] = "Nobody is on it " + "x" * 400
    answer["lines"] = -5

    asyncio.run(tags.tag_batch("owner/repo", [7]))
    tag = tags.all()["owner/repo#7"]

    assert tag["name"] == "Fix crash on empty input"
    assert tag["lines"] == 0
    reason = tag["reason"].split(" Merge: ")[0]
    assert len(reason) == REASON_CHARS
    assert reason.endswith("x…")


def test_long_name_is_cut(tags, answer):
    answer["name"] = "Fix " + "very " * 20 + "long name"

    asyncio.run(tags.tag_batch("owner/repo", [7]))
    name = tags.all()["owner/repo#7"]["name"]

    assert len(name) <= NAME_CHARS
    assert name.endswith("very…")


# The batch around the rule.


def test_only_the_issues_asked_about_are_kept(tags, monkeypatch, answer):
    async def fake_judge(prompt, schema, effort):
        return {"issues": [answer, dict(answer, number=8)]}

    monkeypatch.setattr(issue_tags, "judge", fake_judge)

    assert asyncio.run(tags.tag_batch("owner/repo", [7])) == ["owner/repo#7"]
    assert list(tags.all()) == ["owner/repo#7"]


def test_gone_issue_is_left_out(tags, github, prompts):
    github["i7"] = None

    assert asyncio.run(tags.tag_batch("owner/repo", [7])) == []
    assert prompts == []
    assert tags.all() == {}


def test_tag_asks_by_repo_a_batch_at_a_time_and_skips_failed_ones(tags, monkeypatch, github):
    asked = []
    # Only owner/repo is on GitHub: the call for owner/broken fails (a KeyError here, ValueError from GitHub).
    sent = {"owner/repo": github}

    def fake_get_issues(owner, repo, numbers, login):
        asked.append((f"{owner}/{repo}", numbers))
        return copy.deepcopy(sent[f"{owner}/{repo}"])

    monkeypatch.setattr(issue_tags, "get_issues_for_tags", fake_get_issues)
    ids = [f"owner/repo#{number}" for number in range(1, 46)] + ["owner/broken#1"]

    assert asyncio.run(tags.tag(ids)) == ["owner/repo#7"]
    assert sorted(len(numbers) for name, numbers in asked) == [1, 5, 20, 20]


def test_tags_are_saved_and_come_back(tags, tmp_path, signals):
    asyncio.run(tags.tag_batch("owner/repo", [7]))
    tags.flush(now=True)

    assert json.loads((tmp_path / "issue_tags.json").read_text()) == tags.all()
    assert tags.version > 0
    restarted = IssueTags(signals, tags.github_account)
    assert restarted.all() == tags.all()


def test_tags_file_is_written_at_most_every_save_seconds(tags, tmp_path):
    # The file is 49 MB at 90,000 issues: written on every change, it held the backend up.
    with tags.lock:
        tags.tags["owner/repo#1"] = {"status": "free"}
        tags.save()
    tags.flush()
    assert json.loads((tmp_path / "issue_tags.json").read_text()) == {"owner/repo#1": {"status": "free"}}

    with tags.lock:
        tags.tags["owner/repo#2"] = {"status": "assigned"}
        tags.save()
    tags.flush()
    assert json.loads((tmp_path / "issue_tags.json").read_text()) == {"owner/repo#1": {"status": "free"}}

    tags.flush(now=True)
    assert sorted(json.loads((tmp_path / "issue_tags.json").read_text())) == ["owner/repo#1", "owner/repo#2"]


def test_closed_issues_and_gone_repos_lose_their_tags(tags):
    with tags.lock:
        for issue_id in ["owner/repo#1", "owner/repo#2", "Owner/Repo#3", "owner/repo-two#9", "other/gone#4", "other/gone#5"]:
            tags.tags[issue_id] = {"status": "free"}

    # owner/repo#2 is closed; #3 is in the Issues list (closed or not, its tags stay); owner/repo-two is another repo.
    tags.forget_closed("owner/repo", ["owner/repo#1"], ["owner/repo#3"])
    assert sorted(tags.all()) == ["Owner/Repo#3", "other/gone#4", "other/gone#5", "owner/repo#1", "owner/repo-two#9"]

    # other/gone left Repos; other/gone#5 is in the Issues list.
    tags.forget_repos(["owner/repo", "owner/repo-two"], ["other/gone#5"])
    assert sorted(tags.all()) == ["Owner/Repo#3", "other/gone#5", "owner/repo#1", "owner/repo-two#9"]


# What Claude is shown, so it can judge the cases above.


@pytest.mark.parametrize(
    "line, asks",
    [
        ("### Are you willing to submit a PR?", True),
        ("Would you like to work on this?", True),
        ("I'm interested in implementing this", True),
        ("- [ ] I'd like to contribute a fix", True),
        ("Would you open a pull request for it?", True),
        ("### Steps to reproduce", False),
        ("### Expected behavior", False),
    ],
)
def test_willing_finds_where_the_template_asks_about_fixing_it(line, asks):
    assert bool(WILLING.search(line)) is asks


def test_mcp_memory_service_1910_willing_part_of_a_long_template_is_kept(tags, github, prompts):
    github["i7"]["body"] = "### Describe the bug\n" + "word " * 500 + "\n### Are you willing to submit a PR?\n- [x] Yes, the fix and its test are below"

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert len(github["i7"]["body"]) > BODY_CHARS
    assert " […cut]" in prompts[0]
    assert "From the rest of the template:\n### Are you willing to submit a PR?\n- [x] Yes, the fix and its test are below" in prompts[0]


def test_template_hints_are_left_out(tags, github, prompts):
    github["i7"]["body"] = "<!-- Describe the bug here.\nBe as clear as you can. -->\nRunning it on an empty file crashes."

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert "Running it on an empty file crashes." in prompts[0]
    assert "Describe the bug here" not in prompts[0]


def test_oh_my_pi_17037_long_comment_keeps_its_end(tags, github, answer, prompts):
    # The triage note's conclusion was at its very end, past where a plain cut would stop.
    note = "Triage note. " + "Some analysis. " * 100 + "Not implementing until a maintainer accepts the direction."
    github["i7"]["latest"] = {
        "totalCount": 1,
        "nodes": [{"body": note, "createdAt": "2026-11-08T08:00:00Z", "authorAssociation": "COLLABORATOR", "author": {"login": "roboomp", "__typename": "User"}}],
    }
    answer["status"] = "waiting"

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.all()["owner/repo#7"]["merge"] == "waiting"
    assert "--- roboomp (COLLABORATOR), 2026-11-08:\nTriage note." in prompts[0]
    assert " […] " in prompts[0]
    assert "Not implementing until a maintainer accepts the direction." in prompts[0]


def test_bot_comment_is_cut_shorter(tags, github, prompts):
    words = "a" * 300 + "b" * 300
    github["i7"]["latest"] = {
        "totalCount": 1,
        "nodes": [{"body": words, "createdAt": "2026-11-08T08:00:00Z", "authorAssociation": "NONE", "author": {"login": "renovate", "__typename": "Bot"}}],
    }

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert "--- renovate, a bot (NONE), 2026-11-08:\n" + "a" * (BOT_CHARS * 2 // 3) + " […] " + "b" * (BOT_CHARS // 3) in prompts[0]


def test_long_thread_shows_its_first_and_last_comments(tags, github, prompts):
    comment = {"body": "Same here.", "createdAt": "2026-11-08T08:00:00Z", "authorAssociation": "NONE", "author": {"login": "someone", "__typename": "User"}}
    github["i7"]["earliest"] = {"nodes": [comment] * 5}
    github["i7"]["latest"] = {"totalCount": 40, "nodes": [comment] * 30}

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert "40 comments, the first 5 and the last 30:" in prompts[0]
    assert "[… 5 comments left out here …]" in prompts[0]


def test_closed_issue_says_so(tags, github, prompts):
    github["i7"]["state"] = "CLOSED"

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert "It is closed.\n" in prompts[0]


def test_weknora_4655_pr_that_only_names_the_number_is_shown(tags, github, answer, pull, prompts):
    # #4655 said "Closes #4652" and was merged, but GitHub never tied it to the issue.
    pull["number"] = 4655
    pull["state"] = "MERGED"
    pull["closedAt"] = "2026-10-23T10:00:00Z"
    pull["body"] = "<!-- Describe your change -->\nCloses #7. Handles an empty file before parsing."
    github["named"] = {7: [pull]}
    answer["status"] = "fixed"

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.all()["owner/repo#7"]["merge"] == "fixed"
    assert "names its number in its text, but GitHub didn't tie it to the issue" in prompts[0]
    assert "merged 2026-10-23. Its description starts: Closes #7. Handles an empty file before parsing." in prompts[0]


def test_runanywhere_sdks_1181_closed_prs_last_comment_is_shown(tags, github, answer, pull, prompts):
    # #1210 was closed as redundant: the fix was already on main.
    pull["number"] = 1210
    pull["state"] = "CLOSED"
    pull["closedAt"] = "2026-11-05T10:00:00Z"
    pull["comments"]["nodes"].append(
        {"body": "Closing: redundant, the fix is already on main (#844).", "createdAt": "2026-11-05T10:00:00Z", "authorAssociation": "OWNER", "author": {"login": "lead", "__typename": "User"}}
    )
    github["i7"]["closedByPullRequestsReferences"]["nodes"].append(pull)
    answer["status"] = "fixed"

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.all()["owner/repo#7"]["merge"] == "fixed"
    assert "Its last comment, by lead (OWNER): Closing: redundant, the fix is already on main (#844)." in prompts[0]
    assert "A pull request closed because the fix was already in" in prompts[0]


def test_tabularis_1410_issue_it_builds_on_with_an_open_pr_is_shown(tags, github, answer, prompts):
    # #1410 had to reuse what #1409 adds, and #1409's pull request (#1423) wasn't merged.
    github["i7"]["body"] = "Search inside linked folders, reusing the linked-folder model from #1409."
    github["mentioned"] = {
        1409: {
            "__typename": "Issue",
            "title": "Link SQL folders",
            "state": "OPEN",
            "closedByPullRequestsReferences": {"nodes": [{"number": 1423, "state": "OPEN", "author": {"login": "bob"}}]},
        }
    }
    answer["status"] = "waiting"

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert tags.all()["owner/repo#7"]["merge"] == "waiting"
    assert (
        "Its description mentions issue #1409 (\"Link SQL folders\"): still open, and pull request #1423 by bob "
        "that would close it is still open, not merged." in prompts[0]
    )


def test_runanywhere_sdks_1191_follow_up_to_an_open_pr_is_shown(tags, github, prompts):
    # A follow-up from an open pull request's review waits until that one is merged. Its own number is left out.
    github["i7"]["body"] = "Follow-up from the review of #1190 (see #7 above)."
    github["mentioned"] = {
        1190: {"__typename": "PullRequest", "title": "Add model loader", "state": "OPEN"},
        7: {"__typename": "Issue", "title": "Crash on empty input", "state": "OPEN", "closedByPullRequestsReferences": {"nodes": []}},
    }

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert "Its description mentions pull request #1190 (\"Add model loader\"): still open, not merged." in prompts[0]
    assert "mentions issue #7" not in prompts[0]


def test_mentioned_pr_already_tied_is_listed_once(tags, github, pull, prompts):
    github["i7"]["body"] = "See #9."
    github["i7"]["timelineItems"]["nodes"].append({"__typename": "CrossReferencedEvent", "source": pull})
    github["mentioned"] = {9: {"__typename": "PullRequest", "title": "Fix crash on empty input", "state": "OPEN"}}

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert "Pull request #9 (" in prompts[0]
    assert "Its description mentions pull request #9" not in prompts[0]


def test_commits_that_mention_it_are_shown(tags, github, pull, prompts):
    pull["number"] = 822
    pull["state"] = "MERGED"
    pull["closedAt"] = "2026-11-03T10:00:00Z"
    github["i7"]["timelineItems"]["nodes"] = [
        {
            "__typename": "ReferencedEvent",
            "createdAt": "2026-11-02T10:00:00Z",
            "commitRepository": {"nameWithOwner": "someone/fork"},
            "commit": {"abbreviatedOid": "abc1234", "messageHeadline": "Try a fix for #7", "associatedPullRequests": {"nodes": []}},
        },
        {
            "__typename": "ReferencedEvent",
            "createdAt": "2026-11-03T10:00:00Z",
            "commitRepository": {"nameWithOwner": "owner/repo"},
            "commit": {"abbreviatedOid": "def5678", "messageHeadline": "Handle empty input (#822)", "associatedPullRequests": {"nodes": [pull]}},
        },
    ]

    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert "Commit abc1234 in someone/fork mentions it, 2026-11-02: \"Try a fix for #7\"" in prompts[0]
    assert "Pull request #822 (\"Fix crash on empty input\") by alice has a commit that mentions it (\"Handle empty input (#822)\")" in prompts[0]
    assert "merged 2026-11-03." in prompts[0]


def test_nothing_tied_says_so(tags, prompts):
    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert "No pull request or commit is tied to it.\n" in prompts[0]
    assert "No comments." in prompts[0]


@pytest.mark.parametrize(
    "incident, words",
    [
        ("mcp-memory-service#1910", "the author said they will fix it or send the pull request themselves"),
        ("open-mercato#8416", "a problem found in code that only someone else's open pull request or unmerged feature branch has"),
        ("tabularis#1410", "So is one that builds on another issue that is still open"),
        ("oh-my-pi#17037", "left questions for the maintainers"),
        ("mastra#28528", "a label like 'status: needs triage'"),
        ("openchoreo#5371", "a maintainer's or core developer's follow-up to their own work still in progress"),
        ("openinference#4288", "a fresh one a maintainer opened only days ago as their own planned work"),
        ("WeKnora#4652", "also the ones that only name its number"),
        ("kestra#14059", "'this will be handled by the internal team' from them is a no"),
        ("DeskcommCRM#4410", "leave this one to a newcomer"),
        ("hydro#3281", "'appears to be an autonomously generated PR'"),
    ],
)
def test_prompt_keeps_each_incidents_rule(tags, prompts, incident, words):
    asyncio.run(tags.tag_batch("owner/repo", [7]))

    assert words in prompts[0], incident
