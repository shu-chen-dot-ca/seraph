"""How each repo treats outside contributors (github_searcher/repo_signals.py): the numbers fetch() works out from GitHub's
answers (merge rate, first reply, time to merge, stale outside PRs, newcomers, maintainers, who reviews), the lines about
AI it hands to Claude, and when complete() asks Claude again.

GitHub and Claude are fakes: every answer is hand-made in the shape search.py's queries give, and "now" is fixed at NOW,
so the dates below stay as old as they say. Bots and AI reviewers never count as maintainers. The tests named after a
repo rebuild what went wrong there (surveyjs #8169, pytorch, hydro #3295, harper, nextcloud, rust-clippy, bulwarkmail,
DeepSeek-Reasonix). The store keeps its file in pytest's temporary folder, never in DATA_DIR."""

import asyncio
import base64
import json
from datetime import UTC, datetime

import httpx
import pytest

from github_searcher import repo_signals
from github_searcher.claude_judge import JudgeError
from github_searcher.repo_signals import AI_REVIEWERS, AI_WORDS, POLICY_VERSION, RepoSignals

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)

# People. Outsiders (CONTRIBUTOR or NONE on GitHub), a maintainer, a private member GitHub shows as CONTRIBUTOR but who
# merges PRs, and bots.
ANA = {"login": "ana", "__typename": "User"}
BEN = {"login": "ben", "__typename": "User"}
CARA = {"login": "cara", "__typename": "User"}
DAN = {"login": "dan", "__typename": "User"}
MAYA = {"login": "maya", "__typename": "User"}
PRIYA = {"login": "priya", "__typename": "User"}
CODERABBIT = {"login": "coderabbitai", "__typename": "Bot"}
CODECOV = {"login": "codecov", "__typename": "Bot"}

# The repo's newest PRs (PULLS_QUERY recent): ana's, opened 2 weeks ago.
OPEN = {
    "createdAt": "2026-11-01T12:00:00Z",
    "state": "OPEN",
    "merged": False,
    "mergedAt": None,
    "closedAt": None,
    "authorAssociation": "CONTRIBUTOR",
    "author": ANA,
    "closing": {"nodes": []},
    "reviews": {"nodes": []},
    "comments": {"nodes": []},
}
MERGED = {**OPEN, "state": "MERGED", "merged": True, "mergedAt": "2026-11-03T12:00:00Z", "closedAt": "2026-11-03T12:00:00Z"}
CLOSED = {**OPEN, "state": "CLOSED", "closedAt": "2026-11-03T12:00:00Z"}
# Its most recently finished PRs (PULLS_QUERY finished).
DONE_MERGED = {
    "createdAt": "2026-11-01T12:00:00Z",
    "merged": True,
    "mergedAt": "2026-11-03T12:00:00Z",
    "closedAt": "2026-11-03T12:00:00Z",
    "mergedBy": {"login": "maya", "__typename": "User"},
    "authorAssociation": "CONTRIBUTOR",
    "author": ANA,
    "closing": {"nodes": []},
}
DONE_CLOSED = {**DONE_MERGED, "merged": False, "mergedAt": None, "mergedBy": None}
# Reviews and comments on a newest PR.
RABBIT_REVIEW = {"createdAt": "2026-11-01T13:00:00Z", "authorAssociation": "NONE", "author": CODERABBIT}
MAYA_REVIEW = {"createdAt": "2026-11-02T12:00:00Z", "authorAssociation": "MEMBER", "author": MAYA}
CODECOV_COMMENT = {"createdAt": "2026-11-01T12:30:00Z", "authorAssociation": "NONE", "author": CODECOV}
# A finished outside PR with what was written on it (REVIEW_FEEDBACK_QUERY): four notes from maya, and a bot's and the
# author's own, which aren't a maintainer's.
MAYA_CHANGES = {
    "body": "Needs a test first.",
    "state": "CHANGES_REQUESTED",
    "authorAssociation": "MEMBER",
    "author": MAYA,
    "comments": {"nodes": [{"body": "Rename this to parse_empty."}]},
}
FEEDBACK_PR = {
    "number": 12,
    "title": "Fix the crash on empty input",
    "merged": True,
    "authorAssociation": "CONTRIBUTOR",
    "author": ANA,
    "comments": {
        "nodes": [
            {"body": "Thanks! Could you add a test for this?", "authorAssociation": "MEMBER", "author": MAYA},
            {"body": "Please add a changelog entry too.", "authorAssociation": "MEMBER", "author": MAYA},
            {"body": "Coverage went up by 0.1%.", "authorAssociation": "NONE", "author": CODECOV},
            {"body": "Done, thanks!", "authorAssociation": "CONTRIBUTOR", "author": ANA},
        ]
    },
    "reviews": {"nodes": [MAYA_CHANGES]},
}


class FrozenDatetime(datetime):
    """datetime, with now() at NOW."""

    @classmethod
    def now(cls, tz=None):
        return NOW


@pytest.fixture
def github(tmp_path, monkeypatch):
    """A fake GitHub and Claude with one quiet repo, acme/tool: no PRs, no issues, no files about AI. Each test fills in
    what it needs. asked lists what was read besides the repo itself, fetched the pages httpx.get was asked for, and
    prompts what Claude was asked, as (kind, prompt): "tag" for the AI policy, "tone" for the atmosphere, "verdict" for
    newcomers. claude holds its answers by kind (an exception is raised instead)."""
    github = {
        "repo": {
            "nameWithOwner": "acme/tool",
            "description": "A tool",
            "stargazerCount": 4000,
            "isArchived": False,
            "isFork": False,
            "pushedAt": "2026-11-14T12:00:00Z",
            "primaryLanguage": {"name": "Python"},
            "repositoryTopics": {"nodes": [{"topic": {"name": "cli"}}]},
            "oldestOpen": {"nodes": []},
            "defaultBranchRef": {"target": {"history": {"totalCount": 10}, "allHistory": {"totalCount": 5000}}},
            "openPullRequests": {"totalCount": 40},
            "mergedPullRequests": {"totalCount": 900},
            "closedPullRequests": {"totalCount": 200},
            "openIssues": {"totalCount": 120},
            "firstLabels": {"nodes": []},
            "beginnerLabels": {"nodes": []},
            "easyLabels": {"nodes": []},
            "helpLabels": {"nodes": []},
            "aiPolicy": None,
            "contributing": None,
            "contributingRst": None,
            "githubContributing": None,
            "docsContributing": None,
            "prTemplate": None,
            "prTemplateLower": None,
            "agentsFile": None,
            "agentPolicy": None,
            "pageSize": 100,
        },
        "pulls": {"pageSize": 100, "recent": {"nodes": []}, "finished": {"nodes": []}},
        "earlier": {},
        # 30 PRs, 30 issues and 30 commits in 90 days: 30 a month together; the last 30 days have 10 of each.
        "activity": {
            "prs30": {"issueCount": 10},
            "prs90": {"issueCount": 30},
            "merged30": {"issueCount": 8},
            "merged90": {"issueCount": 24},
            "issues30": {"issueCount": 10},
            "issues90": {"issueCount": 30},
            "closed30": {"issueCount": 9},
            "closed90": {"issueCount": 27},
            "repository": {
                "hasDiscussionsEnabled": False,
                "codeOfConduct": None,
                "releases": {"nodes": []},
                "defaultBranchRef": {"target": {"history": {"totalCount": 30}}},
                "recentIssues": {"nodes": []},
            },
        },
        "readme": "# Tool\n\nA command line tool for data files.\n",
        "contributors": 120,
        "merged_since": [],
        "feedback": {"pullRequests": {"nodes": []}},
        "org_policy": None,
        "pages": {},
        "claude": {
            "tag": {"tag": "welcome", "quote": "", "file": ""},
            "tone": {"tone": "warm", "summary": "Friendly reviews.", "asks_for": []},
            "verdict": {"verdict": "welcome", "reason": "Outside PRs get merged."},
        },
        "asked": [],
        "fetched": [],
        "prompts": [],
    }

    def get_review_feedback(owner, repo):
        github["asked"].append(f"feedback {owner}/{repo}")
        return github["feedback"]

    def get_contents(owner, repo, path):
        github["asked"].append(f"contents {owner}/{repo}/{path}")
        return github["org_policy"]

    def get(url, follow_redirects, timeout, headers):
        github["fetched"].append(url)
        content_type, text = github["pages"].get(url, ("text/plain", ""))
        status = 200 if url in github["pages"] else 404
        return httpx.Response(status, content=text.encode(), headers={"content-type": content_type}, request=httpx.Request("GET", url))

    async def judge(prompt, schema, effort):
        kind = list(schema["properties"])[0]
        github["prompts"].append((kind, prompt))
        if isinstance(github["claude"][kind], Exception):
            raise github["claude"][kind]
        return github["claude"][kind]

    monkeypatch.setattr(repo_signals, "DATA_DIR", tmp_path)
    monkeypatch.setattr(repo_signals, "datetime", FrozenDatetime)
    monkeypatch.setattr(repo_signals, "get_repo_signals", lambda owner, repo, since: github["repo"])
    monkeypatch.setattr(repo_signals, "get_repo_pulls", lambda owner, repo: github["pulls"])
    monkeypatch.setattr(repo_signals, "count_earlier_prs", lambda owner, repo, logins, before: github["earlier"])
    monkeypatch.setattr(repo_signals, "get_repo_activity", lambda owner, repo, since30, since90: github["activity"])
    monkeypatch.setattr(repo_signals, "get_readme", lambda owner, repo: github["readme"])
    monkeypatch.setattr(repo_signals, "count_contributors", lambda owner, repo: github["contributors"])
    monkeypatch.setattr(repo_signals, "get_merged_prs_since", lambda owner, repo, since: github["merged_since"])
    monkeypatch.setattr(repo_signals, "get_review_feedback", get_review_feedback)
    monkeypatch.setattr(repo_signals, "get_contents", get_contents)
    monkeypatch.setattr(repo_signals, "judge", judge)
    monkeypatch.setattr(httpx, "get", get)
    return github


@pytest.fixture
def store(github):
    """The signals store, its repo_signals.json in pytest's temporary folder (github points DATA_DIR there)."""
    return RepoSignals()


# Outside PRs: staff, merges, first replies.


def test_surveyjs_8169_whoever_merged_a_pr_is_staff_not_an_outsider(github, store):
    # priya is a private member: GitHub shows her as CONTRIBUTOR, but she merges PRs. Her merged PRs made surveyjs look
    # like it merges almost every outside PR, while the real outsiders' PRs (ours among them) were closed.
    github["pulls"]["finished"]["nodes"] = [{**DONE_MERGED, "author": PRIYA, "mergedBy": {"login": "priya", "__typename": "User"}}] * 4 + [
        {**DONE_CLOSED, "author": ANA},
        {**DONE_CLOSED, "author": BEN},
        {**DONE_CLOSED, "author": CARA},
    ]
    github["pulls"]["recent"]["nodes"] = [{**OPEN, "author": PRIYA}, {**OPEN, "author": ANA}]
    github["repo"]["oldestOpen"]["nodes"] = [
        {"createdAt": "2026-09-01T12:00:00Z", "authorAssociation": "CONTRIBUTOR", "author": PRIYA, "reviews": {"nodes": []}, "comments": {"nodes": []}}
    ]

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    assert signals["outside_merged_90d"] == 0
    assert signals["outside_closed_90d"] == 3
    assert signals["outside_merge_rate"] == 0.0
    assert signals["outside_prs_90d"] == 1
    assert signals["stale_outside_prs"] == 0


def test_pytorch_pr_closed_by_a_commit_counts_as_merged(github, store):
    # pytorch lands a change with its merge bot and then closes the PR: GitHub says closed, not merged.
    github["pulls"]["finished"]["nodes"] = [
        {**DONE_CLOSED, "author": ANA, "closedAt": "2026-11-05T12:00:00Z", "closing": {"nodes": [{"closer": {"__typename": "Commit"}}]}},
        {**DONE_CLOSED, "author": BEN, "closing": {"nodes": [{"closer": {"__typename": "PullRequest"}}]}},
        {**DONE_CLOSED, "author": CARA, "closing": {"nodes": [{"closer": None}]}},
        {**DONE_MERGED, "author": DAN},
    ]

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    assert signals["outside_merged_90d"] == 2
    assert signals["outside_closed_90d"] == 2
    assert signals["outside_merge_rate"] == 0.5
    # ana's took 4 days (opened to closed), dan's 2.
    assert signals["median_days_to_merge"] == 3.0


def test_merge_rate_needs_three_outside_prs_finished_in_90_days(github, store):
    github["pulls"]["finished"]["nodes"] = [
        {**DONE_MERGED, "author": ANA},
        {**DONE_MERGED, "author": BEN},
        # Closed in July: before the 90 days.
        {**DONE_CLOSED, "author": CARA, "createdAt": "2026-07-20T12:00:00Z", "closedAt": "2026-08-01T12:00:00Z"},
    ]

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    assert signals["outside_merged_90d"] == 2
    assert signals["outside_closed_90d"] == 0
    assert signals["outside_merge_rate"] is None


def test_only_a_maintainer_answer_is_a_first_reply(github, store):
    # Opened 11-01 at noon; maya answers three days later. Before her: an AI review, a CLA bot, another outsider, the
    # author herself and a robot account. None of them is a reply.
    github["pulls"]["recent"]["nodes"] = [
        {
            **OPEN,
            "reviews": {"nodes": [RABBIT_REVIEW]},
            "comments": {
                "nodes": [
                    {"createdAt": "2026-11-01T12:05:00Z", "authorAssociation": "NONE", "author": {"login": "CLAassistant", "__typename": "Bot"}},
                    {"createdAt": "2026-11-02T12:00:00Z", "authorAssociation": "CONTRIBUTOR", "author": BEN},
                    {"createdAt": "2026-11-02T13:00:00Z", "authorAssociation": "CONTRIBUTOR", "author": ANA},
                    {"createdAt": "2026-11-02T14:00:00Z", "authorAssociation": "MEMBER", "author": {"login": "k8s-ci-robot", "__typename": "User"}},
                    {"createdAt": "2026-11-04T12:00:00Z", "authorAssociation": "MEMBER", "author": MAYA},
                ]
            },
        }
    ]

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    assert signals["median_days_to_first_reply"] == 3.0


def test_a_merge_with_no_answer_before_it_is_the_first_reply(github, store):
    github["pulls"]["recent"]["nodes"] = [MERGED]

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    assert signals["median_days_to_first_reply"] == 2.0


def test_a_private_member_who_merges_answers_as_a_maintainer(github, store):
    github["pulls"]["finished"]["nodes"] = [{**DONE_MERGED, "author": BEN, "mergedBy": {"login": "priya", "__typename": "User"}}]
    github["pulls"]["recent"]["nodes"] = [
        {**OPEN, "comments": {"nodes": [{"createdAt": "2026-11-02T12:00:00Z", "authorAssociation": "CONTRIBUTOR", "author": PRIYA}]}}
    ]

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    assert signals["median_days_to_first_reply"] == 1.0


@pytest.mark.parametrize(
    "reviews, counts",
    [
        ([[RABBIT_REVIEW], [RABBIT_REVIEW], [RABBIT_REVIEW], [CODECOV_COMMENT]], {"agent": 3, "both": 0, "human": 0, "tag": "agent"}),
        ([[MAYA_REVIEW], [MAYA_REVIEW], [MAYA_REVIEW, CODECOV_COMMENT], []], {"agent": 0, "both": 0, "human": 3, "tag": "human"}),
        ([[RABBIT_REVIEW], [RABBIT_REVIEW, MAYA_REVIEW], [MAYA_REVIEW], []], {"agent": 1, "both": 1, "human": 1, "tag": "both"}),
        ([[MAYA_REVIEW], [MAYA_REVIEW], [CODECOV_COMMENT], []], {"agent": 0, "both": 0, "human": 2, "tag": "few"}),
    ],
)
def test_who_reviews_outside_prs(github, store, reviews, counts):
    # Each list is one outside PR's reviews. A CI bot (codecov) counts neither way, nor does a PR nobody reviewed.
    for each in reviews:
        github["pulls"]["recent"]["nodes"].append({**OPEN, "reviews": {"nodes": each}})

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    assert signals["reviewers"] == counts


def test_average_merge_counts_each_outside_contributor_once(github, store):
    by_maya = {"login": "maya"}
    github["merged_since"] = [
        {"createdAt": "2026-11-01T12:00:00Z", "mergedAt": "2026-11-03T12:00:00Z", "authorAssociation": "CONTRIBUTOR", "author": ANA, "mergedBy": by_maya},
        {"createdAt": "2026-11-02T12:00:00Z", "mergedAt": "2026-11-06T12:00:00Z", "authorAssociation": "CONTRIBUTOR", "author": ANA, "mergedBy": by_maya},
        {"createdAt": "2026-11-01T12:00:00Z", "mergedAt": "2026-11-10T12:00:00Z", "authorAssociation": "FIRST_TIME_CONTRIBUTOR", "author": BEN, "mergedBy": by_maya},
        # Merged by its own author: whoever can merge is a maintainer, whatever GitHub calls them.
        {"createdAt": "2026-11-01T12:00:00Z", "mergedAt": "2026-11-02T12:00:00Z", "authorAssociation": "CONTRIBUTOR", "author": CARA, "mergedBy": {"login": "cara"}},
        {"createdAt": "2026-11-01T12:00:00Z", "mergedAt": "2026-11-02T12:00:00Z", "authorAssociation": "NONE", "author": {"login": "dependabot", "__typename": "Bot"}, "mergedBy": by_maya},
        {"createdAt": "2026-11-01T12:00:00Z", "mergedAt": "2026-11-02T12:00:00Z", "authorAssociation": "MEMBER", "author": MAYA, "mergedBy": by_maya},
    ]

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    # ana's mean is 3 days, ben's 9: 6. The plain mean of their three PRs would be 5.
    assert signals["average_days_to_merge_30d"] == 6.0
    assert signals["merge_authors_30d"] == 2


def test_a_failed_read_of_merged_prs_keeps_the_average_before(github, store, monkeypatch):
    store.put("acme/tool", {"ai_policy": None, "atmosphere": None, "average_days_to_merge_30d": 4.2, "merge_authors_30d": 3})

    def merged_prs_fail(owner, repo, since):
        raise httpx.ConnectError("Network is unreachable")

    monkeypatch.setattr(repo_signals, "get_merged_prs_since", merged_prs_fail)

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    assert signals["average_days_to_merge_30d"] == 4.2
    assert signals["merge_authors_30d"] == 3


def test_maintainers_are_the_people_who_merged_in_30_days(github, store):
    github["pulls"]["finished"]["nodes"] = [
        {**DONE_MERGED, "mergedBy": {"login": "maya", "__typename": "User"}},
        {**DONE_MERGED, "mergedBy": {"login": "priya", "__typename": "User"}},
        {**DONE_MERGED, "mergedBy": {"login": "pytorchmergebot", "__typename": "User"}},
        {**DONE_MERGED, "mergedBy": {"login": "renovate[bot]", "__typename": "User"}},
        # Merged two months ago.
        {**DONE_MERGED, "mergedBy": {"login": "ben", "__typename": "User"}, "createdAt": "2026-09-10T12:00:00Z", "mergedAt": "2026-09-15T12:00:00Z", "closedAt": "2026-09-15T12:00:00Z"},
    ]

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    assert signals["active_mergers_30d"] == 2


def test_app_bots_that_merge_are_no_maintainers(github, store):
    # GitHub apps merge as Bots whose logins don't end in "bot": they made a one-maintainer repo look like it had three.
    github["pulls"]["finished"]["nodes"] = [
        {**DONE_MERGED, "mergedBy": {"login": "maya", "__typename": "User"}},
        {**DONE_MERGED, "mergedBy": {"login": "mergify", "__typename": "Bot"}},
        {**DONE_MERGED, "mergedBy": {"login": "kodiakhq", "__typename": "Bot"}},
    ]

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    assert signals["active_mergers_30d"] == 1


def test_active_contributors_are_everyone_but_bots(github, store):
    github["pulls"]["recent"]["nodes"] = [
        {**OPEN, "author": ANA},
        {**OPEN, "author": ANA},
        {**OPEN, "author": BEN},
        {**OPEN, "authorAssociation": "MEMBER", "author": MAYA},
        {**OPEN, "authorAssociation": "NONE", "author": {"login": "dependabot", "__typename": "Bot"}},
        {**OPEN, "authorAssociation": "MEMBER", "author": {"login": "k8s-ci-robot", "__typename": "User"}},
        # A deleted account (GitHub's ghost).
        {**OPEN, "author": None},
    ]

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    assert signals["active_contributors"] == 3
    assert signals["outside_prs_90d"] == 3


def test_window_is_how_far_back_the_newest_prs_reach(github, store):
    # A busy repo: a full page of its newest PRs (3 here) reaches back 20 days, not 90.
    github["pulls"]["pageSize"] = 3
    github["pulls"]["recent"]["nodes"] = [
        {**OPEN, "createdAt": "2026-11-14T12:00:00Z"},
        {**OPEN, "createdAt": "2026-11-05T12:00:00Z"},
        {**OPEN, "createdAt": "2026-10-26T12:00:00Z"},
    ]

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    assert signals["pr_window_days"] == 20
    assert signals["outside_prs_90d"] == 3


def test_stale_outside_prs_are_a_month_old_with_no_maintainer_answer(github, store):
    old = {"createdAt": "2026-10-01T12:00:00Z", "authorAssociation": "CONTRIBUTOR", "author": ANA, "reviews": {"nodes": []}, "comments": {"nodes": []}}
    github["repo"]["oldestOpen"]["nodes"] = [
        old,
        {**old, "author": BEN, "comments": {"nodes": [{"authorAssociation": "NONE", "author": CODECOV}]}},
        {**old, "author": CARA, "comments": {"nodes": [{"authorAssociation": "CONTRIBUTOR", "author": CARA}, {"authorAssociation": "CONTRIBUTOR", "author": DAN}]}},
        # Answered by maya.
        {**old, "author": DAN, "reviews": {"nodes": [{"authorAssociation": "MEMBER", "author": MAYA}]}},
        # Ten days old, and a maintainer's own.
        {**old, "createdAt": "2026-11-05T12:00:00Z"},
        {**old, "authorAssociation": "MEMBER", "author": MAYA},
    ]

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    assert signals["stale_outside_prs"] == 3


# Newcomers: outside authors with no PR there before the window.


@pytest.mark.parametrize(
    "first_pr, tag",
    [
        ({**MERGED, "createdAt": "2026-10-20T12:00:00Z", "mergedAt": "2026-10-21T12:00:00Z", "closedAt": "2026-10-21T12:00:00Z"}, "welcomes"),
        ({**CLOSED, "createdAt": "2026-10-20T12:00:00Z", "closedAt": "2026-10-25T12:00:00Z"}, "turned_away"),
        ({**OPEN, "createdAt": "2026-10-01T12:00:00Z"}, "left_waiting"),
        # Merged, but after 10 days with no answer: a slow first reply alone is no bad sign.
        ({**MERGED, "createdAt": "2026-10-20T12:00:00Z", "mergedAt": "2026-10-30T12:00:00Z", "closedAt": "2026-10-30T12:00:00Z"}, "ok"),
    ],
)
def test_newcomer_tag_from_how_their_first_prs_went(github, store, first_pr, tag):
    github["pulls"]["recent"]["nodes"] = [{**first_pr, "author": ANA}, {**first_pr, "author": BEN}, {**first_pr, "author": CARA}]
    github["earlier"] = {"ana": 0, "ben": 0, "cara": 0}

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    assert signals["newcomers"]["prs"] == 3
    assert signals["newcomers"]["tag"] == tag


def test_a_first_pr_opened_days_ago_is_not_counted_yet(github, store):
    # Opened two days ago, over a holiday say: nobody may have looked at it yet.
    github["pulls"]["recent"]["nodes"] = [{**OPEN, "author": CARA, "createdAt": "2026-11-13T12:00:00Z"}, {**MERGED, "author": BEN}, {**MERGED, "author": ANA}]
    github["earlier"] = {"ana": 0, "ben": 0, "cara": 0}

    newcomers = asyncio.run(store.fetch("acme/tool", judged=False))["newcomers"]

    assert newcomers["authors_checked"] == 3
    assert newcomers["prs"] == 2
    assert newcomers["tag"] == "few"


def test_newcomers_who_came_back_and_old_hands_left_out(github, store):
    github["pulls"]["recent"]["nodes"] = [
        {**OPEN, "author": ANA, "createdAt": "2026-11-08T12:00:00Z"},
        {**MERGED, "author": DAN},
        {**MERGED, "author": BEN},
        {**MERGED, "author": ANA},
    ]
    # dan opened 4 PRs there before: not a newcomer.
    github["earlier"] = {"ana": 0, "ben": 0, "dan": 4}

    newcomers = asyncio.run(store.fetch("acme/tool", judged=False))["newcomers"]

    assert newcomers["prs"] == 2
    assert newcomers["merged"] == 2
    assert newcomers["returned"] == 1


# Beginner issues, activity, README and chat links.


def test_beginner_issues_each_once_newest_first(github, store):
    issue_7 = {"number": 7, "title": "Typo in --help", "createdAt": "2026-11-10T12:00:00Z", "assignees": {"totalCount": 0}, "timelineItems": {"totalCount": 0}}
    issue_5 = {"number": 5, "title": "Add --quiet", "createdAt": "2026-11-01T12:00:00Z", "assignees": {"totalCount": 1}, "timelineItems": {"totalCount": 0}}
    issue_3 = {"number": 3, "title": "Crash on empty file", "createdAt": "2026-10-20T12:00:00Z", "assignees": {"totalCount": 0}, "timelineItems": {"totalCount": 1}}
    issue_9 = {"number": 9, "title": "Vendor the parser", "createdAt": "2026-11-12T12:00:00Z", "assignees": {"totalCount": 0}, "timelineItems": {"totalCount": 0}}
    github["repo"]["firstLabels"]["nodes"] = [
        {"name": "good first issue", "issues": {"nodes": [issue_7, issue_5]}},
        # GitHub's label search for "first" finds this one too: not a beginner label.
        {"name": "first-party", "issues": {"nodes": [issue_9]}},
    ]
    github["repo"]["easyLabels"]["nodes"] = [{"name": "Difficulty: Easy", "issues": {"nodes": [issue_3]}}]
    github["repo"]["helpLabels"]["nodes"] = [{"name": "help wanted", "issues": {"nodes": [issue_7, issue_3]}}, {"name": "helpers", "issues": {"nodes": [issue_9]}}]

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    beginner = signals["beginner_issues"]
    assert [entry["number"] for entry in beginner] == [7, 5, 3]
    assert beginner[0]["labels"] == ["good first issue", "help wanted"]
    assert beginner[2]["labels"] == ["Difficulty: Easy", "help wanted"]
    # Only #7 has no assignee and nothing mentioning it.
    assert signals["unclaimed_beginner_issues"] == 1


@pytest.mark.parametrize("prs, issues, commits, trend", [(10, 10, 10, "flat"), (20, 10, 10, "up"), (5, 5, 10, "down")])
def test_trend_compares_the_last_30_days_with_the_monthly_average(github, store, prs, issues, commits, trend):
    # The 90 days have 30 PRs, 30 issues and 30 commits: a monthly average of 30 together. A quarter more or less moves.
    github["activity"]["prs30"]["issueCount"] = prs
    github["activity"]["issues30"]["issueCount"] = issues
    github["repo"]["defaultBranchRef"]["target"]["history"]["totalCount"] = commits

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    assert signals["activity"]["trend"] == trend
    assert signals["activity"]["prs_opened_month"] == 10


def test_issue_reply_rate_is_maintainer_answers_within_a_week(github, store):
    answer = {"createdAt": "2026-10-27T12:00:00Z", "authorAssociation": "MEMBER", "author": MAYA}
    late = {"createdAt": "2026-11-05T12:00:00Z", "authorAssociation": "MEMBER", "author": MAYA}
    outsider = {"createdAt": "2026-10-27T12:00:00Z", "authorAssociation": "CONTRIBUTOR", "author": BEN}
    issue = {"createdAt": "2026-10-25T12:00:00Z", "authorAssociation": "NONE", "author": ANA, "comments": {"nodes": []}}
    github["activity"]["repository"]["recentIssues"]["nodes"] = [
        {**issue, "comments": {"nodes": [answer]}},
        {**issue, "comments": {"nodes": [answer]}},
        {**issue, "comments": {"nodes": [answer]}},
        {**issue, "comments": {"nodes": [late]}},
        {**issue, "comments": {"nodes": [outsider]}},
        # Opened two days ago, and a maintainer's own: neither is checked.
        {**issue, "createdAt": "2026-11-13T12:00:00Z"},
        {**issue, "authorAssociation": "MEMBER", "author": MAYA},
    ]

    activity = asyncio.run(store.fetch("acme/tool", judged=False))["activity"]

    assert activity["issues_checked"] == 5
    assert activity["issue_reply_rate"] == 0.6


def test_issue_reply_rate_counts_staff_as_maintainers(github, store):
    # priya merged a PR, so she is staff though GitHub shows her as CONTRIBUTOR: her answers count, her own issue isn't
    # an outsider's.
    github["pulls"]["finished"]["nodes"] = [{**DONE_MERGED, "author": BEN, "mergedBy": {"login": "priya", "__typename": "User"}}]
    answer = {"createdAt": "2026-10-27T12:00:00Z", "authorAssociation": "CONTRIBUTOR", "author": PRIYA}
    issue = {"createdAt": "2026-10-25T12:00:00Z", "authorAssociation": "NONE", "author": ANA, "comments": {"nodes": [answer]}}
    github["activity"]["repository"]["recentIssues"]["nodes"] = [
        issue,
        issue,
        issue,
        issue,
        {**issue, "comments": {"nodes": []}},
        {**issue, "authorAssociation": "CONTRIBUTOR", "author": PRIYA, "comments": {"nodes": []}},
    ]

    activity = asyncio.run(store.fetch("acme/tool", judged=False))["activity"]

    assert activity["issues_checked"] == 5
    assert activity["issue_reply_rate"] == 0.8


def test_issue_reply_rate_needs_five_issues(github, store):
    issue = {"createdAt": "2026-10-25T12:00:00Z", "authorAssociation": "NONE", "author": ANA, "comments": {"nodes": []}}
    github["activity"]["repository"]["recentIssues"]["nodes"] = [issue, issue, issue, issue]

    activity = asyncio.run(store.fetch("acme/tool", judged=False))["activity"]

    assert activity["issues_checked"] == 4
    assert activity["issue_reply_rate"] is None


@pytest.mark.parametrize(
    "readme, english",
    [
        ("# Tool\n\nA command line tool that sorts and checks data files.\n\n[中文说明](README.zh-CN.md)\n", True),
        ("# 数据工具\n\n这是一个用来整理和检查数据文件的命令行工具。\n\n运行 pip install tool 安装。\n", False),
        # Its code has long Chinese comments; code doesn't count.
        ("# Tool\n\nRun it like this.\n\n```\n# 这一行是很长的中文注释，用来说明这个命令的每一个参数分别是什么意思\ntool --check\n```\n", True),
    ],
)
def test_readme_in_english(github, store, readme, english):
    github["readme"] = readme

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    assert signals["readme_english"] is english


def test_a_readme_that_cannot_be_read_is_not_known(github, store, monkeypatch):
    def no_readme(owner, repo):
        request = httpx.Request("GET", "https://api.github.com/repos/acme/tool/readme")
        raise httpx.HTTPStatusError("Not Found", request=request, response=httpx.Response(404, request=request))

    monkeypatch.setattr(repo_signals, "get_readme", no_readme)

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    assert signals["readme_english"] is None
    assert signals["community"]["channels"] == []


def test_chat_links_in_the_readme(github, store):
    github["readme"] = "# Tool\n\nChat on https://discord.gg/abcd or https://join.slack.com/t/acme/shared_invite/x. Mail https://lists.example.com\n"

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    assert signals["community"]["channels"] == ["Discord", "Slack"]


def test_a_renamed_repo_is_read_by_its_new_name(github, store):
    # GitHub's search only knows a repo by its current name: after the first read, the rest go to that.
    github["repo"]["nameWithOwner"] = "acme-labs/tool"

    asyncio.run(store.fetch("acme/tool", judged=False))

    assert "feedback acme-labs/tool" in github["asked"]
    assert "contents acme-labs/.github/AI_POLICY.md" in github["asked"]


# The lines about AI, for Claude to read.


@pytest.mark.parametrize(
    "line, about_ai",
    [
        ("AI-assisted PRs must say so.", True),
        ("Using LLMs is fine.", True),
        ("No vibe-coded patches.", True),
        ("Generated by Claude or ChatGPT", True),
        ("As the maintainers said, run the tests.", False),
        ("Rain falls mainly on the plain.", False),
    ],
)
def test_lines_about_ai(line, about_ai):
    assert (AI_WORDS.search(line) is not None) is about_ai


@pytest.mark.parametrize(
    "login, ai_reviewer",
    [
        ("coderabbitai", True),
        ("copilot-pull-request-reviewer", True),
        ("gemini-code-assist", True),
        ("cursor", True),
        ("codecov", False),
        ("github-actions", False),
        ("precursor-ci", False),
    ],
)
def test_ai_reviewer_bots(login, ai_reviewer):
    assert (AI_REVIEWERS.search(login) is not None) is ai_reviewer


def test_only_the_lines_about_ai_are_taken_from_contributing(github, store):
    github["repo"]["contributing"] = {"text": "Run the tests first.\nAI-generated code must be marked as such.\nAs we said, keep commits small.\n"}

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    assert signals["_policy_text"] == "=== CONTRIBUTING.md (only the lines about AI)\nAI-generated code must be marked as such."
    assert signals["_policy_files"] == ["CONTRIBUTING.md"]
    assert len(signals["_policy_basis"]) == 16


def test_harper_agent_policy_is_read_whole_up_to_its_last_lines(github, store):
    # harper's AGENT_POLICY.md bans agent-written PR descriptions in an update at its very end, in lines that never
    # say "AI".
    rule = "Update 9/2/2026: we will no longer accept pull requests with descriptions written by an agent."
    github["repo"]["agentPolicy"] = {"text": "# Agent policy\n" + "Read the style guide before you change a rule.\n" * 40 + rule + "\n"}

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    assert rule in signals["_policy_text"]
    assert signals["_policy_files"] == ["AGENT_POLICY.md"]


def test_nextcloud_organization_ai_policy_holds_for_all_its_repos(github, store):
    # nextcloud/calendar says nothing of its own about AI; nextcloud's .github repo has the AI_POLICY.md for all.
    rule = "AI agents must not open pull requests or comment on their own."
    github["repo"]["nameWithOwner"] = "nextcloud/calendar"
    github["org_policy"] = {"encoding": "base64", "content": base64.b64encode(rule.encode()).decode()}

    signals = asyncio.run(store.fetch("nextcloud/calendar", judged=False))

    assert "contents nextcloud/.github/AI_POLICY.md" in github["asked"]
    assert signals["_policy_files"] == ["nextcloud/.github: AI_POLICY.md"]
    assert rule in signals["_policy_text"]


def test_rust_clippy_policy_page_it_adopts_by_a_link_is_read(github, store):
    # clippy's PR template says LLM contributions aren't banned, but its CONTRIBUTING adopts rust-lang's LLM policy,
    # on the web, which bans LLM-written PR descriptions.
    page = "https://forge.rust-lang.org/policies/llm-usage.html"
    github["repo"]["nameWithOwner"] = "rust-lang/rust-clippy"
    github["repo"]["contributing"] = {"text": f"We follow the same [LLM usage policy]({page}) as rust-lang/rust.\n"}
    github["repo"]["prTemplate"] = {"text": "LLM contributions are not banned.\n"}
    github["pages"][page] = (
        "text/html; charset=utf-8",
        "<html><head><style>.llm { color: red }</style></head>\n<body><nav>AI menu</nav>\n"
        "<p>LLM-created PR descriptions are not allowed.</p>\n<p>Be kind.</p></body></html>\n",
    )

    signals = asyncio.run(store.fetch("rust-lang/rust-clippy", judged=False))

    assert github["fetched"] == [page]
    assert signals["_policy_files"] == ["CONTRIBUTING.md", ".github/PULL_REQUEST_TEMPLATE.md", page]
    assert "LLM-created PR descriptions are not allowed." in signals["_policy_text"]
    assert "color: red" not in signals["_policy_text"]
    assert "AI menu" not in signals["_policy_text"]
    assert "Be kind." not in signals["_policy_text"]


def test_bulwarkmail_guide_the_ai_lines_point_to_is_read_as_raw_text(github, store):
    # bulwarkmail's CONTRIBUTING points to its guide, which says there is no need to say AI helped: welcome, not disclose.
    guide = "https://github.com/bulwarkmail/webmail/blob/main/docs/GUIDE.md"
    raw = "https://raw.githubusercontent.com/bulwarkmail/webmail/main/docs/GUIDE.md"
    github["repo"]["contributing"] = {"text": f"The guide's [AI-assisted contributions]({guide}) section explains what we expect.\n"}
    github["pages"][raw] = ("text/plain; charset=utf-8", "## Contributing\nAI-assisted contributions are fine, and you don't need to say that you did.\nWrite tests.\n")

    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    assert github["fetched"] == [raw]
    assert guide in signals["_policy_files"]
    assert "you don't need to say that you did" in signals["_policy_text"]


def test_policy_links_never_reach_this_computer_or_its_network(github, store):
    github["repo"]["contributing"] = {"text": "Our AI policy: https://127.0.0.1/ai-policy and https://localhost/ai-policy and https://192.168.1.10/ai-policy\n"}

    asyncio.run(store.fetch("acme/tool", judged=False))

    assert github["fetched"] == []


def test_links_on_ai_lines_that_are_no_policy_guide_or_rules_are_not_read(github, store):
    github["repo"]["contributing"] = {"text": "Our AI search runs on https://search.example.com/ai\n"}

    asyncio.run(store.fetch("acme/tool", judged=False))

    assert github["fetched"] == []


def test_at_most_three_policy_pages_are_read(github, store):
    github["repo"]["contributing"] = {"text": "".join(f"AI policy part {number}: https://example.com/policy-{number}\n" for number in range(1, 5))}

    asyncio.run(store.fetch("acme/tool", judged=False))

    assert github["fetched"] == ["https://example.com/policy-1", "https://example.com/policy-2", "https://example.com/policy-3"]


# Claude's judgments: complete().


def test_no_lines_about_ai_is_none_and_claude_is_not_asked_about_it(github, store):
    signals = asyncio.run(store.fetch("acme/tool"))

    assert signals["ai_policy"] == {"tag": "none", "quote": "", "file": "", "basis": "", "version": POLICY_VERSION}
    assert signals["atmosphere"]["tone"] == "unknown"
    assert [kind for kind, _ in github["prompts"]] == ["verdict"]
    assert [key for key in signals if key.startswith("_")] == []


def test_hydro_3295_reviews_that_close_ai_made_prs_ask_about_the_policy_again(github, store):
    # hydro's AGENTS.md welcomes AI agents, so its policy was "welcome". Then a maintainer closed #3295, our kind of fix,
    # as "an autonomously generated PR", and the review summary said so: Claude has to read the policy again with it.
    github["repo"]["nameWithOwner"] = "hydro-project/hydro"
    github["repo"]["agentsFile"] = {"text": "# Agents\nRun cargo test before you push.\n"}
    asyncio.run(store.refresh("hydro-project/hydro"))
    assert store.get("hydro-project/hydro")["ai_policy"]["tag"] == "welcome"

    summary = "Maintainers close outside PRs that look autonomously generated, like #3295."
    store.update("hydro-project/hydro", {"atmosphere": {"tone": "curt", "summary": summary, "asks_for": [], "prs": 6, "judged_at": NOW.isoformat()}})
    github["claude"]["tag"] = {"tag": "unclear", "quote": "", "file": ""}
    github["prompts"] = []
    asyncio.run(store.refresh("hydro-project/hydro"))

    asked = [prompt for kind, prompt in github["prompts"] if kind == "tag"]
    assert len(asked) == 1
    assert summary in asked[0]
    assert store.get("hydro-project/hydro")["ai_policy"]["tag"] == "unclear"

    # Nothing changed since: the policy isn't asked again.
    github["prompts"] = []
    asyncio.run(store.refresh("hydro-project/hydro"))
    assert [kind for kind, _ in github["prompts"]] == ["verdict"]


def test_a_failed_policy_ask_is_unclear_and_asked_again_next_time(github, store):
    github["repo"]["contributing"] = {"text": "AI-assisted PRs must say which tool was used.\n"}
    github["claude"]["tag"] = JudgeError("Claude gave no answer")
    asyncio.run(store.refresh("acme/tool"))
    assert store.get("acme/tool")["ai_policy"] == {"tag": "unclear", "quote": "", "file": "", "basis": "", "version": POLICY_VERSION}

    github["claude"]["tag"] = {"tag": "disclose", "quote": "AI-assisted PRs must say which tool was used.", "file": "CONTRIBUTING.md"}
    asyncio.run(store.refresh("acme/tool"))

    assert store.get("acme/tool")["ai_policy"]["tag"] == "disclose"


def test_a_policy_from_before_policy_version_is_asked_again(github, store):
    github["repo"]["agentPolicy"] = {"text": "Agents may open PRs. Say that AI helped.\n"}
    asyncio.run(store.refresh("acme/tool"))
    old = store.get("acme/tool")["ai_policy"]
    store.update("acme/tool", {"ai_policy": {**old, "version": POLICY_VERSION - 1}})
    github["prompts"] = []

    asyncio.run(store.refresh("acme/tool"))

    assert [kind for kind, _ in github["prompts"]] == ["tag", "verdict"]
    assert store.get("acme/tool")["ai_policy"]["version"] == POLICY_VERSION


def test_review_atmosphere_reads_only_what_maintainers_wrote(github, store):
    github["feedback"]["pullRequests"]["nodes"] = [FEEDBACK_PR]
    github["claude"]["tone"] = {"tone": "strict", "summary": "Reviewers want tests and a changelog entry.", "asks_for": ["tests", "tests", "be friendlier", "changelog"]}

    signals = asyncio.run(store.fetch("acme/tool"))

    asked = [prompt for kind, prompt in github["prompts"] if kind == "tone"][0]
    assert "PR #12 (merged): Fix the crash on empty input" in asked
    assert "(changes_requested) Rename this to parse_empty." in asked
    assert "Coverage" not in asked
    assert "Done, thanks!" not in asked
    # Only ASKS' keys, each once.
    assert signals["atmosphere"]["tone"] == "strict"
    assert signals["atmosphere"]["asks_for"] == ["tests", "changelog"]
    assert signals["atmosphere"]["prs"] == 1


def test_too_little_maintainer_feedback_is_unknown_without_asking(github, store):
    # Three notes from maya; the bot's and the author's own don't make a fourth.
    github["feedback"]["pullRequests"]["nodes"] = [{**FEEDBACK_PR, "reviews": {"nodes": [{**MAYA_CHANGES, "comments": {"nodes": []}}]}}]

    signals = asyncio.run(store.fetch("acme/tool"))

    assert signals["atmosphere"]["tone"] == "unknown"
    assert [kind for kind, _ in github["prompts"]] == ["verdict"]


@pytest.mark.parametrize(
    "judged_at, asks_for, read_again",
    [
        ("2026-11-12T12:00:00+00:00", ["tests"], False),
        ("2026-11-07T12:00:00+00:00", ["tests"], True),
        # Free text from before ASKS: read again however new.
        ("2026-11-12T12:00:00+00:00", ["more unit tests please"], True),
    ],
)
def test_atmosphere_is_read_again_once_a_week_old(github, store, judged_at, asks_for, read_again):
    atmosphere = {"tone": "warm", "summary": "Friendly reviews.", "asks_for": asks_for, "prs": 5, "judged_at": judged_at}
    store.put("acme/tool", {"ai_policy": None, "atmosphere": atmosphere})

    asyncio.run(store.fetch("acme/tool", judged=False))

    assert ("feedback acme/tool" in github["asked"]) is read_again


def test_a_failed_newcomer_verdict_keeps_the_one_before(github, store):
    before = {"verdict": "closed", "reason": "A core team writes the code.", "version": 2, "judged_at": "2026-11-01T12:00:00+00:00"}
    store.put("acme/tool", {"ai_policy": None, "atmosphere": None, "newcomer_verdict": before})
    github["claude"]["verdict"] = JudgeError("Claude gave no answer")

    signals = asyncio.run(store.fetch("acme/tool"))

    assert signals["newcomer_verdict"] == before


def test_deepseek_reasonix_pr_template_reaches_the_newcomer_verdict(github, store):
    # Its PR template closes outsiders' PRs, and the newcomer verdict said welcome without reading it.
    rule = "Pull requests are limited to maintainers and invited contributors; one from anyone else is closed automatically."
    github["repo"]["nameWithOwner"] = "esengine/DeepSeek-Reasonix"
    github["repo"]["contributing"] = {"text": "# Contributing\nOpen an issue before you start.\n"}
    github["repo"]["prTemplateLower"] = {"text": f"## Before you open this\n{rule}\n"}

    signals = asyncio.run(store.fetch("esengine/DeepSeek-Reasonix", judged=False))

    assert signals["_contributing_text"].startswith("=== CONTRIBUTING.md (the start of it)\n# Contributing")
    assert "=== .github/pull_request_template.md (the PR template, the start of it)" in signals["_contributing_text"]

    github["claude"]["verdict"] = {"verdict": "closed", "reason": "Its PR template closes outsiders' PRs."}
    asyncio.run(store.refresh("esengine/DeepSeek-Reasonix"))

    asked = [prompt for kind, prompt in github["prompts"] if kind == "verdict"][0]
    assert rule in asked
    assert "Open an issue before you start." in asked
    assert store.get("esengine/DeepSeek-Reasonix")["newcomer_verdict"]["verdict"] == "closed"


def test_newcomer_verdict_reads_stars_per_contributor(github, store):
    # 4000 stars, 120 contributors.
    asyncio.run(store.fetch("acme/tool"))

    asked = [prompt for kind, prompt in github["prompts"] if kind == "verdict"][0]
    assert "All-time contributors: 120\nStars per contributor: 33" in asked


# The store.


def test_put_keeps_only_what_is_shown(github, store, tmp_path):
    signals = asyncio.run(store.fetch("acme/tool", judged=False))

    store.put("acme/tool", signals)

    kept = json.loads((tmp_path / "repo_signals.json").read_text())["acme/tool"]
    assert [key for key in kept if key.startswith("_")] == []
    assert kept["stars"] == 4000


def test_forget_drops_repos_no_longer_listed(store):
    store.put("acme/tool", {"stars": 4000})
    store.put("acme/old", {"stars": 2000})

    store.forget(["acme/tool"])

    assert list(store.all()) == ["acme/tool"]


def test_update_adds_only_to_a_repo_it_has(store):
    store.update("acme/unknown", {"commits_total": 5})

    assert store.get("acme/unknown") is None
