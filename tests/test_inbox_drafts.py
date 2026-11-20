"""The stores drafts and jobs live in: the Inbox (github_searcher/inbox.py) and jobs (github_searcher/jobs.py). A draft is decided once, edited only while pending, deleted only once decided, and
what went to GitHub stays in the actions list even when its draft is gone. Older records load with the fields added
since. A job's steps, statuses and evidence follow the rules jobs.py describes.

Every store keeps its files in pytest's temporary folder, never in DATA_DIR."""

import json

import pytest

from github_searcher import inbox as inbox_module
from github_searcher import jobs as jobs_module
from github_searcher.inbox import Inbox
from github_searcher.jobs import STEPS, Jobs

PR_DIFF = "diff --git a/cli.py b/cli.py\n--- a/cli.py\n+++ b/cli.py\n@@ -1 +1 @@\n-HELP = 'usage'\n+HELP = 'usage: proj'\n"


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    """An empty Inbox, its drafts and actions.json in a temporary folder."""
    monkeypatch.setattr(inbox_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(inbox_module, "ACTIONS_FILE", tmp_path / "actions.json")
    return Inbox()


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    """No jobs yet, their files and evidence in a temporary folder."""
    monkeypatch.setattr(jobs_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(jobs_module, "EVIDENCE_DIR", tmp_path / "evidence")
    return Jobs()


# The Inbox


def test_new_draft_waits_for_the_user(inbox, tmp_path):
    draft = inbox.create("pr", "agent-1", "Fix the help output", "Fixes #12.", job="job_a1b2c3", repo="owner/proj",
                         target="owner/proj#12", diff=PR_DIFF, base="origin/main", base_sha="b" * 40)

    assert draft["id"].startswith("draft_")
    assert draft["status"] == "pending"
    assert draft["reply"] == ""
    assert draft["decided_at"] is None
    assert draft["sent"] is None
    assert draft["edited"] is False
    assert draft["commits"] == []
    assert draft["evidence"] == []
    assert json.loads((tmp_path / "inbox" / f"{draft['id']}.json").read_text()) == draft


def test_draft_keeps_its_own_copy_of_what_it_was_made_with(inbox):
    commits = [{"sha": "c1", "message": "fix: help\n", "own": True}]
    evidence = [{"id": "ev_000001", "topic": "help output", "stage": "after"}]
    draft = inbox.create("pr", "agent-1", "Fix", "Body", commits=commits, evidence=evidence)

    commits[0]["own"] = False
    evidence.append({"id": "ev_000002"})
    returned = inbox.get(draft["id"])
    returned["title"] = "Changed by the caller"

    stored = inbox.get(draft["id"])
    assert stored["commits"][0]["own"] is True
    assert len(stored["evidence"]) == 1
    assert stored["title"] == "Fix"


def test_draft_from_before_the_newer_fields_loads_with_them(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(inbox_module, "ACTIONS_FILE", tmp_path / "actions.json")
    (tmp_path / "inbox").mkdir()
    old = {
        "id": "draft_0ld001", "kind": "pr", "agent": "agent-1", "job": None, "repo": "owner/proj", "target": "owner/proj#3",
        "title": "Fix it", "body": "Fixes #3", "diff": PR_DIFF, "branch": "fix-3", "base": "origin/main", "vm": "vm1",
        "path": "/home/sam/proj", "status": "approved", "reply": "", "created_at": "2026-10-20T10:00:00+00:00",
        "decided_at": "2026-10-20T11:00:00+00:00",
    }
    (tmp_path / "inbox" / "draft_0ld001.json").write_text(json.dumps(old))

    draft = Inbox().get("draft_0ld001")

    assert draft["evidence"] == []
    assert draft["overview"] == {}
    assert draft["template"] is None
    assert draft["base_sha"] == ""
    assert draft["commits"] == []
    assert draft["sent"] is None
    assert draft["update_of"] is None
    assert draft["rebase_of"] is None
    assert draft["edited"] is False
    assert draft["review"] is None
    assert draft["replaces"] is None
    assert draft["previous"] is None
    assert draft["options"] == []
    assert draft["reply_to"] is None
    assert draft["resolve"] is None


def test_half_written_draft_from_a_crash_is_left_out(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(inbox_module, "ACTIONS_FILE", tmp_path / "actions.json")
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "draft_c0ffee.json.tmp").write_text('{"id": "draft_c0ffee", "kind": "pr"')

    assert Inbox().list() == []


def test_list_is_newest_first(inbox):
    first = inbox.create("comment", "agent-1", "Comment on owner/proj#1", "First")
    second = inbox.create("comment", "agent-1", "Comment on owner/proj#2", "Second")

    assert [draft["id"] for draft in inbox.list()] == [second["id"], first["id"]]


def test_unknown_draft_is_a_key_error(inbox):
    with pytest.raises(KeyError):
        inbox.get("draft_000000")
    with pytest.raises(KeyError):
        inbox.decide("draft_000000", "approved")


def test_draft_is_decided_once(inbox):
    draft = inbox.create("pr", "agent-1", "Fix", "Body")

    decided = inbox.decide(draft["id"], "approved")

    assert decided["status"] == "approved"
    assert decided["decided_at"] is not None
    with pytest.raises(ValueError, match="already approved"):
        inbox.decide(draft["id"], "rejected", "Too late")
    assert inbox.get(draft["id"])["status"] == "approved"


def test_only_known_decisions(inbox):
    draft = inbox.create("pr", "agent-1", "Fix", "Body")

    with pytest.raises(ValueError, match="Unknown decision"):
        inbox.decide(draft["id"], "sent")
    assert inbox.get(draft["id"])["status"] == "pending"


def test_who_answered_is_kept_on_questions_only(inbox):
    question = inbox.create("question", "agent-1", "Which flag?", "Keep -v?", options=["Keep it", "Drop it"], recommended="Keep it")
    pr = inbox.create("pr", "agent-1", "Fix", "Body")

    question = inbox.decide(question["id"], "replied", "I pick: Keep it", answered_by="timer")
    pr = inbox.decide(pr["id"], "approved", answered_by="timer")

    assert question["answered_by"] == "timer"
    assert pr["answered_by"] is None


def test_edit_changes_title_and_text(inbox):
    draft = inbox.create("pr", "agent-1", "Fix the help", "Old text")

    edited = inbox.edit(draft["id"], "  fix(cli): list every flag in the help  ", "  New text\n")

    assert edited["title"] == "fix(cli): list every flag in the help"
    assert edited["body"] == "New text"
    assert edited["edited"] is True


def test_saving_the_same_text_is_not_an_edit(inbox):
    draft = inbox.create("comment", "agent-1", "Comment on owner/proj#4", "Thanks, done.\n")

    edited = inbox.edit(draft["id"], "Comment on owner/proj#4", "Thanks, done.")

    assert edited["edited"] is False
    assert edited["body"] == "Thanks, done.\n"


def test_edit_needs_a_title_and_a_text(inbox):
    draft = inbox.create("pr", "agent-1", "Fix", "Body")

    with pytest.raises(ValueError, match="can't be empty"):
        inbox.edit(draft["id"], "Fix", "   ")
    with pytest.raises(ValueError, match="can't be empty"):
        inbox.edit(draft["id"], "", "Body")


def test_only_prs_comments_and_edits_can_be_edited(inbox):
    question = inbox.create("question", "agent-1", "Which flag?", "Keep -v?")

    with pytest.raises(ValueError, match="Only a PR, a comment"):
        inbox.edit(question["id"], "Which flag?", "Keep --verbose?")


def test_decided_draft_cant_be_edited(inbox):
    draft = inbox.create("pr", "agent-1", "Fix", "Body")
    inbox.decide(draft["id"], "approved")

    with pytest.raises(ValueError, match="already approved"):
        inbox.edit(draft["id"], "Fix", "Changed after Approve")
    assert inbox.get(draft["id"])["body"] == "Body"


def test_delete_leaves_pending_drafts(inbox, tmp_path):
    pending = inbox.create("pr", "agent-1", "Waiting", "Body")
    decided = inbox.create("comment", "agent-1", "Rejected", "Body")
    inbox.decide(decided["id"], "rejected")

    deleted = inbox.delete([pending["id"], decided["id"], "draft_000000"])

    assert deleted == [decided["id"]]
    assert [draft["id"] for draft in inbox.list()] == [pending["id"]]
    assert not (tmp_path / "inbox" / f"{decided['id']}.json").exists()
    assert (tmp_path / "inbox" / f"{pending['id']}.json").exists()


def test_pr_owners_count_prs_that_are_or_may_soon_be_on_github(inbox):
    inbox.create("pr", "agent-1", "Waiting", "Body")
    approved = inbox.create("pr", "agent-1", "Approved", "Body")
    inbox.decide(approved["id"], "approved")
    rejected = inbox.create("pr", "agent-2", "Rejected", "Body")
    inbox.decide(rejected["id"], "rejected")
    inbox.create("comment", "agent-2", "A comment", "Body")

    assert inbox.pr_owners() == {"agent-1": 2}


def test_set_review(inbox):
    draft = inbox.create("pr", "agent-1", "Fix", "Body", review={"state": "waiting", "agent": None, "job": None, "notes": "", "at": "x"})

    reviewed = inbox.set_review(draft["id"], {"state": "passed", "agent": "agent-2", "job": "job_r1", "notes": "Looks right.", "at": "y"})

    assert reviewed["review"]["state"] == "passed"
    assert inbox.get(draft["id"])["review"]["notes"] == "Looks right."


def test_sent_draft_becomes_one_action_that_outlives_it(inbox, tmp_path):
    draft = inbox.create("comment", "agent-1", "Comment on owner/proj#4", "Body", job="job_a1b2c3")
    inbox.decide(draft["id"], "approved")
    sent = {"kind": "comment", "url": "https://github.com/owner/proj/issues/4#issuecomment-1", "id": 1, "repo": "owner/proj", "number": 4, "at": "t1"}

    inbox.mark_sent(draft["id"], sent)
    # Deleted later from the GitHub tab: the same draft comes back with deleted_at.
    inbox.mark_sent(draft["id"], dict(sent, deleted_at="t2"))
    inbox.delete([draft["id"]])

    actions = inbox.actions()
    assert len(actions) == 1
    assert actions[0]["draft"] == draft["id"]
    assert actions[0]["job"] == "job_a1b2c3"
    assert actions[0]["sent"]["deleted_at"] == "t2"
    assert json.loads((tmp_path / "actions.json").read_text()) == actions


def test_actions_are_newest_first(inbox):
    inbox.add_action({"draft": None, "kind": "issue", "agent": "agent-1", "job": None, "title": "First", "sent": {"at": "t1"}})
    inbox.add_action({"draft": None, "kind": "update_branch", "agent": "agent-1", "job": None, "title": "Second", "sent": {"at": "t2"}})

    assert [action["title"] for action in inbox.actions()] == ["Second", "First"]


def test_first_actions_list_is_made_from_drafts_sent_before_it(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(inbox_module, "ACTIONS_FILE", tmp_path / "actions.json")
    (tmp_path / "inbox").mkdir()
    base = {"agent": "agent-1", "job": None, "repo": "owner/proj", "target": "owner/proj#1", "body": "", "status": "approved",
            "reply": "", "created_at": "2026-10-01T00:00:00+00:00", "decided_at": "2026-10-01T00:00:00+00:00"}
    later = dict(base, id="draft_000002", kind="pr", title="Sent later", sent={"url": "u2", "at": "2026-10-03T00:00:00+00:00"})
    earlier = dict(base, id="draft_000001", kind="comment", title="Sent first", sent={"url": "u1", "at": "2026-10-02T00:00:00+00:00"})
    never = dict(base, id="draft_000003", kind="pr", title="Never sent", sent=None)
    for draft in [later, earlier, never]:
        (tmp_path / "inbox" / f"{draft['id']}.json").write_text(json.dumps(draft))

    actions = Inbox().actions()

    assert [action["title"] for action in actions] == ["Sent later", "Sent first"]
    assert (tmp_path / "actions.json").is_file()


# Jobs


def test_new_job_takes_its_repo_from_its_issue_or_thread(jobs):
    fix = jobs.create("fix_issue", "Fix the help", "agent-1", "user", issue="owner/proj#12", agent_name="agent-1")
    follow = jobs.create("follow_up", "Answer the review", "agent-1", "user", thread="owner/other#40")

    assert fix["repo"] == "owner/proj"
    assert follow["repo"] == "owner/other"
    assert fix["status"] == "queued"
    assert fix["steps"] == ["understand", "set_up", "reproduce", "fix", "test", "draft"]
    assert fix["tests"] == {"before": None, "after": None}
    assert fix["skip_checks"] is False


def test_unknown_kind_gets_the_task_steps(jobs):
    job = jobs.create("tidy_docs", "Tidy the docs", "agent-1", "agent-1")

    assert job["steps"] == STEPS["task"]


def test_timeline_starts_with_who_has_the_job(jobs):
    assigned = jobs.create("fix_issue", "Fix", "agent-1", "user", issue="owner/proj#1", agent_name="agent-1")
    own = jobs.create("task", "Look around", "agent-1", "agent-1", agent_name="agent-1")
    unnamed = jobs.create("task", "Look around", "agent-1", "user")

    assert assigned["timeline"][0]["text"] == "Assigned to agent-1"
    assert own["timeline"][0]["text"] == "Created by agent-1"
    assert unnamed["timeline"][0]["text"] == "Assigned to an agent"


def test_only_updatable_fields_change(jobs):
    job = jobs.create("fix_issue", "Fix", "agent-1", "user", issue="owner/proj#1")

    with pytest.raises(ValueError, match="kind can't be changed"):
        jobs.update(job["id"], kind="task")
    with pytest.raises(ValueError, match="Unknown job status"):
        jobs.update(job["id"], status="sent")
    with pytest.raises(ValueError, match="Unknown step 'work'"):
        jobs.update(job["id"], step="work")
    assert jobs.get(job["id"])["kind"] == "fix_issue"


def test_started_and_step_times_are_kept(jobs):
    job = jobs.create("fix_issue", "Fix", "agent-1", "user", issue="owner/proj#1")

    working = jobs.update(job["id"], status="working", step="understand")
    again = jobs.update(job["id"], status="working", step="understand")
    fixing = jobs.update(job["id"], step="fix")

    assert working["started_at"] is not None
    assert again["started_at"] == working["started_at"]
    assert again["step_at"] == working["step_at"]
    assert fixing["step_at"] != working["step_at"]


def test_update_keeps_its_own_copy_of_the_drafts(jobs):
    job = jobs.create("fix_issue", "Fix", "agent-1", "user", issue="owner/proj#1")
    drafts = ["draft_000001"]

    jobs.update(job["id"], drafts=drafts)
    drafts.append("draft_000002")

    assert jobs.get(job["id"])["drafts"] == ["draft_000001"]


def test_retake_replaces_its_evidence_in_place(jobs):
    job = jobs.create("fix_issue", "Fix", "agent-1", "user", issue="owner/proj#1")
    jobs.add_evidence(job["id"], {"id": "ev_000001", "topic": "Help output", "stage": "before"})
    jobs.add_evidence(job["id"], {"id": "ev_000002", "topic": "Help output", "stage": "after"})

    replaced = jobs.add_evidence(job["id"], {"id": "ev_000003", "topic": "  help OUTPUT ", "stage": "before"})
    added = jobs.add_evidence(job["id"], {"id": "ev_000004", "topic": "Error message", "stage": "before"})

    assert replaced is True
    assert added is False
    assert [item["id"] for item in jobs.get(job["id"])["evidence"]] == ["ev_000003", "ev_000002", "ev_000004"]


def test_remove_evidence(jobs):
    job = jobs.create("fix_issue", "Fix", "agent-1", "user", issue="owner/proj#1")
    jobs.add_evidence(job["id"], {"id": "ev_000001", "topic": "Help output", "stage": "before"})

    assert jobs.remove_evidence(job["id"], ["ev_000001", "ev_999999"]) == ["ev_000001"]
    assert jobs.remove_evidence(job["id"], ["ev_000001"]) == []
    assert jobs.get(job["id"])["evidence"] == []


def test_timeline_entry_with_its_step(jobs):
    job = jobs.create("fix_issue", "Fix", "agent-1", "user", issue="owner/proj#1")

    jobs.add_timeline(job["id"], "step", "Found the cause", step="fix")
    jobs.add_timeline(job["id"], "notice", "Someone else was assigned")

    timeline = jobs.get(job["id"])["timeline"]
    assert [entry["kind"] for entry in timeline] == ["created", "step", "notice"]
    assert timeline[1]["step"] == "fix"
    assert "step" not in timeline[2]


def test_deleted_agent_cancels_only_its_open_jobs(jobs):
    open_job = jobs.create("fix_issue", "Open", "agent-1", "user", issue="owner/proj#1")
    done_job = jobs.create("fix_issue", "Done", "agent-1", "user", issue="owner/proj#2")
    jobs.update(done_job["id"], status="done")
    other = jobs.create("fix_issue", "Someone else's", "agent-2", "user", issue="owner/proj#3")

    jobs.delete_for_agent("agent-1")

    assert jobs.get(open_job["id"])["status"] == "cancelled"
    assert jobs.get(done_job["id"])["status"] == "done"
    assert jobs.get(other["id"])["status"] == "queued"


def test_renamed_vm_keeps_when_the_job_last_changed(jobs):
    job = jobs.create("fix_issue", "Fix", "agent-1", "user", issue="owner/proj#1", vm="vm1")

    jobs.rename_vm("vm1", "builder")

    renamed = jobs.get(job["id"])
    assert renamed["vm"] == "builder"
    assert renamed["updated_at"] == job["updated_at"]


def test_job_from_before_progress_loads_with_it(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_module, "DATA_DIR", tmp_path)
    (tmp_path / "jobs").mkdir()
    old = {"id": "job_0ld001", "kind": "follow_up", "title": "Answer", "agent": "agent-1", "issue": None, "repo": "owner/proj",
           "vm": None, "status": "done", "instructions": "", "notes": "", "drafts": [], "created_by": "user",
           "created_at": "2026-10-01T00:00:00+00:00", "updated_at": "2026-10-01T00:00:00+00:00"}
    (tmp_path / "jobs" / "job_0ld001.json").write_text(json.dumps(old))

    job = Jobs().get("job_0ld001")

    assert job["steps"] == STEPS["follow_up"]
    assert job["step"] is None
    assert job["evidence"] == []
    assert job["tests"] == {"before": None, "after": None}
    assert job["thread"] is None
    assert job["timeline"] == []
    assert job["skip_checks"] is False
