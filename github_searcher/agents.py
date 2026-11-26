"""All agents: their worker loops, and the rules that tie them to jobs, the VM queue and the Inbox.

Each agent (agent/agent.py) is one Claude conversation with a record on disk,
DATA_DIR/agents/<id>.json:

    {"id": "agent_a1b2c3", "name": "agent-1", "target_vm": "vm1" | null, "claude_session_id",
     "history": [HistoryEntry, ...], "context_used", "context_max", "cost_usd", "compactions", "tokens_used", "created_at",
     "pending": [message, ...], "awake": bool, "archived_at": null | when it was archived,
     "name_by": "auto" | "user" | "agent", "priority": bool,
     "role": "reviewer" | "closed_prs" | null, "reviews": "owner/name" (a reviewer's repo, give_review)}

name_by says who gave the name. Every agent is called "agent-N", the first free number (auto): agents don't name
themselves, and the app gives its own agents (reviewers, the ones it assigns issues to) no names either. Only the user renames
one (user). Agents from before that were named for their work got the next free number once, by age (numbered).

Any agent can be archived: it stops, its open jobs are cancelled and it leaves every VM queue, but its
conversation stays, so it can pick up where it left off (an update on its PR). The app's messages to an
archived agent wait without waking it; a message from the user, a job given to it, or a reply to one of
its drafts brings it back (unarchive), and those messages go in then. An agent that made PRs (a PR draft
that waits for the user or was approved: Inbox.pr_owners) can't be deleted, only archived.
The app archives an agent itself once its work is over (keep_going): no open job, message, waiting draft, run or VM
place. Reviewers and the closed PRs agent (below) stay. When a PR or issue is merged or closed, its agent's open jobs
on it are cancelled and it is archived (follow_up), and it never comes back for it: what happens there afterwards goes
to one agent for all of them (role "closed_prs").

Every agent has a worker (an asyncio task) that waits for messages, joins the waiting ones into
one prompt, each starting with [User] (the user typed it) or [System] (the app: a new job, a VM
that is its turn now, the user's decision on a draft, a reminder), and runs one turn with them.
Each turn is a Claude Code process of its own, closed when the turn ends (the next one resumes the conversation), and
at most MAX_AGENTS_AT_ONCE agents are in a turn at once: the others wait for one to end.
A message sent while the agent works waits in a queue (the chat shows it as pending; MAX_QUEUED of
the user's at most). Each of the user's messages gets a turn of its own, in order, together with the
app's messages that came before it; interrupting a turn (Esc in the chat) starts the next one. The user can take
one of their queued messages out before it goes in (cancel_queued); the agent list carries their texts (queued).
A message from the user while the agent is in the middle of a job (status working) is not a stop: its turn's prompt
also says to answer, take it in, and carry on with the job in that same turn, unless the user said to stop or change
course. Only interrupting with nothing queued stops the agent until the user writes again.
When the user fills in empty env variables an agent added for a secret (env_var_add), that agent is told
(secrets_filled, from the env endpoints in backend/vms_api.py), so it never asks for them in the Inbox.
Waiting messages are saved with the record, so a backend restart (it reloads on every code
change) doesn't lose them. An agent with messages waiting is woken with them after the restart (not an archived one);
one cut off in the middle of a turn gets one more saying so, when it has a job queued or working.

After each turn the worker enforces the VM rule: an agent never holds a VM it has nothing to do in.
- Holding a VM with no queued or working job for it: the VM is released for it, and what it left going on its desktop is
  stopped first (VM.clean_up, as by its release_vm).
- Holding one while its run goes there (a test suite or build it left going, sandbox/agent/long_runs.py): it keeps
  its desktop and sleeps; watch_runs wakes it when the run ends. An agent never gives up its desktop while it has work
  there: nobody steps aside. Only the user (Take over, Give, Remove) or a full VM (watch_room, below) takes it.
- Holding one with open jobs there: it is reminded to go on with them now, not to wait for an answer in chat. After
  MAX_NUDGES reminders in a row with no change to its jobs, the reminders stop; it keeps the desktop.
- In no queue but with queued jobs for a VM: it is reminded to queue_for_vm (MAX_NUDGES times at most).
An agent with open work never just stops: every HEARTBEAT_CHECK_SECONDS (keep_going), one with a job queued or working
that has been out of its turn for HEARTBEAT_SECONDS is told to carry on, whatever ended it (a turn that failed,
reminders that ran out, a VM released for it, a backend restart, a blocker it reported). Only a real wait is left alone:
its place in a VM's line (the grant wakes it), waiting for a VM while none takes agents (below), a run of its going (watch_runs wakes it), the user (waiting_on_user, a
draft of the job still waiting with its reviewer or in the Inbox whatever the job's status says, or the user stopped it),
or being archived. How long it has been out: since the newest entry in its history with a time
(its turn's end, an error, a message), so restarts don't put it off.
A blocker waiting for the user on the Blockers page (ask_approval) is tried again by its agent every
BLOCKER_RETRY_SECONDS (keep_going): what held the job up may have gone away by itself (the agreement shows signed). Then
the agent takes it back (clear_blocker, "cleared") and goes on, and the user never has to look at it.
A VM steps down when it runs out of room (watch_room, every ROOM_CHECK_SECONDS, from the VM's free memory and free
disk; the CPU load holds nobody back). Full (less than ROOM_MEMORY_PERCENT of its memory free, or less than ROOM_DISK_GB
of its disk free), it takes nobody new (VMQueue.full, with why): agents wait in its line instead
of getting a free desktop or adding one, and are told why. When its disk runs low, the agents holding its desktops are
told once to free what they can in their own homes (the folders of jobs that are over, caches).
The app also clears agents' leftovers itself (clean_disks, every CLEAN_SECONDS), so it never rests on agents remembering:
clones of repos nobody works on anymore, and with the disk low, download caches and Docker's unused images.
An agent is never stuck on one VM: one waiting in a VM's line for any desktop, with nothing of its jobs set up there,
goes to another running VM with a desktop free and nobody waiting (watch_room; queue_for_vm does the same when it
queues for a VM that is off, gone, full or has every desktop taken). One whose project is set up there stays: setting it
up again costs downloads and builds.
When no VM takes agents at all (none running, or each suspended or shutting down), an agent that needs one waits for
one (waiting_for_vm: from queue_for_vm, or taken out of a suspended or shutting-down VM's line) instead of trying them,
and the Dashboard shows it waiting. keep_going wakes it once a VM takes agents again.
A VM the user shuts down gracefully (graceful_shutdown, sandbox/vms.py) takes nobody new: the agents holding its desktops
finish (none is taken back), whoever still waits for it is sent to pick another VM, and once nobody holds a desktop and
no run goes, watch_room shuts it down. A VM the user suspended (suspended, sandbox/vms.py) is the same, but stays on.
Overloaded (less than OVERLOAD_MEMORY_PERCENT of its memory free), it also takes one desktop back from its agent, at most every STEP_DOWN_SECONDS, and removes that desktop
(VMQueue.step_down): the agent goes to the front of the line asking for it (behind the work that goes first, below),
and nothing it runs is stopped (its runs, servers and files stay). Never an agent the user gave priority; one on a pull
request that needs action only when nobody else is left, one reviewing a PR draft only when nobody else but those is;
one out of its turn first, then the highest desktop.
With room again, whoever waits gets a free desktop, or the desktop they wait for is added back (one that was taken
back, or a new one for an agent that asked for none), one a check, up to the VM's max desktops.
A desktop nobody needs anymore (nobody holds it or has a run on it) shuts down right away (watch_desktops, within
DESKTOP_CHECK_SECONDS or two), so its session and browser give their memory and CPU back. Not while agents wait for the
VM: it goes to them. The VM keeps one desktop (its lowest, when none is in use). Its home stays, and queue_for_vm adds
it again when an agent asks for it (or adds a new one when none is free, as long as memory allows, up to the VM's max
desktops).
The VM queue (sandbox/vm_queue.py: one line per desktop of each VM, and agents on different desktops work at
the same time) tells Agents when an agent's turn comes (on_grant: a message
that wakes it, with the user's GitHub name and noreply address to commit with, then the VM's notes on what earlier agents
set up in it for its jobs' repos and the whole VM (the other repos only by name, however many notes the VM has), or the VM
passes on at once
if it has no open jobs there anymore) and when the
user took the VM or its place away (on_kick: it is interrupted, and what it still ran in that
VM is killed, except its runs).

Runs nobody waits for anymore (the agent's turn ended, or the backend restarted) are checked every
RUN_CHECK_SECONDS (watch_runs). When one ends, its agent gets the result (bash: ComputerTools.bash_result; tests:
WorkTools.finish_tests, which keeps it on the job). An agent waiting in that VM's line (its desktop was taken back)
gets it together with the message that a desktop is its again; any other agent right away. Archiving or deleting an agent stops its runs.

The user's side: assign() turns an issue into a fix_issue job for an agent (the backend picks the issues and calls it,
backend/issues_api.py). decide() passes the user's decision on a draft back to its agent (with the link,
when Approve sent it to GitHub, or pushed a new version onto the user's PR). When the user edited the draft
before deciding, the agent also gets the final text, so it learns how they want it written.

The GitHub tab's side: follow_up() is called when someone else wrote on a PR or issue of the user's that an
agent follows (agent mode Drafts), or the PR's checks failed (pr_tracking.needs_reply). The agent gets a
follow_up job for that thread (an open one it has for it hears the news instead; an open job whose next version of
that PR waits hears it, whoever's it is, so only one agent works on a PR at a time), and an archived agent comes
back for it. It reads the thread and suggests a reply (draft_comment), a new version of the user's own PR made
on that PR's branch (draft_pr with pr: Approve pushes it there and posts its text on the PR as a comment), or
nothing (it marks the job done). It never posts anything itself. It answers only the project's maintainers and the
PR's reviewers (anyone else, a bot too, only when the merge needs it), in one comment of ours per round
(agent/work_tools.py).
A merged or closed thread's news never goes to its agent (archived then, above). It goes to the closed PRs agent as a
follow_up job: the end alone is only noted on a job marked done; when someone wrote there, it reads it and does nothing,
replies (draft_comment), opens an issue for more work, which a new agent takes (open_issue), or reopens a PR we closed
ourselves (reopen_pr, which lets it reopen any agent's). It never works in a VM.

Every PR draft is reviewed before it reaches the Inbox: give_review() hands each to its repo's own reviewer (record
"role": "reviewer", "reviews": the repo, made the first time), which checks it the way the repo's maintainers will,
every point asked and the edge cases of its kind, on the author's desktop, so they don't find what was missed one
review round at a time. review_finished() takes its verdict (agent/review_tools.py review_done): passed, the draft
shows in the Inbox; changes, it goes back to its author.

Agents of features the app no longer has (a repository's Live agent: record "repo" and "live"; a project's chat agent,
workers and reviewer: "project"; the Workflow tab's: "workflow" and "workflow_role") are archived by start() and lose
those fields, and open jobs of kinds it no longer makes (set_up_repo, reproduce_paper) are cancelled.

When an issue an agent has a job for goes from free to assigned (someone else is on it now: the
tags say so, backend/issues_api.py), issue_taken() tells the agent who has it (the assignees' logins, or else the
tags' reason), once per job, and puts that on the job's timeline. When someone else's open pull request comes to be
tied to it (it says it closes it, or only mentions it: the tags' open_prs), the agent hears of it at once, once for
each, also when the issue stays free or the user's claim went out, and reads it to decide. The user isn't asked: the agent finds out who that is
(read_issue shows each person's role, search_issues their merged PRs there) and stops, cancelling its job with a note
on who took it, for a maintainer, a member or someone who often gets PRs merged there; for a new, unknown or bot-like
account it goes on.

When the issue of a job whose PR hasn't gone out yet is fixed on GitHub (its tags say a merged pull request or a commit
on the default branch already does it) or closed, issue_fixed() tells the agent at once, once per job, and it reads it
before any more long runs: openclaw's maintainers fix many issues on main themselves within hours of them being opened,
and an agent that only finds out at its draft has spent those hours on checks.

Some repos ask contributors to claim an issue before they start: be assigned to it, often with a "/claim" comment.
There a fix_issue job's agent drafts that claim first (its one comment, WorkTools.draft_comment) and goes straight on
with the fix: neither the user's approval nor the maintainers' answer holds the job up (we assume nobody answers), so
the user finds the claim and the PR in the Inbox, to approve in that order. issue_taken() leaves the job alone when the
issue is assigned to the user (their claim went through); someone else assigned is taken, as for any job.

The user can give an agent priority (set_priority, the Give priority button on its page) until its tasks are over: no
open job, no run going and no turn (watch_runs then takes it back by itself). It joins a VM's waiting line ahead of
everyone without priority (VMQueue.prioritized), and in the VM its runs and the desktops it holds or runs on get ten
times the CPU share and its runs are ended last when memory runs out (long_runs.prioritize, set again by watch_runs
whenever that changes).

Agents work on the Issues board in its order: Needs action, then Review, then In progress and Catalog. The agents on a
pull request of the user's that needs action get priority like the user's (set_pr_priority); the agents reviewing a PR
draft (a review job queued or working, set_review_priority) come next in a VM's waiting line (VMQueue.reviewing), and
the rest after them. Both are worked out again by backend/github_api.py every few seconds.

Everything here runs in the backend's event loop. notify() and the queue callbacks may be called
from request threads, so they hand their work to the loop. version goes up on every change the
agent list shows (status, history, context, queue), for the live feed.

    agents = Agents(repos, issues, jobs, inbox, vms, queue, repo_signals, issue_tags, explore, artifacts, your_repositories, crashes)
    await agents.start()
    agents.assign("pallets/click#812", None, "vm1")
"""

import asyncio
import functools
import json
import os
import re
import secrets
import shlex
import shutil
import threading
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

from github_searcher import search, secret_vault
from github_searcher.agent.agent import AGENT_HOME, Agent
from github_searcher.agent.work_tools import WorkTools
from github_searcher.claude_models import BIG_REPO_MODEL, BIG_REPO_STARS, MODELS
from sandbox.agent import long_runs
from sandbox.agent.tools import ComputerTools
from sandbox.images import load_inventory
from sandbox.vms import FIX_VM, INCUS_DIR, VMsError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# override: the backend reloads itself on code changes, and .env changes should apply then too.
load_dotenv(PROJECT_ROOT / ".env", override=True)

DATA_DIR = PROJECT_ROOT / os.environ["DATA_DIR"]
# Reminders in a row, with no change to the agent's jobs or queue place, before the app stops reminding.
MAX_NUDGES = 2
# The user's messages that may wait for their turn at once.
MAX_QUEUED = 10
# Agents in a turn at the same time. Each turn is a Claude Code process of its own (about 150 MB), closed when the turn
# ends; the others wait for one to end, their messages kept (2026-11-21: a restart woke 270 at once, 42 GB).
MAX_AGENTS_AT_ONCE = 10
# While an agent works, its record is saved this often (and after every turn).
SAVE_SECONDS = 5
# How often the runs nobody waits for are checked.
RUN_CHECK_SECONDS = 10
# The heartbeat: an agent with open work out of its turn this long, for no reason, is told to carry on; looked this often.
HEARTBEAT_SECONDS = 10 * 60
HEARTBEAT_CHECK_SECONDS = 60
# A blocker waiting for the user is tried again by its agent this often (keep_going).
BLOCKER_RETRY_SECONDS = 60 * 60
# How often each running VM's free memory and free disk are read (watch_room). Full: less than ROOM_MEMORY_PERCENT of
# its memory free, or less than ROOM_DISK_GB of its disk free (a fresh clone and build of a big project, or a long test
# run's files, need about that). Overloaded: less than OVERLOAD_MEMORY_PERCENT of its memory free; then a desktop is taken
# back from its agent, at most every STEP_DOWN_SECONDS, so the memory has time to show it. The CPU load counts for
# neither: agents add desktops as long as memory allows, up to the VM's max desktops.
ROOM_CHECK_SECONDS = 60
ROOM_MEMORY_PERCENT = 20
ROOM_DISK_GB = 20
OVERLOAD_MEMORY_PERCENT = 10
STEP_DOWN_SECONDS = 15 * 60
# How often the desktops nobody needs anymore are looked for (watch_desktops): they shut down right away.
DESKTOP_CHECK_SECONDS = 5
# How often the app clears agents' leftovers off each running VM's disk (clean_disks): a clone nobody touched for
# CLEAN_UNTOUCHED_DAYS, of a repo with no open job or PR. With less than CLEAN_LOW_DISK_PERCENT of the disk free, also
# Docker's unused images (not the ones its image came with), volumes and build cache, and these download caches in each
# home: all fill again by themselves.
CLEAN_SECONDS = 10 * 60
CLEAN_UNTOUCHED_DAYS = 2
CLEAN_LOW_DISK_PERCENT = 15
# Run after a clear: what it freed in the VM goes back to this computer's disk too.
CLEAN_TRIM = "fstrim -a || true"
CLEAN_CACHES = [
    ".cache/pip", ".cache/uv", ".npm/_cacache", ".local/share/pnpm/store", ".cache/go-build", ".cargo/registry/cache",
    ".cache/yarn", ".bun/install/cache", ".gradle/caches", ".m2/repository",
]
# Run as root in a VM (clean_disks): its disk in all and free (kB), each desktop's home ("home", its desktop, the folder),
# then each git clone at the top of a home ("clone", its desktop, the folder, when its .git last changed in seconds since
# 1970, its origin URL). Desktop 1's user is the image's own (uid 1000), desktop n's is desktopn.
CLEAN_LIST_SCRIPT = r"""
df -Pk /home | awk 'NR == 2 {print "disk", $2, $4}'
one=$(getent passwd 1000 | cut -d: -f6)
for home in /home/*; do
    number=""
    [ "$home" = "$one" ] && number=1
    case "$home" in /home/desktop[0-9]*) number=${home#/home/desktop} ;; esac
    [ -n "$number" ] || continue
    printf 'home\t%s\t%s\n' "$number" "$home"
    for dir in "$home"/*/; do
        dir=${dir%/}
        [ -e "$dir/.git" ] || continue
        url=$(git -c safe.directory='*' -C "$dir" remote get-url origin 2> /dev/null) || continue
        printf 'clone\t%s\t%s\t%s\t%s\n' "$number" "$dir" "$(stat -c %Y "$dir/.git")" "$url"
    done
done
"""
# Run as root in a VM with its disk low (clean_disks), after protected= (the Docker images its image came with, by
# space). docker rmi without -f leaves an image any container uses, running or stopped.
CLEAN_DOCKER_SCRIPT = r"""
command -v docker > /dev/null || exit 0
for image in $(docker image ls --format '{{.Repository}}:{{.Tag}}'); do
    case " $protected " in *" $image "*) continue ;; esac
    docker rmi "$image" > /dev/null 2>&1
done
docker image prune -f > /dev/null 2>&1
docker volume prune -f > /dev/null 2>&1
docker builder prune -af > /dev/null 2>&1
true
"""
# How often an agent's time on a VM is added to its job (count_vm_time): every desktop holder working on a job gets
# this much more.
VM_TIME_SECONDS = 30
OPEN_STATUSES = ["queued", "working"]
# The record fields of agents of features the app no longer has (a repository's Live agent, a project's agents, the
# Workflow tab's): start() archives an agent that has any of them, and takes them off.
GONE_FIELDS = ["repo", "live", "project", "workflow", "workflow_role"]
# Kinds of job the app no longer makes (setting a repo up, reproducing a paper): start() cancels the open ones.
GONE_KINDS = ["set_up_repo", "reproduce_paper"]
# What an agent does when its job's issue was assigned to someone else (issue_taken): it decides itself,
# the user isn't asked.
TAKEN_ADVICE = (
    " Decide yourself whether to go on; the user isn't asked. Find out who that is: read_issue shows the assignees and "
    "each person's role (OWNER, MEMBER and COLLABORATOR are the project's own people; CONTRIBUTOR, FIRST_TIME_CONTRIBUTOR, "
    "NONE and BOT are not), and search_issues how often their PRs get merged there (`repo:{repo} is:pr is:merged "
    "author:LOGIN`). A maintainer, a member, or someone who often gets PRs merged there: stop. Cancel {job} with "
    "job_update (status cancelled) and a note in plain words on who took it and why you stopped, then go on with your "
    "other jobs. A new, unknown or bot-like account: keep going, and say why with job_progress. When it is someone else's "
    "open PR that closes it, stop whoever they are: close_issue with the PR's link, since nobody wants a second fix."
)
# What an agent does when someone else's open pull request came to be tied to its job's issue (issue_taken with prs: it
# says it closes it, or only mentions it): it reads it and decides, before any more long runs.
PR_ADVICE = (
    " This comes before everything else, also before a run of yours that is going: read_issue the issue and that pull "
    "request now. When it is a fix for this issue (it says it closes it, or makes the same change), someone else is on it: "
    "stop {job} whoever they are (run_stop what you run for it, then close_issue with the PR's link), since nobody wants "
    "a second fix. When it only mentions the issue for something else, keep going, and say why with job_progress."
)
# The same news about an issue we opened ourselves (as the user): we never give one of those up.
OURS_ADVICE = (
    " It is an issue we opened ourselves, as the user, and we never give one of those up: keep going with {job} whoever "
    "it is, and say so with job_progress. Don't cancel it or close the issue."
)
# What an agent does when its job's issue was fixed or closed on GitHub before our PR went out (issue_fixed): it reads it
# and decides, before any more long runs.
FIXED_ADVICE = (
    " This comes before everything else, also before a run of yours that is going: read_issue it now. When a merged pull "
    "request or a commit on the default branch already does what it asks, or the maintainers closed it, nothing is left "
    "for us: stop {job} (run_stop what you run for it, then close_issue with the link that shows it). When it isn't so "
    "(it was reopened, or that fix doesn't cover what it asks), keep going, and say why with job_progress."
)


class Agents:
    def __init__(self, repos, issues, jobs, inbox, vms, queue, repo_signals, issue_tags, explore, artifacts, your_repositories, crashes):
        self.repos = repos
        # The app's own errors (crashes.py): a turn that fails with an exception is one.
        self.crashes = crashes
        # What went wrong in how the app made agents work, as they report it (problems.py): backend/shared.py puts it here.
        self.problems = None
        # The user's repositories and GitHub account, read with their sign-in: their login and noreply address.
        self.your_repositories = your_repositories
        # Each agent's own folder (github_searcher/artifacts.py). A change in one shows in the agent list (artifacts_stamp).
        self.artifacts = artifacts
        artifacts.on_change = self.changed
        self.issues = issues
        # Each repo's signals (check_activity works them out the same way): its AI policy decides where agents work.
        self.repo_signals = repo_signals
        # Each issue's tags (free or assigned, merge, kind) and Explore: nothing here reads them any more, they are kept
        # for whoever reads them through agents.
        self.issue_tags = issue_tags
        self.explore = explore
        self.jobs = jobs
        self.inbox = inbox
        self.vms = vms
        self.queue = queue
        self.folder = DATA_DIR / "agents"
        self.version = 0
        # Each agent's todo progress as summaries() last worked it out: (its history's length then, done, total).
        self.todo_progress = {}
        # By repo in lower case, its column on the Repositories page and the model that column's settings pick (only
        # where it isn't Default), worked out every round by backend/issues_api.py take_from_catalog; repo_models is None
        # until the first round.
        self.repo_columns = {}
        self.repo_models = None
        self.agents: dict[str, Agent] = {}
        # Messages for each agent's next turn: {"from": "User" | "System", "text", "shown"}.
        # shown: already in the history (a kick), so it isn't added again when it is sent.
        self.pending: dict[str, list] = {}
        self.wake: dict[str, asyncio.Event] = {}
        self.workers: dict[str, asyncio.Task] = {}
        # A place for each agent in a turn: MAX_AGENTS_AT_ONCE at most, the others wait in work().
        self.turns = asyncio.Semaphore(MAX_AGENTS_AT_ONCE)
        # VM rule reminders in a row: {"count", "state"}; state is what the jobs and queue place
        # looked like, and a change in it starts the count again.
        self.nudges: dict[str, dict] = {}
        # What long_runs.prioritize last set in each running VM (its runs and desktops, each with or without priority),
        # so it runs again only when that changed. Not saved: after a restart it is set once more.
        self.priority_set: dict[str, list] = {}
        # The agents with priority because they work on a pull request of the user's that needs action (set_pr_priority).
        # Not saved: the backend works it out again a moment after a restart.
        self.pr_priority: set[str] = set()
        # The running VMs whose disk is low (watch_room), whose holders were told to free room. Not saved: after a restart
        # they are told once more.
        self.disk_low: set[str] = set()
        # The agents waiting for a VM because none takes agents (module docstring), woken by keep_going once one does. Not
        # saved: after a restart the heartbeat wakes them, and queue_for_vm puts them back.
        self.waiting_for_vm: set[str] = set()
        self.loop = None
        self.loop_thread = None
        self.saver = None
        self.run_watcher = None
        self.heartbeat = None
        self.room_watcher = None
        self.desktop_watcher = None
        self.disk_cleaner = None
        self.vm_timer = None
        queue.on_grant = self.on_grant
        queue.on_kick = self.on_kick
        # Every place in a queue shows in the agent list.
        queue.on_change = self.changed

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.loop_thread = threading.get_ident()
        self.folder.mkdir(parents=True, exist_ok=True)
        # "*.json" leaves out a "*.json.tmp" a crash may have left behind.
        for path in sorted(self.folder.glob("*.json")):
            record = json.loads(path.read_text())
            # Agents from before compactions and tokens were counted: the compactions from the history, the tokens from
            # Claude Code's own file of the conversation it has now (each reply once: its blocks come in lines of their
            # own, each with the reply's usage).
            if "compactions" not in record:
                record["compactions"] = len([entry for entry in record["history"] if entry["type"] == "system" and entry["text"] == "Context compacted"])
            if "tokens_used" not in record:
                transcript = Path.home() / ".claude" / "projects" / re.sub(r"[^a-zA-Z0-9]", "-", str(AGENT_HOME)) / f"{record['claude_session_id']}.jsonl"
                lines = transcript.read_text().splitlines() if record["claude_session_id"] is not None and transcript.exists() else []
                replies = {}
                for line in lines:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    message = entry.get("message")
                    if entry.get("type") != "assistant" or not isinstance(message, dict) or not message.get("usage"):
                        continue
                    usage = message["usage"]
                    replies[message.get("id")] = (
                        (usage.get("input_tokens") or 0)
                        + (usage.get("cache_creation_input_tokens") or 0)
                        + (usage.get("cache_read_input_tokens") or 0)
                        + (usage.get("output_tokens") or 0)
                    )
                record["tokens_used"] = sum(replies.values())
            # partial, not a lambda: the target VM is read from this record each time, not from the loop variable.
            computer_tools = ComputerTools(self.vms, self.queue, record["id"], functools.partial(record.get, "target_vm"), record["history"])
            agent = Agent(record, computer_tools, WorkTools(self, record), self.changed)
            self.agents[agent.id] = agent
            # Messages that waited when the backend stopped: it wakes for them, as it would have without the restart (a
            # message always wakes an agent that isn't archived). Not by "awake": a turn that failed while the backend
            # stopped saved it as False, and the agent never woke again (agent-89).
            self.pending[agent.id] = record.get("pending", [])
            self.wake[agent.id] = asyncio.Event()
            # Agents from before archiving, and from before name_by (an "agent-N" name was the automatic one).
            record.setdefault("archived_at", None)
            record.setdefault("name_by", "auto" if re.fullmatch(r"agent-\d+", record["name"]) else "user")
            # And from before reviewers.
            record.setdefault("role", None)
            # And from before priority.
            record.setdefault("priority", False)
            if record["priority"]:
                self.queue.prioritized.add(record["id"])
            if self.pending[agent.id] and record["archived_at"] is None:
                self.wake[agent.id].set()
            self.nudges[agent.id] = {"count": 0, "state": None}
            self.workers[agent.id] = asyncio.create_task(self.work(agent))

        # Every agent is called agent-N: older ones named for their work (by themselves or the app) get the next free
        # number, oldest first, once.
        names = [agent.name for agent in self.agents.values()]
        for agent in sorted(self.agents.values(), key=lambda each: each.record.get("created_at", "")):
            if agent.record.get("numbered"):
                continue
            if not re.fullmatch(r"agent-\d+", agent.name):
                number = 1
                while f"agent-{number}" in names:
                    number += 1
                agent.name = f"agent-{number}"
                agent.record["name"] = agent.name
                agent.record["name_by"] = "auto"
                names.append(agent.name)
            agent.record["numbered"] = True
            self.save(agent)

        # The queues are saved with the VMs: take out agents whose record is gone.
        for vm_record in self.vms.list():
            waiting = list(vm_record.queue)
            for line in vm_record.desktops.values():
                waiting.append(line["holder"])
            for agent_id in waiting:
                if agent_id is None or agent_id == "user" or agent_id in self.agents:
                    continue
                self.queue.leave_all(agent_id)

        # Agents of features the app no longer has (GONE_FIELDS): archived, so they stop and leave every VM queue (their
        # open jobs are cancelled), and the fields are taken off, so one the user brings back is a plain agent.
        for agent in list(self.agents.values()):
            gone = [field for field in GONE_FIELDS if agent.record.get(field) is not None]
            for field in GONE_FIELDS:
                agent.record.pop(field, None)
            if not gone:
                continue
            # A project's worker or reviewer had a role too; a repo's own reviewer ("reviews") never has these fields.
            agent.record["role"] = None
            await self.archive(agent.id)
            self.save(agent)

        # Open jobs of kinds the app no longer makes (GONE_KINDS): cancelled. Their agents hear it with their next turn.
        for job in self.jobs.list():
            if job["kind"] not in GONE_KINDS or job["status"] in ["done", "cancelled"]:
                continue
            self.jobs.update(job["id"], status="cancelled")
            self.jobs.add_timeline(job["id"], "status", "Cancelled: the app no longer does this kind of job")
            if job["agent"] in self.agents:
                text = f"{job['id']} ({job['title']}) is cancelled: the app no longer does this kind of job. Do nothing more for it."
                self.pending[job["agent"]].append({"from": "System", "text": text, "shown": False})
                self.save(self.agents[job["agent"]])

        # A VM an agent held when the backend stopped is still its own: it carries on.
        for agent_id in self.agents:
            vm_name, place = self.queue.place(agent_id)
            if place != 0:
                continue
            self.notify(agent_id, f"The backend restarted; you still hold {vm_name}. Check where your jobs for it stand (my_jobs), finish them, then release_vm.")

        # No tool call waits for a run anymore after a restart: they are all collected by watch_runs now.
        self.queue.to_background()
        self.saver = asyncio.create_task(self.autosave())
        self.run_watcher = asyncio.create_task(self.watch_runs())
        self.heartbeat = asyncio.create_task(self.keep_going())
        self.room_watcher = asyncio.create_task(self.watch_room())
        self.desktop_watcher = asyncio.create_task(self.watch_desktops())
        self.disk_cleaner = asyncio.create_task(self.clean_disks())
        self.vm_timer = asyncio.create_task(self.count_vm_time())

    async def stop(self) -> None:
        if self.saver is not None:
            self.saver.cancel()
        if self.run_watcher is not None:
            self.run_watcher.cancel()
        if self.heartbeat is not None:
            self.heartbeat.cancel()
        if self.room_watcher is not None:
            self.room_watcher.cancel()
        if self.desktop_watcher is not None:
            self.desktop_watcher.cancel()
        if self.disk_cleaner is not None:
            self.disk_cleaner.cancel()
        if self.vm_timer is not None:
            self.vm_timer.cancel()
        for worker in self.workers.values():
            worker.cancel()
        for agent in self.agents.values():
            # Its turn is cut off here: after the restart it is woken with this (start()), when it has open work. One with
            # none was only looking (2026-11-21: 260 of those, woken again on every restart, all at once).
            open_jobs = [job for job in self.jobs.for_agent(agent.id) if job["status"] in OPEN_STATUSES]
            if agent.busy and open_jobs:
                text = "The backend restarted in the middle of your turn; check my_jobs and carry on."
                # Its runs go on in the VM through a restart (long_runs.py), but a log file of its own may still be empty
                # then: it is told, so it doesn't take them for lost and start them again (reticle#1525).
                runs = []
                for vm_record in self.vms.list():
                    for run in vm_record.runs:
                        if run["agent"] == agent.id:
                            runs.append(f"{run['id']} in {vm_record.name} (`{run['label'][:120]}`)")
                if runs:
                    text += (
                        " A restart doesn't stop your runs: these go on in the VM until they end, and you get each one's result "
                        "in a message then (a file it writes may stay empty until it ends), so don't start them again: "
                        + "; ".join(runs) + "."
                    )
                self.pending[agent.id].insert(0, {"from": "System", "text": text, "shown": False})
            self.save(agent)
            await agent.stop()

    def changed(self) -> None:
        self.version += 1

    def save(self, agent: Agent) -> None:
        record = agent.record
        record["claude_session_id"] = agent.session_id
        record["context_used"] = agent.context_used
        record["context_max"] = agent.context_max
        record["cost_usd"] = agent.cost_usd
        record["compactions"] = agent.compactions
        record["tokens_used"] = agent.tokens_used
        record["pending"] = self.pending[agent.id]
        record["awake"] = agent.busy or self.wake[agent.id].is_set()
        # Write, then rename: a crash never leaves half a record.
        temporary = self.folder / f"{agent.id}.json.tmp"
        temporary.write_text(json.dumps(record))
        temporary.replace(self.folder / f"{agent.id}.json")

    async def autosave(self) -> None:
        while True:
            await asyncio.sleep(SAVE_SECONDS)
            for agent in list(self.agents.values()):
                if agent.busy:
                    self.save(agent)

    async def work(self, agent: Agent) -> None:
        """The agent's worker: wait for messages, run a turn with them, then apply the VM rule."""
        while True:
            await self.wake[agent.id].wait()
            # Its place among the agents in a turn (MAX_AGENTS_AT_ONCE): it waits here for one, its messages kept. Given
            # back in the finally below; nothing in between waits.
            await self.turns.acquire()
            self.wake[agent.id].clear()
            messages = self.pending[agent.id]
            # Archived while it waited: its messages wait for it to come back.
            if not messages or agent.record["archived_at"] is not None:
                self.turns.release()
                continue

            # "/compact" (the Compact button) is a command for Claude Code itself: it goes alone and as it is.
            batch = messages[:1]
            prompt = messages[0]["text"]
            if not prompt.startswith("/compact"):
                batch = []
                for message in messages:
                    if message["text"].startswith("/compact"):
                        break
                    batch.append(message)
                    # One of the user's messages per turn: the ones after it wait for the next turns.
                    if message["from"] == "User":
                        break
                prompt = "\n\n".join(f"[{message['from']}] {message['text']}" for message in batch)
                # The user wrote in the middle of a job (often stopping the turn to get it in): it answers, then goes on
                # with the job, unless they told it to stop or change course. Only in the prompt, not in the chat.
                working = [job for job in self.jobs.for_agent(agent.id) if job["status"] == "working"]
                if batch[-1]["from"] == "User" and working:
                    titles = ", ".join(f"{job['id']} ({job['title']})" for job in working)
                    prompt += (
                        f"\n\n[System] You are in the middle of {titles}. Answer the user and take in what they said, then "
                        "carry on with that work in this same turn, from where you were. Don't end your turn to ask whether "
                        "to go on, and don't release the VM to wait for their answer. Stop, wait or change course only when "
                        "they tell you to."
                    )
            self.pending[agent.id] = messages[len(batch):]
            if self.pending[agent.id]:
                self.wake[agent.id].set()

            now = datetime.now(UTC).isoformat()
            for message in batch:
                if message["shown"]:
                    continue
                kind = "user" if message["from"] == "User" else "system"
                agent.history.append({"type": kind, "text": message["text"], "time": now})
            agent.busy = True
            agent.last_event_at = now
            self.version += 1
            # The model (claude_models.py): by the job it works on, the one working, else the first still open. A reviewer
            # reviews. With no job it talks with you and keeps the model it has: switching re-reads the whole
            # conversation at full price, so the model only changes with a job.
            current = None
            for job in self.jobs.for_agent(agent.id):
                if job["status"] == "working" or (current is None and job["status"] in ["queued", "waiting_on_user", "waiting_on_maintainers"]):
                    current = job
            work = "chat"
            repo = None
            model = agent.model
            if current is not None:
                work = current["kind"] if current["kind"] in MODELS else "task"
                repo = current["repo"]
                model = MODELS[work]
            if agent.record["role"] == "reviewer":
                work = "review"
                repo = agent.record.get("reviews")
                model = MODELS["review"]
            # Fixing and following up in a big name's repository: the most capable model.
            stars = 0
            for item in self.repos.items():
                if repo is not None and item["full_name"].lower() == repo.lower():
                    stars = item["stars"]
            if work in ["fix_issue", "follow_up"] and stars >= BIG_REPO_STARS:
                model = BIG_REPO_MODEL
            # Over that, the Model of the repo's column on the Repositories page (repo_models), picked for the job's first
            # turn once the columns are worked out; the job keeps it, so a change there is for new jobs.
            if work in ["fix_issue", "follow_up"] and current.get("model"):
                model = current["model"]
            elif work in ["fix_issue", "follow_up"] and self.repo_models is not None:
                model = self.repo_models.get((repo or "").lower(), model)
                self.jobs.update(current["id"], model=model)
            agent.work = {"work": work, "job": current["id"] if current is not None else None, "repo": repo}
            # Its process starts with the turn (below), so it starts on this model.
            agent.model = model
            # Fresh GitHub answers every turn: an issue may have been taken or fixed since the last one.
            search.CACHE.clear()
            try:
                await agent.run(prompt)
            except Exception as error:
                agent.history.append({"type": "system", "text": f"Error: {error}", "time": datetime.now(UTC).isoformat()})
                self.crashes.add("agent", f"{agent.name}'s turn failed: {type(error).__name__}: {error}", traceback.format_exc())
            finally:
                # A desktop lock the agent set ends with its turn, also one that failed or was cancelled.
                agent.computer_tools.end_turn()
                self.turns.release()
                # Its Claude Code process ends with the turn, so an agent between turns takes no memory. The next turn
                # starts a new one, which resumes the conversation.
                await agent.stop()
            agent.busy = False
            self.save(agent)
            self.version += 1
            # Its turn stopped on the Claude token's usage limit and the next one, with no limit yet, is in use now
            # (secret_vault.py): carry on at once on it, not at the next heartbeat.
            in_use = secret_vault.CLAUDE_SETTINGS["in_use"]
            if agent.hit_limit and in_use != agent.claude_token and in_use not in secret_vault.CLAUDE_SETTINGS["limits"]:
                text = "Your last turn stopped on the Claude account's usage limit. Another account is in use now: carry on from where you left off."
                self.pending[agent.id].append({"from": "System", "text": text, "shown": False})
                self.wake[agent.id].set()
            # Runs it left going have no tool call waiting for them anymore: watch_runs collects them.
            self.queue.to_background(agent.id)

            # The VM rule. Reminders count again from 0 whenever its place in a queue or a job's status
            # changes. Not on new notes: rewriting them is not progress.
            vm_name, place = self.queue.place(agent.id)
            jobs = self.jobs.for_agent(agent.id)
            state = [vm_name, place] + [[job["id"], job["status"]] for job in jobs]
            nudge = self.nudges[agent.id]
            if state != nudge["state"]:
                nudge["count"] = 0
                nudge["state"] = state
            open_jobs = [job for job in jobs if job["status"] in OPEN_STATUSES]
            jobs_here = [job for job in open_jobs if vm_name is not None and job["vm"] == vm_name]
            titles = ", ".join(f"{job['id']} ({job['title']})" for job in jobs_here)

            if place == 0 and not jobs_here:
                # Before the desktop goes to the next one: stop what it left going there (VM.clean_up), unless a run of
                # its still goes there.
                try:
                    vm_record = self.vms.get(vm_name)
                except VMsError:
                    continue
                desktop = vm_record.desktop_of(agent.id)
                runs_here = [run for run in vm_record.runs if run.get("desktop", 1) == desktop]
                if not runs_here:
                    others = [number for number, line in vm_record.desktops.items() if number != desktop and line["holder"] is not None]
                    idle = not others and not vm_record.runs
                    await asyncio.to_thread(vm_record.desktop_vm(desktop).clean_up, idle)
                try:
                    self.queue.release(vm_name, agent.id)
                except (ValueError, VMsError):
                    # The user took it, or deleted the VM, in the meantime.
                    continue
                agent.history.append({"type": "system", "text": f"Released {vm_name}: no jobs left", "time": datetime.now(UTC).isoformat()})
                self.save(agent)
                self.version += 1
                continue
            # Interrupted by the user: it waits for them. More messages waiting: it goes on anyway.
            if agent.stopped or self.wake[agent.id].is_set():
                continue

            # Its run goes in the VM: it keeps its desktop and sleeps; watch_runs wakes it when the run ends.
            runs = []
            for vm_record in self.vms.list():
                if place == 0 and vm_record.name == vm_name:
                    runs = [run for run in vm_record.runs if run["agent"] == agent.id]
            if runs:
                continue
            # Reminded enough: it keeps the desktop anyway (the heartbeat wakes it later).
            if place == 0 and nudge["count"] >= MAX_NUDGES:
                continue
            if place == 0:
                nudge["count"] += 1
                text = (
                    f"You still hold {vm_name} and have open jobs: {titles}. Carry on with them now; don't wait for an answer "
                    "in chat. release_vm only when they are done, wait on a draft in the Inbox, or the user told you to stop."
                )
                self.pending[agent.id].append({"from": "System", "text": text, "shown": False})
                self.wake[agent.id].set()
                continue

            waiting = [job for job in open_jobs if job["status"] == "queued" and job["vm"] is not None]
            if place is not None or not waiting or nudge["count"] >= MAX_NUDGES or agent.id in self.waiting_for_vm:
                continue
            nudge["count"] += 1
            titles = ", ".join(f"{job['id']} ({job['title']})" for job in waiting)
            text = f"You have queued jobs for {waiting[0]['vm']}: {titles}. Use queue_for_vm when you are ready to work on them."
            self.pending[agent.id].append({"from": "System", "text": text, "shown": False})
            self.wake[agent.id].set()

    def summaries(self) -> list[dict]:
        summaries = []
        prs = self.inbox.pr_owners()
        vm_records = self.vms.list()
        for agent in sorted(self.agents.values(), key=lambda agent: agent.record["created_at"]):
            vm_name, place = self.queue.place(agent.id)
            status = "idle"
            if agent.busy:
                status = "working"
            if place is not None and place > 0:
                status = "in_queue"
            desktop = None
            for vm_record in vm_records:
                if vm_record.name == vm_name:
                    desktop = vm_record.desktop_of(agent.id)
            if place == 0:
                status = "using_vm"
            # The last thing it did, for the one-line activity column.
            recent = [entry for entry in agent.history[-50:] if entry["type"] in ["tool", "system"]]
            activity = ""
            if recent:
                activity = recent[-1].get("summary") or recent[-1].get("text") or ""
            # How far its todo list is, from the latest one it wrote (TodoWrite always sends the whole list).
            # Only the recent history: an old list doesn't matter anymore. This runs on every change, for every agent
            # ever made, so it is worked out again only when the agent's history grew (todo_progress).
            known = self.todo_progress.get(agent.id)
            if known is None or known[0] != len(agent.history):
                todo_done = 0
                todo_total = 0
                for entry in reversed(agent.history[-3000:]):
                    if entry["type"] != "tool" or entry["name"] != "TodoWrite":
                        continue
                    todos = entry["input"].get("todos")
                    if isinstance(todos, list):
                        todo_total = len(todos)
                        todo_done = len([todo for todo in todos if isinstance(todo, dict) and todo.get("status") == "completed"])
                    break
                self.todo_progress[agent.id] = (len(agent.history), todo_done, todo_total)
            todo_done = self.todo_progress[agent.id][1]
            todo_total = self.todo_progress[agent.id][2]
            summaries.append(
                {
                    "id": agent.id,
                    "name": agent.name,
                    "target_vm": agent.record["target_vm"],
                    "status": status,
                    "busy": agent.busy,
                    # Messages wait to wake it, out of its turn: it waits for a place among the agents in a turn
                    # (MAX_AGENTS_AT_ONCE), or is about to start.
                    "waiting": not agent.busy and self.wake[agent.id].is_set() and agent.record["archived_at"] is None,
                    # It needs a VM and none takes agents now: it waits for one (waiting_for_vm).
                    "waiting_for_vm": not agent.busy and agent.id in self.waiting_for_vm,
                    "vm": vm_name,
                    # The desktop of that VM it holds or asked for (None: it waits for any).
                    "desktop": desktop,
                    "place": place,
                    "context_used": agent.context_used,
                    "context_max": agent.context_max,
                    "cost_usd": agent.cost_usd,
                    "compactions": agent.compactions,
                    "tokens_used": agent.tokens_used,
                    "history_length": len(agent.history),
                    "pending": len([message for message in self.pending[agent.id] if message["from"] == "User"]),
                    "queued": [message["text"] for message in self.pending[agent.id] if message["from"] == "User"],
                    "activity": activity,
                    "last_event_at": agent.last_event_at,
                    # A tool call without its result yet: a command or the test suite is running, so a long quiet
                    # spell is that tool working (each has a time limit), not the agent being stuck.
                    "in_tool": agent.busy and len(agent.history) > 0 and agent.history[-1]["type"] == "tool",
                    "todo_done": todo_done,
                    "todo_total": todo_total,
                    "created_at": agent.record["created_at"],
                    "archived_at": agent.record["archived_at"],
                    # PR drafts that wait for the user or were approved: then it can only be archived, not deleted.
                    "prs": prs.get(agent.id, 0),
                    # Goes up on every change to its artifacts, so an open Artifacts tab reads its folder again.
                    "artifacts_stamp": self.artifacts.stamps.get(agent.id, 0),
                    # "reviewer" for a repo's reviewer (give_review), "closed_prs" for the closed PRs agent (follow_up),
                    # else None.
                    "role": agent.record["role"],
                    # The Claude model of its turn, or of its last one (claude_models.py, picked per job in work).
                    "model": agent.model,
                    # The user gave it priority until its tasks are over (set_priority).
                    "priority": agent.record["priority"],
                }
            )
        return summaries

    def create(self, name: str = "") -> dict:
        """A new agent with no target VM. Without a name it gets the first free "agent-N"."""
        names = [agent.name for agent in self.agents.values()]
        name = name.strip()
        name_by = "user" if name else "auto"
        if name in names:
            raise ValueError(f"There is already an agent named {name}")
        if not name:
            number = 1
            while f"agent-{number}" in names:
                number += 1
            name = f"agent-{number}"
        agent_id = "agent_" + secrets.token_hex(3)
        while agent_id in self.agents:
            agent_id = "agent_" + secrets.token_hex(3)

        record = {
            "id": agent_id,
            "name": name,
            "target_vm": None,
            "claude_session_id": None,
            "history": [],
            "context_used": 0,
            "context_max": 0,
            "cost_usd": 0.0,
            "compactions": 0,
            "tokens_used": 0,
            "created_at": datetime.now(UTC).isoformat(),
            "archived_at": None,
            "name_by": name_by,
            "numbered": True,
            "role": None,
            "priority": False,
        }
        computer_tools = ComputerTools(self.vms, self.queue, agent_id, functools.partial(record.get, "target_vm"), record["history"])
        agent = Agent(record, computer_tools, WorkTools(self, record), self.changed)
        self.agents[agent_id] = agent
        self.pending[agent_id] = []
        self.wake[agent_id] = asyncio.Event()
        self.nudges[agent_id] = {"count": 0, "state": None}
        self.workers[agent_id] = self.loop.create_task(self.work(agent))
        self.save(agent)
        self.version += 1
        created = dict(record)
        del created["history"]
        del created["pending"]
        del created["awake"]
        return created

    def rename(self, agent_id: str, new_name: str, by: str = "user") -> None:
        """The user (or the agent itself, by "agent") renamed the agent. Jobs, drafts and the VM queue know it by its
        id, so nothing else changes."""
        agent = self.agents[agent_id]
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("The name is empty")
        if new_name == agent.name:
            return
        if new_name in [other.name for other in self.agents.values()]:
            raise ValueError(f"There is already an agent named {new_name}")
        agent.name = new_name
        agent.record["name"] = new_name
        agent.record["name_by"] = by
        self.save(agent)
        self.version += 1

    def set_priority(self, agent_id: str, on: bool) -> None:
        """The user gives the agent priority (on) or takes it back. With it, the agent goes first: to the front of the
        VM's waiting line, and for the VM's CPU and memory (watch_runs). Only for an agent with tasks going (an open
        job, a run or a turn): it ends by itself once they are over (watch_runs)."""
        agent = self.agents[agent_id]
        if agent.record["priority"] == on:
            return
        text = "Priority taken back by the user"
        if on:
            open_jobs = [job for job in self.jobs.for_agent(agent_id) if job["status"] in OPEN_STATUSES]
            runs = []
            for vm_record in self.vms.list():
                runs += [run for run in vm_record.runs if run["agent"] == agent_id]
            if not open_jobs and not runs and not agent.busy:
                raise ValueError(f"{agent.name} has no tasks going (no open job, run or turn)")
            text = "Given priority by the user, until its tasks are over"
        agent.record["priority"] = on
        if on:
            self.queue.prioritized.add(agent_id)
        elif agent_id not in self.pr_priority:
            # Still on a pull request that needs action: it keeps that priority (set_pr_priority).
            self.queue.prioritized.discard(agent_id)
        # Waiting for a VM: to the front of the line now.
        vm_name, place = self.queue.place(agent_id)
        if on and place is not None and place > 0:
            try:
                self.queue.move_to_front(vm_name, agent_id)
            except (ValueError, VMsError):
                # It left the line meanwhile.
                pass
        agent.history.append({"type": "system", "text": text, "time": datetime.now(UTC).isoformat()})
        self.save(agent)
        self.version += 1

    def set_pr_priority(self, agent_ids: set[str]) -> None:
        """The agents working on a pull request of the user's that needs action now (backend/github_api.py, after every
        look at the pull requests): they get priority like the user's (VMQueue.prioritized: ahead in a VM's line, more
        CPU; an overloaded VM takes their desktop back only when nobody without priority is left), until their pull request no longer needs action or their job on it is over. An agent the
        user gave priority keeps it either way."""
        for agent_id in agent_ids:
            if agent_id not in self.agents or agent_id in self.pr_priority:
                continue
            self.pr_priority.add(agent_id)
            if agent_id in self.queue.prioritized:
                continue
            self.queue.prioritized.add(agent_id)
            # Waiting for a VM: ahead of everyone without priority now.
            vm_name, place = self.queue.place(agent_id)
            if place is not None and place > 0:
                try:
                    self.queue.move_up(vm_name, agent_id)
                except (ValueError, VMsError):
                    # It left the line meanwhile.
                    pass
            self.version += 1
        for agent_id in list(self.pr_priority):
            if agent_id in agent_ids:
                continue
            self.pr_priority.discard(agent_id)
            agent = self.agents.get(agent_id)
            if agent is None or not agent.record["priority"]:
                self.queue.prioritized.discard(agent_id)
            self.version += 1

    def set_review_priority(self, agent_ids: set[str]) -> None:
        """The agents with a review job queued or working, a PR draft's check before the Inbox (the Issues board's Review;
        backend/github_api.py, every few seconds): they go next in a VM's line, behind everyone with priority (the user's,
        a pull request that needs action) and ahead of the rest (In progress and Catalog), and an overloaded VM takes their
        desktop back only after the rest's (watch_room), until their review jobs are over."""
        for agent_id in agent_ids:
            if agent_id not in self.agents or agent_id in self.queue.reviewing:
                continue
            self.queue.reviewing.add(agent_id)
            if agent_id in self.queue.prioritized:
                continue
            # Waiting for a VM: ahead of everyone without priority now.
            vm_name, place = self.queue.place(agent_id)
            if place is not None and place > 0:
                try:
                    self.queue.move_up(vm_name, agent_id)
                except (ValueError, VMsError):
                    # It left the line meanwhile.
                    pass
            self.version += 1
        for agent_id in list(self.queue.reviewing):
            if agent_id in agent_ids:
                continue
            self.queue.reviewing.discard(agent_id)
            self.version += 1

    async def delete(self, agent_id: str) -> None:
        """Stop the agent and delete it. Its open jobs become cancelled; its drafts stay in the Inbox.
        Not an agent that made PRs: it keeps its conversation for updates on them (archive it instead)."""
        agent = self.agents[agent_id]
        prs = self.inbox.pr_owners().get(agent_id, 0)
        if prs > 0:
            raise ValueError(f"{agent.name} made {prs} PR{'s' if prs > 1 else ''}. Archive it instead, so it keeps its conversation for updates on them.")
        await agent.interrupt()
        # The VM it holds or waits for, read before it leaves the queue.
        vm_name, place = self.queue.place(agent_id)
        # Out of the dicts first, so nothing (a grant, a save) reaches it anymore.
        del self.agents[agent_id]
        self.workers.pop(agent_id).cancel()
        del self.pending[agent_id]
        del self.wake[agent_id]
        del self.nudges[agent_id]
        self.queue.leave_all(agent_id)
        self.queue.prioritized.discard(agent_id)
        self.queue.reviewing.discard(agent_id)
        self.pr_priority.discard(agent_id)
        self.jobs.delete_for_agent(agent_id)
        self.version += 1
        await agent.stop()
        await self.stop_runs(agent_id)
        # Its desktop lock and whatever it still runs in the VM end with it.
        agent.computer_tools.end_turn()
        if vm_name is not None:
            await asyncio.to_thread(agent.computer_tools.cancel, vm_name)
        (self.folder / f"{agent_id}.json").unlink(missing_ok=True)
        # Its artifacts go with it (an archived agent keeps them).
        await asyncio.to_thread(self.artifacts.delete_all, agent_id)

    async def archive(self, agent_id: str) -> None:
        """Put the agent away: it stops, its open jobs become cancelled and it leaves every VM queue (what it still
        ran in the VM is killed). Its conversation stays; unarchive() brings it back."""
        agent = self.agents[agent_id]
        if agent.record["archived_at"] is not None:
            return
        await agent.interrupt()
        vm_name, place = self.queue.place(agent_id)
        self.queue.leave_all(agent_id)
        self.jobs.delete_for_agent(agent_id)
        # The user's messages that still waited are dropped; the app's wait for when it is back.
        self.pending[agent_id] = [message for message in self.pending[agent_id] if message["from"] != "User"]
        self.wake[agent_id].clear()
        agent.record["archived_at"] = datetime.now(UTC).isoformat()
        agent.history.append({"type": "system", "text": "Archived: its open jobs were cancelled", "time": agent.record["archived_at"]})
        agent.computer_tools.end_turn()
        await self.stop_runs(agent_id)
        if vm_name is not None:
            await asyncio.to_thread(agent.computer_tools.cancel, vm_name)
        self.save(agent)
        self.version += 1

    def unarchive(self, agent_id: str) -> None:
        """Bring an archived agent back. Messages that waited for it go in now."""
        agent = self.agents[agent_id]
        if agent.record["archived_at"] is None:
            return
        agent.record["archived_at"] = None
        agent.history.append({"type": "system", "text": "Back from the archive", "time": datetime.now(UTC).isoformat()})
        if self.pending[agent_id]:
            self.wake[agent_id].set()
        self.save(agent)
        self.version += 1

    def history(self, agent_id: str, since: int) -> list[dict]:
        return self.agents[agent_id].history[since:]

    def send(self, agent_id: str, text: str) -> None:
        """A chat message from the user. It waits while the agent works, then goes with its next turn."""
        if agent_id not in self.agents:
            raise KeyError(f"No agent {agent_id}")
        if not text.strip():
            raise ValueError("The message is empty")
        # Talking to an archived agent brings it back.
        self.unarchive(agent_id)
        waiting = [message for message in self.pending[agent_id] if message["from"] == "User"]
        if len(waiting) >= MAX_QUEUED:
            raise ValueError(f"{MAX_QUEUED} messages already wait; send more when one has gone in")
        self.pending[agent_id].append({"from": "User", "text": text.strip(), "shown": False})
        self.wake[agent_id].set()
        self.version += 1

    def cancel_queued(self, agent_id: str, index: int, text: str) -> None:
        """Take one of the user's queued messages out before it goes in: the index-th of theirs, when it still has that
        text (one may have gone in meanwhile, moving the others up), or else the first of theirs with that text."""
        if agent_id not in self.agents:
            raise KeyError(f"No agent {agent_id}")
        users = [message for message in self.pending[agent_id] if message["from"] == "User"]
        chosen = None
        if 0 <= index < len(users) and users[index]["text"] == text:
            chosen = users[index]
        for message in users:
            if chosen is None and message["text"] == text:
                chosen = message
        if chosen is None:
            raise ValueError("That message isn't waiting anymore: it went in, or was taken out already.")
        self.pending[agent_id].remove(chosen)
        self.save(self.agents[agent_id])
        self.version += 1

    def notify(self, agent_id: str, text: str) -> None:
        """A message from the app that wakes the agent. Safe to call from any thread."""
        if threading.get_ident() != self.loop_thread:
            self.loop.call_soon_threadsafe(self.notify, agent_id, text)
            return
        # An agent deleted in the meantime.
        if agent_id not in self.agents:
            return
        self.pending[agent_id].append({"from": "System", "text": text, "shown": False})
        # An archived agent hears it once it is back.
        if self.agents[agent_id].record["archived_at"] is None:
            self.wake[agent_id].set()
        self.version += 1

    def secrets_filled(self, names: list[str], where: str) -> None:
        """The user gave a value to empty env variables (where: "for all VMs" or "on vm2"). Each agent that added
        one of them (env_var_add in its history) is told, so it carries on with what waited for it. Any thread."""
        if threading.get_ident() != self.loop_thread:
            self.loop.call_soon_threadsafe(self.secrets_filled, names, where)
            return
        for agent in self.agents.values():
            added = [entry.get("input", {}).get("name") for entry in agent.history if entry["type"] == "tool" and entry["name"] == "env_var_add"]
            filled = [name for name in names if name in added]
            if filled:
                self.notify(agent.id, f"The user filled in {', '.join(filled)} ({where}). Carry on with what waited for it.")

    async def interrupt(self, agent_id: str) -> None:
        await self.agents[agent_id].interrupt()

    async def pause_job(self, job_id: str) -> None:
        """The user paused the issue the job is for (Pause on the Dashboard's Issues board): the job stops as it is
        (paused, with paused_from), and when its agent was working on it, so does the agent: its turn, its desktop lock
        and what it runs in the VM. The agent hears it with its next turn; this doesn't wake it."""
        job = self.jobs.get(job_id)
        if job["status"] not in ("queued", "working", "waiting_on_user"):
            return
        self.jobs.update(job_id, status="paused", paused_from=job["status"])
        self.jobs.add_timeline(job_id, "status", "Paused by you")
        agent_id = job["agent"]
        if agent_id not in self.agents:
            return
        text = f"The user paused {job_id} ({job['title']}). Don't work on it at all until they resume it; you will be told."
        self.pending[agent_id].append({"from": "System", "text": text, "shown": False})
        if job["status"] == "working":
            agent = self.agents[agent_id]
            await agent.interrupt()
            agent.computer_tools.end_turn()
            await self.stop_runs(agent_id)
            vm_name, place = self.queue.place(agent_id)
            if vm_name is not None:
                await asyncio.to_thread(agent.computer_tools.cancel, vm_name)
        self.version += 1

    def resume_job(self, job_id: str) -> None:
        """Resume on the board: the paused job gets its status back, and its agent is woken to go on with it."""
        job = self.jobs.get(job_id)
        if job["status"] != "paused":
            return
        self.jobs.update(job_id, status=job.get("paused_from") or "queued", paused_from=None)
        self.jobs.add_timeline(job_id, "status", "Resumed by you")
        self.notify(job["agent"], f"The user resumed {job_id} ({job['title']}): go on with it where you left off.")

    def set_target_vm(self, agent_id: str, vm_name: str | None, by_agent: bool = False) -> None:
        """The VM the agent works in. Its unfinished jobs move along. Not while it waits for or holds a VM.

        The user sets it, or the agent picks one itself (choose_vm, by_agent=True: then it isn't told).
        """
        agent = self.agents[agent_id]
        if vm_name == agent.record["target_vm"]:
            return
        queued_vm, place = self.queue.place(agent_id)
        if place == 0:
            raise ValueError(f"{agent.name} holds {queued_vm}; change its target VM after it releases it")
        if place is not None:
            raise ValueError(f"{agent.name} waits for {queued_vm}; change its target VM after it leaves the queue")
        if vm_name == FIX_VM:
            raise ValueError(f"{FIX_VM} is Seraph's own VM, for fixing the app: pick another VM.")
        # Every name, so an agent that guessed one (choose_vm) can pick a real one. Not Seraph's own VM: no agent gets it.
        names = [vm_record.name for vm_record in self.vms.list() if vm_record.name != FIX_VM]
        if vm_name is not None and vm_name not in names:
            raise ValueError(f"No VM named {vm_name}. The VMs are: {', '.join(names) or 'none'}.")
        for vm_record in self.vms.list():
            if vm_record.name == vm_name and vm_record.graceful_shutdown:
                raise ValueError(f"{vm_name} shuts down once the agents on it are done and takes nobody new: pick another VM.")
            if vm_record.name == vm_name and vm_record.suspended:
                raise ValueError(f"{vm_name} is suspended and takes nobody new: pick another VM.")

        agent.record["target_vm"] = vm_name
        moved = []
        for job in self.jobs.for_agent(agent_id):
            if job["status"] in ["done", "cancelled"]:
                continue
            self.jobs.update(job["id"], vm=vm_name)
            moved.append(job)
        self.save(agent)
        self.version += 1
        if by_agent:
            return

        # Queued jobs can start now, so that wakes it; otherwise it hears with its next message.
        text = f"The user set your target VM to {vm_name}."
        if vm_name is None:
            text = "The user took your target VM away; pick another with vms_list and choose_vm when you need one."
        if any(job["status"] == "queued" for job in moved) and vm_name is not None:
            self.notify(agent_id, text + " Your open jobs moved to it. Use queue_for_vm when you are ready to work on them.")
            return
        self.pending[agent_id].append({"from": "System", "text": text, "shown": False})
        self.save(agent)

    def rename_vm(self, name: str, new_name: str) -> None:
        """The user renamed a VM: agents aimed at it and the jobs on it follow. Those agents hear with their next message."""
        if new_name == name:
            return
        self.jobs.rename_vm(name, new_name)
        for agent in self.agents.values():
            if agent.record["target_vm"] != name:
                continue
            agent.record["target_vm"] = new_name
            self.pending[agent.id].append({"from": "System", "text": f"The user renamed {name} to {new_name}. It is still your target VM.", "shown": False})
            self.save(agent)
        self.version += 1

    def assign(self, issue_id: str, agent_id: str | None, vm_name: str | None, instructions: str = "") -> dict:
        """The user gives an issue to an agent (a new one when agent_id is None): a fix_issue job."""
        matches = [item for item in self.issues.items() if item["id"] == issue_id]
        if not matches:
            raise KeyError(f"{issue_id} is not in the Issues list")
        issue = matches[0]
        if vm_name is not None and vm_name not in [vm_record.name for vm_record in self.vms.list()]:
            raise ValueError(f"No VM named {vm_name}")
        if vm_name == FIX_VM:
            raise ValueError(f"{FIX_VM} is Seraph's own VM, for fixing the app: pick another VM.")
        if agent_id is None:
            agent_id = self.create()["id"]
        if agent_id not in self.agents:
            raise KeyError(f"No agent {agent_id}")
        agent = self.agents[agent_id]
        # Raises ValueError while the agent waits for or holds another VM.
        if vm_name is not None:
            self.set_target_vm(agent_id, vm_name)
        self.unarchive(agent_id)

        title = f"Fix {issue_id}: {issue['title']}"
        vm_name = agent.record["target_vm"]
        job = self.jobs.create("fix_issue", title, agent_id, "user", issue=issue_id, repo=issue["repo"], vm=vm_name, instructions=instructions, agent_name=agent.name)
        text = f"New job {job['id']}: {title}"
        if instructions:
            text += f"\nInstructions from the user: {instructions}"
        # The user's own words on the issue (an earlier claim of theirs, an issue we opened as them) are ours, never someone
        # else on it (QwenPaw#8698: the user's claim, taken for someone else's).
        login = self.your_repositories.github_account.status().get("login")
        if login:
            text += (
                f"\nThe user's GitHub login is {login}: whatever {login} wrote or opened on the issue is ours (an earlier claim "
                "of theirs too; read_issue marks it by_user), never someone else on it."
            )
        if vm_name is None:
            text += "\nYou have no target VM: pick the VM that suits the job with vms_list and choose_vm, then queue_for_vm when ready."
        else:
            text += f"\nIt is for {vm_name}. Use queue_for_vm when ready."
        self.notify(agent_id, text)
        return job

    def give_review(self, draft: dict, desktop: int) -> None:
        """A PR draft (work_tools.py draft_pr, made on desktop of draft["vm"]) for a reviewer: a review job. The draft waits
        out of the Inbox until review_finished(). It goes to its repo's own reviewer (record "role": "reviewer", "reviews":
        the repo), made the first time, aimed at the draft's VM: it checks the draft the way the repo's maintainers will,
        in the author's folder on the author's desktop, where the project is set up and built."""
        now = datetime.now(UTC).isoformat()
        if draft["repo"] is None:
            self.inbox.set_review(draft["id"], {"state": "passed", "agent": None, "job": None, "notes": "It names no repo, so nobody reviewed it.", "at": now})
            return
        reviewer = None
        for agent in self.agents.values():
            if agent.record.get("role") == "reviewer" and agent.record.get("reviews") == draft["repo"].lower():
                reviewer = agent.id
        if reviewer is None:
            created = self.create()
            agent = self.agents[created["id"]]
            agent.record["role"] = "reviewer"
            agent.record["reviews"] = draft["repo"].lower()
            self.save(agent)
            reviewer = agent.id
        self.unarchive(reviewer)
        # It checks the draft where it was made. While it holds or waits for another VM it keeps that one, and its
        # message says where to go next.
        if draft["vm"] is not None:
            try:
                self.set_target_vm(reviewer, draft["vm"], by_agent=True)
            except ValueError:
                pass
        author = draft["agent"]
        if author in self.agents:
            author = self.agents[author].name
        vm_name = self.agents[reviewer].record["target_vm"]
        title = f"Review {draft['id']}: {draft['title']}"
        job = self.jobs.create("review", title, reviewer, "user", issue=draft["target"], repo=draft["repo"], vm=vm_name, agent_name=self.agents[reviewer].name)
        self.inbox.set_review(draft["id"], {"state": "waiting", "agent": reviewer, "job": job["id"], "notes": "", "at": now})
        what = "a new PR"
        if draft["update_of"] is not None:
            what = f"the next version of the user's PR {draft['update_of']}"
        text = (
            f"New job {job['id']}: {title}\n{author} drafted {what} for {draft['target']} in {draft['repo']}, someone else's "
            "project. Before it reaches the user's Inbox, check it the way that project's maintainers will, as in Reviewing a "
            f"PR before it goes out: review_read {draft['id']}, read the whole thread it is for, go through every point that was "
            "asked, then try to break it in the VM, and end with review_done.\n"
            f"It was made in {draft['path']} on desktop {desktop} of {draft['vm']}, where the project is set up and built: "
            f"queue_for_vm with desktop {desktop} once you have read it, check in that folder, and leave it as you found it."
        )
        # What the user wrote on the thread is ours (the author's claim, an earlier version, a reply the app sent as them):
        # on QwenPaw#8698 the reviewer took the user's own claim for someone else's and sent the PR back.
        login = self.your_repositories.github_account.status().get("login")
        if login:
            text += (
                f"\nThe user's GitHub login is {login}: whatever {login} wrote or opened there is ours (the author's claim, "
                "an earlier version, a reply the app sent as the user; read_issue marks it by_user), never someone else on it."
            )
        if vm_name != draft["vm"]:
            text += f"\nYour target VM is {vm_name}: once you hold none, choose_vm {draft['vm']} for this one."
        self.notify(reviewer, text)

    def review_finished(self, draft_id: str, passed: bool, notes: str) -> None:
        """The reviewer's verdict on a PR draft (agent/review_tools.py review_done). Passed: it shows in the Inbox, and
        its author hears so with its next message. Changes: it is rejected with the notes, so it never shows, and its
        author's job is open again, to fix and draft again."""
        draft = self.inbox.get(draft_id)
        review = dict(draft["review"])
        review["state"] = "passed" if passed else "changes"
        review["notes"] = notes
        review["at"] = datetime.now(UTC).isoformat()
        self.inbox.set_review(draft_id, review)
        if review["job"] is not None:
            verdict = "Passed" if passed else "Asked for changes"
            self.jobs.update(review["job"], status="done", notes=f"{verdict}: {notes}")
        author = self.agents.get(draft["agent"])
        if author is None:
            return
        if passed:
            text = f"Your PR draft {draft_id} ({draft['title']}) passed review and is in the user's Inbox now. The reviewer's notes: {notes}"
            self.pending[author.id].append({"from": "System", "text": text, "shown": False})
            self.save(author)
            self.version += 1
            return
        self.inbox.decide(draft_id, "rejected", notes)
        job_name = "your work"
        if draft["job"] is not None:
            job = self.jobs.get(draft["job"])
            job_name = job["id"]
            if job["status"] == "waiting_on_user":
                self.jobs.update(job["id"], status="queued")
        text = (
            f"The reviewer asked for changes on your PR draft {draft_id} ({draft['title']}) for {job_name}:\n{notes}\n"
            "Make them (queue_for_vm when you need the VM), run the tests again with when: after, and draft_pr again: the new "
            "draft is reviewed again."
        )
        self.notify(author.id, text)

    def remake_pr(self, pr: dict, days: int) -> dict | None:
        """One of the user's PRs that an agent owns had no update on GitHub for days (backend/issues_api.py
        keep_stale_prs): its agent makes it again as a fresh PR, all its changes on the newest base with a clean history
        and a fresh description, as a fix_issue job whose thread is that PR. Its draft replaces the PR, which is closed
        once the new one is on GitHub. pr is pr_tracking's entry. Returns the job, or None when its agent is gone."""
        agent = self.agents.get(pr["agent"])
        if agent is None:
            return None
        self.unarchive(agent.id)
        issue_id = None
        if pr["job"] is not None:
            try:
                issue_id = self.jobs.get(pr["job"])["issue"]
            except KeyError:
                pass
        if issue_id is None and pr["issues"]:
            issue_id = f"{pr['repo']}#{pr['issues'][0]['number']}"
        title = f"Remake #{pr['number']} fresh: {pr['title']}"
        vm_name = agent.record["target_vm"]
        job = self.jobs.create("fix_issue", title, agent.id, "user", issue=issue_id, repo=pr["repo"], vm=vm_name, thread=pr["id"], agent_name=agent.name)
        text = (
            f"New job {job['id']}: {title}\n"
            f"Your PR {pr['id']} ({pr['url']}) has had no update on GitHub for {days} days: it stalled. Make it again as a "
            "fresh PR with a clean history. read_issue on it first: every review point and comment there must be done in "
            "the new one. Then sync_code, a new branch from the newest default branch, all of its changes on top again "
            "(squashed into one commit, or a few clean ones the way the project's rules want), with every point the "
            "reviewers made done. Then as for any fix: the tests on the newest code (when: before) and with your change "
            "(when: after), the before and after pictures again, and draft_pr: a fresh title and description written to "
            f"the project's rules, with 'Supersedes #{pr['number']}' in it. Its draft replaces {pr['id']}: once the new PR is "
            "on GitHub, the old one is closed."
        )
        if vm_name is not None:
            text += f"\nIt is for {vm_name}: queue_for_vm when ready."
        self.notify(agent.id, text)
        return job

    def issue_taken(self, issue_id: str, reason: str, assignees: list[str], prs: list[str] | None = None) -> None:
        """The issue went from free to assigned: someone else is on it now. The agent of every open job on it is told
        who, and decides itself whether to stop (TAKEN_ADVICE): the user isn't asked. On an issue our agents opened as the
        user it is told to keep going instead (OURS_ADVICE): we never give one of those up. assignees are their GitHub logins
        (issue_facts.py); without any, the tags' reason says who seems to be on it. Once per job at most: a job told
        before has the notice on its timeline (the only notice the app puts there).
        prs: other people's open pull requests that came to be tied to it since its last read ("owner/name#n by login",
        the tags' open_prs, issue_tags.py: one that says it closes it, or only mentions it). Then the agent is told of
        those (PR_ADVICE), once each, whatever it heard before, whoever is assigned and whether its claim went out:
        DeskcommCRM#4511 only said "Refs #4495", the issue stayed free, and our agent ran five more hours of checks before
        it found the PR at its draft."""
        # Assigned to the user is never someone else taking it (often their claim going through). Without the user's
        # sign-in the app can't tell who they are: for a job whose claim the user approved, any assignee counts as them.
        claimed = [draft["job"] for draft in self.inbox.list() if draft["kind"] == "comment" and draft["status"] == "approved"]
        account = self.your_repositories.github_account.status()
        login = None
        if account["connected"]:
            login = account["login"]
        you = login is not None and login.lower() in [name.lower() for name in assignees]
        # reason is the tags' sentence on who has it, then one on its merge ("Merge: ..."); only the first part matters here.
        why = re.split(r"\sMerge: ", reason)[0]
        who = ", ".join(f"@{login}" for login in assignees)
        ours = [f"{action['sent']['repo']}#{action['sent']['number']}".lower() for action in self.inbox.actions() if action["kind"] == "issue"]
        for job in self.jobs.list():
            if job["issue"] != issue_id or job["status"] in ["done", "cancelled"]:
                continue
            if you and not prs:
                continue
            if job["kind"] == "fix_issue" and job["id"] in claimed and (login is None or not assignees) and not prs:
                continue
            if job["agent"] not in self.agents:
                continue
            notices = [entry for entry in job["timeline"] if entry["kind"] == "notice"]
            # Once per job. A pull request tied to it is news of its own: once for each, whatever the job heard before, and
            # it doesn't count as having heard of an assignment.
            told = [entry for entry in notices if not entry["text"].startswith(("Someone else's pull request", "Issue was fixed or closed"))]
            if told and not prs:
                continue
            fresh = []
            for pr in prs or []:
                if not [entry for entry in notices if pr in entry["text"]]:
                    fresh.append(pr)
            if prs and not fresh:
                continue
            text = f"{issue_id} isn't free anymore on GitHub: someone else seems to be on it. {why}"
            notice = "Someone else seems to be on the issue on GitHub; told the agent"
            if who:
                text = f"{issue_id} isn't free anymore on GitHub: it is assigned to {who}."
                notice = f"Issue was assigned to {who} on GitHub; told the agent"
            advice = TAKEN_ADVICE.format(job=job["id"], repo=job["repo"])
            if fresh:
                text = f"Someone else's open pull request is tied to {issue_id} on GitHub now: {', '.join(fresh)}."
                notice = f"Someone else's pull request {', '.join(fresh)} is tied to the issue on GitHub; told the agent"
                advice = PR_ADVICE.format(job=job["id"])
            if issue_id.lower() in ours:
                advice = OURS_ADVICE.format(job=job["id"])
            text += f" You have {job['id']} ({job['title']}) on it." + advice
            self.jobs.add_timeline(job["id"], "notice", notice)
            self.notify(job["agent"], text)

    def issue_fixed(self, issue_id: str, reason: str, closed: bool) -> None:
        """The issue was fixed on GitHub (its tags' status is fixed: a merged pull request or a commit on the default
        branch already does what it asks) or closed. The agent of every job on it whose PR hasn't gone out yet (queued,
        working, waiting on the user) is told, once per job, and decides itself (FIXED_ADVICE). A job whose PR is open
        is left to that PR's follow-ups. reason is the tags' sentence on it."""
        why = re.split(r"\sMerge: ", reason)[0]
        for job in self.jobs.list():
            if job["issue"] != issue_id or job["status"] not in ["queued", "working", "waiting_on_user"]:
                continue
            if job["agent"] not in self.agents:
                continue
            told = [entry for entry in job["timeline"] if entry["kind"] == "notice" and entry["text"].startswith("Issue was fixed or closed")]
            if told:
                continue
            text = f"{issue_id} seems fixed on GitHub already: {why}"
            if closed:
                text = f"{issue_id} was closed on GitHub. {why}"
            text += f" You have {job['id']} ({job['title']}) on it." + FIXED_ADVICE.format(job=job["id"])
            self.jobs.add_timeline(job["id"], "notice", "Issue was fixed or closed on GitHub; told the agent")
            self.notify(job["agent"], text)

    async def stop_repo(self, repo: str) -> None:
        """The user deleted the repo on the Repositories page (backend/repos_api.py): every open job on it is stopped
        now (stop_jobs)."""
        ids = [job["id"] for job in self.jobs.list() if (job["repo"] or "").lower() == repo.lower()]
        await self.stop_jobs(ids, f"{repo} was deleted")

    async def stop_jobs(self, job_ids: list[str], why: str) -> None:
        """The user stopped these jobs on the Repositories page (backend/repos_api.py: a deleted repo, Stop all on its
        issues in progress, Close all on its open PRs): each still open is cancelled now, and an agent working on one
        stops at once, as for Pause (its turn, its runs, what it runs in the VM). The drafts of those jobs that wait in the
        Inbox are rejected, so nothing more goes out there. The agents hear it with their next turn; this doesn't wake
        them. why: what the user did, in a few words ("owner/name was deleted")."""
        drafts = self.inbox.list()
        for job in self.jobs.list():
            if job["status"] in ["done", "cancelled"] or job["id"] not in job_ids:
                continue
            self.jobs.update(job["id"], status="cancelled")
            self.jobs.add_timeline(job["id"], "status", f"Stopped by you: {why}")
            for draft in drafts:
                if draft["job"] == job["id"] and draft["status"] == "pending":
                    self.inbox.decide(draft["id"], "rejected", why)
            agent_id = job["agent"]
            if agent_id not in self.agents:
                continue
            text = f"The user stopped it ({why}): {job['id']} ({job['title']}) is cancelled. Do nothing more for it."
            self.pending[agent_id].append({"from": "System", "text": text, "shown": False})
            if job["status"] == "working":
                agent = self.agents[agent_id]
                await agent.interrupt()
                agent.computer_tools.end_turn()
                await self.stop_runs(agent_id)
                vm_name, place = self.queue.place(agent_id)
                if vm_name is not None:
                    await asyncio.to_thread(agent.computer_tools.cancel, vm_name)
        self.version += 1

    def stop_job(self, job_id: str, why: str) -> None:
        """The app no longer wants this job done (backend/issues_api.py: its issue was deleted on GitHub, its repo left
        Repos, or its repo doesn't take AI-made contributions). Its agent is told to stop and cancel it itself, once:
        the notice on its timeline says so."""
        job = self.jobs.get(job_id)
        told = [entry for entry in job["timeline"] if entry["kind"] == "notice" and entry["text"].endswith("told the agent to stop")]
        if told or job["agent"] not in self.agents or job["status"] in ["done", "cancelled"]:
            return
        self.jobs.add_timeline(job_id, "notice", f"{why.rstrip('.')}; told the agent to stop")
        text = (
            f"{why} Stop {job_id} ({job['title']}) now: cancel it with job_update (status cancelled) and a note saying "
            "why, tidy up what you left for it in the VM, and release the VM if nothing else needs it. Draft nothing more "
            "for it."
        )
        self.notify(job["agent"], text)

    def follow_up(self, entry: dict) -> dict | None:
        """Someone else wrote on a PR or issue an agent follows for the user (agent mode Drafts on the GitHub tab), the
        PR's checks failed, or anything else changed on the user's own PR (merged, closed, a push, a conflict, ...): an
        entry of pr_tracking.needs_reply ({"id", "kind", "relation", "state", "title", "url", "agent", "reason", "at",
        "failed_sha", "head", "base", "signals"}; only the user's own open PR, relation author, gets offered a new version
        or a rebase, and only the user's own PR or issue a new title or description). The agent's open follow_up job for
        that thread hears about it; else a new one is made, but not on a stopped repo (the button on its card, repo_list.py).
        When an open job of any agent has the PR's next version waiting (draft_pr with pr), that job hears it instead: one
        agent per PR at a time. Returns the job, or None when the agent is gone or the repo is stopped. Any thread.
        A merged or closed one never goes to its agent: that agent is done with it (below)."""
        thread = entry["id"]
        repo = thread.split("#")[0]
        what = "issue"
        if entry["kind"] == "pr":
            what = "PR"
        # Merged or closed: its agent's work on it is over. Its open jobs on it are cancelled, and keep_going archives it
        # once it has no other work, never to come back for this thread. What happens there from now on goes to the one
        # agent that looks after every merged or closed PR and issue (role "closed_prs", made the first time), as a job: a
        # turn only when someone wrote there; the end alone is only noted. Not on a removed repo either.
        if entry.get("state", "open") != "open":
            owner = self.agents.get(entry["agent"])
            if owner is not None and owner.record["role"] is None:
                cancelled = []
                for job in self.jobs.for_agent(owner.id):
                    if job["status"] not in ["done", "cancelled"] and job["thread"] == thread:
                        self.jobs.update(job["id"], status="cancelled", notes=f"{thread} is {entry['state']}")
                        cancelled.append(job["id"])
                # Not archived from here: an archive sent from here ran after the next entry had brought the agent back
                # with a new job, and cancelled that job too (linq2db#6435: the follow-up on its issue #6137, where the
                # maintainer asked to reopen the PR, was lost that way). keep_going archives it once its work is over.
                if cancelled:
                    self.notify(owner.id, f"{thread} is {entry['state']} now, so {', '.join(cancelled)} is cancelled: nothing more goes there. Go on with your other jobs, if you have any.")
            keeper = None
            for agent in self.agents.values():
                if agent.record["role"] == "closed_prs":
                    keeper = agent
            if keeper is None:
                keeper = self.agents[self.create()["id"]]
                keeper.record["role"] = "closed_prs"
                self.save(keeper)
            title = f"Follow up on {thread}"
            job = self.jobs.create("follow_up", title, keeper.id, "user", repo=repo, thread=thread, agent_name=keeper.name)
            removed = [name.lower() for name in self.repos.removed()]
            if entry["at"] is None or repo.lower() in removed:
                self.jobs.update(job["id"], status="done", notes=f"{entry['reason']}; nothing more goes there")
                return job
            if threading.get_ident() == self.loop_thread:
                self.unarchive(keeper.id)
            else:
                self.loop.call_soon_threadsafe(self.unarchive, keeper.id)
            text = (
                f"New job {job['id']}: {title}\n{entry['reason']} on the {what} {thread} ({entry['title']}): {entry['url']}\n"
                f"It is {entry['state']}, and the agent that had it is done with it: you look after every merged or closed PR "
                "and issue of the user's. Read the whole thread with read_issue, then do at most one of these, and mark "
                f"{job['id']} done (job_update) with a note on what you did and why:\n"
                "- Nothing, which is most of the time: a thanks, a note, a release, people talking among themselves, anyone "
                "who isn't one of its maintainers or reviewers.\n"
                f"- A maintainer or a reviewer asked us something: one short reply, draft_comment with target {thread}.\n"
                "- They report a bug in our change, or ask for more work: open_issue for it, and a new agent takes it and "
                "fixes it. When the repo doesn't let you open issues, put it in the note.\n"
                "- A PR we closed ourselves (close_pr), and the reason is gone now: reopen_pr, with a comment saying why.\n"
                "You never work in a VM: anything that needs one goes to a new agent through open_issue."
            )
            self.notify(keeper.id, text)
            return job

        # One agent per PR at a time: when an open job's next version of this PR waits (in review, in the Inbox, or
        # approved and not sent yet), the news goes to that job and its agent, which hold the work, instead of a second
        # agent starting on it (openmed#5511: a follow-up on the PR went to its owner while another agent's version, drafted
        # from a follow-up on its issue, waited, and both drafted one). draft_pr refuses a second one from another job too.
        agent_id = entry["agent"]
        holder_job = None
        for draft in self.inbox.list():
            waiting = draft["status"] == "pending" or (draft["status"] == "approved" and draft["sent"] is None)
            if draft["kind"] != "pr" or not waiting or (draft["update_of"] or "").lower() != entry["id"].lower():
                continue
            if draft["job"] is None or draft["agent"] not in self.agents:
                continue
            open_jobs = [job["id"] for job in self.jobs.for_agent(draft["agent"]) if job["status"] not in ["done", "cancelled"]]
            if draft["job"] in open_jobs:
                agent_id = draft["agent"]
                holder_job = draft["job"]
        agent = self.agents.get(agent_id)
        if agent is None:
            return None
        number = thread.split("#")[1]
        head = entry["head"]
        # A new version goes on the PR's own branch, which only the user's own open PR has (not one they only commented on).
        own = entry.get("relation", "author") == "author"
        own_pr = entry["kind"] == "pr" and head is not None and own
        # A removed repo gets no new work: only a job already open on it hears it.
        removed = [name.lower() for name in self.repos.removed()]
        if repo.lower() in removed and holder_job is None:
            open_ones = []
            for job in self.jobs.for_agent(agent.id):
                if job["status"] not in ["done", "cancelled"] and job["kind"] == "follow_up" and job["thread"] == thread:
                    open_ones.append(job)
            if not open_ones:
                return None
        # It comes back from the archive for it, as for a job the user gives it. unarchive() wakes it: on the loop.
        if threading.get_ident() == self.loop_thread:
            self.unarchive(agent.id)
        else:
            self.loop.call_soon_threadsafe(self.unarchive, agent.id)

        for job in self.jobs.for_agent(agent.id):
            if job["status"] in ["done", "cancelled"]:
                continue
            if holder_job is not None and job["id"] != holder_job:
                continue
            if holder_job is None and (job["kind"] != "follow_up" or job["thread"] != thread):
                continue
            text = (
                f"More on {thread} ({entry['title']}) for {job['id']}: {entry['reason']}. Read it again with read_issue and take "
                "it into account: reproduce anything new it reports or asks about in the VM before you act on it."
            )
            if entry["failed_sha"]:
                text += f" Its checks failed on {entry['failed_sha'][:10]}: see which and why on {entry['url']}/checks."
            if own_pr:
                text += (
                    f" Its branch {head['branch']} in {head['repo']} is at {head['sha']} now: a new version goes on top of that "
                    "commit. When it conflicts with the branch it goes into, adding commits doesn't settle that: rebase it "
                    "onto the newest one (with your change, if you have one) and draft_pr with rebase: true."
                )
            if job["status"] == "waiting_on_user":
                text += " Your draft for it still waits in the user's Inbox; if it no longer fits, draft a new one and say why in it."
            self.notify(agent.id, text)
            return job

        title = f"Follow up on {thread}"
        vm_name = agent.record["target_vm"]
        job = self.jobs.create("follow_up", title, agent.id, "user", repo=repo, vm=vm_name, thread=thread, agent_name=agent.name)
        text = f"New job {job['id']}: {title}\n{entry['reason']} on the {what} {thread} ({entry['title']}): {entry['url']}"
        # The user's own pull request that is out there waits on it: that comes before new work.
        if own_pr:
            text += (
                "\nThis goes first: before your other jobs (at a good point in the one you are on, e.g. once a run you "
                "started ends). While the pull request needs something from us, you also go ahead in the VM's line."
            )
        if entry["failed_sha"]:
            text += (
                f"\nIts checks failed on {entry['failed_sha'][:10]}: see which and why on its checks page ({entry['url']}/checks, "
                "with browser_open), and reproduce the failure in the VM before you fix it. A failure that isn't the PR's fault "
                "(a flaky test, a broken main branch) needs no new version: a short reply saying so, or nothing."
            )
        text += (
            "\nYou follow it for the user: whatever the project's maintainers and the PR's reviewers write there (a question, a review, a request, a "
            "bug report) or when its checks fail, you do the work it needs yourself and draft it, and the user approves every "
            "push and comment before it goes out (Approve sends it as them). Never ask the user to do any of it by hand: no "
            "push, rebase, conflict or edit for them to do. You never post, push or send anything yourself.\n"
            "Only maintainers and reviewers get answers (read_issue's maintainer: OWNER, MEMBER, COLLABORATOR, or someone who "
            "merges its PRs; and the PR's reviewers, people who reviewed it). Anyone else, even when they ask something, and "
            "every review bot (CodeRabbit, Copilot) get no reply, no thanks and no 'fixed', unless the merge needs one (a CLA bot's sign line, a claim, a bot command or a resolved conversation the project's rules "
            "require). Their code points only when one is a real bug in what the PR changes that a maintainer would send back, "
            "and then silently in the next version, never style, nitpicks, tests they want or corner cases beyond the issue: "
            "a bot reviews every push again and always finds a next one. One comment of ours per round (until someone else "
            "writes): the new version's comment when you push one, else one draft_comment; never both, never one per point.\n"
            "First read the whole thread with read_issue: every comment and review, the mentions, the related PRs and the checks. Then reproduce what it reports or asks about, in the VM, before "
            "you change code or answer: the bug a reviewer saw, the failing check, the conflict with main, whether something "
            "works. Never act on reading alone; add what you saw as evidence. When it doesn't happen, change nothing and say "
            "so in a reply, with what you ran. A reviewer's case is one example of a kind: once it reproduces, find and test "
            "the rest of that kind too (other values, types, inputs, drivers, platforms, the same mistake elsewhere in the PR) "
            "and fix the kind, not the example. Before a new version, go through every point a maintainer or reviewer raised "
            "on the thread and every requirement of the issue again (draft_pr's checklist). Then do one of these (see Following up on PRs and "
            "issues):\n"
            f"- A reply, when a maintainer or reviewer asked something or waits for an answer: draft_comment with target {thread}. Short, "
            "friendly, in the project's tone, the way the user would write it. Never ask them or anyone else for anything, "
            "and never wait for an answer: assume nobody replies. When their point leaves a choice, make it and say what "
            "you did."
        )
        if entry["kind"] == "pr":
            text += (
                "\n- A reviewer's comment on a line of code (a person's, not a bot's): answer it in its conversation, draft_comment with reply_to (the "
                "comment's id from read_issue's conversations), not below the PR, unless the organization doesn't let the app "
                "answer there (draft_comment says so): then in the round's one comment. On the user's own PR, add resolve: true "
                "once the change it asked for is pushed there, when the project wants every conversation resolved before a "
                "merge or lets the author resolve them. A bot's conversation gets no answer."
            )
        if own_pr:
            text += (
                "\n- A new version of the PR, when a maintainer or reviewer asked for changes, its checks failed, or a bot found a real bug "
                "in the change. Its branch is "
                f"{head['branch']} in the user's fork {head['repo']}, newest commit {head['sha']}. In the VM, in the project's "
                f"folder (~/{repo.split('/')[1]}; clone it if it isn't there): `git fetch https://github.com/{head['repo']} "
                f"{head['branch']} && git switch -C pr-{number} {head['sha']}`, and work on top of that commit. Commit your "
                f"change on pr-{number} in the project's style, then run the tests once, with your change: run_tests with "
                f"when: after, base {head['sha']}, and the checks the project's rules ask for before a PR, however long. No "
                "when: before run on the main branch: the PR's first version already had one. Then draft_pr with pr "
                f"{thread} and "
                f"base {head['sha']}: its title is the commit message's subject, its body the comment posted on the PR with "
                "the push (what changed, in a line or two, and your answers to the maintainers and reviewers this round); "
                "leave the body empty when none of them asked for it."
                "\n- A rebase of the PR, when a maintainer asks for one, it conflicts with main, or a reviewer asks to squash, "
                f"reword or sign off its commits. Fetch its branch the same way, then on pr-{number} `git fetch origin && git "
                "rebase origin/<the branch it goes into>` (or rewrite the commits as asked), settle each conflict keeping what "
                "both sides meant, commit, and run the checks the project's rules ask for before a PR, however long: run_tests "
                "with when: after and base the commit your branch now starts from (e.g. origin/main). Then draft_pr with pr "
                f"{thread}, that base and rebase: true; Approve force-pushes it. Its body is the comment posted with the push "
                "(what it is rebased onto, and how each conflict was settled)."
            )
        if own:
            text += (
                f"\n- A new title or description, when someone asks for one on the user's own {what}, or its text no longer "
                f"matches what it does: draft_edit with target {thread}. Approve changes them on GitHub as the user."
            )
        text += (
            f"\n- Nothing, when nothing needs an answer (a thank-you, a bot's note with no findings, checks that passed, a "
            f"label, an approval without questions, anything from someone who is neither a maintainer nor a reviewer, or "
            f"from a bot, that the merge doesn't need), or when only the maintainers or the project's gate can move it on "
            f"(a draft its gate keeps until their label or their OK to run the workflows; no tool of yours marks a PR "
            f"ready for review, changes labels or approves checks): job_update {job['id']} with status done and a note on "
            "why. You own it for the user: you hear about every change there, and a new job comes with the next one."
        )
        if entry["kind"] == "pr" and not own_pr:
            text += "\nThe PR's code isn't the user's to change: a reply or nothing."
        # The user's own words there are ours, not someone else's to answer or step aside for (QwenPaw#8698).
        login = self.your_repositories.github_account.status().get("login")
        if login:
            text += (
                f"\nThe user's GitHub login is {login}: whatever {login} wrote there is ours (read_issue marks it by_user): "
                "never answer it, and never take it for someone else."
            )
        if vm_name is None:
            text += (
                "\nYou have no target VM. Reproducing and a new version need one: pick it with vms_list and choose_vm, then "
                "queue_for_vm. Only a reply with nothing to reproduce (a thank-you, a question about plans) needs none."
            )
        else:
            text += (
                f"\nIt is for {vm_name}: queue_for_vm to reproduce and for a new version. Only a reply with nothing to reproduce "
                "(a thank-you, a question about plans) needs no VM."
            )
        self.notify(agent.id, text)
        return job

    def decide(self, draft_id: str, decision: str, reply: str = "", answered_by: str = "user") -> dict:
        """The user's decision on a draft (approved, rejected or replied) goes to its agent, and its job is open again,
        unless another draft of it still waits (a PR draft with its reviewer or in the Inbox). answered_by is "automation"
        when the repo's or issue's Level of automation answers an old question at once (backend/repo_automation_api.py),
        and "agent" when the agent took its own blocker back ("cleared", work_tools.py clear_blocker): it knows already."""
        draft = self.inbox.decide(draft_id, decision, reply, answered_by)
        job = None
        if draft["job"] is not None:
            job = self.jobs.get(draft["job"])

        # A fix_issue job's one comment is its claim (WorkTools.draft_comment). It never held the job up, so deciding it
        # leaves the job as it is (it may wait on the user for its PR by now).
        claim = draft["kind"] == "comment" and job is not None and job["kind"] == "fix_issue"
        # Another draft of the job still waits (a PR draft with its reviewer or in the Inbox): the job keeps
        # waiting on the user until that one is decided too (openmed#5511: an approved new description put the job back
        # in the queue while its PR draft was still with the reviewer, so the heartbeat and the VM's reminders woke it
        # over and over, and job_progress made it working). A claim waits for nothing.
        others = []
        if job is not None:
            for other_id in job["drafts"]:
                try:
                    other = self.inbox.get(other_id)
                except KeyError:
                    # Deleted from the Inbox.
                    continue
                if other_id != draft_id and other["status"] == "pending" and not (other["kind"] == "comment" and job["kind"] == "fix_issue"):
                    others.append(other_id)
        if job is not None and job["status"] == "waiting_on_user" and not claim and not others:
            job = self.jobs.update(job["id"], status="queued")

        kinds = {"pr": "PR", "comment": "comment", "question": "question", "edit": "title and description", "approval": "approval request"}
        about = f"your {kinds.get(draft['kind'], draft['kind'])} draft {draft_id} ({draft['title']})"
        job_name = job["id"] if job is not None else "your work"
        # Approve sends a PR or comment first when the user's GitHub account is connected (inbox_api.py): then it is on GitHub.
        sent = draft["sent"]
        # A new version of the user's open PR (update_of): pushed onto its branch, and the body posted there as a comment.
        if decision == "approved" and draft["kind"] == "pr" and sent is not None and sent.get("update"):
            text = (
                f"The user approved {about}, and it is pushed onto their PR {sent['url']} (branch {sent['branch']} of "
                f"{sent['fork']}, now at {sent['commit'][:10]})."
            )
            if sent.get("rebase_of"):
                text = (
                    f"The user approved {about}, and it is force-pushed onto their PR {sent['url']}: branch {sent['branch']} of "
                    f"{sent['fork']} is now your rebased commits, at {sent['commit'][:10]}, instead of {sent['rebase_of'][:10]}."
                )
            if sent["comment_url"]:
                text += f" Your text is posted there as their comment: {sent['comment_url']}."
            if sent["comment_error"]:
                text += f" The comment couldn't be posted ({sent['comment_error']}); tell the user in one line."
            text += f" Put the link in the job's notes. If it finishes {job_name}, mark the job done with job_update."
        elif decision == "approved" and draft["kind"] == "pr" and sent is not None:
            text = (
                f"The user approved {about}, and it is on GitHub now, as their PR: {sent['url']} (branch {sent['branch']} of "
                f"{sent['fork']}). Put the link in the job's notes. If it finishes {job_name}, mark the job done with job_update."
            )
        elif decision == "approved" and draft["kind"] == "pr" and draft["update_of"]:
            text = f"The user approved {about}. They push it onto {draft['update_of']} themselves. If it finishes {job_name}, mark the job done with job_update."
            if draft["rebase_of"]:
                text = f"The user approved {about}. They force-push it onto {draft['update_of']} themselves. If it finishes {job_name}, mark the job done with job_update."
        elif decision == "approved" and draft["kind"] == "pr":
            text = f"The user approved {about}. They send it to GitHub themselves. If it finishes {job_name}, mark the job done with job_update."
        elif decision == "approved" and draft["kind"] == "edit" and sent is not None:
            text = f"The user approved {about}, and {sent['repo']}#{sent['number']} has the new text on GitHub now: {sent['url']}. Carry on with {job_name}."
        elif decision == "approved" and draft["kind"] == "edit":
            text = f"The user approved {about}. They change it on GitHub themselves. Carry on with {job_name}."
        elif decision == "approved" and claim and sent is not None:
            text = (
                f"The user approved {about}, and it is posted: {sent['url']}. Nothing else to do for it: nobody waits for the "
                f"maintainers to assign the user, so {job_name} goes on as it is."
            )
        elif decision == "approved" and claim:
            text = (
                f"The user approved {about}. They post it themselves. Nothing else to do for it: nobody waits for the "
                f"maintainers to assign the user, so {job_name} goes on as it is."
            )
        elif decision == "approved" and draft["kind"] == "comment" and sent is not None:
            text = f"The user approved {about}, and it is posted: {sent['url']}."
            if sent.get("resolved"):
                text += " Its conversation is resolved now."
            if sent.get("resolve_error"):
                text += f" Its conversation couldn't be resolved ({sent['resolve_error']}); tell the user in one line."
            text += f" Carry on with {job_name}."
        elif decision == "approved" and draft["kind"] == "comment":
            text = f"The user approved {about}. They post it themselves. Carry on with {job_name}."
        elif decision == "approved" and draft["kind"] == "approval":
            # A blocker only the user could lift (work_tools.py ask_approval): the agent goes on and does what it asked for.
            # The user clicks Done only once it is done, so the agent never checks it or asks for it again.
            text = f"The user approved {about}: Done means it is done."
            if reply:
                text += f" Their note: {reply}"
            text += (
                f" Carry on with {job_name}. Don't check whether they did it and don't ask for it again: a bot or page that "
                "doesn't show it yet catches up by itself. What you said you would do on Approve, do now. A CLA: sign it the "
                "way the project asks, from the user's account, through your drafts (the bot's sign line as a draft_comment on "
                "the PR once its bot asks, a PR adding the user to its contributors file, or the license line in the PR's "
                "text). One only a sign page can sign (cla-assistant.io) the user signed there themselves."
            )
        elif decision == "cleared":
            # The agent took its own blocker back: it went away by itself (work_tools.py clear_blocker).
            text = f"{about} is off the Blockers page: it doesn't hold {job_name} up any more. Carry on with it."
        elif decision == "rejected" and draft["kind"] == "approval":
            text = f"The user rejected {about}."
            if reply:
                text += f" Their note: {reply}"
            text += (
                f" Give {job_name} up (prompt: Approvals): no PR yet, cancel it with job_update and take back a claim you "
                "posted (delete_comment); a PR of ours open, close_pr with a short polite comment, then mark the job done."
            )
        elif decision == "approved":
            text = f"The user approved {about}. Carry on with {job_name}."
        elif decision == "rejected" and claim:
            text = f"The user rejected {about}: no claim."
            if reply:
                text += f" Their note: {reply}"
            text += f" Go on with {job_name} without one, unless their note says otherwise."
        elif decision == "rejected":
            text = f"The user rejected {about}."
            if reply:
                text += f" Their note: {reply}"
            text += f" Don't draft it again as it is: change course, or cancel {job_name} with job_update if it no longer makes sense or you aren't sure."
        elif answered_by == "automation":
            # Its repo's (or issue's) Level of automation answers questions at once (backend/repo_automation_api.py).
            text = (
                f"The user lets the app answer questions there for them, so it picked your recommendation for {about}: "
                f"{draft['recommended']}. Go on with that on {job_name}, and say in its progress that you did."
            )
        else:
            text = f"The user replied to {about}:\n{reply}\nDo what they say and keep working on {job_name}; draft again when it's ready."
            # The user wants work done: an archived agent comes back for it.
            if draft["agent"] in self.agents:
                self.unarchive(draft["agent"])
        # A follow-up's reply that went out often answers everything there was.
        if decision == "approved" and draft["kind"] == "comment" and job is not None and job["kind"] == "follow_up":
            text += f" If that answers everything on {job['thread']} for now, mark {job['id']} done; the app makes a new job when someone writes there again."
        # The user changed the text before deciding: the agent sees how they wanted it, to write it that way next time.
        if draft["edited"]:
            final = draft["body"]
            if draft["kind"] in ["pr", "edit"]:
                final = f"{draft['title']}\n\n{draft['body']}"
            text += f"\nThe user edited your draft before deciding. The final text:\n{final}\nSee what they changed, and write it their way next time."
        # An agent that still holds its desktop of the job's VM (for other work there) goes on there at once.
        held_vm, place = self.queue.place(draft["agent"])
        if job is not None and job["status"] == "queued" and job["vm"] is not None and held_vm == job["vm"] and place == 0:
            text += f"\n{job['id']} is queued again, and you still hold your desktop of {job['vm']}: go on with it there now."
        elif job is not None and job["status"] == "queued" and job["vm"] is not None:
            text += f"\n{job['id']} is queued again; use queue_for_vm if you need {job['vm']} for it."
        if job is not None and job["status"] == "waiting_on_user" and others:
            text += (
                f"\n{job['id']} still waits on your other draft {', '.join(others)}: nothing to do for it until that one is "
                "decided (you hear it then). Go on with your other jobs."
            )
        if answered_by != "agent":
            self.notify(draft["agent"], text)
        # A repo's CLA is signed once: the same decision goes to the other jobs' requests to sign it, still waiting.
        if draft["kind"] == "approval" and draft["overview"].get("kind") == "cla" and decision in ["approved", "rejected", "cleared"]:
            for other in self.inbox.list():
                if other["kind"] != "approval" or other["status"] != "pending" or other["overview"].get("kind") != "cla":
                    continue
                if (other["repo"] or "").lower() != (draft["repo"] or "").lower():
                    continue
                try:
                    self.decide(other["id"], decision, reply)
                except (KeyError, ValueError):
                    pass  # Decided in the meantime.
        return draft

    def on_grant(self, vm_name: str, agent_id: str) -> None:
        """The VM queue made the agent the holder (its turn came, or the user gave it the VM). Any thread.

        An agent with nothing left to do there (its jobs were cancelled or finished while it waited)
        passes the VM on at once: it never holds a VM with nothing to do, even while busy with other work.
        """
        if threading.get_ident() != self.loop_thread:
            self.loop.call_soon_threadsafe(self.on_grant, vm_name, agent_id)
            return
        agent = self.agents.get(agent_id)
        if agent is None:
            return
        jobs = [job for job in self.jobs.for_agent(agent_id) if job["status"] in OPEN_STATUSES and job["vm"] == vm_name]
        if jobs:
            titles = ", ".join(f"{job['id']} ({job['title']})" for job in jobs)
            # Its notes come with it, so the agent always knows what earlier agents left in it.
            try:
                vm_record = self.vms.get(vm_name)
                notes = vm_record.notes
                desktop = vm_record.holding(agent_id)
            except VMsError:
                notes = []
                desktop = None
            text = f"Desktop {desktop} of {vm_name} is yours now. Your open jobs for it: {titles}. Do them all, then release_vm."
            # Commits are made as the user, the way they go out (github_account.py): draft_pr refuses any other address.
            account = self.your_repositories.github_account.load()
            if account is not None:
                text += (
                    f"\nCommit as the user, with their GitHub name and noreply address: `git config --global user.name "
                    f"\"{account['name']}\" && git config --global user.email \"{account['id']}+{account['login']}@users.noreply.github.com\"` "
                    "(a repo's own git config wins over it, so fix that too where one is set). Never another address, and never "
                    "the email address in your own context: it is private."
                )
            # In full only the notes for the repos of its open jobs here and the VM-wide ones (the user's, and those naming
            # no repo any job was for); the other repos only by name. All of vm1's 108 notes made this 53,000 characters,
            # and agents missed the git identity above under them.
            known = set(job["repo"].lower() for job in self.jobs.list() if job["repo"])
            own = set(job["repo"].lower() for job in jobs if job["repo"])
            shown = []
            others = set()
            for note in notes:
                # The repos it names, as owner/name (vm_note_add asks for that).
                named = set(name.rstrip(".") for name in re.findall(r"[\w.-]+/[\w.-]+", note["text"].lower()))
                if note["by"] != "user" and named & known and not named & own:
                    others.update(named & known)
                    continue
                shown.append(note)
            if shown:
                text += "\nIts notes for your jobs' repos and the whole VM (check what is really there before you rely on them):"
            for note in shown:
                by = self.agents[note["by"]].name if note["by"] in self.agents else note["by"]
                on = f", on desktop {note['desktop']}" if "desktop" in note else ""
                text += f"\n- {note['id']} by {by}, {note['at'][:10]}{on}: {note['text']}"
            if others:
                text += "\nOther repos with notes here (vms_list with repo shows a repo's notes): " + ", ".join(sorted(others)) + "."
            if not notes:
                text += "\nIt has no notes yet: nobody wrote down what is set up in it."
            self.notify(agent_id, text)
            return
        agent.history.append({"type": "system", "text": f"Passed {vm_name} on: no open jobs for it", "time": datetime.now(UTC).isoformat()})
        self.version += 1
        try:
            self.queue.release(vm_name, agent_id)
        except (ValueError, VMsError):
            # The user took it, or deleted the VM, in the meantime.
            pass

    async def keep_going(self) -> None:
        """The heartbeat (module docstring), every HEARTBEAT_CHECK_SECONDS: an agent with a job queued or working, out of
        its turn for HEARTBEAT_SECONDS, is woken to carry on, unless it waits in a VM's line or for a VM while none takes
        agents (woken here once one does), a run of its goes, the user
        stopped it, or it is archived. A job waiting on the user isn't open work here: the user's answer wakes it. Nor is
        one with a draft that still waits (a PR draft with its reviewer or in the Inbox), whatever its status
        says: the reviewer's verdict or the user's decision wakes it. A fix_issue job's claim holds nothing up. A blocker
        waiting for the user is tried again by its agent every BLOCKER_RETRY_SECONDS."""
        while True:
            await asyncio.sleep(HEARTBEAT_CHECK_SECONDS)
            now = datetime.now(UTC)
            # A blocker waiting for the user, tried again by its agent every BLOCKER_RETRY_SECONDS: it may have gone away
            # by itself (2026-11-20: 7 jobs asked the user to renew a GitHub token, and sat there after GitHub worked again).
            for draft in self.inbox.pending():
                if draft["kind"] != "approval":
                    continue
                last = draft.get("retried_at") or draft["created_at"]
                if now - datetime.fromisoformat(last) < timedelta(seconds=BLOCKER_RETRY_SECONDS):
                    continue
                agent = self.agents.get(draft["agent"])
                if agent is None or agent.record["archived_at"] is not None or agent.busy or agent.stopped:
                    continue
                self.inbox.retried(draft["id"])
                text = (
                    f"Blocker check: {draft['id']} ({draft['title']}) has held {draft['job']} up on the user's Blockers page "
                    f"since {draft['created_at'][:16].replace('T', ' ')} UTC. See if it is still in the way: try again what "
                    "needed it (the call or check that failed, whether the CLA bot or the project shows it signed now). Gone: "
                    "take it back with clear_blocker and carry on with the job. A problem in the app or its tools (a GitHub "
                    "error, a token, a tool or VM that fails) was never a blocker: clear_blocker it, report_problem it if you "
                    "haven't, and carry on; if it still fails, stop for now and the heartbeat wakes you to try again. Still in "
                    "the way: leave it as it is and go back to what you were doing; you are asked again in an hour."
                )
                self.pending[agent.id].append({"from": "System", "text": text, "shown": False})
                self.wake[agent.id].set()
            # Waiting for a VM because none took agents (waiting_for_vm): woken once one does.
            takes = []
            for vm_record in self.vms.list():
                if vm_record.name != FIX_VM and vm_record.status == "running" and not vm_record.graceful_shutdown and not vm_record.suspended:
                    takes.append(vm_record.name)
            for agent_id in list(self.waiting_for_vm):
                if not takes:
                    break
                self.waiting_for_vm.discard(agent_id)
                self.version += 1
                if agent_id not in self.agents or self.agents[agent_id].record["archived_at"] is not None:
                    continue
                text = f"A VM takes agents again ({', '.join(takes)}): carry on with your open jobs, queue_for_vm when you need it."
                self.pending[agent_id].append({"from": "System", "text": text, "shown": False})
                self.wake[agent_id].set()
            running = []
            for vm_record in self.vms.list():
                running += [run["agent"] for run in vm_record.runs]
            # The open jobs with a draft that still waits (openmed#5511: woken again and again while its PR draft was with
            # the reviewer; itsaplan#826: while its question waited for the user, after the agent set the job working).
            waiting = []
            for job in self.jobs.list():
                if job["status"] not in OPEN_STATUSES:
                    continue
                for draft_id in job["drafts"]:
                    try:
                        draft = self.inbox.get(draft_id)
                    except KeyError:
                        # Deleted from the Inbox.
                        continue
                    if draft["status"] == "pending" and not (draft["kind"] == "comment" and job["kind"] == "fix_issue"):
                        waiting.append(job["id"])
            for agent in list(self.agents.values()):
                if agent.record["archived_at"] is not None or agent.busy or agent.stopped or self.wake[agent.id].is_set():
                    continue
                open_jobs = [job for job in self.jobs.for_agent(agent.id) if job["status"] in OPEN_STATUSES and job["id"] not in waiting]
                # A run of its goes: watch_runs wakes it when it ends.
                if not open_jobs or agent.id in running:
                    continue
                # Its place in a VM's line: the grant wakes it. Waiting for a VM while none takes agents: woken above.
                vm_name, place = self.queue.place(agent.id)
                if (place is not None and place > 0) or agent.id in self.waiting_for_vm:
                    continue
                # Out of its turn long enough.
                times = [entry["time"] for entry in agent.history[-500:] if entry.get("time")]
                if times and now - datetime.fromisoformat(times[-1]) < timedelta(seconds=HEARTBEAT_SECONDS):
                    continue
                titles = ", ".join(f"{job['id']} ({job['title']})" for job in open_jobs)
                text = (
                    f"Heartbeat: you have open jobs and nothing is running: {titles}. Carry on with them now, from where you "
                    "left off (queue_for_vm when you need the VM). Don't stop or wait without a reason. When one is truly "
                    "blocked on something only the user could give or allow, ask_approval; when it can't be done, give it up: "
                    "cancel it with job_update and say why. A problem in the app or its tools you reported (a GitHub error, a "
                    "tool or VM that fails) may be fixed by now: try again. It is never a blocker for the user and never a "
                    "reason to give a job up: if it still fails, stop for now and you are woken to try again."
                )
                self.pending[agent.id].append({"from": "System", "text": text, "shown": False})
                self.wake[agent.id].set()
            # An agent whose work is over is archived: no job left open, no message waiting, no draft of its waiting (with
            # its reviewer, in the Inbox, or approved and not sent), no run and no place in a VM. Its conversation stays.
            # News on a PR of its that is still open brings it back (follow_up); news on one that was merged or closed goes
            # to the closed PRs agent instead. Not a reviewer or that agent: they stay for their next one.
            drafting = []
            for draft in self.inbox.list():
                if draft["status"] == "pending" or (draft["status"] == "approved" and draft["sent"] is None):
                    drafting.append(draft["agent"])
            for agent in list(self.agents.values()):
                if agent.record["archived_at"] is not None or agent.busy or self.pending[agent.id] or self.wake[agent.id].is_set():
                    continue
                if agent.record["role"] in ["reviewer", "closed_prs"] or agent.id in running or agent.id in drafting:
                    continue
                if [job for job in self.jobs.for_agent(agent.id) if job["status"] not in ["done", "cancelled"]]:
                    continue
                vm_name, place = self.queue.place(agent.id)
                if place is not None:
                    continue
                await self.archive(agent.id)

    async def count_vm_time(self) -> None:
        """Every VM_TIME_SECONDS, each agent holding a VM desktop adds that much to the job it works on (jobs.py
        vm_seconds), while that job is working: its tests, builds and everything else it does there count. Waiting in a
        VM's line doesn't."""
        while True:
            await asyncio.sleep(VM_TIME_SECONDS)
            for agent in list(self.agents.values()):
                job_id = agent.work["job"]
                if job_id is None:
                    continue
                vm_name, place = self.queue.place(agent.id)
                if place != 0:
                    continue
                try:
                    job = self.jobs.get(job_id)
                except KeyError:
                    continue
                if job["status"] != "working":
                    continue
                self.jobs.add_vm_seconds(job_id, VM_TIME_SECONDS)

    async def watch_desktops(self) -> None:
        """Desktops nobody needs anymore shut down right away (module docstring), every DESKTOP_CHECK_SECONDS: one nobody
        holds or has a run on, seen so on two checks in a row (a desktop queue_for_vm just added is given out in between).
        An agent keeps its desktop while it holds it, also asleep or while its long runs go. Not while agents wait for
        the VM (the desktop goes to them), it is off, or it shuts down gracefully. vm1 kept 4 desktops for 1 agent while
        this waited 10 minutes: the user wants them gone as soon as nobody needs them."""
        # The desktops seen unused on the last check: (VM name, number).
        unused = set()
        while True:
            await asyncio.sleep(DESKTOP_CHECK_SECONDS)
            seen = set()
            for vm_record in self.vms.list():
                if vm_record.status != "running" or vm_record.name == FIX_VM or vm_record.graceful_shutdown or vm_record.queue:
                    continue
                runs = [run.get("desktop", 1) for run in vm_record.runs]
                # The VM keeps one desktop: the lowest, when none is in use.
                kept = min(vm_record.desktops)
                for number, line in vm_record.desktops.items():
                    if line["holder"] is not None or number in runs:
                        kept = None
                for number, line in vm_record.desktops.items():
                    if line["holder"] is None and number not in runs and number != kept:
                        seen.add((vm_record.name, number))
                for number in list(vm_record.desktops):
                    if (vm_record.name, number) not in seen or (vm_record.name, number) not in unused:
                        continue
                    try:
                        await asyncio.to_thread(vm_record.remove_desktop, number, self.queue.lock)
                    except VMsError:
                        # Busy, or someone took it meanwhile: again next check.
                        pass
            unused = seen

    async def watch_room(self) -> None:
        """A VM steps down when it runs out of room (module docstring), every ROOM_CHECK_SECONDS: each running VM's free
        memory and free disk are read in it. Full: nobody new gets a desktop (VMQueue.full, with why). Overloaded: one
        desktop is taken back from its agent and removed. Low on disk: its holders are told once to free room in their
        homes. Room again: whoever waits gets a desktop, one a check."""
        while True:
            await asyncio.sleep(ROOM_CHECK_SECONDS)
            # Graceful shutdown and Suspend (sandbox/vms.py): an agent still waiting for it (its desktop was taken back, or
            # it queued just before) leaves the line and picks another VM. Graceful shutdown only: once nobody holds a
            # desktop and no run goes, it shuts down.
            for vm_record in self.vms.list():
                if not vm_record.graceful_shutdown and not vm_record.suspended:
                    continue
                why = "is suspended"
                if vm_record.graceful_shutdown:
                    why = "shuts down once the agents on it are done"
                for agent_id in list(vm_record.queue):
                    self.queue.leave_all(agent_id)
                    if agent_id not in self.agents:
                        continue
                    self.set_target_vm(agent_id, None, by_agent=True)
                    # No other VM takes agents: it waits for one (waiting_for_vm), told when keep_going wakes it, so it
                    # isn't woken just to end its turn.
                    takes = []
                    for each in self.vms.list():
                        if each.name != FIX_VM and each.status == "running" and not each.graceful_shutdown and not each.suspended:
                            takes.append(each.name)
                    if not takes:
                        self.waiting_for_vm.add(agent_id)
                        text = f"{vm_record.name} {why} and takes nobody new, so you were taken out of its queue and have no target VM."
                        self.pending[agent_id].append({"from": "System", "text": text, "shown": False})
                        self.version += 1
                        continue
                    self.notify(
                        agent_id,
                        f"{vm_record.name} {why} and takes nobody new, so you are out of its "
                        "queue and have no target VM. Pick another with vms_list and choose_vm, queue_for_vm, set your project up "
                        "there if it isn't, and carry on.",
                    )
                if not vm_record.graceful_shutdown:
                    continue
                holders = [line["holder"] for line in vm_record.desktops.values() if line["holder"] is not None]
                if vm_record.status != "running" or holders or vm_record.runs:
                    continue
                try:
                    self.vms.stop_in_background(vm_record.name)
                except VMsError:
                    # Busy (a start or stop going on): again next time.
                    pass

            for vm_record in self.vms.list():
                if vm_record.status != "running":
                    self.queue.full.pop(vm_record.name, None)
                    self.disk_low.discard(vm_record.name)
                    continue
                # The memory in all and free (kB), then the disk the desktops' homes are on, in all and free (kB).
                script = "awk '/^MemTotal:|^MemAvailable:/ {print $2}' /proc/meminfo; df -Pk /home | awk 'NR == 2 {print $2, $4}'"
                try:
                    result = await asyncio.to_thread(vm_record.vm.exec_root, script, 30)
                    numbers = result.stdout.split()
                    free = int(numbers[1]) * 100 / int(numbers[0])
                    disk_gb = int(numbers[2]) / 1024 / 1024
                    disk_free_gb = int(numbers[3]) / 1024 / 1024
                except Exception:
                    # The VM doesn't answer right now: look again next time.
                    continue

                # The disk running low: the agents holding its desktops are told once, to free what they can in their own
                # homes now (nobody else can: each home is its desktop's). vm1's disk sat at 98 to 100% for days, full of
                # agents' old clones and caches, and broke 2-hour test runs (ENOSPC, SQLITE_FULL: prb_69d8c4, prb_c4dd4b).
                # Only the agents holding its desktops can free it, so with nobody on it a low disk holds nobody back:
                # otherwise nobody would ever get in to free it. The next one in is told at the next check.
                holders = [line["holder"] for line in vm_record.desktops.values() if line["holder"] in self.agents]
                disk_short = disk_free_gb < ROOM_DISK_GB and len(holders) > 0
                if disk_free_gb >= ROOM_DISK_GB:
                    self.disk_low.discard(vm_record.name)
                if disk_short and vm_record.name not in self.disk_low:
                    self.disk_low.add(vm_record.name)
                    text = (
                        f"{vm_record.name}'s disk is nearly full: {disk_free_gb:.1f} GB free of {disk_gb:.0f} GB. Nobody new "
                        f"gets a desktop there until {ROOM_DISK_GB} GB are free, and runs fail for lack of room. Free what you "
                        "can in your own home now, then go on: the folders of jobs that are over (a PR merged or closed, a job "
                        "cancelled, or a repo vms_list marks with no open job: the clone, its builds and environments), with "
                        "their notes (vm_note_remove), and caches that fill again by themselves (~/.cache/pip, ~/.cache/uv, "
                        "~/.npm/_cacache, ~/.local/share/pnpm/store, ~/.cache/go-build, ~/.cargo/registry/cache). Never "
                        "another desktop's home, a folder a run works in, ~/.cache/sandbox-runs (the app's), or Docker's images."
                    )
                    for holder in holders:
                        self.notify(holder, text)

                # Room is memory: the CPU load holds nobody back (the user: agents add desktops as long as memory allows,
                # up to the VM's max desktops).
                if free >= ROOM_MEMORY_PERCENT and not disk_short:
                    self.queue.full.pop(vm_record.name, None)
                    # Room: a free desktop goes to whoever waits.
                    try:
                        await asyncio.to_thread(self.queue.fill, vm_record.name)
                    except VMsError:
                        continue
                    # Then a desktop the VM lacks is added for the first one waiting for it (taken back from it) or for
                    # any desktop, up to the VM's max desktops.
                    add = False
                    number = None
                    for agent_id in list(vm_record.queue):
                        wanted = vm_record.wants.get(agent_id)
                        if not add and (wanted is None or wanted not in vm_record.desktops):
                            add = True
                            number = wanted
                    if not add or len(vm_record.desktops) >= vm_record.max_desktops:
                        continue
                    try:
                        await asyncio.to_thread(vm_record.add_desktop, self.queue.lock, number)
                        await asyncio.to_thread(self.queue.fill, vm_record.name)
                    except VMsError:
                        # The VM is busy (a start, a stop, another desktop) or gone: again next time.
                        pass
                    continue

                # Full, with why, for the agents that wait (queue_for_vm, desktop_add). A full disk alone takes no desktop
                # back: that frees no room.
                why = []
                if free < ROOM_MEMORY_PERCENT:
                    why.append(f"{free:.0f}% of its memory free")
                if disk_short:
                    why.append(f"{disk_free_gb:.1f} GB of its disk free")
                self.queue.full[vm_record.name] = ", ".join(why)
                if free >= OVERLOAD_MEMORY_PERCENT:
                    continue
                last = vm_record.stepped_down_at
                if last is not None and datetime.now(UTC) - datetime.fromisoformat(last) < timedelta(seconds=STEP_DOWN_SECONDS):
                    continue
                # A VM shutting down gracefully or suspended keeps the agents on it: taken back, a desktop would never
                # come back.
                if len(vm_record.desktops) < 2 or vm_record.graceful_shutdown or vm_record.suspended:
                    continue
                # Overloaded: a desktop is taken back. Never from an agent the user gave priority; from one on a pull
                # request that needs action only when nobody else is left, from one reviewing a PR draft only when
                # nobody but those is. From one out of its turn first (nothing is cut off), then from the highest
                # desktop.
                chosen = None
                for line in vm_record.desktops.values():
                    agent = self.agents.get(line["holder"])
                    if agent is None or agent.id in self.queue.prioritized or agent.id in self.queue.reviewing:
                        continue
                    if chosen is None or chosen.busy or not agent.busy:
                        chosen = agent
                reviewer = None
                for line in vm_record.desktops.values():
                    agent = self.agents.get(line["holder"])
                    if agent is None or agent.id in self.queue.prioritized:
                        continue
                    if reviewer is None or reviewer.busy or not agent.busy:
                        reviewer = agent
                fallback = None
                for line in vm_record.desktops.values():
                    agent = self.agents.get(line["holder"])
                    if agent is None or agent.record["priority"]:
                        continue
                    if fallback is None or fallback.busy or not agent.busy:
                        fallback = agent
                if chosen is None:
                    chosen = reviewer
                if chosen is None:
                    chosen = fallback
                if chosen is None:
                    continue
                try:
                    number = self.queue.step_down(vm_record.name, chosen.id)
                except (ValueError, VMsError):
                    continue
                text = (
                    f"{vm_record.name} ran out of room ({free:.0f}% of its memory free), so "
                    f"the app took desktop {number} back for now. Nothing you started there was stopped: your runs, servers and "
                    "files are all still there. You are at the front of its queue (behind the work that goes first) and get the "
                    "desktop back, with a message, once there is room. End your turn now."
                )
                chosen.history.append({"type": "system", "text": text, "time": datetime.now(UTC).isoformat()})
                # It hears it with its next message (the one giving the desktop back), or now if it is in a turn: the turn
                # stops, since its VM tools refuse without a desktop.
                self.pending[chosen.id].append({"from": "System", "text": text, "shown": True})
                self.save(chosen)
                self.version += 1
                await chosen.interrupt()
                try:
                    await asyncio.to_thread(vm_record.remove_desktop, number, self.queue.lock, True)
                except VMsError:
                    # The VM is busy: the desktop stays, free, until its agent gets it back.
                    pass

            # An agent waiting in a VM's line for any desktop, with nothing of its jobs set up there (no agent's note there
            # names one of their repos), goes to another running VM with a desktop free and nobody waiting: it sets its
            # project up from nothing either way. One that asked for a desktop (its project is there) waits for it.
            for vm_record in self.vms.list():
                named = set()
                for note in vm_record.notes:
                    if note["by"] != "user":
                        named.update(name.rstrip(".") for name in re.findall(r"[\w.-]+/[\w.-]+", note["text"].lower()))
                for agent_id in list(vm_record.queue):
                    if agent_id not in self.agents or agent_id in vm_record.wants:
                        continue
                    repos = set(job["repo"].lower() for job in self.jobs.for_agent(agent_id) if job["status"] in OPEN_STATUSES and job["repo"])
                    if named & repos:
                        continue
                    other = None
                    for each in self.vms.list():
                        free = [number for number, line in each.desktops.items() if line["holder"] is None]
                        if each.name == FIX_VM or each.name == vm_record.name or each.graceful_shutdown or each.suspended:
                            continue
                        if other is None and each.status == "running" and each.name not in self.queue.full and not each.queue and free:
                            other = each
                    if other is None:
                        continue
                    self.queue.leave_all(agent_id)
                    try:
                        self.set_target_vm(agent_id, other.name, by_agent=True)
                        place = self.queue.join(other.name, agent_id)
                    except (ValueError, VMsError):
                        continue
                    self.notify(
                        agent_id,
                        f"You waited in {vm_record.name}'s queue and nothing of your jobs is set up there, so the app moved you "
                        f"to {other.name}, which had a desktop free. Your target VM is {other.name} now and your open jobs moved "
                        "with it.",
                    )
                    # A desktop given right in join isn't reported by the queue: its message comes from here.
                    if place == 0:
                        self.on_grant(other.name, agent_id)

    async def clean_disks(self) -> None:
        """Agents' leftovers on each running VM's disk, cleared by the app itself every CLEAN_SECONDS: no agent has to
        remember it, and it costs no tokens. vm1 filled its 512 GB with clones of repos whose PRs were long merged, tool
        downloads and Docker images, while the agents told to free their homes (watch_room) freed little.

        A clone (a git folder at the top of a desktop's home, its origin on GitHub) goes when nobody works on its repo
        anymore: no job for it is open (paused and waiting ones count) and no PR of ours there is open, nobody touched it
        (its .git) for CLEAN_UNTOUCHED_DAYS, and its desktop has no holder and no run. Repos are matched by name, not
        owner, so a clone of a fork stays with its PR. The agents' notes on that desktop naming the repo go with it.
        With less than CLEAN_LOW_DISK_PERCENT of the disk free and no clone to delete, also the download caches
        (CLEAN_CACHES) in the homes of desktops with no holder and no run, and Docker's images no container uses (but
        not the ones the VM's image came with), unused volumes and build cache: all come back by themselves, at the
        cost of a download, so only then."""
        while True:
            await asyncio.sleep(CLEAN_SECONDS)
            # This computer's disk, where the VMs' disks are (11-26: vm1's filled it and the app's data files came out
            # empty). Nearly full: every VM clears as if its own were, and the Feedback page says so, once while open.
            host = shutil.disk_usage(INCUS_DIR)
            host_low = host.free * 100 / host.total < CLEAN_LOW_DISK_PERCENT
            start = "This computer's disk is nearly full"
            reported = [item for item in self.problems.list() if item["text"].startswith(start) and item["closed_at"] is None]
            if host_low and not reported:
                self.problems.add("seraph", None, None, f"{start}: {host.free / 1024 ** 3:.0f}GB free of {host.total / 1024 ** 3:.0f}GB. The VMs' disks are on it.")
            # The repos someone may still work on, by name: those of jobs not over and of our open PRs.
            keep = set()
            for job in self.jobs.list():
                if job["status"] in ["done", "cancelled"]:
                    continue
                for repo in [job.get("repo"), (job.get("thread") or "").split("#")[0], (job.get("issue") or "").split("#")[0]]:
                    if repo:
                        keep.add(repo.split("/")[-1].lower())
            try:
                tracking = json.loads((DATA_DIR / "pr_tracking.json").read_text())
            except (OSError, ValueError):
                # Which PRs are open isn't known: nothing goes.
                continue
            for pr in tracking.get("prs", {}).values():
                if pr["state"] == "open":
                    keep.add(pr["repo"].split("/")[-1].lower())

            for vm_record in self.vms.list():
                # Seraph's own VM holds the app's own clone, which no job names.
                if vm_record.status != "running" or vm_record.name == FIX_VM:
                    continue
                busy = set()
                for number, line in vm_record.desktops.items():
                    if line["holder"] is not None:
                        busy.add(number)
                for run in vm_record.runs:
                    busy.add(run.get("desktop", 1))
                try:
                    result = await asyncio.to_thread(vm_record.vm.exec_root, CLEAN_LIST_SCRIPT, 120)
                except Exception:
                    # The VM doesn't answer right now: again next time.
                    continue
                disk = []
                homes = []
                doomed = []
                now = datetime.now(UTC).timestamp()
                for line in result.stdout.splitlines():
                    parts = line.split("\t")
                    if line.startswith("disk "):
                        disk = [int(number) for number in line.split()[1:]]
                    if parts[0] == "home" and len(parts) == 3 and parts[1].isdigit() and int(parts[1]) not in busy:
                        homes.append(parts[2])
                    if parts[0] != "clone" or len(parts) != 5 or not parts[1].isdigit() or not parts[3].isdigit():
                        continue
                    name = parts[4].strip().rstrip("/").removesuffix(".git").split("/")[-1].lower()
                    if "github.com" not in parts[4] or int(parts[1]) in busy or name in keep:
                        continue
                    if now - int(parts[3]) < CLEAN_UNTOUCHED_DAYS * 24 * 60 * 60:
                        continue
                    doomed.append((int(parts[1]), parts[2], name))

                if doomed:
                    folders = " ".join(shlex.quote(folder) for number, folder, name in doomed)
                    try:
                        await asyncio.to_thread(vm_record.vm.exec_root, f"rm -rf -- {folders}\n{CLEAN_TRIM}", 30 * 60)
                    except Exception:
                        continue
                    gone = []
                    for note in vm_record.notes:
                        named = set(each.rstrip(".").split("/")[-1] for each in re.findall(r"[\w.-]+/[\w.-]+", note["text"].lower()))
                        if note["by"] == "user" or "desktop" not in note:
                            continue
                        if any(note["desktop"] == number and name in named for number, folder, name in doomed):
                            gone.append(note["id"])
                    if gone:
                        vm_record.remove_notes(gone, "app")
                        self.version += 1
                    # What that freed shows at the next round, before anything that has to be downloaded again goes.
                    continue

                if len(disk) != 2:
                    continue
                if disk[1] * 100 / disk[0] >= CLEAN_LOW_DISK_PERCENT and not host_low:
                    continue
                script = ""
                for home in homes:
                    script += "rm -rf -- " + " ".join(shlex.quote(f"{home}/{cache}") for cache in CLEAN_CACHES) + "\n"
                inventory = load_inventory(vm_record.image_fingerprint) or {"packages": []}
                protected = " ".join(package["name"] for package in inventory["packages"] if package["kind"] == "docker")
                script += f"protected={shlex.quote(protected)}\n" + CLEAN_DOCKER_SCRIPT + "\n" + CLEAN_TRIM
                try:
                    await asyncio.to_thread(vm_record.vm.exec_root, script, 30 * 60)
                except Exception:
                    pass

    async def watch_runs(self) -> None:
        """Every RUN_CHECK_SECONDS: the runs no tool call waits for. One that ended goes to its agent (run_ended).
        Then priority: it ends for an agent whose tasks are over, and each running VM gets it set again when its runs,
        its desktops' holders or who has priority changed (long_runs.prioritize)."""
        while True:
            await asyncio.sleep(RUN_CHECK_SECONDS)
            runs = []
            for vm_record in self.vms.list():
                runs += [(vm_record, run) for run in vm_record.runs if run["background"]]
            for vm_record, run in runs:
                try:
                    ended = await asyncio.to_thread(long_runs.check, vm_record, run)
                except Exception:
                    # The VM doesn't answer right now: look again next time.
                    continue
                if ended is None or not self.queue.claim_run(run["id"]):
                    continue
                try:
                    await self.run_ended(vm_record, run, ended)
                except Exception as error:
                    # Never lose the run: it is gone from the VM either way, and the agent hears why.
                    self.notify(run["agent"], f"Your run {run['id']} in {vm_record.name} ended, but its result couldn't be read: {error}")
                try:
                    self.queue.finish_run(vm_record.name, run["id"])
                except VMsError:
                    # The VM was deleted meanwhile.
                    pass

            # Tasks over: no open job, no run going and no turn.
            running = []
            for vm_record in self.vms.list():
                running += [run["agent"] for run in vm_record.runs]
            for agent in list(self.agents.values()):
                if not agent.record["priority"] or agent.busy or agent.id in running:
                    continue
                if [job for job in self.jobs.for_agent(agent.id) if job["status"] in OPEN_STATUSES]:
                    continue
                agent.record["priority"] = False
                if agent.id not in self.pr_priority:
                    self.queue.prioritized.discard(agent.id)
                agent.history.append({"type": "system", "text": "Priority ended: its tasks are over", "time": datetime.now(UTC).isoformat()})
                self.save(agent)
                self.version += 1

            for vm_record in self.vms.list():
                if vm_record.status != "running":
                    # Set again once it runs: a restart starts it over.
                    self.priority_set.pop(vm_record.name, None)
                    continue
                state = [[run["id"], run["agent"] in self.queue.prioritized] for run in vm_record.runs]
                state += [[number, line["holder"] in self.queue.prioritized] for number, line in vm_record.desktops.items()]
                if self.priority_set.get(vm_record.name) == state:
                    continue
                try:
                    await asyncio.to_thread(long_runs.prioritize, vm_record, set(self.queue.prioritized))
                except Exception:
                    # The VM doesn't answer right now: again next time.
                    continue
                self.priority_set[vm_record.name] = state

    async def run_ended(self, vm_record, run: dict, ended: dict) -> None:
        """A run in the background ended: its agent gets the result. One that waits in a VM's line (its desktop was taken
        back from a full VM, or the user took it) gets it with the message that a desktop is its again (finish_run,
        right after this, may give it one at once), so it starts one turn with both; any other agent is woken now."""
        agent = self.agents.get(run["agent"])
        if agent is None:
            return
        if run["kind"] == "tests":
            answer = await agent.work_tools.finish_tests(vm_record, run, ended)
            text = f"Your test run {run['id']} for {run['job']} ended. " + answer["content"][0]["text"]
        else:
            text = f"Your run {run['id']} in {vm_record.name} ended: `{run['label'][:200]}`, " + agent.computer_tools.bash_result(vm_record, run, ended)
        agent.history.append({"type": "system", "text": f"Its run in {vm_record.name} ended: {run['label'][:120]}", "time": datetime.now(UTC).isoformat()})
        vm_name, place = self.queue.place(agent.id)
        if place is None or place == 0:
            self.notify(agent.id, text)
            return
        text += f"\nYou get a desktop of {vm_name} back, with a message, as soon as one is yours; until then end your turn."
        self.pending[agent.id].append({"from": "System", "text": text, "shown": False})
        self.save(agent)
        self.version += 1

    async def stop_runs(self, agent_id: str) -> None:
        """The agent was archived or deleted: its runs end too (watch_runs then takes them off their VMs)."""
        self.queue.to_background(agent_id)
        for vm_record in self.vms.list():
            for run in [run for run in vm_record.runs if run["agent"] == agent_id]:
                try:
                    await asyncio.to_thread(long_runs.stop, vm_record, run)
                except Exception:
                    # The VM is off or doesn't answer: the run isn't going there then.
                    pass

    def on_kick(self, vm_name: str, agent_id: str, reason: str) -> None:
        """The user took the VM or the agent's queue place away. It is interrupted, not woken. Any thread."""
        if threading.get_ident() != self.loop_thread:
            self.loop.call_soon_threadsafe(self.on_kick, vm_name, agent_id, reason)
            return
        agent = self.agents.get(agent_id)
        if agent is None:
            return
        agent.history.append({"type": "system", "text": reason, "time": datetime.now(UTC).isoformat()})
        # It hears about it with its next message.
        self.pending[agent_id].append({"from": "System", "text": reason, "shown": True})
        self.version += 1
        self.loop.create_task(agent.interrupt())
        # Its commands still running in the VM (a long bash, typing) would go on under the new holder.
        self.loop.create_task(asyncio.to_thread(agent.computer_tools.cancel, vm_name))
