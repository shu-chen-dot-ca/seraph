"""What an agent's draft must have before it reaches the Inbox (github_searcher/agent/work_tools.py): the checks in
draft_pr, draft_comment and evidence_add, and the claim a job takes back when it ends (job_update, close_issue).

A PR draft needs an overview, a checklist and also_tested, a before and an after of the problem, passing tests on
exactly its diff, the project's rules read, and an AI line only where the repo's policy asks for one (kestra). It never
carries a secret, GitNexus's own files, someone else's commit,
a co-author, or a git address other than the user's noreply one (openmed#5425, #5427). It is refused while someone
else's PR closes the issue (repowise#5369) or another job's version of the same PR waits (openmed#5511). A claim comes
only once the job is taken (repowise#5421); one comment per round on a thread, and none to a bot (grimmory#3112).
Pictures the agent drew (matplotlib) are refused.

The Agents manager is a stand-in: the real Jobs and Inbox in pytest's temporary folder (never DATA_DIR), and a VM whose
git answers with hand-made output. Nothing reaches GitHub, Claude, AWS or a VM: the calls that would are replaced."""

import asyncio
import base64
import copy
import hashlib
import subprocess
import time
from types import SimpleNamespace

import pytest

from github_searcher import inbox as inbox_module
from github_searcher import jobs as jobs_module
from github_searcher.agent import work_tools
from github_searcher.agent.agent import SYSTEM_PROMPT
from github_searcher.agent.review_tools import ReviewTools
from github_searcher.agent.work_tools import AI_NOTE, EMOJI, WorkTools
from github_searcher.inbox import Inbox
from github_searcher.jobs import Jobs
from github_searcher.projects import TITLE
from sandbox.file_transfer import FileTransferError

ISSUE = "owner/proj#12"
PR = "owner/proj#40"
ACCOUNT = {"login": "sam-example", "id": 1234, "name": "Sam Example"}
NOREPLY = "1234+sam-example@users.noreply.github.com"
BASE_SHA = "b" * 40
COMMIT = "c" * 40
SECRET = "sk-test-0123456789abcdef"
DIFF = "diff --git a/cli.py b/cli.py\n--- a/cli.py\n+++ b/cli.py\n@@ -1 +1 @@\n-HELP = 'usage: proj'\n+HELP = 'usage: proj [--verbose]'\n"
# The branch's commits as git log prints them for the co-author and authorship checks: address, name, short sha, subject.
LOG = f"{NOREPLY}\x1fSam Example\x1fccccccc\x1ffix(cli): list --verbose in the help\n"
# The same commits with their messages and patches, after the VM's git address, the way draft_pr reads them.
HISTORY = (
    f"{NOREPLY}\n\x1e{COMMIT}\x1f{BASE_SHA}\x1fSam Example\x1f{NOREPLY}\x1f2026-11-10T10:00:00+00:00\x1f"
    f"fix(cli): list --verbose in the help\n\nSigned-off-by: Sam Example <{NOREPLY}>\n\x1f\n\n{DIFF}"
)
PR_ARGS = {
    "path": "~/proj",
    "base": "origin/main",
    "title": "Fix the help output",
    "body": "Fixes #12.\n\nThe help now lists every flag.",
    "project": "proj: a command line tool for notes",
    "problem": "The help leaves out the --verbose flag.",
    "cause": "The help text was written before the flag was added.",
    "fix": "The help text now lists it.",
    "risks": ["Scripts that read the help text see one more line."],
    "checklist": [{"item": "List --verbose in the help", "done": True, "how": "Ran proj --help: it shows --verbose."}],
    "also_tested": ["proj -h shows the same text."],
}
COMMENT_ARGS = {
    "target": PR,
    "body": "Renamed it as asked.",
    "project": "proj: a command line tool for notes",
    "problem": "A reviewer asked for a clearer name.",
    "why": "To tell the reviewer the change is in.",
}
# The user's PR #40 as read_issue's GraphQL has it: a conversation only a review bot wrote in, and one a maintainer
# started that the user already answered.
THREAD = {
    "__typename": "PullRequest",
    "author": {"login": "sam-example"},
    "reviewThreads": {"nodes": [
        {"id": "PRRT_bot", "isResolved": False, "comments": {"nodes": [
            {"databaseId": 501, "author": {"login": "coderabbitai", "__typename": "Bot"}},
        ]}},
        {"id": "PRRT_person", "isResolved": False, "comments": {"nodes": [
            {"databaseId": 601, "author": {"login": "maintainer", "__typename": "User"}},
            {"databaseId": 602, "author": {"login": "sam-example", "__typename": "User"}},
        ]}},
    ]},
}
# The user's PR #40 as read_issue's GraphQL reads it in full: our comment at 22:45, and a maintainer's review asking for
# changes, started at 21:00 and submitted at 23:26.
REVIEWED_PR = {
    "__typename": "PullRequest",
    "title": "Fix the help output",
    "url": "https://github.com/owner/proj/pull/40",
    "state": "OPEN",
    "createdAt": "2026-11-20T10:00:00Z",
    "updatedAt": "2026-11-24T23:26:41Z",
    "author": {"login": "sam-example", "__typename": "User"},
    "authorAssociation": "CONTRIBUTOR",
    "labels": {"nodes": []},
    "assignees": {"nodes": []},
    "body": "Fixes #12.",
    "comments": {"nodes": [
        {"createdAt": "2026-11-24T22:45:00Z", "author": {"login": "sam-example", "__typename": "User"}, "authorAssociation": "CONTRIBUTOR", "body": "Renamed it."},
    ]},
    "timelineItems": {"nodes": []},
    "mergers": ["maintainer"],
    "default_branch": None,
    "isDraft": False,
    "merged": False,
    "baseRefName": "main",
    "headRefName": "fix-help",
    "commits": {"nodes": []},
    "mergeable": "MERGEABLE",
    "reviewDecision": "CHANGES_REQUESTED",
    "reviews": {"nodes": [
        {
            "body": "Please also cover -h.", "state": "CHANGES_REQUESTED", "createdAt": "2026-11-24T21:00:00Z",
            "submittedAt": "2026-11-24T23:26:41Z", "authorAssociation": "MEMBER", "author": {"login": "maintainer", "__typename": "User"},
            "comments": {"nodes": []},
        },
    ]},
    "reviewThreads": {"nodes": []},
}
# A change to a binary file, cache.db, whose new content holds a token: git's plain diff only says it differs, its
# binary patch packs the content (zlib, then base85), and only read as text (--text) does the token show.
BINARY_FILE = "diff --git a/cache.db b/cache.db\nindex b627a7e..fa188cf 100644\nBinary files a/cache.db and b/cache.db differ\n"
BINARY_PATCH = (
    "diff --git a/cache.db b/cache.db\n"
    "index b627a7e02faf085f2303b43c09929ddcbd90c332..fa188cf3148607301042613452ce35723a3cf3a5 100644\n"
    "GIT binary patch\nliteral 39\nucmWFz^vNtqWnd`D&rZ#=EzZ_0Ni8nXH83<XHZe6bx3El1N=`{lV*mj6>kI1u\n\n"
    "literal 15\nWcmWFz^vNtqWnd`D&rZ#=WdHysMFf!m\n\n"
)
BINARY_AS_TEXT = (
    "diff --git a/cache.db b/cache.db\nindex b627a7e..fa188cf 100644\n--- a/cache.db\n+++ b/cache.db\n@@ -1 +1 @@\n"
    "-SQLite\x00\x00token=\x00\n\\ No newline at end of file\n"
    f"+SQLite\x00\x00token={SECRET}\x00\n\\ No newline at end of file\n"
)
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(13)
MATPLOTLIB_PNG = PNG + b"\x00\x00\x00\x2ctEXtSoftware\x00Matplotlib version3.9.2, https://matplotlib.org/"


class FakeVM:
    """vm1, whose desktop 1 agent-1 holds. Its commands answer with hand-made output: the repo folder and branch, no PR
    template, the diff (its binary patch, and read as text), the base commit, the git address with the co-author count
    and the commits, the commits in full, a file's full path, and the picture an image's path holds. A command with a
    part in errors fails instead, with that error text. env holds the user's secrets, as a VM's settings do."""

    def __init__(self):
        self.diff = DIFF
        self.binary = ""
        self.as_text = ""
        self.email = NOREPLY
        self.coauthors = "0"
        self.log = LOG
        self.history = HISTORY
        self.picture = PNG
        self.errors = {}
        self.global_env = {}
        self.env = {}

    def holding(self, agent_id):
        return 1

    def desktop_vm(self, desktop):
        return self

    def exec(self, command, timeout, *rest, exact=False):
        for part, stderr in self.errors.items():
            if part in command:
                return subprocess.CompletedProcess(command, 1, "", stderr)
        stdout = ""
        if "pull_request_template" in command:
            stdout = ""
        elif "rev-parse --abbrev-ref HEAD" in command:
            stdout = "/home/sam/proj\nfix-help\n"
        elif "git diff --binary" in command:
            stdout = self.binary
        elif "git diff --text" in command:
            stdout = self.as_text
        elif "realpath" in command:
            stdout = "/home/sam/results.txt\n"
        elif "git diff" in command:
            stdout = self.diff
        elif "rev-parse --verify" in command:
            stdout = BASE_SHA + "\n"
        elif "grep -ci" in command:
            stdout = f"{self.email}\n{self.coauthors}\n{self.log}"
        elif "git log --reverse" in command:
            stdout = self.history
        elif "base64 -w0" in command:
            stdout = base64.b64encode(self.picture).decode()
        # As the real one reads it: as text, every "\r\n" comes back as "\n", unless read exactly.
        if not exact:
            stdout = stdout.replace("\r\n", "\n")
        return subprocess.CompletedProcess(command, 0, stdout, "")


@pytest.fixture
def agents(tmp_path, monkeypatch):
    """What the work tools reach through the Agents manager: the jobs and the Inbox (in a temporary folder), the repos'
    AI policies (signals), the signed-in account and vm1. The reviews asked for are kept in
    reviewed. Every call that would read GitHub or ask Claude fails the test unless the test answers it."""
    monkeypatch.setattr(jobs_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(jobs_module, "EVIDENCE_DIR", tmp_path / "evidence")
    monkeypatch.setattr(inbox_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(inbox_module, "ACTIONS_FILE", tmp_path / "actions.json")
    monkeypatch.setattr(work_tools, "EVIDENCE_DIR", tmp_path / "evidence")
    monkeypatch.setattr(work_tools, "AUTOMATION_FILE", tmp_path / "repo_automation.json")
    for name in ["get_pr_status", "get_issue_in_full", "get_contents", "judge"]:
        monkeypatch.setattr(work_tools, name, lambda *args, **kwargs: pytest.fail("Nothing may reach GitHub or Claude here."))
    signals = {}
    reviewed = []
    vm = FakeVM()
    github_account = SimpleNamespace(load=lambda: dict(ACCOUNT), status=lambda: {"login": ACCOUNT["login"]})
    return SimpleNamespace(
        jobs=Jobs(),
        inbox=Inbox(),
        signals=signals,
        repo_signals=SimpleNamespace(all=lambda: signals, get=lambda repo: signals.get(repo)),
        agents={"agent-2": SimpleNamespace(name="agent-2")},
        vm=vm,
        vms=SimpleNamespace(get=lambda name: vm),
        your_repositories=SimpleNamespace(github_account=github_account),
        queue=SimpleNamespace(place=lambda agent_id: ("vm1", 0)),
        issues=SimpleNamespace(dismiss=lambda ids: {"removed": ids, "working": False}),
        reviewed=reviewed,
        give_review=lambda draft, desktop: reviewed.append(draft["id"]),
    )


@pytest.fixture
def tools(agents):
    """agent-1's work tools. It read owner/proj's rules and merged PRs, and vm1 is its target."""
    record = {"id": "agent-1", "name": "agent-1", "target_vm": "vm1", "guides_read": ["owner/proj"], "pr_examples_read": ["owner/proj"]}
    return WorkTools(agents, record)


@pytest.fixture
def job(agents, tools):
    """agent-1's fix_issue job on owner/proj#12, taken and ready for its PR: a before and an after of the problem (command
    runs), the tests passing on exactly DIFF, and the issue read just now."""
    job = agents.jobs.create("fix_issue", "Fix the help output", "agent-1", "user", issue=ISSUE, agent_name="agent-1")
    after = {"command": "pytest tests/test_help.py", "scope": "focused", "passed": True, "diff_hash": hashlib.sha256(DIFF.encode()).hexdigest()}
    agents.jobs.update(job["id"], status="working", step="fix", tests={"before": None, "after": after})
    agents.jobs.add_evidence(job["id"], {"id": "ev_000001", "kind": "command", "topic": "help output", "stage": "before"})
    agents.jobs.add_evidence(job["id"], {"id": "ev_000002", "kind": "command", "topic": "help output", "stage": "after"})
    tools.threads_read[ISSUE] = time.time()
    return job["id"]


@pytest.fixture
def follow_up(agents, tools):
    """agent-1's follow_up job on the user's PR #40, which it read just now."""
    job = agents.jobs.create("follow_up", "Answer the review", "agent-1", "user", thread=PR, agent_name="agent-1")
    agents.jobs.update(job["id"], status="working", step="work")
    tools.threads_read[PR] = time.time()
    return job["id"]


# The rules as patterns


@pytest.mark.parametrize(
    "title, conventional",
    [
        ("fix(search): keep the filter after a reload", True),
        ("feat(sandbox): add a desktop", True),
        ("docs(readme): add the merged pr table", True),
        ("Fix(search): keep the filter", False),
        ("fix: keep the filter", False),
        ("fix(search): Keep the filter", False),
        ("fix(search): keep the filter.", False),
        ("feature(search): keep the filter", False),
        ("fix(search,ui): keep the filter", False),
    ],
)
def test_app_titles_are_conventional_commits(title, conventional):
    assert (TITLE.fullmatch(title) is not None) is conventional


@pytest.mark.parametrize(
    "text, says_ai_helped",
    [
        ("## AI Authors\n\nClaude Code", True),
        ("### AI disclosure\nNone", True),
        ("AI-assisted: written with the help of Claude Code", True),
        ("This PR was prepared with the help of an AI.", True),
        ("Generated with Claude", True),
        ("Adds an AI feature to the search", False),
        ("Fix the AI provider settings page", False),
        ("The AI model now returns JSON", False),
    ],
)
def test_ai_note_is_a_line_saying_ai_helped_not_a_mention_of_ai(text, says_ai_helped):
    assert (AI_NOTE.search(text) is not None) is says_ai_helped


def test_emoji_found_but_plain_arrows_and_signs_are_fine():
    assert EMOJI.findall("Done ✅ and \U0001F916 Agent:") == ["✅", "\U0001F916"]
    assert EMOJI.findall("a -> b, x ≤ y, → next, © 2026") == []


# draft_pr: what is checked before the VM


def test_pr_needs_a_title(tools, job):
    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job, title="  ")))

    assert result["is_error"] is True
    assert result["content"][0]["text"] == "The PR needs a title."


def test_pr_refused_for_an_ended_job(agents, tools, job):
    agents.jobs.update(job, status="cancelled")

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result["is_error"] is True
    assert "no drafts for it anymore" in result["content"][0]["text"]
    assert agents.inbox.list() == []


def test_pr_refused_on_another_agents_job(agents, tools):
    other = agents.jobs.create("fix_issue", "Theirs", "agent-2", "user", issue=ISSUE)

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=other["id"])))

    assert result["is_error"] is True
    assert "is not your job" in result["content"][0]["text"]


def test_tabularis_pr_of_a_task_without_a_repo_is_refused(agents, tools):
    # Such a draft could never be sent: it doesn't say where it goes.
    task = agents.jobs.create("task", "Add column usage", "agent-1", "user")
    agents.jobs.update(task["id"], status="working")

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=task["id"])))

    assert result["is_error"] is True
    assert "has no repo of its own: give repo" in result["content"][0]["text"]


def test_no_new_pr_where_ai_made_contributions_arent_taken(agents, tools, job):
    agents.signals["owner/proj"] = {"ai_policy": {"tag": "no_ai"}}

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result["is_error"] is True
    assert "doesn't take AI-made contributions" in result["content"][0]["text"]


def test_rebase_goes_with_pr(tools, follow_up):
    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=follow_up, rebase=True)))

    assert result["is_error"] is True
    assert "rebase is only for a new version" in result["content"][0]["text"]


def test_pr_must_name_a_pull_request(tools, follow_up):
    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=follow_up, pr="owner/proj/40")))

    assert result["is_error"] is True
    assert "pr must be owner/name#number" in result["content"][0]["text"]


def test_only_your_own_pr_is_made_again(tools, job):
    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job, replaces="owner/proj#7")))

    assert result["is_error"] is True
    assert "owner/proj#7 isn't a PR of yours" in result["content"][0]["text"]


def test_openmed_5511_second_version_of_a_pr_from_another_job_is_refused(agents, tools, follow_up):
    # One agent's follow-up drafted a commit on top of the PR while another's rebased that same commit.
    other = agents.inbox.create("pr", "agent-2", "test: cover the date shift", "", job="job_other", repo="owner/proj", target=PR, update_of=PR)

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=follow_up, pr=PR, body="")))

    assert result["is_error"] is True
    text = result["content"][0]["text"]
    assert f"{other['id']} by agent-2 (job_other) is already the next version of {PR}, in its review or the user's Inbox" in text

    agents.inbox.decide(other["id"], "approved")
    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=follow_up, pr=PR, body="")))
    assert "approved, not sent yet" in result["content"][0]["text"]


def test_version_of_another_job_already_on_github_holds_nothing(agents, tools, follow_up):
    other = agents.inbox.create("pr", "agent-2", "test: cover the date shift", "", job="job_other", repo="owner/proj", target=PR, update_of=PR)
    agents.inbox.decide(other["id"], "approved")
    agents.inbox.mark_sent(other["id"], {"kind": "pr", "update": True, "url": "https://github.com/owner/proj/pull/40"})

    # It goes on to the next check: here the overview, left out on purpose.
    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=follow_up, pr=PR, body="", project="")))

    assert result["content"][0]["text"].startswith("Give project")


def test_grimmory_3112_new_versions_comment_waits_its_round(agents, tools, follow_up):
    # Our answer below the PR is there already, and nobody else wrote since: the push goes without a comment.
    ours = agents.inbox.create("comment", "agent-1", "Comment on owner/proj#40", "Renamed it.", job=follow_up, repo="owner/proj", target=PR)

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=follow_up, pr=PR, body="Pushed the rename.")))

    assert result["is_error"] is True
    assert f"{ours['id']} (pending) already speaks for this round on {PR}" in result["content"][0]["text"]


def test_someone_writing_after_our_comment_starts_a_new_round(agents, tools, follow_up):
    ours = agents.inbox.create("comment", "agent-1", "Comment on owner/proj#40", "Renamed it.", job=follow_up, repo="owner/proj", target=PR)
    agents.inbox.drafts[ours["id"]]["created_at"] = "2026-11-12T09:00:00+00:00"
    tools.threads_other_at[PR] = "2026-11-12T10:00:00+00:00"

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=follow_up, pr=PR, body="Pushed the rename.", project="")))

    assert result["content"][0]["text"].startswith("Give project")


def test_lance_11087_review_submitted_after_our_comment_starts_a_new_round(agents, tools, follow_up, monkeypatch):
    # The maintainer started the review before our comment and submitted it after: the round counts from the submit.
    ours = agents.inbox.create("comment", "agent-1", "Comment on owner/proj#40", "Renamed it.", job=follow_up, repo="owner/proj", target=PR)
    agents.inbox.decide(ours["id"], "approved")
    agents.inbox.drafts[ours["id"]]["created_at"] = "2026-11-24T22:40:00+00:00"
    monkeypatch.setattr(work_tools, "get_issue_in_full", lambda owner, name, number: copy.deepcopy(REVIEWED_PR))
    asyncio.run(tools.read_issue({"thread": PR}))

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=follow_up, pr=PR, body="Changed it as you asked.", project="")))

    assert tools.threads_other_at[PR] == "2026-11-24T23:26:41Z"
    assert result["content"][0]["text"].startswith("Give project")


def test_psalm_14071_push_comment_waits_for_a_read_after_the_news(agents, tools, follow_up):
    # Told of the maintainer's review after the last read: the round it opens isn't known until the PR is read again.
    agents.jobs.add_timeline(follow_up, "news", "@maintainer reviewed it: changes requested")
    tools.threads_read[PR] = time.time() - 60

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=follow_up, pr=PR, body="Changed it as you asked.")))

    assert result["is_error"] is True
    assert f"First read {PR} again in full with read_issue" in result["content"][0]["text"]


def test_grimmory_3112_push_comment_waits_for_a_read_after_a_restart(agents, follow_up):
    # A backend restart forgets every read: the round would count every comment of ours ever made.
    tools = WorkTools(agents, {"id": "agent-1", "name": "agent-1", "target_vm": "vm1", "guides_read": ["owner/proj"]})

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=follow_up, pr=PR, body="Pushed the rename.")))

    assert result["is_error"] is True
    assert f"First read {PR} again in full with read_issue" in result["content"][0]["text"]


@pytest.mark.parametrize("part", ["project", "problem", "cause", "fix"])
def test_overview_part_is_needed(tools, job, part):
    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job, **{part: " "})))

    assert result["is_error"] is True
    assert result["content"][0]["text"].startswith(f"Give {part}")


def test_overview_is_short(tools, job):
    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job, problem="x" * 401)))

    assert result["is_error"] is True
    assert "problem is 401 characters; keep it under 400" in result["content"][0]["text"]


@pytest.mark.parametrize("risks", [[], ["  "], ["One", "Two", "Three", "Four"]])
def test_one_to_three_risks(tools, job, risks):
    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job, risks=risks)))

    assert result["is_error"] is True
    assert "Give 1 to 3 risks" in result["content"][0]["text"]


def test_checklist_is_required(tools, job):
    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job, checklist=[])))

    assert result["is_error"] is True
    assert "Give the checklist, 1 to 40 points" in result["content"][0]["text"]


@pytest.mark.parametrize(
    "point",
    [
        {"item": "List --verbose", "done": "yes", "how": "Ran it."},
        {"item": "List --verbose", "done": True, "how": ""},
        {"item": "", "done": False, "how": "Not asked after all."},
    ],
)
def test_each_checklist_point_has_item_done_and_how(tools, job, point):
    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job, checklist=[point])))

    assert result["is_error"] is True
    assert "Each checklist point needs item" in result["content"][0]["text"]


def test_also_tested_is_required(tools, job):
    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job, also_tested=["  "])))

    assert result["is_error"] is True
    assert "Give also_tested, 1 to 15 cases" in result["content"][0]["text"]


def test_no_emoji_in_a_pr(tools, job):
    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job, body="## Summary ✨\n\nFixes #12.")))

    assert result["is_error"] is True
    assert result["content"][0]["text"].startswith("No emoji anywhere")
    assert "✨" in result["content"][0]["text"]


def test_no_ai_line_where_the_policy_isnt_disclose(agents, tools, job):
    agents.signals["owner/proj"] = {"ai_policy": {"tag": "welcome"}}

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job, body="Fixes #12.\n\nAI-assisted: written with the help of Claude Code.")))

    assert result["is_error"] is True
    assert "owner/proj's AI policy is welcome, not disclose" in result["content"][0]["text"]


def test_kestra_disclose_repo_wants_the_ai_line(agents, tools, job):
    # Three kestra drafts left the line out, and each cost a review round.
    agents.signals["owner/proj"] = {"ai_policy": {"tag": "disclose"}}

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result["is_error"] is True
    assert "owner/proj's AI policy is disclose" in result["content"][0]["text"]


def test_rules_and_merged_prs_are_read_first(agents, job):
    unread = WorkTools(agents, {"id": "agent-1", "name": "agent-1", "target_vm": "vm1"})
    unread.threads_read[ISSUE] = time.time()

    result = asyncio.run(unread.draft_pr(dict(PR_ARGS, job_id=job)))
    assert "First read owner/proj's rules for contributors (contributing_guide)" in result["content"][0]["text"]

    unread.guides_read.add("owner/proj")
    result = asyncio.run(unread.draft_pr(dict(PR_ARGS, job_id=job)))
    assert "First read how owner/proj's own people write their PRs (pr_examples)" in result["content"][0]["text"]


def test_issue_is_read_again_before_its_pr(tools, job):
    tools.threads_read[ISSUE] = time.time() - 2 * 60 * 60

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result["is_error"] is True
    assert "First read owner/proj#12 again with read_issue" in result["content"][0]["text"]


def test_lmcache_6430_read_from_before_the_taken_notice_doesnt_count(agents, tools, job):
    # Someone else's PR came after the agent's read; the notice of it was lost among restart messages.
    tools.threads_read[ISSUE] = time.time() - 60
    agents.jobs.add_timeline(job, "notice", "Someone else opened a PR that closes owner/proj#12.")

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result["is_error"] is True
    assert "First read owner/proj#12 again" in result["content"][0]["text"]


def test_repowise_5369_no_pr_while_someone_elses_pr_closes_the_issue(agents, tools, job):
    tools.threads_taken[ISSUE] = "https://github.com/owner/proj/pull/89 by someone, open, closes it"

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result["is_error"] is True
    assert "someone else is on it now" in result["content"][0]["text"]
    assert agents.inbox.list() == []


def test_pr_and_its_pictures(agents, tools, job):
    agents.jobs.add_evidence(job, {"id": "ev_aaaaaa", "kind": "screenshot", "topic": "help window", "stage": "before"})
    agents.jobs.add_evidence(job, {"id": "ev_bbbbbb", "kind": "screenshot", "topic": "help window", "stage": "after"})

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))
    assert "Put your before and after pictures in the body" in result["content"][0]["text"]

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job, body="Fixes #12.\n\n![before](evidence:ev_cccccc)")))
    assert "ev_cccccc, which aren't pictures of" in result["content"][0]["text"]

    body = "Fixes #12.\n\n| Before | After |\n| --- | --- |\n| ![before](evidence:ev_aaaaaa) | ![after](evidence:ev_bbbbbb) |"
    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job, body=body)))
    assert result.get("is_error") is None


def test_pr_needs_a_before_and_an_after_of_the_problem(agents, tools, job):
    agents.jobs.remove_evidence(job, ["ev_000001"])
    # The test suite's own runs show nothing about the issue.
    agents.jobs.add_evidence(job, {"id": "ev_000003", "kind": "command", "topic": "tests that cover the change", "stage": "before"})

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result["is_error"] is True
    assert "at least one 'before'" in result["content"][0]["text"]


# draft_pr: what is checked in the VM


def test_pr_goes_to_its_reviewer_with_its_commits(agents, tools, job):
    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result.get("is_error") is None
    draft = agents.inbox.list()[0]
    assert result["content"][0]["text"].startswith(f"{draft['id']} goes to owner/proj's reviewer first")
    assert agents.reviewed == [draft["id"]]
    assert draft["review"]["state"] == "waiting"
    assert draft["diff"] == DIFF
    assert draft["base_sha"] == BASE_SHA
    assert draft["branch"] == "fix-help"
    assert draft["target"] == ISSUE
    assert draft["overview"]["checklist"] == PR_ARGS["checklist"]
    assert draft["commits"] == [{
        "sha": COMMIT,
        "message": f"fix(cli): list --verbose in the help\n\nSigned-off-by: Sam Example <{NOREPLY}>\n",
        "author": {"name": "Sam Example", "email": NOREPLY, "date": "2026-11-10T10:00:00+00:00"},
        "own": True,
        "vm_email": NOREPLY,
        "diff": DIFF,
    }]
    job_now = agents.jobs.get(job)
    assert job_now["status"] == "waiting_on_user"
    assert job_now["step"] == "draft"
    assert job_now["drafts"] == [draft["id"]]


def test_branch_not_starting_at_base_keeps_no_commits(agents, tools, job):
    # Sending then makes one commit of the reviewed diff.
    agents.vm.history = HISTORY.replace(f"\x1f{BASE_SHA}\x1f", "\x1f" + "d" * 40 + "\x1f")

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result.get("is_error") is None
    assert agents.inbox.list()[0]["commits"] == []


def test_skipped_checks_go_straight_to_the_inbox(agents, tools, job):
    agents.jobs.update(job, skip_checks=True, tests={"before": None, "after": None})

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    draft = agents.inbox.list()[0]
    assert "in the user's Inbox now" in result["content"][0]["text"]
    assert draft["review"]["state"] == "passed"
    assert agents.reviewed == []


def test_diff_with_a_secret_is_refused_by_its_name_never_its_value(agents, tools, job):
    agents.vm.env = {"OPENAI_API_KEY": SECRET}
    agents.vm.diff = DIFF + f"diff --git a/.env b/.env\nnew file mode 100644\n--- /dev/null\n+++ b/.env\n@@ -0,0 +1 @@\n+OPENAI_API_KEY={SECRET}\n"

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result["is_error"] is True
    text = result["content"][0]["text"]
    assert "The diff contains the value of the environment variable OPENAI_API_KEY, in: .env." in text
    assert SECRET not in text
    assert agents.inbox.list() == []


def test_secret_in_the_branchs_history_is_refused_too(agents, tools, job):
    # A later commit took it out of the diff, but the history would still carry it out.
    agents.vm.global_env = {"OPENAI_API_KEY": SECRET}
    agents.vm.history = HISTORY.replace(f"\n\x1f\n\n{DIFF}", f"\n\x1f\n\n{DIFF}+KEY = '{SECRET}'\n")

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result["is_error"] is True
    assert "Commit cccccccccc on your branch contains the value of the environment variable OPENAI_API_KEY" in result["content"][0]["text"]
    assert SECRET not in result["content"][0]["text"]


@pytest.mark.parametrize(
    "extra, file",
    [
        ("diff --git a/AGENTS.md b/AGENTS.md\n--- a/AGENTS.md\n+++ b/AGENTS.md\n@@ -1 +1,2 @@\n # Agents\n+<!-- gitnexus:start --> 4120 symbols\n", "AGENTS.md"),
        ("diff --git a/.gitnexus/meta.json b/.gitnexus/meta.json\nnew file mode 100644\n--- /dev/null\n+++ b/.gitnexus/meta.json\n@@ -0,0 +1 @@\n+{}\n", ".gitnexus/meta.json"),
    ],
)
def test_what_gitnexus_writes_by_itself_stays_out(agents, tools, job, extra, file):
    agents.vm.diff = DIFF + extra

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result["is_error"] is True
    assert f"The diff changes what GitNexus writes by itself when it builds its index: {file}." in result["content"][0]["text"]


def test_agents_md_change_of_its_own_is_fine(agents, tools, job):
    agents.vm.diff = DIFF + "diff --git a/AGENTS.md b/AGENTS.md\n--- a/AGENTS.md\n+++ b/AGENTS.md\n@@ -1 +1,2 @@\n # Agents\n+Run make lint first.\n"
    after = {"passed": True, "diff_hash": hashlib.sha256(agents.vm.diff.encode()).hexdigest()}
    agents.jobs.update(job, tests={"before": None, "after": after})

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result.get("is_error") is None


def test_no_pr_until_the_tests_pass(agents, tools, job):
    agents.jobs.update(job, tests={"before": None, "after": {"passed": False, "diff_hash": hashlib.sha256(DIFF.encode()).hexdigest()}})

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result["is_error"] is True
    assert "No PR until the tests pass with your change" in result["content"][0]["text"]


def test_tests_must_have_passed_on_exactly_this_code(agents, tools, job):
    agents.vm.diff = DIFF + "diff --git a/notes.txt b/notes.txt\nnew file mode 100644\n--- /dev/null\n+++ b/notes.txt\n@@ -0,0 +1 @@\n+left behind\n"

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result["is_error"] is True
    assert "The code changed since the tests last passed" in result["content"][0]["text"]


@pytest.mark.parametrize(
    "email",
    [
        # openmed#5425: the user's own address, which would be public in the commit.
        "sam@example.com",
        # openmed#5427: a made-up identity, whose noreply address is some other account's.
        "contributor@users.noreply.github.com",
        "",
    ],
)
def test_commits_are_made_with_your_noreply_address_only(agents, tools, job, email):
    agents.vm.email = email

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result["is_error"] is True
    assert f'git config user.email "{NOREPLY}"' in result["content"][0]["text"]
    assert agents.inbox.list() == []


def test_no_co_authors(agents, tools, job):
    agents.vm.coauthors = "1"

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result["is_error"] is True
    assert "has a Co-authored-by line" in result["content"][0]["text"]


def test_someone_elses_commit_on_the_branch_is_refused(agents, tools, job):
    agents.vm.log = LOG + "else@example.com\x1fSomeone Else\x1fdeadbee\x1ffix: their fix\n"

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result["is_error"] is True
    assert "deadbee by Someone Else <else@example.com>: fix: their fix" in result["content"][0]["text"]
    assert agents.inbox.list() == []


def test_first_commit_is_checked_when_the_vm_has_no_git_address(agents, tools, job):
    # Not signed in, so there is no noreply address to ask for. With the address line empty, the first commit was skipped.
    agents.your_repositories.github_account.load = lambda: None
    agents.vm.email = ""
    agents.vm.log = "else@example.com\x1fSomeone Else\x1fdeadbee\x1ffix: their fix\n"

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result["is_error"] is True
    assert "deadbee by Someone Else <else@example.com>: fix: their fix" in result["content"][0]["text"]
    assert agents.inbox.list() == []


def test_secret_in_a_binary_file_is_refused(agents, tools, job):
    # The draft carries git's binary patch, where the secret is packed and never shows as text.
    agents.vm.env = {"OPENAI_API_KEY": SECRET}
    agents.vm.diff = DIFF + BINARY_FILE
    agents.vm.binary = DIFF + BINARY_PATCH
    agents.vm.as_text = DIFF + BINARY_AS_TEXT
    agents.jobs.update(job, tests={"before": None, "after": {"passed": True, "diff_hash": hashlib.sha256(agents.vm.diff.encode()).hexdigest()}})

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert SECRET not in BINARY_PATCH
    assert result["is_error"] is True
    text = result["content"][0]["text"]
    assert "The diff contains the value of the environment variable OPENAI_API_KEY, in: cache.db." in text
    assert SECRET not in text
    assert agents.inbox.list() == []


def test_binary_file_without_a_secret_goes_as_gits_binary_patch(agents, tools, job):
    agents.vm.env = {"OPENAI_API_KEY": "sk-test-not-in-this-change"}
    agents.vm.diff = DIFF + BINARY_FILE
    agents.vm.binary = DIFF + BINARY_PATCH
    agents.vm.as_text = DIFF + BINARY_AS_TEXT
    agents.jobs.update(job, tests={"before": None, "after": {"passed": True, "diff_hash": hashlib.sha256(agents.vm.diff.encode()).hexdigest()}})

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result.get("is_error") is None
    assert agents.inbox.list()[0]["diff"] == DIFF + BINARY_PATCH


@pytest.mark.parametrize(
    "failing, diff, said",
    [
        ("git diff --binary", DIFF + BINARY_FILE, "git diff --binary failed: "),
        ("git diff --text", DIFF + BINARY_FILE, "git diff --text failed: "),
        ("grep -ci", DIFF, "Could not read your branch's commits: "),
    ],
    ids=["binary patch", "as text", "commits"],
)
def test_vm_error_text_hides_the_users_secrets(agents, tools, job, failing, diff, said):
    agents.vm.env = {"OPENAI_API_KEY": SECRET}
    agents.vm.diff = diff
    agents.vm.binary = diff
    agents.vm.errors[failing] = f"fatal: unable to access 'https://x-access-token:{SECRET}@github.com/owner/proj/'"
    agents.jobs.update(job, tests={"before": None, "after": {"passed": True, "diff_hash": hashlib.sha256(diff.encode()).hexdigest()}})

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result["is_error"] is True
    text = result["content"][0]["text"]
    assert text == said + "fatal: unable to access 'https://x-access-token:[hidden]@github.com/owner/proj/'"


# draft_comment


def test_comment_target_is_an_issue_or_pr(tools, follow_up):
    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=follow_up, target="owner/proj")))

    assert result["content"][0]["text"] == "target must be owner/name#number."


def test_comment_needs_text_and_its_overview(tools, follow_up):
    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=follow_up, body=" ")))
    assert result["content"][0]["text"] == "The comment is empty."

    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=follow_up, why="")))
    assert result["content"][0]["text"].startswith("Give why")


def test_no_emoji_in_a_comment(tools, follow_up):
    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=follow_up, body="Renamed it ✅")))

    assert result["is_error"] is True
    assert result["content"][0]["text"].startswith("No emoji anywhere")


def test_horizon_8075_marker_the_projects_rules_require_may_have_its_emoji(agents, tools, job, monkeypatch):
    # horizon's AGENTS.md wants every agent comment to start with the robot emoji and "Agent:"; its claim bot ignored ours without.
    rules = "# Agents\n\nEvery agent comment starts with \U0001F916 Agent: and then the command.\n"
    asked = []

    def agents_md(owner, name, path):
        asked.append(f"{owner}/{name}/{path}")
        return {"encoding": "base64", "content": base64.b64encode(rules.encode()).decode()}

    monkeypatch.setattr(work_tools, "get_contents", agents_md)
    claim = dict(COMMENT_ARGS, job_id=job, target=ISSUE, body="\U0001F916 Agent: /claim", emoji_rule="Every agent comment starts with \U0001F916 Agent:", emoji_rule_file="./AGENTS.md")

    result = asyncio.run(tools.draft_comment(claim))

    assert result.get("is_error") is None
    assert asked == ["owner/proj/AGENTS.md"]
    assert agents.inbox.list()[0]["body"] == "\U0001F916 Agent: /claim"


def test_emoji_rule_the_file_doesnt_say_is_refused(agents, tools, job, monkeypatch):
    monkeypatch.setattr(work_tools, "get_contents", lambda owner, name, path: {"encoding": "base64", "content": base64.b64encode(b"# Agents\n").decode()})
    claim = dict(COMMENT_ARGS, job_id=job, target=ISSUE, body="\U0001F916 Agent: /claim", emoji_rule="Start with \U0001F916", emoji_rule_file="AGENTS.md")

    result = asyncio.run(tools.draft_comment(claim))

    assert result["is_error"] is True
    assert "AGENTS.md in owner/proj doesn't say" in result["content"][0]["text"]
    assert agents.inbox.list() == []


def test_repowise_5421_no_claim_before_the_job_is_taken(agents, tools, job):
    # Its claim was drafted right after the first read, posted two seconds later, and then the issue turned out fixed.
    agents.jobs.update(job, step="understand")

    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=job, target=ISSUE, body="I'd like to work on this.")))

    assert result["is_error"] is True
    assert "First decide whether owner/proj#12 still stands" in result["content"][0]["text"]
    assert agents.inbox.list() == []


def test_fix_issue_job_comments_only_its_claim(tools, job):
    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=job, target="owner/proj#13")))

    assert result["is_error"] is True
    assert "the only comment is the claim, on its issue owner/proj#12" in result["content"][0]["text"]


def test_claim_holds_nothing_up(agents, tools, job):
    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=job, target=ISSUE, body="I'd like to work on this.", wait_for_assignment=True)))

    draft = agents.inbox.list()[0]
    assert "Don't wait for it" in result["content"][0]["text"]
    assert draft["title"] == "Claim owner/proj#12"
    assert draft["wait_for_assignment"] is True
    job_now = agents.jobs.get(job)
    assert job_now["status"] == "working"
    assert job_now["drafts"] == [draft["id"]]


def test_one_claim_per_job_unless_the_first_was_rejected(agents, tools, job):
    asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=job, target=ISSUE, body="I'd like to work on this.")))
    first = agents.inbox.list()[0]

    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=job, target=ISSUE, body="Still on it.")))
    assert f"already has its claim, {first['id']} (pending)" in result["content"][0]["text"]

    agents.inbox.decide(first["id"], "rejected")
    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=job, target=ISSUE, body="I'd like to work on this.")))
    assert result.get("is_error") is None


def test_no_claim_on_an_issue_someone_elses_pr_closes(tools, job):
    tools.threads_taken[ISSUE] = "https://github.com/owner/proj/pull/89 by someone, open, closes it"

    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=job, target=ISSUE, body="I'd like to work on this.")))

    assert result["is_error"] is True
    assert "someone else is on it. Don't claim it" in result["content"][0]["text"]


def test_no_claim_where_ai_made_contributions_arent_taken(agents, tools, job):
    agents.signals["owner/proj"] = {"ai_policy": {"tag": "no_ai"}}

    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=job, target=ISSUE, body="I'd like to work on this.")))

    assert result["is_error"] is True
    assert "doesn't take AI-made contributions" in result["content"][0]["text"]


def test_thread_is_read_before_commenting(tools, follow_up):
    del tools.threads_read[PR]

    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=follow_up)))

    assert result["is_error"] is True
    assert "First read owner/proj#40 in full with read_issue" in result["content"][0]["text"]


def test_follow_up_comment_waits_on_the_user(agents, tools, follow_up):
    asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=follow_up)))

    draft = agents.inbox.list()[0]
    assert draft["title"] == "Comment on owner/proj#40"
    assert draft["wait_for_assignment"] is None
    assert agents.jobs.get(follow_up)["status"] == "waiting_on_user"


def test_grimmory_3112_one_comment_per_round(agents, tools, follow_up):
    # An answer, then the push's comment saying the same: eleven of ours on one PR.
    asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=follow_up)))
    first = agents.inbox.list()[0]

    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=follow_up, body="Also: the tests pass.")))
    assert f"{first['id']} (pending) already speaks for this round on {PR}" in result["content"][0]["text"]

    agents.inbox.drafts[first["id"]]["created_at"] = "2026-11-12T09:00:00+00:00"
    tools.threads_other_at[PR] = "2026-11-12T10:00:00+00:00"
    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=follow_up, body="Done, see the new version.")))
    assert result.get("is_error") is None


def test_resolve_goes_with_reply_to(tools, follow_up):
    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=follow_up, resolve=True)))

    assert result["is_error"] is True
    assert "resolve goes with reply_to" in result["content"][0]["text"]


def test_claim_goes_below_the_issue(tools, job):
    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=job, target=ISSUE, body="I'd like to work on this.", reply_to=501)))

    assert result["is_error"] is True
    assert "A claim goes below the issue" in result["content"][0]["text"]


def test_grimmory_3112_no_answer_to_a_review_bot(agents, tools, follow_up, monkeypatch):
    # Six answers went to CodeRabbit there.
    monkeypatch.setattr(work_tools, "get_issue_in_full", lambda owner, name, number: THREAD)

    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=follow_up, reply_to=501)))

    assert result["is_error"] is True
    assert "Only a bot wrote in that conversation (coderabbitai)" in result["content"][0]["text"]
    assert agents.inbox.list() == []


def test_mcp_memory_service_1912_bots_conversation_answered_to_resolve_it(agents, tools, follow_up, monkeypatch):
    # The project merges only once every review conversation, bots' too, is answered and resolved.
    monkeypatch.setattr(work_tools, "get_issue_in_full", lambda owner, name, number: THREAD)

    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=follow_up, reply_to=501, resolve=True)))

    assert result.get("is_error") is None
    draft = agents.inbox.list()[0]
    assert draft["title"] == "Reply and resolve a conversation on owner/proj#40"
    assert draft["reply_to"] == 501
    assert draft["resolve"] == "PRRT_bot"


def test_reply_goes_below_the_conversations_first_comment(agents, tools, follow_up, monkeypatch):
    # GitHub takes no replies to replies.
    monkeypatch.setattr(work_tools, "get_issue_in_full", lambda owner, name, number: THREAD)

    asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=follow_up, reply_to=602)))

    draft = agents.inbox.list()[0]
    assert draft["reply_to"] == 601
    assert draft["resolve"] is None


def test_reply_to_a_comment_in_no_conversation_is_refused(tools, follow_up, monkeypatch):
    monkeypatch.setattr(work_tools, "get_issue_in_full", lambda owner, name, number: THREAD)

    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=follow_up, reply_to=999)))

    assert result["is_error"] is True
    assert "999 isn't a comment in a conversation on lines of code" in result["content"][0]["text"]


def test_only_the_prs_author_resolves_its_conversations(tools, follow_up, monkeypatch):
    theirs = dict(THREAD, author={"login": "maintainer"})
    monkeypatch.setattr(work_tools, "get_issue_in_full", lambda owner, name, number: theirs)

    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=follow_up, reply_to=601, resolve=True)))

    assert result["is_error"] is True
    assert "is maintainer's PR, not the user's" in result["content"][0]["text"]


def test_openchoreo_no_resolve_where_a_resolve_failed_before(agents, tools, follow_up, monkeypatch):
    # The organization restricts OAuth Apps: once a resolve failed there, every later one would too.
    monkeypatch.setattr(work_tools, "get_issue_in_full", lambda owner, name, number: THREAD)
    earlier = agents.inbox.create("comment", "agent-1", "Reply and resolve", "Fixed.", repo="owner/other", target="owner/other#5", reply_to=1, resolve="PRRT_1")
    agents.inbox.mark_sent(earlier["id"], {"kind": "comment", "url": "https://github.com/owner/other/pull/5#discussion_r2",
                                           "resolved": False, "resolve_error": "the `owner` organization has enabled OAuth App access restrictions"})

    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=follow_up, reply_to=601, resolve=True)))

    assert result["is_error"] is True
    assert "The owner organization restricts what apps may do on its repos" in result["content"][0]["text"]


def test_voltagent_no_answer_inside_a_conversation_where_one_went_below_the_pr(agents, tools, follow_up, monkeypatch):
    monkeypatch.setattr(work_tools, "get_issue_in_full", lambda owner, name, number: THREAD)
    earlier = agents.inbox.create("comment", "agent-1", "Reply in a conversation", "Fixed.", repo="owner/other", target="owner/other#5", reply_to=1)
    agents.inbox.mark_sent(earlier["id"], {"kind": "comment", "url": "https://github.com/owner/other/pull/5#issuecomment-3"})

    result = asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=follow_up, reply_to=601)))

    assert result["is_error"] is True
    assert "doesn't let the app answer inside a conversation on its repos" in result["content"][0]["text"]


# A job that ends takes its claim back


def test_repowise_5421_job_that_ends_withdraws_its_waiting_claim(agents, tools, job):
    asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=job, target=ISSUE, body="I'd like to work on this.")))
    claim = agents.inbox.list()[0]

    result = asyncio.run(tools.job_update({"job_id": job, "status": "cancelled", "notes": "Fixed already by #5289."}))

    assert f"Its claim {claim['id']} is withdrawn." in result["content"][0]["text"]
    withdrawn = agents.inbox.get(claim["id"])
    assert withdrawn["status"] == "rejected"
    assert withdrawn["reply"] == f"Withdrawn by agent-1: {job} is cancelled"


def test_repowise_5421_close_issue_names_a_claim_posted_already(agents, tools, job):
    # The repo's Level of automation posted the claim two seconds after it was drafted; the agent must take it back.
    asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=job, target=ISSUE, body="I'd like to work on this.")))
    claim = agents.inbox.list()[0]
    agents.inbox.decide(claim["id"], "approved", answered_by="automation")
    agents.inbox.mark_sent(claim["id"], {"kind": "comment", "url": "https://github.com/owner/proj/issues/12#issuecomment-1"})

    result = asyncio.run(tools.close_issue({"job_id": job, "reason": "Fixed already by https://github.com/owner/proj/pull/5289"}))

    text = result["content"][0]["text"]
    assert f"But your claim was posted already: {claim['id']} (https://github.com/owner/proj/issues/12#issuecomment-1)" in text
    assert agents.jobs.get(job)["status"] == "cancelled"


def test_close_issue_withdraws_what_still_waits(agents, tools, job):
    asyncio.run(tools.draft_comment(dict(COMMENT_ARGS, job_id=job, target=ISSUE, body="I'd like to work on this.")))
    claim = agents.inbox.list()[0]

    result = asyncio.run(tools.close_issue({"job_id": job, "reason": "A duplicate of #3."}))

    assert result["content"][0]["text"].startswith(f"Closed: {job} is cancelled")
    assert agents.inbox.get(claim["id"])["status"] == "rejected"


# Evidence: real screenshots only


@pytest.fixture
def picture_args(job):
    """An image from the VM, as the after of the help window."""
    return {"job_id": job, "kind": "image", "stage": "after", "topic": "help window", "caption": "The help lists --verbose.",
            "context": "The help window before and after the change.", "path": "~/help.png"}


def test_picture_drawn_with_matplotlib_is_refused(agents, tools, picture_args, tmp_path):
    agents.vm.picture = MATPLOTLIB_PNG

    result = asyncio.run(tools.evidence_add(picture_args))

    assert result["is_error"] is True
    assert "was made with matplotlib: a picture you drew" in result["content"][0]["text"]
    assert not (tmp_path / "evidence").exists()


def test_matplotlibs_own_pictures_are_fine_on_matplotlib(agents, tools, picture_args):
    work = agents.jobs.create("fix_issue", "Fix the legend", "agent-1", "user", issue="matplotlib/matplotlib#30001")
    agents.jobs.update(work["id"], status="working")
    agents.vm.picture = MATPLOTLIB_PNG

    result = asyncio.run(tools.evidence_add(dict(picture_args, job_id=work["id"])))

    assert result.get("is_error") is None


def test_real_picture_is_kept_and_a_retake_replaces_it(agents, tools, picture_args, tmp_path):
    first = asyncio.run(tools.evidence_add(picture_args))
    again = asyncio.run(tools.evidence_add(dict(picture_args, caption="The help lists --verbose, retaken.")))

    assert first.get("is_error") is None
    assert "It replaced the after you had for that topic." in again["content"][0]["text"]
    pictures = [item for item in agents.jobs.get(picture_args["job_id"])["evidence"] if item["kind"] == "image"]
    assert len(pictures) == 1
    assert pictures[0]["caption"] == "The help lists --verbose, retaken."
    assert (tmp_path / "evidence" / pictures[0]["file"]).read_bytes() == PNG


def test_only_png_jpeg_gif_or_webp(agents, tools, picture_args):
    agents.vm.picture = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"

    result = asyncio.run(tools.evidence_add(picture_args))

    assert result["is_error"] is True
    assert "is not a PNG, JPEG, GIF or WebP image" in result["content"][0]["text"]


# VM error text never shows the user's secrets


def test_copy_from_the_vm_hides_the_users_secrets(agents, tools):
    agents.vm.env = {"OPENAI_API_KEY": SECRET}

    def failing_copy(agent_id, vm, source, folder):
        raise FileTransferError(f"incus file pull failed: Error: open /home/sam/{SECRET}: permission denied")

    agents.artifacts = SimpleNamespace(from_vm=failing_copy)

    result = asyncio.run(tools.artifact_from_vm({"source": "~/results.txt"}))

    assert result["is_error"] is True
    assert result["content"][0]["text"] == "incus file pull failed: Error: open /home/sam/[hidden]: permission denied"


def test_copy_into_the_vm_hides_the_users_secrets(agents, tools, tmp_path, monkeypatch):
    agents.vm.global_env = {"OPENAI_API_KEY": SECRET}
    notes = tmp_path / "notes.txt"
    notes.write_text("notes")
    agents.artifacts = SimpleNamespace(resolve=lambda agent_id, path: notes, has_links=lambda agent_id, path: False)

    def failing_copy(vm, source, target):
        raise FileTransferError(f"incus file push failed: Error: {SECRET} is not a folder")

    monkeypatch.setattr(work_tools, "to_vm", failing_copy)

    result = asyncio.run(tools.artifact_to_vm({"path": "notes.txt", "folder": "~/work"}))

    assert result["is_error"] is True
    assert result["content"][0]["text"] == "incus file push failed: Error: [hidden] is not a folder"


# Reviewing a draft by the author's rules (github_searcher/agent/review_tools.py)


def test_pr_agent_5147_reviewer_is_told_an_empty_push_comment_follows_the_rules(agents, follow_up):
    # A new version only bots asked for went without a comment, and its reviewer sent it back for having none.
    review = {"state": "waiting", "agent": "reviewer-1", "job": None, "notes": "", "at": "2026-11-25T10:00:00+00:00"}
    draft = agents.inbox.create("pr", "agent-1", "fix(ci): quote the path", "", job=follow_up, repo="owner/proj", target=PR, diff=DIFF, update_of=PR, review=review)
    reviewer = ReviewTools(agents, {"id": "reviewer-1", "name": "agent-3", "role": "reviewer", "target_vm": None})

    result = asyncio.run(reviewer.review_read({"draft_id": draft["id"]}))

    text = result["content"][0]["text"]
    assert f"This is the next version of the user's PR {PR}" in text
    assert "Never ask for a push comment in those cases, and never for an answer to a review bot" in text


def test_lancedb_4922_rebase_and_review_follow_the_same_push_comment_rule():
    # The rebase's instructions asked for a comment the round's rule refused, and its reviewer asked for one again.
    assert "empty when nobody asked (a conflict with main nobody mentioned" in SYSTEM_PROMPT
    assert "no push comment on a new version or rebase that no maintainer or reviewer asked for this round" in SYSTEM_PROMPT


# The rules read for the files a change touches (contributing_guide with paths), which run_tests' after run waits for


def test_deskcommcrm_5021_paths_read_stay_read_after_a_restart(agents, job, monkeypatch):
    # After a backend restart contributing_guide failed with a GitHub error, and the after run waited for the same files.
    monkeypatch.setattr(work_tools, "get_repository", lambda owner, repo: {"default_branch": "main"})
    monkeypatch.setattr(work_tools, "get_tree", lambda owner, repo, ref: {"tree": [{"type": "blob", "path": "cli.py"}]})
    record = {"id": "agent-1", "name": "agent-1", "target_vm": "vm1", "guides_read": ["owner/proj"], "pr_examples_read": ["owner/proj"]}
    asyncio.run(WorkTools(agents, record).contributing_guide({"name": "owner/proj", "paths": ["cli.py"]}))

    restarted = WorkTools(agents, record)
    restarted.threads_read[ISSUE] = time.time()
    agents.queue.add_run = lambda vm_name, run: None
    run = {"job_id": job, "path": "~/proj", "base": "origin/main", "command": "pytest tests/test_help.py", "scope": "focused", "when": "after", "background": True}
    result = asyncio.run(restarted.run_tests(run))

    assert record["paths_checked"] == {"owner/proj": ["cli.py"]}
    assert result["content"][0]["text"].startswith("Started the tests in the background as run_")


def test_serverpod_6000_diff_of_a_file_with_windows_line_ends_keeps_them(agents, tools, job):
    # Read without its "\r", the diff of a CRLF file no longer applied to that file when the PR was sent.
    crlf = "diff --git a/runtime.dart b/runtime.dart\n--- a/runtime.dart\n+++ b/runtime.dart\n@@ -1 +1 @@\n-var port = 80;\r\n+var port = 8080;\r\n"
    agents.vm.diff = crlf
    after = dict(agents.jobs.get(job)["tests"]["after"], diff_hash=hashlib.sha256(crlf.encode()).hexdigest())
    agents.jobs.update(job, tests={"before": None, "after": after})

    result = asyncio.run(tools.draft_pr(dict(PR_ARGS, job_id=job)))

    assert result.get("is_error") is None
    assert agents.inbox.list()[0]["diff"] == crlf
