"""Sending an approved draft as the user (github_searcher/github_account.py): what send() holds back, and how a PR's
commits are replayed.

send() never lets a PR out before its claim is decided, nor, where the repo's rules want an assignment, before GitHub
shows the user assigned (mcp-memory-service#1912). A claim whose job ended is never posted (repowise#5421). A comment or
an edit of a job waits for that job's new version of a PR (openmed#5413). The replayed commits go out as the user: the
VM's git address becomes the user's noreply address and every Signed-off-by line becomes theirs (LMCache#6430);
someone else's commit never goes. A send cut off after GitHub opened the PR keeps that PR (openmed#5512).

GitHub is a fake here (httpx.MockTransport): answers set by each test, and git trees worked out from what is posted,
as GitHub does. Nothing reaches GitHub, AWS or anything else. The Inbox, the jobs and the signed-in account are kept in
pytest's temporary folder, never in DATA_DIR."""

import base64
import hashlib
import json

import httpx
import pytest

from github_searcher import github_account
from github_searcher import inbox as inbox_module
from github_searcher import jobs as jobs_module
from github_searcher.github_account import GithubAccount, SendError
from github_searcher.inbox import Inbox
from github_searcher.jobs import Jobs

PROJECT = "owner/proj"
FORK = "sam-example/proj"
ISSUE = "owner/proj#12"
PR = "owner/proj#40"
ACCOUNT = {"token": "not-a-real-token", "login": "sam-example", "id": 1234, "name": "Sam Example", "scopes": ["repo"], "connected_at": "2026-11-01T00:00:00+00:00"}
YOU = {"name": "Sam Example", "email": "1234+sam-example@users.noreply.github.com"}
SIGNED_OFF = "Signed-off-by: Sam Example <1234+sam-example@users.noreply.github.com>"
# The VM's own git identity, the way an agent set it before it was told the user's (LMCache#6430).
VM_EMAIL = "agent@vm.internal"
BASE_SHA = "b" * 40
# The project's one file, as the base commit has it, and its git blob id.
OLD = b"HELP = 'usage: proj'\n"
OLD_BLOB = hashlib.sha1(b"blob %d\0" % len(OLD) + OLD).hexdigest()
# The reviewed change, and the agent's two commits that make it up.
DIFF = (
    "diff --git a/cli.py b/cli.py\n--- a/cli.py\n+++ b/cli.py\n@@ -1 +1,2 @@\n"
    "-HELP = 'usage: proj'\n+HELP = 'usage: proj [--verbose]'\n+VERSION = '1.1'\n"
)
FIRST_DIFF = "diff --git a/cli.py b/cli.py\n--- a/cli.py\n+++ b/cli.py\n@@ -1 +1 @@\n-HELP = 'usage: proj'\n+HELP = 'usage: proj [--verbose]'\n"
SECOND_DIFF = "diff --git a/cli.py b/cli.py\n--- a/cli.py\n+++ b/cli.py\n@@ -1 +1,2 @@\n HELP = 'usage: proj [--verbose]'\n+VERSION = '1.1'\n"
FIRST = {
    "sha": "1" * 40,
    "message": f"fix(cli): list --verbose in the help\n\nTested-by: vm-user <{VM_EMAIL}>\nSigned-off-by: vm-user <{VM_EMAIL}>\n",
    "author": {"name": "vm-user", "email": VM_EMAIL, "date": "2026-11-10T10:00:00+00:00"},
    "own": True,
    "vm_email": VM_EMAIL,
    "diff": FIRST_DIFF,
}
SECOND = {
    "sha": "2" * 40,
    "message": f"chore(cli): bump the version\n\nsigned-off-by: vm-user <{VM_EMAIL}>\n",
    "author": {"name": "vm-user", "email": VM_EMAIL, "date": "2026-11-10T10:05:00+00:00"},
    "own": True,
    "vm_email": VM_EMAIL,
    "diff": SECOND_DIFF,
}
# The user's open PR #40, as GitHub answers for it: theirs, its branch in their fork, at BASE_SHA.
PULL = {
    "merged": False,
    "state": "open",
    "user": {"login": "sam-example"},
    "head": {"sha": BASE_SHA, "ref": "fix-help", "repo": {"owner": {"login": "sam-example"}, "full_name": FORK}},
    "base": {"ref": "main"},
    "html_url": "https://github.com/owner/proj/pull/40",
}


class FakeGitHub:
    """GitHub's API the way the send path uses it. answers: (method, path) -> (status, json), set by the test. Trees and
    commits are made from what is posted (a tree's id comes from its files, as GitHub's does). taken: branches that are
    there already. Every request is kept in requests as (method, path, json)."""

    def __init__(self):
        self.answers = {}
        self.requests = []
        self.taken = []
        self.trees = {"tree-base": {"cli.py": OLD_BLOB}}

    def __call__(self, request):
        path = request.url.path
        body = None
        if request.content:
            body = json.loads(request.content)
        self.requests.append((request.method, path, body))
        if request.method == "POST" and path.endswith("/git/trees"):
            files = dict(self.trees[body["base_tree"]])
            for entry in body["tree"]:
                content = (entry.get("content") or "").encode()
                files[entry["path"]] = entry.get("sha") or hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()
            sha = "tree-" + hashlib.sha1(json.dumps(sorted(files.items())).encode()).hexdigest()[:12]
            self.trees[sha] = files
            return httpx.Response(201, json={"sha": sha})
        if request.method == "POST" and path.endswith("/git/commits"):
            made = [each for each in self.requests if each[0] == "POST" and each[1].endswith("/git/commits")]
            return httpx.Response(201, json={"sha": f"commit-{len(made)}"})
        if request.method == "POST" and path.endswith("/git/refs") and body["ref"] in self.taken:
            return httpx.Response(422, json={"message": "Reference already exists"})
        status, answer = self.answers.get((request.method, path), (404, {"message": "Not Found"}))
        return httpx.Response(status, json=answer)


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    """An empty Inbox in a temporary folder."""
    monkeypatch.setattr(inbox_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(inbox_module, "ACTIONS_FILE", tmp_path / "actions.json")
    return Inbox()


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    """No jobs yet, in a temporary folder."""
    monkeypatch.setattr(jobs_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(jobs_module, "EVIDENCE_DIR", tmp_path / "evidence")
    return Jobs()


@pytest.fixture
def account(tmp_path, monkeypatch, inbox, jobs):
    """Signed in as sam-example (github_account.json in a temporary folder), with the Inbox and the jobs. httpx.get, the
    assignment check's call, fails the test unless the test answers it."""
    monkeypatch.setattr(github_account, "DATA_DIR", tmp_path)
    monkeypatch.setattr(github_account, "EVIDENCE_DIR", tmp_path / "evidence")
    (tmp_path / "github_account.json").write_text(json.dumps(ACCOUNT))
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: pytest.fail("Nothing may reach GitHub here."))
    account = GithubAccount(inbox)
    account.jobs = jobs
    return account


@pytest.fixture
def went(account, monkeypatch):
    """send()'s checks only: whatever gets past them is kept here (its draft id) instead of going to GitHub."""
    went = []

    def fake_send(client, signed_in, draft):
        went.append(draft["id"])
        return {"kind": draft["kind"], "url": "https://github.com/owner/proj/pull/40", "at": "2026-11-15T00:00:00+00:00"}

    monkeypatch.setattr(account, "send_pr", fake_send)
    monkeypatch.setattr(account, "send_update", fake_send)
    monkeypatch.setattr(account, "post_comment", fake_send)
    monkeypatch.setattr(account, "send_edit", fake_send)
    return went


@pytest.fixture
def github():
    """The fake GitHub, with what a new PR from the user's fork needs: the project, the fork, the base commit, its tree
    and its file, and an opened PR."""
    github = FakeGitHub()
    github.answers[("GET", f"/repos/{PROJECT}")] = (200, {"owner": {"login": "owner"}, "full_name": PROJECT, "default_branch": "main", "private": False})
    github.answers[("POST", f"/repos/{PROJECT}/forks")] = (202, {"full_name": FORK})
    github.answers[("GET", f"/repos/{FORK}/branches")] = (200, [{"name": "main"}])
    github.answers[("GET", f"/repos/{FORK}/git/commits/{BASE_SHA}")] = (200, {"tree": {"sha": "tree-base"}})
    listing = {"truncated": False, "tree": [{"path": "cli.py", "mode": "100644", "type": "blob", "sha": OLD_BLOB}]}
    github.answers[("GET", f"/repos/{FORK}/git/trees/tree-base")] = (200, listing)
    github.answers[("GET", f"/repos/{FORK}/git/blobs/{OLD_BLOB}")] = (200, {"content": base64.b64encode(OLD).decode()})
    github.answers[("POST", f"/repos/{FORK}/git/refs")] = (201, {})
    github.answers[("GET", f"/repos/{PROJECT}/pulls")] = (200, [])
    github.answers[("POST", f"/repos/{PROJECT}/pulls")] = (201, {"html_url": "https://github.com/owner/proj/pull/41", "number": 41})
    return github


@pytest.fixture
def client(github):
    """An httpx client whose every request goes to the fake GitHub."""
    with httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(github)) as client:
        yield client


# What send() holds back


def test_not_signed_in(account, inbox, tmp_path):
    (tmp_path / "github_account.json").unlink()
    draft = inbox.create("comment", "agent-1", "Comment on owner/proj#40", "Done.", target=PR)

    with pytest.raises(SendError, match="Sign in with GitHub first"):
        account.send(draft["id"])


def test_sent_draft_isnt_sent_again(account, inbox, went):
    draft = inbox.create("comment", "agent-1", "Comment on owner/proj#40", "Done.", target=PR)
    inbox.mark_sent(draft["id"], {"kind": "comment", "url": "https://github.com/owner/proj/pull/40#issuecomment-1"})

    with pytest.raises(SendError, match="on GitHub already"):
        account.send(draft["id"])
    assert went == []


def test_questions_never_go_to_github(account, inbox, went):
    draft = inbox.create("question", "agent-1", "Which flag?", "Keep -v?")

    with pytest.raises(SendError, match="Only PRs, comments"):
        account.send(draft["id"])
    assert went == []


def test_pr_waits_while_its_claim_waits_for_the_user(account, inbox, jobs, went):
    job = jobs.create("fix_issue", "Fix the help", "agent-1", "user", issue=ISSUE)
    inbox.create("comment", "agent-1", "Claim owner/proj#12", "I'd like to work on this.", job=job["id"], target=ISSUE, wait_for_assignment=False)
    pr = inbox.create("pr", "agent-1", "fix(cli): list every flag", "Fixes #12.", job=job["id"], repo=PROJECT, target=ISSUE)

    with pytest.raises(SendError, match="Approve or reject Claim owner/proj#12 first"):
        account.send(pr["id"])
    assert went == []


def test_mcp_memory_service_1912_pr_waits_until_github_shows_you_assigned(account, inbox, jobs, went, monkeypatch):
    job = jobs.create("fix_issue", "Fix the help", "agent-1", "user", issue=ISSUE)
    claim = inbox.create("comment", "agent-1", "Claim owner/proj#12", "/claim", job=job["id"], target=ISSUE, wait_for_assignment=True)
    inbox.decide(claim["id"], "approved")
    pr = inbox.create("pr", "agent-1", "fix(cli): list every flag", "Fixes #12.", job=job["id"], repo=PROJECT, target=ISSUE)
    inbox.decide(pr["id"], "approved")
    asked = []

    def nobody_assigned(url, **kwargs):
        asked.append(url)
        return httpx.Response(200, json={"assignees": []}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", nobody_assigned)

    with pytest.raises(SendError, match="GitHub doesn't show you assigned yet"):
        account.send(pr["id"])
    assert went == []
    assert asked == ["https://api.github.com/repos/owner/proj/issues/12"]

    # The maintainer assigned the user (GitHub's spelling of the login may differ in case).
    you = {"assignees": [{"login": "Sam-Example"}]}
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: httpx.Response(200, json=you, request=httpx.Request("GET", url)))

    sent = account.send(pr["id"])
    assert went == [pr["id"]]
    assert sent["sent"]["url"] == "https://github.com/owner/proj/pull/40"


def test_claim_from_before_the_flag_waits_for_assignment_too(account, inbox, jobs, went, monkeypatch):
    job = jobs.create("fix_issue", "Fix the help", "agent-1", "user", issue=ISSUE)
    claim = inbox.create("comment", "agent-1", "Claim owner/proj#12", "/claim", job=job["id"], target=ISSUE, wait_for_assignment=None)
    inbox.decide(claim["id"], "approved")
    pr = inbox.create("pr", "agent-1", "fix(cli): list every flag", "Fixes #12.", job=job["id"], repo=PROJECT, target=ISSUE)
    nobody = {"assignees": []}
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: httpx.Response(200, json=nobody, request=httpx.Request("GET", url)))

    with pytest.raises(SendError, match="assign you to owner/proj#12"):
        account.send(pr["id"])
    assert went == []


def test_assignment_that_cant_be_checked_holds_the_pr(account, inbox, jobs, went, monkeypatch):
    job = jobs.create("fix_issue", "Fix the help", "agent-1", "user", issue=ISSUE)
    claim = inbox.create("comment", "agent-1", "Claim owner/proj#12", "/claim", job=job["id"], target=ISSUE, wait_for_assignment=True)
    inbox.decide(claim["id"], "approved")
    pr = inbox.create("pr", "agent-1", "fix(cli): list every flag", "Fixes #12.", job=job["id"], repo=PROJECT, target=ISSUE)
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: httpx.Response(502, request=httpx.Request("GET", url)))

    with pytest.raises(SendError, match="Could not check whether you are assigned"):
        account.send(pr["id"])
    assert went == []


def test_claim_without_wait_for_assignment_holds_nothing_once_approved(account, inbox, jobs, went):
    job = jobs.create("fix_issue", "Fix the help", "agent-1", "user", issue=ISSUE)
    claim = inbox.create("comment", "agent-1", "Claim owner/proj#12", "I'd like to work on this.", job=job["id"], target=ISSUE, wait_for_assignment=False)
    inbox.decide(claim["id"], "approved")
    pr = inbox.create("pr", "agent-1", "fix(cli): list every flag", "Fixes #12.", job=job["id"], repo=PROJECT, target=ISSUE)

    account.send(pr["id"])

    assert went == [pr["id"]]


def test_rejected_claim_doesnt_hold_the_pr(account, inbox, jobs, went):
    job = jobs.create("fix_issue", "Fix the help", "agent-1", "user", issue=ISSUE)
    claim = inbox.create("comment", "agent-1", "Claim owner/proj#12", "/claim", job=job["id"], target=ISSUE, wait_for_assignment=True)
    inbox.decide(claim["id"], "rejected")
    pr = inbox.create("pr", "agent-1", "fix(cli): list every flag", "Fixes #12.", job=job["id"], repo=PROJECT, target=ISSUE)

    account.send(pr["id"])

    assert went == [pr["id"]]


@pytest.mark.parametrize("status", ["cancelled", "done"])
def test_repowise_5421_claim_of_an_ended_job_is_never_posted(account, inbox, jobs, went, status):
    # The agent found the fix merged days before and closed the job; the claim had been approved meanwhile.
    job = jobs.create("fix_issue", "Fix the help", "agent-1", "user", issue=ISSUE)
    claim = inbox.create("comment", "agent-1", "Claim owner/proj#12", "I'd like to work on this.", job=job["id"], target=ISSUE, wait_for_assignment=False)
    inbox.decide(claim["id"], "approved")
    jobs.update(job["id"], status=status)

    with pytest.raises(SendError, match=f"which is {status}, so nobody works on owner/proj#12"):
        account.send(claim["id"])
    assert went == []
    assert inbox.get(claim["id"])["sent"] is None


def test_answer_of_a_finished_follow_up_still_goes(account, inbox, jobs, went):
    job = jobs.create("follow_up", "Answer the review", "agent-1", "user", thread=PR)
    comment = inbox.create("comment", "agent-1", "Comment on owner/proj#40", "Renamed it as asked.", job=job["id"], target=PR)
    inbox.decide(comment["id"], "approved")
    jobs.update(job["id"], status="done")

    account.send(comment["id"])

    assert went == [comment["id"]]


@pytest.mark.parametrize("kind", ["comment", "edit"])
def test_openmed_5413_comment_or_edit_waits_for_its_new_version(account, inbox, jobs, went, kind):
    # The comment said new tests were "now added to #5511" while that push still waited for its review.
    job = jobs.create("follow_up", "Add the tests", "agent-1", "user", thread=PR)
    version = inbox.create("pr", "agent-1", "test: cover the date shift", "Added the tests.", job=job["id"], repo=PROJECT, target=PR, update_of=PR)
    said = inbox.create(kind, "agent-1", "Comment on owner/proj#40", "The tests are now added to #40.", job=job["id"], target=PR)

    with pytest.raises(SendError, match="send test: cover the date shift first"):
        account.send(said["id"])

    inbox.decide(version["id"], "approved")
    with pytest.raises(SendError, match="isn't on GitHub yet"):
        account.send(said["id"])
    assert went == []


def test_comment_goes_once_its_version_is_on_github(account, inbox, jobs, went):
    job = jobs.create("follow_up", "Add the tests", "agent-1", "user", thread=PR)
    version = inbox.create("pr", "agent-1", "test: cover the date shift", "Added the tests.", job=job["id"], repo=PROJECT, target=PR, update_of=PR)
    inbox.decide(version["id"], "approved")
    inbox.mark_sent(version["id"], {"kind": "pr", "update": True, "url": "https://github.com/owner/proj/pull/40"})
    comment = inbox.create("comment", "agent-1", "Comment on owner/proj#40", "The tests are now added.", job=job["id"], target=PR)

    account.send(comment["id"])

    assert went == [comment["id"]]


def test_comment_drafted_with_a_version_its_reviewer_sent_back_waits(account, inbox, jobs, went):
    job = jobs.create("follow_up", "Add the tests", "agent-1", "user", thread=PR)
    version = inbox.create("pr", "agent-1", "test: cover the date shift", "Added the tests.", job=job["id"], repo=PROJECT, target=PR, update_of=PR)
    with_it = inbox.create("comment", "agent-1", "Comment on owner/proj#40", "The tests are now added.", job=job["id"], target=PR)
    inbox.set_review(version["id"], {"state": "changes", "agent": "agent-2", "job": "job_r1", "notes": "A test is missing.", "at": "x"})
    inbox.decide(version["id"], "rejected", "A test is missing.")
    after = inbox.create("comment", "agent-1", "Comment on owner/proj#40", "Thanks for the review.", job=job["id"], target=PR)
    # Times written out, so which came first never depends on the clock.
    inbox.drafts[with_it["id"]]["created_at"] = "2026-11-11T17:30:00+00:00"
    inbox.drafts[version["id"]]["decided_at"] = "2026-11-11T17:40:00+00:00"
    inbox.drafts[after["id"]]["created_at"] = "2026-11-11T17:50:00+00:00"

    with pytest.raises(SendError, match="which its reviewer sent back"):
        account.send(with_it["id"])
    account.send(after["id"])

    assert went == [after["id"]]


def test_version_you_rejected_holds_nothing(account, inbox, jobs, went):
    job = jobs.create("follow_up", "Add the tests", "agent-1", "user", thread=PR)
    version = inbox.create("pr", "agent-1", "test: cover the date shift", "Added the tests.", job=job["id"], repo=PROJECT, target=PR, update_of=PR)
    comment = inbox.create("comment", "agent-1", "Comment on owner/proj#40", "Thanks for the review.", job=job["id"], target=PR)
    inbox.decide(version["id"], "rejected", "Not this way.")

    account.send(comment["id"])

    assert went == [comment["id"]]


def test_only_the_jobs_newest_version_counts(account, inbox, jobs, went):
    job = jobs.create("follow_up", "Add the tests", "agent-1", "user", thread=PR)
    older = inbox.create("pr", "agent-1", "Older version", "Body", job=job["id"], repo=PROJECT, target=PR, update_of=PR)
    newer = inbox.create("pr", "agent-1", "Newer version", "Body", job=job["id"], repo=PROJECT, target=PR, update_of=PR)
    inbox.decide(newer["id"], "approved")
    inbox.mark_sent(newer["id"], {"kind": "pr", "update": True, "url": "https://github.com/owner/proj/pull/40"})
    comment = inbox.create("comment", "agent-1", "Comment on owner/proj#40", "Done.", job=job["id"], target=PR)
    inbox.drafts[older["id"]]["created_at"] = "2026-11-11T10:00:00+00:00"
    inbox.drafts[newer["id"]]["created_at"] = "2026-11-11T11:00:00+00:00"

    account.send(comment["id"])

    assert went == [comment["id"]]


# Commits: only the agent's, as the user


def test_someone_elses_commit_never_goes_out(account, inbox):
    theirs = dict(FIRST, own=False, author={"name": "Someone Else", "email": "else@example.com", "date": "x"})
    pr = inbox.create("pr", "agent-1", "fix(cli): list every flag", "Fixes #12.", repo=PROJECT, target=ISSUE, diff=DIFF,
                      base="origin/main", base_sha=BASE_SHA, commits=[theirs])
    update = inbox.create("pr", "agent-1", "fix(cli): list every flag", "Pushed.", repo=PROJECT, target=PR, diff=DIFF,
                          base="origin/main", base_sha=BASE_SHA, commits=[theirs], update_of=PR)

    # Refused before a single request: the client is never used.
    with pytest.raises(SendError, match="is by Someone Else, not the agent"):
        account.send_pr(None, ACCOUNT, inbox.get(pr["id"]))
    with pytest.raises(SendError, match="is by Someone Else, not the agent"):
        account.send_update(None, ACCOUNT, inbox.get(update["id"]))


def test_pr_draft_from_before_sending_isnt_sent(account, inbox):
    pr = inbox.create("pr", "agent-1", "Fix", "Fixes #12.", repo=PROJECT, target=ISSUE, diff=DIFF, base="origin/main")

    with pytest.raises(SendError, match="doesn't say which commit it starts from"):
        account.send_pr(None, ACCOUNT, inbox.get(pr["id"]))


def test_lmcache_6430_replayed_commits_go_out_with_your_name_and_sign_off(account, inbox, github, client):
    # The VM's git name ("vm-user") stayed in the Signed-off-by line next to the noreply address, and the DCO check failed.
    pr = inbox.create("pr", "agent-1", "fix(cli): list every flag", "Fixes #12.", repo=PROJECT, target=ISSUE, diff=DIFF,
                      branch="fix-help", base="origin/main", base_sha=BASE_SHA, commits=[FIRST, SECOND])

    sent = account.send_pr(client, ACCOUNT, inbox.get(pr["id"]))

    commits = [body for method, path, body in github.requests if method == "POST" and path == f"/repos/{FORK}/git/commits"]
    assert len(commits) == 2
    assert commits[0]["message"] == f"fix(cli): list --verbose in the help\n\nTested-by: vm-user <{YOU['email']}>\n{SIGNED_OFF}\n"
    assert commits[1]["message"] == f"chore(cli): bump the version\n\n{SIGNED_OFF}\n"
    assert commits[0]["author"] == YOU
    assert commits[0]["committer"] == YOU
    assert commits[0]["parents"] == [BASE_SHA]
    assert commits[1]["parents"] == ["commit-1"]
    assert VM_EMAIL not in json.dumps(github.requests)
    # The commits end at exactly the reviewed diff: no commit more.
    assert sent["commit"] == "commit-2"
    assert github.trees[commits[1]["tree"]]["cli.py"] != OLD_BLOB


def test_new_pr_opens_from_your_fork_into_the_branch_the_agent_started_from(account, inbox, github, client):
    pr = inbox.create("pr", "agent-1", "fix(cli): list every flag", "Fixes #12.", repo=PROJECT, target=ISSUE, diff=DIFF,
                      branch="fix-help", base="origin/main", base_sha=BASE_SHA, commits=[FIRST, SECOND])

    sent = account.send_pr(client, ACCOUNT, inbox.get(pr["id"]))

    refs = [body for method, path, body in github.requests if method == "POST" and path == f"/repos/{FORK}/git/refs"]
    pulls = [body for method, path, body in github.requests if method == "POST" and path == f"/repos/{PROJECT}/pulls"]
    assert refs == [{"ref": "refs/heads/fix-help", "sha": "commit-2"}]
    assert pulls == [{"title": "fix(cli): list every flag", "body": "Fixes #12.", "head": "sam-example:fix-help", "base": "main", "maintainer_can_modify": True}]
    assert sent["url"] == "https://github.com/owner/proj/pull/41"
    assert sent["fork"] == FORK
    assert sent["base_sha"] == BASE_SHA
    assert sent["as"] == "sam-example"


def test_what_the_commits_leave_out_goes_in_one_more_signed_off_commit(account, inbox, github, client):
    pr = inbox.create("pr", "agent-1", "fix(cli): list every flag", "Fixes #12.", repo=PROJECT, target=ISSUE, diff=DIFF,
                      branch="fix-help", base="origin/main", base_sha=BASE_SHA, commits=[FIRST])

    sent = account.send_pr(client, ACCOUNT, inbox.get(pr["id"]))

    commits = [body for method, path, body in github.requests if method == "POST" and path == f"/repos/{FORK}/git/commits"]
    assert len(commits) == 2
    assert commits[1]["message"] == f"fix(cli): list every flag\n\n{SIGNED_OFF}"
    assert commits[1]["parents"] == ["commit-1"]
    assert commits[1]["author"] == YOU
    assert sent["commit"] == "commit-2"


def test_without_commits_one_commit_with_the_title(account, inbox, github, client):
    pr = inbox.create("pr", "agent-1", "fix(cli): list every flag", "Fixes #12.", repo=PROJECT, target=ISSUE, diff=DIFF,
                      branch="fix-help", base="origin/main", base_sha=BASE_SHA)

    account.send_pr(client, ACCOUNT, inbox.get(pr["id"]))

    commits = [body for method, path, body in github.requests if method == "POST" and path == f"/repos/{FORK}/git/commits"]
    assert len(commits) == 1
    assert commits[0]["message"] == "fix(cli): list every flag"
    assert commits[0]["parents"] == [BASE_SHA]


def test_commits_that_dont_replay_become_one_commit(account, inbox, github, client):
    # A commit that only says a binary file differs can't be rebuilt from its diff.
    binary = dict(FIRST, diff="diff --git a/logo.png b/logo.png\nindex 1111111..2222222 100644\nBinary files a/logo.png and b/logo.png differ\n")
    pr = inbox.create("pr", "agent-1", "fix(cli): list every flag", "Fixes #12.", repo=PROJECT, target=ISSUE, diff=DIFF,
                      branch="fix-help", base="origin/main", base_sha=BASE_SHA, commits=[binary, SECOND])

    account.send_pr(client, ACCOUNT, inbox.get(pr["id"]))

    commits = [body for method, path, body in github.requests if method == "POST" and path == f"/repos/{FORK}/git/commits"]
    assert len(commits) == 1
    assert commits[0]["message"] == f"fix(cli): list every flag\n\n{SIGNED_OFF}"
    assert commits[0]["parents"] == [BASE_SHA]


def test_work_on_the_main_branch_goes_out_on_a_fix_branch(account, inbox, github, client):
    pr = inbox.create("pr", "agent-1", "fix(cli): list every flag", "Fixes #12.", repo=PROJECT, target=ISSUE, diff=DIFF,
                      branch="main", base="origin/main", base_sha=BASE_SHA)

    sent = account.send_pr(client, ACCOUNT, inbox.get(pr["id"]))

    assert sent["branch"] == "fix-12"


def test_openmed_5512_send_cut_off_after_github_opened_the_pr_keeps_that_pr(account, inbox, github, client):
    # One approval opened #5511 and, sent again after a restart, #5512 with the same tree.
    pr = inbox.create("pr", "agent-1", "test: cover the date shift", "Fixes #5413.", repo=PROJECT, target="owner/proj#5413",
                      diff=DIFF, branch="fix-help", base="origin/main", base_sha=BASE_SHA)
    opened = {
        "user": {"login": "Sam-Example"},
        "title": "test: cover the date shift",
        "created_at": pr["created_at"],
        "head": {"sha": "8c54a3bf"},
        "html_url": "https://github.com/owner/proj/pull/5511",
        "number": 5511,
    }
    github.taken.append("refs/heads/fix-help")
    github.answers[("GET", f"/repos/{PROJECT}/pulls")] = (200, [opened])

    sent = account.send_pr(client, ACCOUNT, inbox.get(pr["id"]))

    assert sent["url"] == "https://github.com/owner/proj/pull/5511"
    assert sent["number"] == 5511
    assert sent["commit"] == "8c54a3bf"
    assert [path for method, path, body in github.requests if method == "POST" and path == f"/repos/{PROJECT}/pulls"] == []


def test_branch_name_taken_by_an_older_pr_gets_the_next_number(account, inbox, github, client):
    pr = inbox.create("pr", "agent-1", "fix(cli): list every flag", "Fixes #12.", repo=PROJECT, target=ISSUE, diff=DIFF,
                      branch="fix-help", base="origin/main", base_sha=BASE_SHA)
    # Your PR from that branch, with the same title, but opened before this draft was made: another send's.
    older = {"user": {"login": "sam-example"}, "title": "fix(cli): list every flag", "created_at": "2026-01-01T00:00:00+00:00",
             "head": {"sha": "old"}, "html_url": "https://github.com/owner/proj/pull/3", "number": 3}
    github.taken.append("refs/heads/fix-help")
    github.answers[("GET", f"/repos/{PROJECT}/pulls")] = (200, [older])

    sent = account.send_pr(client, ACCOUNT, inbox.get(pr["id"]))

    assert sent["branch"] == "fix-help-2"
    assert sent["url"] == "https://github.com/owner/proj/pull/41"


# A new version of the user's open PR


@pytest.mark.parametrize(
    "pull, problem",
    [
        ({**PULL, "merged": True}, "is merged already"),
        ({**PULL, "state": "closed"}, "is closed: reopen it first"),
        ({**PULL, "user": {"login": "someone"}}, "isn't yours: it was opened by someone"),
        ({**PULL, "head": {**PULL["head"], "repo": None}}, "its fork was deleted"),
        ({**PULL, "head": {**PULL["head"], "repo": {"owner": {"login": "someone"}, "full_name": "someone/proj"}}}, "not in your fork"),
        ({**PULL, "head": {**PULL["head"], "sha": "c" * 40}}, "changed since the agent drafted this"),
    ],
)
def test_new_version_is_refused(account, inbox, github, client, pull, problem):
    github.answers[("GET", f"/repos/{PROJECT}/pulls/40")] = (200, pull)
    update = inbox.create("pr", "agent-1", "fix(cli): list --verbose", "Renamed it as asked.", repo=PROJECT, target=PR,
                          diff=FIRST_DIFF, base="fix-help", base_sha=BASE_SHA, commits=[FIRST], update_of=PR)

    with pytest.raises(SendError, match=problem):
        account.send_update(client, ACCOUNT, inbox.get(update["id"]))
    assert [method for method, path, body in github.requests if method != "GET"] == []


def test_new_version_is_a_fast_forward_with_its_comment(account, inbox, github, client):
    github.answers[("GET", f"/repos/{PROJECT}/pulls/40")] = (200, PULL)
    github.answers[("PATCH", f"/repos/{FORK}/git/refs/heads/fix-help")] = (200, {})
    github.answers[("POST", f"/repos/{PROJECT}/issues/40/comments")] = (201, {"html_url": "https://github.com/owner/proj/pull/40#issuecomment-9"})
    update = inbox.create("pr", "agent-1", "fix(cli): list --verbose", "Renamed it as asked.", repo=PROJECT, target=PR,
                          diff=FIRST_DIFF, base="fix-help", base_sha=BASE_SHA, commits=[FIRST], update_of=PR)

    sent = account.send_update(client, ACCOUNT, inbox.get(update["id"]))

    pushes = [body for method, path, body in github.requests if method == "PATCH"]
    assert pushes == [{"sha": "commit-1", "force": False}]
    assert sent["update"] is True
    assert sent["rebase_of"] is None
    assert sent["comment_url"] == "https://github.com/owner/proj/pull/40#issuecomment-9"
    assert sent["comment_error"] is None


def test_new_version_stays_sent_when_only_its_comment_is_refused(account, inbox, github, client):
    github.answers[("GET", f"/repos/{PROJECT}/pulls/40")] = (200, PULL)
    github.answers[("PATCH", f"/repos/{FORK}/git/refs/heads/fix-help")] = (200, {})
    github.answers[("POST", f"/repos/{PROJECT}/issues/40/comments")] = (403, {"message": "Conversation is locked"})
    update = inbox.create("pr", "agent-1", "fix(cli): list --verbose", "Renamed it as asked.", repo=PROJECT, target=PR,
                          diff=FIRST_DIFF, base="fix-help", base_sha=BASE_SHA, commits=[FIRST], update_of=PR)

    sent = account.send_update(client, ACCOUNT, inbox.get(update["id"]))

    assert sent["commit"] == "commit-1"
    assert sent["comment_url"] is None
    assert sent["comment_error"].startswith("GitHub answered 403")


def test_rebase_force_pushes_only_while_the_branch_is_where_the_agent_saw_it(account, inbox, github, client):
    rebase_of = "r" * 40
    github.answers[("GET", f"/repos/{PROJECT}/pulls/40")] = (200, {**PULL, "head": {**PULL["head"], "sha": rebase_of}})
    github.answers[("GET", f"/repos/{FORK}/git/ref/heads/fix-help")] = (200, {"object": {"sha": rebase_of}})
    github.answers[("PATCH", f"/repos/{FORK}/git/refs/heads/fix-help")] = (200, {})
    rebase = inbox.create("pr", "agent-1", "fix(cli): list --verbose", "", repo=PROJECT, target=PR, diff=FIRST_DIFF,
                          base="origin/main", base_sha=BASE_SHA, commits=[FIRST], update_of=PR, rebase_of=rebase_of)

    sent = account.send_update(client, ACCOUNT, inbox.get(rebase["id"]))

    pushes = [body for method, path, body in github.requests if method == "PATCH"]
    assert pushes == [{"sha": "commit-1", "force": True}]
    assert sent["rebase_of"] == rebase_of
    # An empty body posts no comment.
    assert [path for method, path, body in github.requests if path.endswith("/comments")] == []


def test_rebase_pushes_nothing_when_the_branch_moved_meanwhile(account, inbox, github, client):
    rebase_of = "r" * 40
    github.answers[("GET", f"/repos/{PROJECT}/pulls/40")] = (200, {**PULL, "head": {**PULL["head"], "sha": rebase_of}})
    github.answers[("GET", f"/repos/{FORK}/git/ref/heads/fix-help")] = (200, {"object": {"sha": "pushed-by-you-meanwhile"}})
    rebase = inbox.create("pr", "agent-1", "fix(cli): list --verbose", "", repo=PROJECT, target=PR, diff=FIRST_DIFF,
                          base="origin/main", base_sha=BASE_SHA, commits=[FIRST], update_of=PR, rebase_of=rebase_of)

    with pytest.raises(SendError, match="changed while this was being sent: nothing was pushed"):
        account.send_update(client, ACCOUNT, inbox.get(rebase["id"]))
    assert [method for method, path, body in github.requests if method == "PATCH"] == []


# A new title and description


@pytest.fixture
def edit(inbox, github):
    """An edit draft for the user's PR #40, drafted on its text as it was then; GitHub has it the same way."""
    github.answers[("GET", f"/repos/{PROJECT}/issues/40")] = (200, {
        "user": {"login": "sam-example"},
        "title": "Fix the help",
        "body": "Lists every flag.\n\n- [x] Tests pass",
        "html_url": "https://github.com/owner/proj/pull/40",
    })
    github.answers[("PATCH", f"/repos/{PROJECT}/issues/40")] = (200, {})
    draft = inbox.create("edit", "agent-1", "fix(cli): list every flag in the help", "Lists every flag, and --verbose.\n\n- [x] Tests pass",
                         repo=PROJECT, target=PR, previous={"title": "Fix the help", "body": "Lists every flag.\n\n- [x] Tests pass"})
    return inbox.get(draft["id"])


def test_edit_changes_title_and_description(account, edit, github, client):
    sent = account.send_edit(client, ACCOUNT, edit)

    patches = [body for method, path, body in github.requests if method == "PATCH"]
    assert patches == [{"title": "fix(cli): list every flag in the help", "body": "Lists every flag, and --verbose.\n\n- [x] Tests pass"}]
    assert sent["kind"] == "edit"
    assert sent["number"] == 40


def test_opencodex_bot_unticking_the_checklist_isnt_a_change(account, edit, github, client):
    # The project's bot unticks the PR's checklist on every push, and GitHub's editor saves Windows line ends.
    github.answers[("GET", f"/repos/{PROJECT}/issues/40")] = (200, {
        "user": {"login": "sam-example"},
        "title": "Fix the help",
        "body": "Lists every flag.\r\n\r\n- [ ] Tests pass\r\n",
        "html_url": "https://github.com/owner/proj/pull/40",
    })

    account.send_edit(client, ACCOUNT, edit)

    assert len([method for method, path, body in github.requests if method == "PATCH"]) == 1


def test_edit_refused_when_the_text_changed_since(account, edit, github, client):
    github.answers[("GET", f"/repos/{PROJECT}/issues/40")] = (200, {
        "user": {"login": "sam-example"},
        "title": "Fix the help",
        "body": "Lists every flag. Edited by hand on GitHub.\n\n- [x] Tests pass",
        "html_url": "https://github.com/owner/proj/pull/40",
    })

    with pytest.raises(SendError, match="changed since the agent drafted this"):
        account.send_edit(client, ACCOUNT, edit)
    assert [method for method, path, body in github.requests if method == "PATCH"] == []


def test_edit_refused_on_someone_elses_pr(account, edit, github, client):
    github.answers[("GET", f"/repos/{PROJECT}/issues/40")] = (200, {
        "user": {"login": "maintainer"},
        "title": "Fix the help",
        "body": "Lists every flag.\n\n- [x] Tests pass",
        "html_url": "https://github.com/owner/proj/pull/40",
    })

    with pytest.raises(SendError, match="isn't yours: it was opened by maintainer"):
        account.send_edit(client, ACCOUNT, edit)


def test_opencodex_8598_edit_github_took_already_isnt_made_again(account, edit, github, client):
    # A send cut off by a restart after GitHub took the new text.
    github.answers[("GET", f"/repos/{PROJECT}/issues/40")] = (200, {
        "user": {"login": "sam-example"},
        "title": "fix(cli): list every flag in the help",
        "body": "Lists every flag, and --verbose.\r\n\r\n- [x] Tests pass",
        "html_url": "https://github.com/owner/proj/pull/40",
    })

    sent = account.send_edit(client, ACCOUNT, edit)

    assert sent["title"] == "fix(cli): list every flag in the help"
    assert [method for method, path, body in github.requests if method == "PATCH"] == []


# Comments


def test_comment_goes_below_its_issue(account, inbox, github, client):
    github.answers[("POST", f"/repos/{PROJECT}/issues/12/comments")] = (201, {"html_url": "https://github.com/owner/proj/issues/12#issuecomment-5", "id": 5})
    draft = inbox.create("comment", "agent-1", "Claim owner/proj#12", "I'd like to work on this.", repo=PROJECT, target=ISSUE)

    sent = account.post_comment(client, ACCOUNT, inbox.get(draft["id"]))

    assert sent["id"] == 5
    assert sent["number"] == 12
    assert sent["resolved"] is False
    assert [body for method, path, body in github.requests if method == "POST"] == [{"body": "I'd like to work on this."}]


def test_comment_without_a_target_isnt_sent(account, inbox):
    draft = inbox.create("comment", "agent-1", "Comment", "Hello", repo=PROJECT, target=None)

    with pytest.raises(SendError, match="no issue or PR to go on"):
        account.post_comment(None, ACCOUNT, inbox.get(draft["id"]))


def test_voltagent_answer_refused_in_the_conversation_goes_below_the_pr(account, inbox, github, client):
    # An organization that restricts OAuth Apps refuses answers inside a conversation on lines of code.
    github.answers[("POST", f"/repos/{PROJECT}/pulls/40/comments/501/replies")] = (403, {"message": "Resource not accessible by integration"})
    github.answers[("POST", f"/repos/{PROJECT}/issues/40/comments")] = (201, {"html_url": "https://github.com/owner/proj/pull/40#issuecomment-7", "id": 7})
    draft = inbox.create("comment", "agent-1", "Reply in a conversation on owner/proj#40", "Renamed it.", repo=PROJECT, target=PR, reply_to=501)

    sent = account.post_comment(client, ACCOUNT, inbox.get(draft["id"]))

    below = [body for method, path, body in github.requests if path == f"/repos/{PROJECT}/issues/40/comments"]
    assert below == [{"body": "In reply to https://github.com/owner/proj/pull/40#discussion_r501:\n\nRenamed it."}]
    assert sent["url"] == "https://github.com/owner/proj/pull/40#issuecomment-7"


def test_mcp_memory_service_1912_answer_resolves_its_conversation(account, inbox, github, client):
    # The project merges only once every review conversation is answered and resolved.
    github.answers[("POST", f"/repos/{PROJECT}/pulls/40/comments/501/replies")] = (201, {"html_url": "https://github.com/owner/proj/pull/40#discussion_r502", "id": 502})
    github.answers[("POST", "/graphql")] = (200, {"data": {"resolveReviewThread": {"clientMutationId": None}}})
    draft = inbox.create("comment", "agent-1", "Reply and resolve a conversation on owner/proj#40", "Fixed in the new version.",
                         repo=PROJECT, target=PR, reply_to=501, resolve="PRRT_kwDO1")

    sent = account.post_comment(client, ACCOUNT, inbox.get(draft["id"]))

    resolved = [body for method, path, body in github.requests if path == "/graphql"]
    assert resolved[0]["variables"] == {"id": "PRRT_kwDO1"}
    assert sent["resolved"] is True
    assert sent["resolve_error"] is None


def test_openchoreo_answer_stays_sent_when_resolving_is_refused(account, inbox, github, client):
    github.answers[("POST", f"/repos/{PROJECT}/pulls/40/comments/501/replies")] = (201, {"html_url": "https://github.com/owner/proj/pull/40#discussion_r502", "id": 502})
    refused = {"errors": [{"message": "Although you appear to have the correct authorization credentials, the `owner` organization has enabled OAuth App access restrictions"}]}
    github.answers[("POST", "/graphql")] = (200, refused)
    draft = inbox.create("comment", "agent-1", "Reply and resolve a conversation on owner/proj#40", "Fixed in the new version.",
                         repo=PROJECT, target=PR, reply_to=501, resolve="PRRT_kwDO1")

    sent = account.post_comment(client, ACCOUNT, inbox.get(draft["id"]))

    assert sent["id"] == 502
    assert sent["resolved"] is False
    assert "OAuth App access restrictions" in sent["resolve_error"]
