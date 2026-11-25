"""The Issues list's background work: the facts and tags of every issue on the board, Remove automatically, giving
Catalog's cards to agents, and remaking stalled PRs. The list itself has no page any more: the Automation fills it and
agents take from it.

Removing never takes out an issue an agent is working on (a job on it queued, working or waiting on the user), and
neither does an undo or redo (github_searcher/issue_list.py): its job has to be cancelled first. An agent gets an issue
(Agents.assign) only once it has a merge (see issue_tags.py), and not when that is fixed (only needs closing), out of
scope (not a pull request to that repo for its own users, only seen on Windows, macOS or a phone, or something the
user excludes) or can't validate: a job we can't prove ends with nothing to show.

The facts about each issue (age, last activity, assignees, linked PRs, ... see
github_searcher/issue_facts.py) are kept fresh by keep_facts(), which the app
runs in the background: new issues get theirs within FACTS_CHECK_SECONDS, and
all of them are fetched again every FACTS_REFRESH_SECONDS. Active issues (an agent
has a job on it: queued, working or waiting on the user) are fetched again every
ACTIVE_REFRESH_SECONDS, so a claim or a pull request by someone else shows within
a minute: a new comment changes the issue on GitHub, so keep_tags has Claude read it
again.

Each issue's tags (free / assigned / waiting, its merge: likely or what stands in the way, its kind:
github_searcher/issue_tags.py) are made by keep_tags(), also in the background, except an issue in the Issues list
with none yet or none read since it was added: keep_new_tags() tags those on its own, from fresh (an issue tagged before
it came in, by Add issues, is read again, and the new tags show on every page), every
NEW_TAGS_SECONDS and again right after a failure, so a new one never waits behind keep_tags' long rounds or
TAGS_RETRY_SECONDS. Remove automatically decides on an issue only once it has those. keep_tags: new issues get
theirs within TAGS_CHECK_SECONDS, an issue that changed on GitHub gets them again, and every issue is read again at the
board's refresh interval for where it is (below). An issue that moves on the board (Open, Catalog,
In progress, Needs action or Waiting approval; a job waiting in the queue is Catalog, as on the board) is read again by keep_tags at once, whatever
else holds (held, failed a moment ago), unless its tags are newer than MOVED_FRESH_SECONDS: so when an agent starts on a
Catalog card, a claim made while it waited there shows, and the agent hears who has it (Agents.issue_taken) and
decides. Not a move to finished.

AUTO_REMOVE_FILE holds the board's settings (saved once from an old page; max_agents now by the Automation page). How often the board's
issues are read again (keep_tags): refresh_open_minutes for ones no agent has started (30 at first), _catalog_ for ones
whose job waits in the queue (15), _ongoing_ for ones an agent works on or that wait on a review (5); finished ones
(job done) only when they change on GitHub. refresh_prs_minutes (10) is how often your open PRs, the board's Needs action
and Waiting approval, are read again from GitHub (keep_prs in backend/github_api.py). And Remove automatically,
which takes issues out of the Issues list by rules: claimed (someone is on it, or it is already fixed), out of scope,
complexity (easy, medium, hard), scope not clear, and opened more than older_than_days days ago (None: off). Only
issues no agent has started (no job on them, or only cancelled ones), so work in progress never goes. Saving applies
them at once, and again right after new tags come in (keep_new_tags, and keep_tags after a round that tagged
anything) and every AUTO_REMOVE_SECONDS anyway (an issue gets older), so an issue that matches later goes then. They
apply to Open and Catalog alike; an issue one of our agents opened (claimed for you) stays. Each time
anything goes it is one undo step of the list. One rule is always on, whatever the robot says: an issue of a repo
no longer in Repos, or archived there, goes from Open and Catalog alike (not one an agent has started). Deleting or
archiving a repo applies it at once (backend/repos_api.py).

Its max_agents (Concurrent agents on the Automation page, backend/automation_api.py) is how many agents work on the board's issues at once: agents with a job queued or working
on an issue in the Issues list, or on a follow-up on a pull request. keep_catalog_agents() looks every
CATALOG_AGENTS_SECONDS, and while there is room it gives Catalog's cards to new agents from the top, first come first
served (the board's order; ones not placed yet after, in the order they were added), each to its own new agent with the
first free agent-N name and no target VM, so the agent picks the VM that suits the job itself (Agents.assign). Only
cards of repos whose Level of automation has Take issues on (backend/repo_automation_api.py; the others wait there for
you), with tags read within twice the board's Catalog refresh time (refresh_catalog_minutes), and only while the repo is
under its Open PRs at once (its open PRs of yours and its issues with an open job before a
PR, from queued to waiting on you; backend/repo_automation_api.py): a repo at it is skipped and the next card of
another repo goes. With the Dashboard's Automation on, the cards of the repos it ranks first go first (its labels: Fast,
Normal, New, Slow, ...; then the most PRs merged a day: backend/automation_api.py), each in the board's order. Over that,
by the column its repo is in on the Repositories page (frontend/src/RepositoryCards.tsx, worked out here the same way):
Target first (not one rejected there: a PR of yours closed without a merge after it went there, which is in that page's
Catalog), then Prioritized, Contributed and last that page's Catalog (REPO_COLUMNS); ours stay first. The cards of a
repo in its Removed column wait, ours too: the ones you deleted (repo_list.py removed), and the ones where every PR of
yours was closed, none merged or open and no issue in progress, unless added to Target. So do the cards of a column
whose switch is off on that page (take_from in the Automation's file, backend/automation_api.py), ours too; what is
going there goes on. Only cards that are Catalog's own:
no job (or only cancelled ones), not paused, open on GitHub, and, like Assign, with its Merge in and not fixed, out of
scope or can't validate, and unlike Assign not claimed either: someone else is on it (assigned, or their open pull
request closes it), so a second fix isn't wanted; nor maintainers only, waiting, no
outside PRs or large feature, which a card picked as Likely can turn into when it is read again (DeepSeek-Reasonix
stopped taking outside PRs, oh-my-pi#17037 waited on a maintainer): no PR of ours would be merged now. The others wait
there, until a new read says otherwise. A card taken leaves Catalog's list, so
its job keeps it on the board, and a job cancelled later sends it back to Open, not to the next agent. Every round,
Catalog and the board's order drop the cards whose issue left the Issues list.

An issue one of our agents opened as you (open_issue in github_searcher/agent/work_tools.py, the Actions in inbox.py)
is claimed for you on GitHub, and we never give one up: an agent always takes it, whatever its repo's Take issues and
Open PRs at once say, and whoever else shows up on it later (tagged assigned); only not one that is closed, fixed or
out of scope. Each round, one of those no agent ever started goes back to the top of Catalog if it isn't there. Nothing
takes one off the board (not even its repo leaving Repos or being archived), no job on one is stopped for its repo, and
its agent is told to keep going when someone else shows up (Agents.issue_taken).

Take new issues off on the Automation page (take_new in its file, backend/automation_api.py) stops
keep_catalog_agents from giving out any of Catalog's cards, ours too, until it is on again; the rest goes on. The same
page's Open pull requests per repository (max_open_per_repo) lowers every repo's Open PRs at once to it, its Open pull
requests (max_open_prs) holds all repos together the same way (the same count, summed), and its AI policy (ai_policies)
says which repos' cards may be taken: a repo whose policy isn't read yet counts as unclear, no_ai never goes, and ours
go anyway.

A repo with Take issues on that is at its Open PRs at once is held (HELD, worked out by take_from_catalog every round):
its issues on the board's Open and Catalog (no job, or only cancelled ones) can't be taken now, so keep_facts and keep_tags
don't read them again until it has room, and Add issues doesn't read its open issues (backend/repo_automation_api.py).
That saves GitHub's quota for the repos that can take work. Once it has room, they are read again before an agent takes
one (the tags' age above).

Its stale_pr_days (14 at first, None: off) closes PRs that stalled: an open PR of yours that an agent owns
(opened from its draft, never one you opened by hand) with no update on GitHub for that many days is made again by its
agent as a fresh PR, all its changes on the newest code with a clean history and every review point done
(Agents.remake_pr); once the new one is on GitHub the old one is closed (github_account.py). Never one on an archived
or removed repo: it waits there as it is. keep_stale_prs() looks every STALE_CHECK_SECONDS. Once per PR: not while a job on it is open, and never again after its remake job.

An open job on a board issue the app no longer wants done is stopped by its agent (Agents.stop_job tells it, once):
the issue was deleted on GitHub or moved away (keep_facts finds it gone, drop_gone_issue: it then leaves the list for
good, so nothing tags, queues or takes it again), its repo was deleted from Repos, or the repo doesn't take AI-made
contributions (AI policy no_ai, repo_signals.py; stop_unwanted_jobs, every CATALOG_AGENTS_SECONDS). Catalog and Assign
never give an agent an issue of a no_ai repo.

When an issue goes from free to assigned either way, Agents.issue_taken tells the agent with a job on it who has it
(the assignees from its facts, or the tags' reason), and the agent decides itself whether to keep working or stop.
Each read also tells it of every open pull request of someone else's tied to the issue (issue_tags.open_prs: it says
it closes it, or only mentions it), once each, whatever the status: with nobody assigned, that is the news. One closed
on GitHub (its facts, read every ACTIVE_REFRESH_SECONDS while a job is on it) or tagged fixed since is news too
(Agents.issue_fixed): the agent stops before more long runs on a fix nobody wants anymore.
"""

import asyncio
import json
import time
import traceback
from datetime import UTC, datetime, timedelta

from backend.shared import agents, inbox, issue_facts, issue_tags, issues, jobs, pr_tracking, repo_signals, repos
from github_searcher.inbox import AUTOMATION_FILE
from github_searcher.issue_tags import CHECKS, DATA_DIR, NAME_VERSION, RULES_VERSION

FACTS_CHECK_SECONDS = 10
FACTS_REFRESH_SECONDS = 30 * 60
ACTIVE_REFRESH_SECONDS = 60
TAGS_CHECK_SECONDS = 10
# An issue that could not be tagged (Claude or GitHub down, the issue gone) is tried again after this long.
TAGS_RETRY_SECONDS = 30 * 60
# An issue in the Issues list with no tags yet is tagged within this long (keep_new_tags), and tried again as soon.
NEW_TAGS_SECONDS = 5
# An issue that moved on the board is read again at once, unless its tags are newer than this (keep_tags).
MOVED_FRESH_SECONDS = 120
# Remove automatically's rules; all off until saved once.
AUTO_REMOVE_FILE = DATA_DIR / "issue_auto_remove.json"
AUTO_REMOVE_OFF = {
    "claimed": False,
    "out_of_scope": False,
    "levels": [],
    "scope_not_clear": False,
    "older_than_days": None,
    "refresh_open_minutes": 30,
    "refresh_catalog_minutes": 15,
    "refresh_ongoing_minutes": 5,
    # How often your open PRs (Needs action and Waiting approval) are read again from GitHub (backend/github_api.py).
    "refresh_prs_minutes": 10,
    # Agents working on the board's issues at once, the next from the top of Catalog (keep_catalog_agents).
    "max_agents": 3,
    # An open PR an agent owns with no update on GitHub for this many days is made again fresh (keep_stale_prs); None: off.
    "stale_pr_days": 14,
}
# How often keep_catalog_agents looks for room for another agent on the board.
CATALOG_AGENTS_SECONDS = 30
# How often keep_stale_prs looks for PRs with no update for stale_pr_days.
STALE_CHECK_SECONDS = 10 * 60
# Remove automatically's rules apply right after new tags come in, and this often anyway (issues get older).
AUTO_REMOVE_SECONDS = 15 * 60
# The Dashboard's Automation (backend/automation_api.py, which imports this file): its labels rank the repos.
DASHBOARD_AUTOMATION_FILE = DATA_DIR / "automation.json"
# The repos (lower case) with Take issues on that are at their Open PRs at once now (take_from_catalog): their Open and
# Catalog issues aren't read again until they have room.
HELD = {"repos": []}
# The Repositories page's columns agents take new issues from, in the order they take them (take_from_catalog); its
# Removed column never.
REPO_COLUMNS = ["target", "prioritized", "contributed", "catalog"]
# The live "automation" topic's version (backend/app.py): up by one whenever the Dashboard's Automation
# (backend/automation_api.py) or any level of automation changes (the board's here, a repo's or an issue's:
# backend/repo_automation_api.py), so its Settings tab and the robot dialogs show the same at once. Here, as both those
# files import this one.
AUTOMATION_VERSION = {"version": 0}
# Set whenever issues get tagged (keep_new_tags, keep_tags), so keep_catalog (backend/repo_automation_api.py) moves the
# Open issues that fit to Catalog, and takes the rest off the board, right after.
TAGGED = asyncio.Event()


def auto_remove_issues() -> list[str]:
    """Take out of the Issues list what Remove automatically's rules pick, from Open and Catalog alike, as one undo step;
    returns the ids taken out. Only issues no agent has started: no job on them, or only cancelled ones. Those of a repo
    no longer in Repos (or archived there) always go, whatever the rules. One our agents opened (claimed for you) always
    stays: we never give one up."""
    # Until saved once the rules are all off: only the repo rule takes anything.
    rules = dict(AUTO_REMOVE_OFF)
    if AUTO_REMOVE_FILE.is_file():
        rules.update(json.loads(AUTO_REMOVE_FILE.read_text()))
    tags = issue_tags.all()
    facts = issue_facts.all()
    started = [job["issue"] for job in jobs.list() if job["issue"] is not None and job["status"] != "cancelled"]
    # The issues our agents opened as you (lower case): claimed for you on GitHub, so an agent fixes them.
    opened = []
    for action in inbox.actions():
        if action["kind"] == "issue":
            opened.append(f"{action['sent']['repo']}#{action['sent']['number']}".lower())
    # By repo name in lower case: an issue's repo may be spelled its own way.
    archived = [name.lower() for name in repos.archived()]
    in_repos = [item["full_name"].lower() for item in repos.items() if item["full_name"].lower() not in archived]
    cutoff = None
    if rules["older_than_days"] is not None:
        cutoff = datetime.now(UTC) - timedelta(days=rules["older_than_days"])
    picked = []
    for item in issues.items():
        if item["id"] in started or item["id"].lower() in opened:
            continue
        if item["repo"].lower() not in in_repos:
            picked.append(item["id"])
            continue
        # The rules decide on tags read since it was added; keep_new_tags reads it again first.
        tag = tags.get(item["id"])
        if tag is None or datetime.fromisoformat(tag["judged_at"]) < datetime.fromisoformat(item["added_at"]):
            continue
        created = (facts.get(item["id"]) or {}).get("created_at")
        out_of_scope = tag.get("merge") == "out of scope"
        if rules["claimed"] and tag.get("status") in ("assigned", "fixed"):
            picked.append(item["id"])
        elif rules["out_of_scope"] and out_of_scope:
            picked.append(item["id"])
        elif not out_of_scope and tag.get("complexity") in rules["levels"]:
            picked.append(item["id"])
        elif rules["scope_not_clear"] and tag.get("scope_clear") is False:
            picked.append(item["id"])
        elif cutoff is not None and created is not None and datetime.fromisoformat(created) < cutoff:
            picked.append(item["id"])
    if not picked:
        return []
    return issues.remove(picked)["removed"]


async def keep_facts() -> None:
    """Runs as long as the backend: fetches facts for issues that have none, for active ones every minute, and for
    all of them now and then.

    An issue that fails (GitHub down, the issue deleted or moved) is left alone until the next full round, unless it
    is active.
    """
    last_full = None
    last_active = time.monotonic()
    failed = []
    while True:
        ids = [item["id"] for item in issues.items()]
        known = issue_facts.all()
        todo = []
        if last_full is None or time.monotonic() - last_full > FACTS_REFRESH_SECONDS:
            last_full = time.monotonic()
            failed = []
            issue_facts.forget(ids)
            # Not the Open and Catalog issues of a held repo: they wait until it has room.
            started = [job["issue"] for job in jobs.list() if job["issue"] is not None and job["status"] != "cancelled"]
            todo = [issue_id for issue_id in ids if issue_id in started or issue_id.split("#")[0].lower() not in HELD["repos"]]
        else:
            todo = [issue_id for issue_id in ids if issue_id not in known and issue_id not in failed]
            # The issues an agent is on now, every ACTIVE_REFRESH_SECONDS.
            if time.monotonic() - last_active > ACTIVE_REFRESH_SECONDS:
                last_active = time.monotonic()
                for job in jobs.list():
                    if job["status"] not in ("queued", "working", "waiting_on_user", "waiting_on_maintainers"):
                        continue
                    if job["issue"] in ids and job["issue"] not in todo:
                        todo.append(job["issue"])
        for issue_id in todo:
            try:
                facts = await asyncio.to_thread(issue_facts.refresh, issue_id)
            except Exception as error:
                failed.append(issue_id)
                # GitHub has no such issue anymore (deleted, or moved away): nobody takes it again.
                if str(error).startswith(("Could not resolve to an Issue", "GitHub has no issue")):
                    drop_gone_issue(issue_id)
                continue
            # Closed on GitHub since the last read (a maintainer fixed it, or a merged PR closed it): the agent with a job
            # on it hears at once, before more hours of runs on a fix nobody wants anymore.
            before = known.get(issue_id)
            if before is not None and before["state"] == "OPEN" and facts["state"] != "OPEN":
                agents.issue_fixed(issue_id, "was closed")
        await asyncio.sleep(FACTS_CHECK_SECONDS)


def drop_gone_issue(issue_id: str) -> None:
    """An issue GitHub doesn't have anymore: the agent of an open job on it is told to stop (Agents.stop_job), and it
    leaves the Issues list for good (with Catalog and the tagging) once no job on it is open; until then keep_facts
    finds it gone again every ACTIVE_REFRESH_SECONDS."""
    for job in jobs.list():
        if job["issue"] == issue_id and job["status"] not in ["done", "cancelled"]:
            agents.stop_job(job["id"], f"{issue_id} was deleted on GitHub (or moved away): there is nothing to fix there anymore.")
    issues.dismiss([issue_id])


async def keep_new_tags() -> None:
    """Runs as long as the backend: tags the Issues list's issues that have no tags yet or none read since they were
    added, at once and from fresh, apart from keep_tags: one tagged before it came in (by Add issues, on the Tracked page,
    ...) is read again, and its new tags are the ones every page shows. Then Remove automatically's rules decide on them.
    A failed one is tried again on the next round instead of waiting TAGS_RETRY_SECONDS."""
    while True:
        known = issue_tags.all()
        todo = []
        for item in issues.items():
            tag = known.get(item["id"])
            if tag is None or datetime.fromisoformat(tag["judged_at"]) < datetime.fromisoformat(item["added_at"]):
                todo.append(item["id"])
        if todo:
            # Forced: nothing from before is kept. A batch that fails leaves its issues as they were: the next round
            # tries them again.
            try:
                await issue_tags.tag(todo, force=True)
            except Exception:
                pass
            TAGGED.set()
            try:
                auto_remove_issues()
            except Exception:
                pass
        await asyncio.sleep(NEW_TAGS_SECONDS)


async def keep_tags() -> None:
    """Runs as long as the backend: tags every issue that has no tags yet, changed on GitHub since, was free an hour ago
    (5 minutes ago when an agent is on it), or is from before merge, one of its checks, complexity, the naming rules (issue_tags.NAME_VERSION) or the status
    rules (issue_tags.RULES_VERSION).

    Those are the Issues list's issues, newest first. issue_tags.tag batches them.
    """
    failed = []
    failed_since = time.monotonic()
    removed_at = 0.0
    # Where each issue of the Issues list was on the board last round.
    last_columns = {}
    while True:
        if time.monotonic() - failed_since > TAGS_RETRY_SECONDS:
            failed = []
            failed_since = time.monotonic()
        known = issue_tags.all()
        facts = issue_facts.all()
        # The board's refresh intervals (the robot button over it).
        rules = dict(AUTO_REMOVE_OFF)
        if AUTO_REMOVE_FILE.is_file():
            rules.update(json.loads(AUTO_REMOVE_FILE.read_text()))
        listed = [item["id"] for item in issues.items()]
        added_at = {item["id"]: item["added_at"] for item in issues.items()}
        catalog = issues.board()["catalog"]
        latest = {}
        for job in jobs.list():
            if job["issue"] is not None and (job["issue"] not in latest or job["created_at"] > latest[job["issue"]]["created_at"]):
                latest[job["issue"]] = job
        # Each issue and its last change on GitHub (None when not known yet).
        candidates = []
        for item in issues.items():
            updated_at = None
            if item["id"] in facts:
                updated_at = facts[item["id"]]["updated_at"]
            candidates.append((item["id"], updated_at))

        # Where each issue is on the board now, as its columns. One that moved since the last round is read again first,
        # unless its tags are newer than MOVED_FRESH_SECONDS; not a move to finished.
        columns = {}
        for issue_id in listed:
            job = latest.get(issue_id)
            status = job["status"] if job is not None else "cancelled"
            column = "open"
            if issue_id in catalog or status == "queued":
                column = "catalog"
            if status in ("working", "waiting_on_user", "paused"):
                column = "in progress"
            if status == "waiting_on_maintainers":
                column = "pull request"
            if status == "done":
                column = "finished"
            columns[issue_id] = column
        fresh = datetime.now(UTC) - timedelta(seconds=MOVED_FRESH_SECONDS)
        moved = []
        for issue_id, column in columns.items():
            tag = known.get(issue_id)
            if issue_id not in last_columns or last_columns[issue_id] == column or column == "finished" or tag is None:
                continue
            if datetime.fromisoformat(tag["judged_at"]) < fresh:
                moved.append(issue_id)
        last_columns = columns

        active = [job["issue"] for job in jobs.list() if job["status"] in ("queued", "working", "waiting_on_user", "waiting_on_maintainers")]
        todo = list(moved)
        for issue_id, updated_at in candidates:
            tags = known.get(issue_id)
            if issue_id in failed or issue_id in todo:
                continue
            # Where it is on the board: open (no job, or only cancelled), catalog (queued, or moved there), ongoing, or
            # finished (done).
            job = latest.get(issue_id)
            minutes = rules["refresh_open_minutes"]
            if issue_id in catalog or (job is not None and job["status"] == "queued"):
                minutes = rules["refresh_catalog_minutes"]
            if job is not None and job["status"] in ("working", "waiting_on_user", "waiting_on_maintainers"):
                minutes = rules["refresh_ongoing_minutes"]
            due = issue_id in listed and not (job is not None and job["status"] == "done")
            if tags is None and issue_id in listed:
                # keep_new_tags tags it, at once.
                continue
            if issue_id in listed and (job is None or job["status"] == "cancelled") and issue_id.split("#")[0].lower() in HELD["repos"]:
                # On Open or Catalog of a repo at its Open PRs at once: not read again until it has room.
                continue
            if issue_id in listed and datetime.fromisoformat(tags["judged_at"]) < datetime.fromisoformat(added_at[issue_id]):
                # Not read since it was added: keep_new_tags reads it again, at once.
                continue
            if tags is None:
                todo.append(issue_id)
            elif updated_at is not None and tags["updated_at"] != updated_at:
                todo.append(issue_id)
            elif due and datetime.fromisoformat(tags["judged_at"]) < datetime.now(UTC) - timedelta(minutes=minutes):
                # In the Issues list: read again at the board's refresh interval for where it is.
                todo.append(issue_id)
            elif "merge" not in tags:
                # From before merge (it had a level: easy, medium or hard): once more, by the merge rules.
                todo.append(issue_id)
            elif tags["checks"] is not None and any(key not in tags["checks"] for key, question in CHECKS):
                # From before one of the checks (issue_tags.CHECKS) was added: once more, for it.
                todo.append(issue_id)
            elif tags["checks"] is not None and ("complexity" not in tags or tags.get("name_version") != NAME_VERSION):
                # From before complexity and scope, or named by older naming rules: once more, for them.
                todo.append(issue_id)
            elif tags.get("rules_version") != RULES_VERSION:
                # Read by older status rules (the user's own claims counted): once more.
                todo.append(issue_id)

        if todo:
            tagged = await issue_tags.tag(todo)
            TAGGED.set()
            # Someone else is on it now: an agent working on it decides whether to go on. With nobody assigned, other
            # people's pull requests tied to it say who (below).
            after = issue_tags.all()
            for issue_id in tagged:
                prs = issue_tags.open_prs.get(issue_id, [])
                if issue_id in known and known[issue_id]["status"] == "free" and after[issue_id]["status"] == "assigned":
                    facts = issue_facts.all().get(issue_id)
                    assignees = facts["assignees"] if facts else []
                    if assignees or not prs:
                        agents.issue_taken(issue_id, after[issue_id]["reason"], assignees)
                # Someone else's open pull request tied to it (it says it closes it, or only mentions it): the agent with a
                # job on it hears of each one at once, also while the issue stays free. DeskcommCRM#4511 only said "Refs
                # #4495", and our agent ran five more hours of checks before it found it at its draft.
                if prs and issue_id in active:
                    agents.issue_taken(issue_id, after[issue_id]["reason"], [], prs)
                # Fixed now, still open (a merged PR or a commit does what it asks): the agent with a job on it hears at once.
                if issue_id in active and after[issue_id]["status"] == "fixed" and (issue_id not in known or known[issue_id]["status"] != "fixed"):
                    agents.issue_fixed(issue_id, "looks fixed already (a merged PR or a commit does what it asks)")
            # What didn't get tagged (GitHub or Claude failed, Claude left it out, it is gone) waits for TAGS_RETRY_SECONDS.
            for issue_id in todo:
                if issue_id not in tagged:
                    failed.append(issue_id)
        # New tags may match Remove automatically's rules now, and an issue may have got older than older_than_days: after
        # a round that tagged anything, and every AUTO_REMOVE_SECONDS. A failure there mustn't stop the tagging.
        if todo or time.monotonic() - removed_at > AUTO_REMOVE_SECONDS:
            removed_at = time.monotonic()
            try:
                auto_remove_issues()
            except Exception:
                pass
        # The tags file, at most every issue_tags.SAVE_SECONDS: written whole, so in a thread.
        await asyncio.to_thread(issue_tags.flush)
        await asyncio.sleep(TAGS_CHECK_SECONDS)


async def keep_catalog_agents() -> None:
    """Runs as long as the backend: gives Catalog's cards to new agents from the top while fewer than max_agents work on
    the board's issues (see the top of this file)."""
    while True:
        try:
            stop_unwanted_jobs()
            take_from_catalog()
        except Exception:
            # A file or an agent failed: the next round tries again.
            traceback.print_exc()
        await asyncio.sleep(CATALOG_AGENTS_SECONDS)


def stop_unwanted_jobs() -> None:
    """Open jobs on the board's issues that the app no longer wants done: their repo was deleted from Repos, or it
    doesn't take AI-made contributions (AI policy no_ai). Each one's agent is told to stop and cancel it (Agents.stop_job),
    once. An archived repo stays in Repos: its jobs go on. Never a job on an issue our agents opened: we never give one up."""
    ids = [item["id"] for item in issues.items()]
    opened = []
    for action in inbox.actions():
        if action["kind"] == "issue":
            opened.append(f"{action['sent']['repo']}#{action['sent']['number']}".lower())
    in_repos = [item["full_name"].lower() for item in repos.items()]
    signals = repo_signals.all()
    no_ai = [name.lower() for name, each in signals.items() if (each.get("ai_policy") or {}).get("tag") == "no_ai"]
    for job in jobs.list():
        if job["kind"] != "fix_issue" or job["issue"] not in ids or job["status"] in ["done", "cancelled"]:
            continue
        if job["issue"].lower() in opened:
            continue
        repo = job["issue"].split("#")[0]
        if repo.lower() not in in_repos:
            agents.stop_job(job["id"], f"{repo} was deleted from Repos: the user doesn't want work there anymore.")
        elif repo.lower() in no_ai:
            agents.stop_job(job["id"], f"{repo} doesn't take AI-made contributions (its AI policy), and we only work as an AI agent.")


def take_from_catalog() -> None:
    rules = dict(AUTO_REMOVE_OFF)
    if AUTO_REMOVE_FILE.is_file():
        rules.update(json.loads(AUTO_REMOVE_FILE.read_text()))
    items = issues.items()
    ids = [item["id"] for item in items]
    all_jobs = jobs.list()
    facts = issue_facts.all()
    tags = issue_tags.all()

    # The issues our agents opened as you (lower case): claimed for you, so an agent always takes them.
    opened = []
    for action in inbox.actions():
        if action["kind"] == "issue":
            opened.append(f"{action['sent']['repo']}#{action['sent']['number']}".lower())
    # Ours that no agent ever started go to the top of Catalog, also when someone else seems to be on them now: we never
    # give one up. Not one that is closed, fixed or out of scope.
    started = [job["issue"] for job in all_jobs if job["issue"] is not None]
    board = issues.board()
    # Only cards of issues still in the list: the ones that left it piled up in Catalog (2,683 of 3,243 by 11-20).
    listed = set(ids)
    catalog = [each for each in board["catalog"] if each in listed]
    order = [each for each in board["order"] if each in listed]
    for item in items:
        tag = tags.get(item["id"])
        if item["id"].lower() not in opened or tag is None:
            continue
        fact = facts.get(item["id"])
        state = fact["state"] if fact else item["state"]
        if item["id"] in catalog or item["id"] in started or item["id"] in board["held"]:
            continue
        if state != "CLOSED" and tag["status"] != "fixed" and tag.get("merge") != "out of scope":
            catalog.insert(0, item["id"])
            order = [item["id"]] + [each for each in order if each != item["id"]]
    if catalog != board["catalog"] or order != board["order"]:
        issues.set_board(catalog, order, board["held"])

    # The agents working on the board's issues now.
    working = []
    for job in all_jobs:
        if job["status"] not in ("queued", "working"):
            continue
        if (job["issue"] in ids or job["thread"] is not None) and job["agent"] not in working:
            working.append(job["agent"])
    room = rules["max_agents"] - len(working)

    # Each issue's latest job: Catalog's own cards have none, or a cancelled one.
    latest = {}
    for job in all_jobs:
        if job["issue"] is not None and (job["issue"] not in latest or job["created_at"] > latest[job["issue"]]["created_at"]):
            latest[job["issue"]] = job
    board = issues.board()
    # The repos agents take issues of (their Level of automation: Take issues), in lower case. Ours go either way.
    settings = {}
    if AUTOMATION_FILE.is_file():
        settings = json.loads(AUTOMATION_FILE.read_text())
    taking = [repo.lower() for repo, each in settings.items() if each.get("take_issues")]
    # The Automation page's settings (backend/automation_api.py).
    automation = {"on": False, "labels": {}}
    if DASHBOARD_AUTOMATION_FILE.is_file():
        automation = json.loads(DASHBOARD_AUTOMATION_FILE.read_text())
    # Each repo's AI policy (repo_signals.py), lower case; one not read yet counts as unclear. The Automation page's AI
    # policy says which may be worked on; no_ai never.
    policies = {name.lower(): (each.get("ai_policy") or {}).get("tag") or "unclear" for name, each in repo_signals.all().items()}
    allowed = automation.get("ai_policies", ["welcome", "disclose", "none", "unclear"])
    waiting = []
    for item in items:
        if item["id"] not in board["catalog"] or item["id"] in board["held"]:
            continue
        if item["repo"].lower() not in taking and item["id"].lower() not in opened:
            continue
        # Never a repo that doesn't take AI-made contributions (its AI policy, repo_signals.py), nor one whose policy the
        # Automation page turned off (ours go anyway: we never give one up).
        policy = policies.get(item["repo"].lower(), "unclear")
        if policy == "no_ai":
            continue
        if policy not in allowed and item["id"].lower() not in opened:
            continue
        if item["id"] in latest and latest[item["id"]]["status"] != "cancelled":
            continue
        fact = facts.get(item["id"])
        state = fact["state"] if fact else item["state"]
        if state == "CLOSED":
            continue
        # Like Assign (assign_issue): once its Merge is in, and not when that says it can't be done. Nor one someone else
        # is on (claimed): assigned to them, or their open PR closes it; nobody wants a second fix. Nor one no PR of ours
        # would be merged in now (maintainers only, waiting, no outside PRs, large feature). Ours go anyway.
        tag = tags.get(item["id"])
        blocked = [None, "fixed", "out of scope", "can't validate", "claimed", "maintainers only", "waiting", "no outside prs", "large feature"]
        if item["id"].lower() in opened:
            blocked = [None, "fixed", "out of scope", "can't validate"]
        if tag is None or tag.get("merge") in blocked:
            continue
        # Read recently: a held repo's cards wait unread (HELD), and are read again once it has room. Ours go anyway.
        stale = datetime.fromisoformat(tag["judged_at"]) < datetime.now(UTC) - timedelta(minutes=rules["refresh_catalog_minutes"] * 2)
        if stale and item["id"].lower() not in opened:
            continue
        waiting.append(item["id"])
    # From the top: the board's order, ones not placed yet after (sorted keeps them in the order they were added).
    waiting.sort(key=lambda issue_id: board["order"].index(issue_id) if issue_id in board["order"] else len(board["order"]))
    # With the Automation on, its best repos first (its rank, then the most PRs merged a day), each in that order; ours
    # stay first.
    ranks = {name.lower(): (each["rank"], -(each.get("per_day") or 0)) for name, each in automation["labels"].items()}
    if automation["on"]:
        waiting.sort(key=lambda issue_id: (-1, 0) if issue_id.lower() in opened else ranks.get(issue_id.split("#")[0].lower(), (len(ranks), 0)))
    # Each repo's column on the Repositories page, in lower case, worked out as the page does: from your PRs there
    # (merged, closed, open, and when the last one closed without a merge) and its issues in progress (fix_issue jobs
    # still open with no PR yet).
    removed = [name.lower() for name in repos.removed()]
    prioritized = [name.lower() for name in repos.prioritized()]
    target = {name.lower(): at for name, at in repos.target().items()}
    mine = [pr for pr in pr_tracking.summary()["items"] if pr["relation"] == "author"]
    pr_jobs = [pr["job"] for pr in mine]
    counts = {}
    last_closed = {}
    for pr in mine:
        repo = pr["repo"].lower()
        counts.setdefault(repo, {"merged": 0, "closed": 0, "open": 0, "working": 0})
        if pr["state"] in ["merged", "closed", "open"]:
            counts[repo][pr["state"]] += 1
        if pr["state"] == "closed" and pr["closed_at"] is not None and pr["closed_at"] > last_closed.get(repo, ""):
            last_closed[repo] = pr["closed_at"]
    for job in all_jobs:
        if job["kind"] != "fix_issue" or job["status"] not in ["queued", "working", "waiting_on_user", "waiting_on_maintainers"]:
            continue
        if job["id"] in pr_jobs or job["repo"] is None:
            continue
        repo = job["repo"].lower()
        counts.setdefault(repo, {"merged": 0, "closed": 0, "open": 0, "working": 0})
        counts[repo]["working"] += 1
    columns = {}
    for issue_id in waiting:
        repo = issue_id.split("#")[0].lower()
        each = counts.get(repo, {"merged": 0, "closed": 0, "open": 0, "working": 0})
        closed_only = each["merged"] == 0 and each["open"] == 0 and each["working"] == 0 and each["closed"] > 0
        if repo in removed or (closed_only and repo not in target):
            columns[repo] = "removed"
        elif each["merged"] > 0 and repo in prioritized:
            columns[repo] = "prioritized"
        elif each["merged"] > 0:
            columns[repo] = "contributed"
        elif repo in target and last_closed.get(repo, "") <= target[repo]:
            columns[repo] = "target"
        else:
            columns[repo] = "catalog"
    # Removed's cards wait, ours too, and so do those of a column switched off on the page.
    take_from = automation.get("take_from", {})
    kept = []
    for issue_id in waiting:
        column = columns[issue_id.split("#")[0].lower()]
        if column != "removed" and take_from.get(column, True):
            kept.append(issue_id)
    waiting = kept
    # By column (REPO_COLUMNS), each in the order above; ours stay first.
    waiting.sort(key=lambda issue_id: (0 if issue_id.lower() in opened else 1, REPO_COLUMNS.index(columns[issue_id.split("#")[0].lower()])))

    # Each repo's Open PRs at once (backend/repo_automation_api.py): its open PRs of yours and its issues with an open
    # job before a PR (queued to waiting on you) count, by repo in lower case; while they reach it, its cards wait.
    busy = {}
    merged = {}
    for pr in pr_tracking.summary()["items"]:
        if pr["relation"] == "author" and pr["state"] == "open":
            busy[pr["repo"].lower()] = busy.get(pr["repo"].lower(), 0) + 1
        if pr["relation"] == "author" and pr["state"] == "merged":
            merged[pr["repo"].lower()] = merged.get(pr["repo"].lower(), 0) + 1
    for issue_id, job in latest.items():
        if job["status"] in ["queued", "working", "waiting_on_user", "paused"] and job["repo"] is not None:
            busy[job["repo"].lower()] = busy.get(job["repo"].lower(), 0) + 1
    limits = {}
    for repo, each in settings.items():
        limits[repo.lower()] = each.get("max_prs", 5) if merged.get(repo.lower(), 0) > 0 else each.get("max_prs_first", 1)
    # The Automation page's Open pull requests per repository goes over every repo's own, when it is lower.
    per_repo = automation.get("max_open_per_repo")
    if per_repo is not None:
        for repo in taking:
            limits[repo] = min(limits.get(repo, 1), per_repo)
    HELD["repos"] = [repo for repo in taking if busy.get(repo, 0) >= limits.get(repo, 1)]
    # And its Open pull requests, all repos together: the same count, summed.
    total = sum(busy.values())
    max_open = automation.get("max_open_prs")

    # Pause new issues on the Dashboard's Automation page: Catalog's cards wait there, ours too; everything else goes on.
    if not automation.get("take_new", True):
        return

    for issue_id in waiting:
        if room <= 0:
            break
        repo = issue_id.split("#")[0].lower()
        # Ours go even when the repo is at its Open PRs at once, or all repos are at the Automation's Open pull requests.
        if busy.get(repo, 0) >= limits.get(repo, 1) and issue_id.lower() not in opened:
            continue
        if max_open is not None and total >= max_open and issue_id.lower() not in opened:
            continue
        agents.assign(issue_id, None, None)
        board = issues.board()
        issues.set_board([each for each in board["catalog"] if each != issue_id], board["order"], board["held"])
        busy[repo] = busy.get(repo, 0) + 1
        total += 1
        room -= 1


async def keep_stale_prs() -> None:
    """Runs as long as the backend: has the PRs that stalled made again fresh (see the top of this file)."""
    while True:
        try:
            remake_stale_prs()
        except Exception:
            # A file or an agent failed: the next round tries again.
            traceback.print_exc()
        await asyncio.sleep(STALE_CHECK_SECONDS)


def remake_stale_prs() -> None:
    rules = dict(AUTO_REMOVE_OFF)
    if AUTO_REMOVE_FILE.is_file():
        rules.update(json.loads(AUTO_REMOVE_FILE.read_text()))
    if rules["stale_pr_days"] is None:
        return
    # GitHub's own format, so it compares as text with the PRs' updated_at.
    cutoff = (datetime.now(UTC) - timedelta(days=rules["stale_pr_days"])).strftime("%Y-%m-%dT%H:%M:%SZ")
    all_jobs = jobs.list()
    archived = [name.lower() for name in repos.archived()]
    removed = [name.lower() for name in repos.removed()]
    for pr in pr_tracking.summary()["items"]:
        # Only an open PR of yours an agent owns: never one you opened by hand, nor one on an archived or removed repo.
        if pr["relation"] != "author" or pr["state"] != "open" or pr["agent"] is None or pr["draft_id"] is None:
            continue
        if pr["repo"].lower() in archived or pr["repo"].lower() in removed:
            continue
        if pr["updated_at"] > cutoff:
            continue
        # Once: not while a job on it is open, and never again after its remake job.
        taken = False
        for job in all_jobs:
            if job["thread"] == pr["id"] and (job["kind"] == "fix_issue" or job["status"] in ["queued", "working", "waiting_on_user"]):
                taken = True
        if not taken:
            agents.remake_pr(pr, rules["stale_pr_days"])
