"""Automation (Settings → Automation, frontend/src/Automation.tsx, and the Explore dialog, frontend/src/ExploreDialog.tsx):
Seraph finds repos, works on them and lets go of them by itself, as you, so the repos it works on keep changing: the
ones that merge our PRs stay, new ones come in, the ones that don't merge leave. Their settings say how much of that
goes on.

Its settings and what it did, in AUTOMATION_FILE (DATA_DIR/automation.json):

    {"on": bool, "active_repos": int,
     "add_repos": bool,                                False: Add repositories off (below)
     "take_new": bool,                                 False: Pause new issues (below)
     "rules": {"fast_days", "normal_days", "max_open_days", "close_days", "idle_days", "leave_days": int},
     "new_repos": the level of automation the repos it adds get (a repo's, repo_automation_api.py),
     "archived": {"owner/name": when it archived it, ...},
     "closed": ["owner/name#n", ...],                the PRs of ours it closed
     "run": started_at of the Explore run it started | None,
     "log": [{"at", "repo", "what", "why"}, ...],   newest last, the last LOG_KEPT
     "labels": {"owner/name": Label, ...},           every repo in Repos, worked out every round, also while off
     "send_prs", "send_comments": bool,             Create pull requests, Reply to reviews and comments
     "max_prs_per_day", "max_open_prs", "max_open_per_repo": int | None,    the limits (None: no limit)
     "ai_policies": ["welcome", ...],               the AI policies whose repos may be worked on (never no_ai)
     "take_from": {"target", "prioritized", "contributed", "catalog": bool},
                                                    the Repositories page's column switches (below)
     "columns": {"target", "prioritized", "contributed", "catalog": {"max_open_per_repo": int | None,
                 "model": "default" | "fable" | "opus" | "sonnet"}}}
                                                    those columns' settings (below)

The Explore dialog's Include and Exclude are not in it: they are Explore's profile's (DATA_DIR/explore_profile.json,
explore.py), so they stay out of the code and out of git. summary() adds them.

    Label = {"label", "rank", "why", "merged", "closed", "open", "days", "idle", "per_day"}

Each repo's label comes from our PRs there: the ones pr_tracking.py follows that we opened, not the ones this closed, nor
one an agent made again as a fresh PR, which closes the old one (backend/issues_api.py keep_stale_prs). Days are
business days, Monday to Friday, except idle. The numbers are the rules' (RULES at first):
    Fast          ours merged within fast_days (the median of them: days)
    Normal        within normal_days
    Slow          longer
    New           none of ours merged yet
    No issues     over the four above: a repo with Queue issues on that had nothing to work on for idle_days days (idle,
                  calendar days since it was added, or since the newest job or PR of ours there; a Catalog card or an
                  open job counts as now)
    Not merging   over all of them: one of ours open more than max_open_days without a merge, or MIN_CLOSED or more of
                  ours closed without a merge and they are MAX_CLOSED_SHARE or more of ours there (closed / all)
LABELS is their order (rank). per_day is how many PRs the repo merges a day, anyone's (its signals: the monthly average
over 90 days, repo_signals.py), None before they are read. Agents take the Issues board's Catalog cards by rank, then by
per_day, the most first (backend/issues_api.py take_from_catalog), and the page lists them so.

keep_automation() runs as long as the backend, every CHECK_SECONDS. It works out the labels and, on or off, holds every
repo to Explore's minimums (explore.py MIN_*: over 1k stars, 40 contributors or more, over 400 closed PRs, over 10 open
issues), so no personal repo stays: once its signals are read, one in Repos that falls short leaves (archived when it
has a PR of ours, else off Repos and kept as checked by Explore, so it never comes back), and so does one in Explore's
found list (also one found before these were checked, which a later run checks anew). Never one in Target (repo_list.py
target): you picked it, so it stays, and nothing below archives it either. On or off too, while Add
repositories is on, it keeps active_repos repos active (below). And while on:
- archives a repo that is Not merging (Repos' Archived, repo_list.py): its issues leave the board's Open and Catalog,
  the jobs on its issues with no PR yet stop, and no new PR goes there (repo_automation_api.py keep_drafts). Our open
  PRs there stay and their agents still answer reviews. close_days business days after it archived the repo, the ones
  still open are closed (their agent set to Off first, so nobody drafts about it). Never for an issue our agents opened
  (its job goes on, its PR stays open): we never give one up; keep_branches_clean
  (backend/github_api.py) deletes their branches, as it does for every PR of ours that isn't open.
- unarchives a repo it archived when one of ours there gets merged after that, unless it is still Not merging.
- archives a repo that had No issues for leave_days days too. Archived repos stay in Repos, so Explore never adds one
  again.
Only repos it archived are unarchived or get their PRs closed: one you archived stays yours.

Add repositories (add_repos), with Manage repositories on or off: it keeps active_repos repos active (in Repos, not
archived; MAX_ACTIVE at most). What Explore found goes into Repos at once, the best first: the best fit to the Include
(strong, good, some; Explore's runs skip weak ones, EXPLORE_FILTERS), then the most PRs merged a day (Explore skips a
repo under MIN_MERGED_PER_DAY, explore.py), then AI policy (welcome, disclose, none, unclear; never no_ai), then
newcomers (welcomes, ok, few). Each comes with new_repos (AUTO_SETTINGS at first: every level of its Automation on, Add,
Queue and Take issues, Questions, Comments and Pull requests), so agents take its issues and send their PRs as you once
the reviewer passed them, under its Open PRs at once and Issue levels (repo_automation_api.py). With still too few, it
starts an Explore run for the rest (explore.py) with as many workers as GitHub's quota allows, after adding a new type of repo to Explore's profile (Explore.add_type), so it
looks wider each time; when the Include changed since the types' searches were planned, they are planned again for it
first (Explore.set_profile). Not within RUN_PAUSE_MINUTES of a run that ended short. Off: nothing goes into Repos from
Explore's found list, no Explore run starts, and the one it started stops.

Take new issues off (take_new False, on or off): agents take no new issues from the Issues board's Catalog
(backend/issues_api.py take_from_catalog), not even ours, but those of repos in Target (a repo in Target always gets
worked); the cards wait there until it is on again. Everything else goes on: the jobs already started, follow-ups on
our PRs, tagging, Explore, the labels and the archiving.

The Repositories page's column switches (take_from, one per column but Removed): off, agents take no new issues of the
repos in that column, ours too (backend/issues_api.py take_from_catalog); what is going there goes on. PUT
/api/automation/take_from sets one.

The same columns' settings (their ⚙ on that page; PUT /api/automation/column sets one):
- Open PRs per repository (max_open_per_repo): the most PRs of ours open at once in each repo of the column, over the
  repo's own Open PRs at once and the Automation's Open pull requests per repository (None: those). What keep_drafts
  sends (backend/repo_automation_api.py) and taking issues (backend/issues_api.py take_from_catalog) both go by it.
- Model: the Claude model of the agents fixing issues and following up on PRs in the column's repos (default: the
  usual, claude_models.py), for new jobs: a job keeps the one it started with (agents.py work).

The page's settings, and where each is obeyed:
- Manage repositories (on): everything above that archives and closes.
- Add repositories (add_repos, the switch in the Explore dialog's header): above.
- Take new issues (take_new): above.
- Create pull requests, Reply to reviews and comments, Pull requests per day, Open pull requests and Open pull requests
  per repository: what keep_drafts sends (backend/repo_automation_api.py); the last two also hold back taking issues
  (backend/issues_api.py take_from_catalog).
- Concurrent agents: the Issues board's max_agents (AUTO_REMOVE_FILE, backend/issues_api.py).
- Include and Exclude: what Explore looks for and keeps out (explore.py), and Exclude also what agents never take
  (issue_tags.py, repo_automation_api.py, the agents' prompt). Explore's own minimum stars (explore.py MIN_STARS) holds
  under them.
- AI policy: only repos with an allowed policy are added, Explore's runs skip the others, and agents take no new issue of
  one (take_from_catalog). no_ai never.

GET /api/automation gives it all (the live "automation" topic too: summary()), with max_agents, include and exclude
besides. PUT /api/automation sets every setting at once (include and exclude only when given). A change goes up AUTOMATION_VERSION (issues_api.py), so the page
shows it at once.
"""

import asyncio
import copy
import json
import statistics
import traceback
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.issues_api import AUTO_REMOVE_FILE, AUTO_REMOVE_OFF, AUTOMATION_VERSION, REPO_COLUMNS, auto_remove_issues
from backend.repo_automation_api import DEFAULTS, SETTINGS_FILE
from backend.shared import agents, explore, github_account, inbox, issues, jobs, pr_tracking, repo_signals, repos
from github_searcher.claude_models import COLUMN_MODELS
from github_searcher.explore import FIT_LEVELS, MIN_CLOSED_PRS, MIN_CONTRIBUTORS, MIN_OPEN_ISSUES, MIN_STARS
from github_searcher.github_account import SendError
from github_searcher.issue_tags import DATA_DIR

router = APIRouter(prefix="/api")

AUTOMATION_FILE = DATA_DIR / "automation.json"
CHECK_SECONDS = 60
# The rules at first; the Settings tab changes them.
RULES = {"fast_days": 3, "normal_days": 5, "max_open_days": 10, "close_days": 10, "idle_days": 14, "leave_days": 30}
MIN_CLOSED = 2
MAX_CLOSED_SHARE = 0.5
LOG_KEPT = 200
MAX_ACTIVE = 300
RUN_PAUSE_MINUTES = 30
LABELS = ["Fast", "Normal", "New", "Slow", "No issues", "Not merging"]
POLICY_ORDER = ["welcome", "disclose", "none", "unclear"]
NEWCOMERS_ORDER = ["welcomes", "ok", "few"]
# Explore's runs skip what bans AI, and what hardly matches the Include.
EXPLORE_FILTERS = {"policy:no_ai": "exclude", "fit:weak": "exclude"}
AUTO_SETTINGS = dict(DEFAULTS)
AUTO_SETTINGS.update({"add_issues": True, "queue_issues": True, "take_issues": True, "questions": True, "comments": True, "pull_requests": True})
OPEN_JOB = ["queued", "working", "waiting_on_user", "paused"]
# The Automation page's settings (PUT /api/automation), as they are until it saves: what went on before they existed.
SETTINGS = {
    "add_repos": True,
    "send_prs": True,
    "send_comments": True,
    "max_prs_per_day": None,
    "max_open_prs": None,
    "max_open_per_repo": None,
    "ai_policies": list(POLICY_ORDER),
    "take_from": {column: True for column in REPO_COLUMNS},
    "columns": {column: {"max_open_per_repo": None, "model": "default"} for column in REPO_COLUMNS},
}
EMPTY = {"on": False, "active_repos": MAX_ACTIVE, "take_new": True, "rules": RULES, "new_repos": AUTO_SETTINGS, "archived": {}, "closed": [], "run": None, "log": [], "labels": {}, **SETTINGS}

# Kept in memory and saved on every change. Everything that changes it runs on the event loop, so it needs no lock.
automation = copy.deepcopy(EMPTY)
if AUTOMATION_FILE.is_file():
    automation.update(json.loads(AUTOMATION_FILE.read_text()))
# Minimum stars is gone: the Include says how big a repo should be, and Explore keeps its own minimum (explore.py
# MIN_STARS).
automation.pop("min_stars", None)
# The PRs a close was tried on (a restart tries them again).
STATE = {"tried": []}


class AutomationRequest(BaseModel):
    on: bool
    add_repos: bool
    take_new: bool
    send_prs: bool
    send_comments: bool
    max_prs_per_day: int | None
    max_open_prs: int | None
    max_open_per_repo: int | None
    max_agents: int
    ai_policies: list[str]
    # The Explore dialog's Include and Exclude (None: as they are). Kept in Explore's profile, in DATA_DIR, never in the
    # code.
    include: str | None = None
    exclude: str | None = None


class TakeFromRequest(BaseModel):
    column: str
    on: bool


class ColumnRequest(BaseModel):
    column: str
    max_open_per_repo: int | None
    model: str


def summary() -> dict:
    """It all (see the top of this file), with Concurrent agents (the Issues board's max_agents) besides. On the event
    loop."""
    data = copy.deepcopy(automation)
    board = dict(AUTO_REMOVE_OFF)
    if AUTO_REMOVE_FILE.is_file():
        board.update(json.loads(AUTO_REMOVE_FILE.read_text()))
    data["max_agents"] = board["max_agents"]
    data["include"] = explore.profile["include"]
    data["exclude"] = explore.profile["exclude"]
    return data


@router.get("/automation")
async def get_automation() -> dict:
    return summary()


@router.put("/automation")
async def put_automation(body: AutomationRequest) -> dict:
    """The Automation page's Save: every setting at once."""
    for value in [body.max_prs_per_day, body.max_open_prs, body.max_open_per_repo]:
        if value is not None and (value < 1 or value > 1000):
            raise HTTPException(status_code=400, detail="A limit is 1 to 1000.")
    if body.max_agents < 1 or body.max_agents > 50:
        raise HTTPException(status_code=400, detail="Concurrent agents is 1 to 50.")
    if any(policy not in POLICY_ORDER for policy in body.ai_policies):
        raise HTTPException(status_code=400, detail=f"The AI policies are some of {', '.join(POLICY_ORDER)}.")
    automation["on"] = body.on
    automation["add_repos"] = body.add_repos
    automation["take_new"] = body.take_new
    automation["send_prs"] = body.send_prs
    automation["send_comments"] = body.send_comments
    automation["max_prs_per_day"] = body.max_prs_per_day
    automation["max_open_prs"] = body.max_open_prs
    automation["max_open_per_repo"] = body.max_open_per_repo
    # In POLICY_ORDER's order, each once.
    automation["ai_policies"] = [policy for policy in POLICY_ORDER if policy in body.ai_policies]
    AUTOMATION_FILE.write_text(json.dumps(automation, indent=2))
    board = dict(AUTO_REMOVE_OFF)
    if AUTO_REMOVE_FILE.is_file():
        board.update(json.loads(AUTO_REMOVE_FILE.read_text()))
    board["max_agents"] = body.max_agents
    AUTO_REMOVE_FILE.write_text(json.dumps(board, indent=2))
    if body.include is not None or body.exclude is not None:
        include = explore.profile["include"]
        exclude = explore.profile["exclude"]
        if body.include is not None:
            include = body.include
        if body.exclude is not None:
            exclude = body.exclude
        explore.set_prompts(include, exclude)
    AUTOMATION_VERSION["version"] += 1
    return summary()


@router.put("/automation/take_from")
async def put_take_from(body: TakeFromRequest) -> dict:
    """A column's switch on the Repositories page: whether agents take new issues of its repos."""
    if body.column not in REPO_COLUMNS:
        raise HTTPException(status_code=400, detail=f"The columns are {', '.join(REPO_COLUMNS)}.")
    automation["take_from"][body.column] = body.on
    AUTOMATION_FILE.write_text(json.dumps(automation, indent=2))
    AUTOMATION_VERSION["version"] += 1
    return summary()


@router.put("/automation/column")
async def put_column(body: ColumnRequest) -> dict:
    """A column's settings on the Repositories page (its ⚙): Open PRs per repository and Model (see the top of this
    file)."""
    if body.column not in REPO_COLUMNS:
        raise HTTPException(status_code=400, detail=f"The columns are {', '.join(REPO_COLUMNS)}.")
    if body.max_open_per_repo is not None and body.max_open_per_repo < 1:
        raise HTTPException(status_code=400, detail="Open PRs per repository is at least 1.")
    if body.model != "default" and body.model not in COLUMN_MODELS:
        raise HTTPException(status_code=400, detail=f"The models are default, {', '.join(COLUMN_MODELS)}.")
    automation["columns"][body.column] = {"max_open_per_repo": body.max_open_per_repo, "model": body.model}
    AUTOMATION_FILE.write_text(json.dumps(automation, indent=2))
    AUTOMATION_VERSION["version"] += 1
    return summary()


async def keep_automation() -> None:
    """Runs as long as the backend: labels the repos and, while on, acts on them (see the top of this file)."""
    while True:
        try:
            await automate()
        except Exception:
            # A file, GitHub or Claude failed: the next round tries again.
            traceback.print_exc()
        await asyncio.sleep(CHECK_SECONDS)


async def automate() -> None:
    before = json.dumps(automation)
    rules = automation["rules"]
    now = datetime.now(UTC)
    # A date as its number of Mondays to Fridays since day one (toordinal() is 1 on a Monday; a Saturday or Sunday
    # counts as the Monday after): two of them apart are the business days between.
    day = now.date().toordinal() - 1
    today = (day // 7) * 5 + min(day % 7, 5)

    # Our PRs, by repo in lower case: the business days each merged one took, when the newest was merged, how many
    # were closed without a merge, how many are open and the oldest open one (business days, number), and when each repo
    # last had work. Not the ones this closed, nor one an agent made again fresh.
    replaced = [draft["replaces"] for draft in inbox.list() if draft.get("replaces") and draft["sent"] is not None]
    prs = [pr for pr in pr_tracking.summary()["items"] if pr["relation"] == "author"]
    merge_days = {}
    merged_last = {}
    closed = {}
    open_prs = {}
    oldest = {}
    worked = {}
    for pr in prs:
        if pr["id"] in automation["closed"] or pr["id"] in replaced:
            continue
        name = pr["repo"].lower()
        day = datetime.fromisoformat(pr["opened_at"]).date().toordinal() - 1
        start = (day // 7) * 5 + min(day % 7, 5)
        end = today
        if pr["closed_at"] is not None:
            day = datetime.fromisoformat(pr["closed_at"]).date().toordinal() - 1
            end = (day // 7) * 5 + min(day % 7, 5)
        if pr["state"] == "merged":
            merge_days[name] = merge_days.get(name, []) + [end - start]
        if pr["state"] == "merged" and pr["closed_at"] > merged_last.get(name, ""):
            merged_last[name] = pr["closed_at"]
        if pr["state"] == "closed":
            closed[name] = closed.get(name, 0) + 1
        if pr["state"] == "open":
            open_prs[name] = open_prs.get(name, 0) + 1
        if pr["state"] == "open" and end - start > oldest.get(name, (-1, 0))[0]:
            oldest[name] = (end - start, pr["number"])
        opened = datetime.fromisoformat(pr["opened_at"])
        if name not in worked or opened > worked[name]:
            worked[name] = opened
    # The jobs on each repo too, and a Catalog card or an open job is work now.
    for job in jobs.list():
        if job["repo"] is None:
            continue
        name = job["repo"].lower()
        created = datetime.fromisoformat(job["created_at"])
        if job["status"] in OPEN_JOB:
            created = now
        if name not in worked or created > worked[name]:
            worked[name] = created
    for issue_id in issues.board()["catalog"]:
        worked[issue_id.split("#")[0].lower()] = now
    settings = {}
    if SETTINGS_FILE.is_file():
        settings = json.loads(SETTINGS_FILE.read_text())
    queuing = [repo.lower() for repo, each in settings.items() if each.get("queue_issues")]

    signals = repo_signals.all()
    labels = {}
    for item in repos.items():
        name = item["full_name"].lower()
        activity = (signals.get(item["full_name"]) or {}).get("activity") or {}
        days = merge_days.get(name, [])
        total = len(days) + closed.get(name, 0) + open_prs.get(name, 0)
        label = {"label": "New", "why": "None of ours merged yet", "merged": len(days), "closed": closed.get(name, 0), "open": open_prs.get(name, 0), "days": None}
        if days:
            label["days"] = statistics.median(days)
            label["label"] = "Slow"
            label["why"] = f"Merges ours in {label['days']:g} business days (the median of {len(days)})"
        if days and label["days"] <= rules["normal_days"]:
            label["label"] = "Normal"
        if days and label["days"] <= rules["fast_days"]:
            label["label"] = "Fast"
        last = datetime.fromisoformat(item["added_at"])
        if name in worked and worked[name] > last:
            last = worked[name]
        label["idle"] = (now - last).days
        if name in queuing and label["idle"] >= rules["idle_days"]:
            label["label"] = "No issues"
            label["why"] = f"Nothing to work on for {label['idle']} days"
        if label["closed"] >= MIN_CLOSED and label["closed"] / total >= MAX_CLOSED_SHARE:
            label["label"] = "Not merging"
            label["why"] = f"{label['closed']} of our {total} PRs closed without a merge"
        if name in oldest and oldest[name][0] > rules["max_open_days"]:
            label["label"] = "Not merging"
            label["why"] = f"#{oldest[name][1]} open {oldest[name][0]} business days without a merge"
        label["rank"] = LABELS.index(label["label"])
        label["per_day"] = None
        if activity.get("prs_merged_month") is not None:
            label["per_day"] = round(activity["prs_merged_month"] / 30, 2)
        labels[item["full_name"]] = label
    automation["labels"] = labels

    # Explore's minimums, on or off: what falls short leaves Repos (archived with a PR of ours) and the found list.
    log = []
    at = now.isoformat()
    archived = repos.archived()
    entries = [(item["full_name"], signals.get(item["full_name"])) for item in repos.items() if item["full_name"] not in archived]
    entries += [(entry["name"], entry.get("signals")) for entry in explore.found]
    found = [entry["name"] for entry in explore.found]
    short = {}
    for name, each in entries:
        # Numbers not read yet: a repo waits for them; a found one from before these were checked leaves. The README's
        # language is checked once it is read (backend/repos_api.py keep_signals).
        if each is None or "merged_prs_total" not in each:
            if name in found:
                short[name] = "Found before the minimums were checked"
            continue
        if each["stars"] <= MIN_STARS:
            short[name] = f"{each['stars']} stars, 1k or fewer"
        elif each["contributors_total"] is not None and each["contributors_total"] < MIN_CONTRIBUTORS:
            short[name] = f"{each['contributors_total']} contributors, under {MIN_CONTRIBUTORS}"
        elif each["merged_prs_total"] + each["closed_prs_total"] <= MIN_CLOSED_PRS:
            short[name] = f"{each['merged_prs_total'] + each['closed_prs_total']} closed PRs, {MIN_CLOSED_PRS} or fewer"
        elif each["open_issues_total"] <= MIN_OPEN_ISSUES:
            short[name] = f"{each['open_issues_total']} open issues, {MIN_OPEN_ISSUES} or fewer"
    ours = [pr["repo"].lower() for pr in prs]
    # Never one in Target: you picked it (repo_list.py target). Not archived below either.
    target = [name.lower() for name in repos.target()]
    leave_archived = []
    leave_removed = []
    for item in repos.items():
        name = item["full_name"]
        if name not in short or name in archived or name.lower() in target:
            continue
        if name.lower() in ours:
            leave_archived.append(name)
            log.append({"at": at, "repo": name, "what": "Archived", "why": short[name]})
        else:
            leave_removed.append(name)
            log.append({"at": at, "repo": name, "what": "Removed", "why": short[name]})
    if leave_archived:
        repos.set_archived(leave_archived, True)
    if leave_removed:
        repos.remove(leave_removed)
    if leave_archived or leave_removed:
        auto_remove_issues()
    explore.remove([name for name in found if name in short])
    # Explore keeps them as checked, so no worker goes over one again (not one found before the minimums: checked anew).
    for name in leave_removed + [name for name in found if name in short]:
        if short[name] != "Found before the minimums were checked":
            explore.checked[name.lower()] = {"at": at, "reason": short[name]}
    if leave_removed or any(name in short for name in found):
        explore.save_checked()

    # Keep active_repos active: what Explore found goes into Repos, the best first. With Manage repositories on or off; not
    # with Add repositories off: nothing is added, and the Explore run it started stops.
    archived = repos.archived()
    room = automation["active_repos"] - len([item for item in repos.items() if item["full_name"] not in archived])
    if not automation["add_repos"]:
        room = 0
        if explore.run is not None and explore.run["status"] == "running" and explore.run["started_at"] == automation["run"]:
            explore.stop()
    ranked = []
    for entry in explore.found:
        # Only the AI policies the Explore dialog allows (never no_ai).
        if entry["ai_policy"] not in automation["ai_policies"]:
            continue
        # How well it matches the Include: strong first (explore.py FIT_LEVELS, the most first).
        fit = 0
        if entry.get("fit") in FIT_LEVELS:
            fit = -FIT_LEVELS[entry["fit"]]
        newcomers = len(NEWCOMERS_ORDER)
        if entry["newcomers"] in NEWCOMERS_ORDER:
            newcomers = NEWCOMERS_ORDER.index(entry["newcomers"])
        activity = (entry.get("signals") or {}).get("activity") or {}
        per_day = (activity.get("prs_merged_month") or 0) / 30
        ranked.append((fit, -per_day, POLICY_ORDER.index(entry["ai_policy"]), newcomers, entry["name"]))
    ranked.sort()
    if room > 0 and ranked:
        notes = {entry["name"]: entry["note"] for entry in explore.found}
        added = await explore.approve([each[4] for each in ranked[:room]])
        settings = {}
        if SETTINGS_FILE.is_file():
            settings = json.loads(SETTINGS_FILE.read_text())
        for name in added:
            settings[name] = copy.deepcopy(automation["new_repos"])
            log.append({"at": at, "repo": name, "what": "Added", "why": notes.get(name, "")})
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2))
        AUTOMATION_VERSION["version"] += 1
        room -= len(added)

    # Still too few: an Explore run for the rest, on a new type of repo too. Not right after one that ended short.
    run = explore.run
    rested = run is None or run["ended_at"] is None or now - datetime.fromisoformat(run["ended_at"]) > timedelta(minutes=RUN_PAUSE_MINUTES)
    if run is not None and run["count"] is not None and run["found"] >= run["count"]:
        rested = True
    if room > 0 and rested and (run is None or run["status"] != "running"):
        try:
            # The Include changed since the types' searches were planned: plan them again for it first.
            if explore.profile["include"].strip() != "" and explore.profile.get("planned_for") != explore.profile["include"]:
                await explore.set_profile(explore.profile["include"], explore.profile["lanes"])
            await explore.add_type()
        except Exception:
            traceback.print_exc()
        # Workers: as many as GitHub's quota allows (None). It skips the AI policies the page turned off too.
        filters = dict(EXPLORE_FILTERS)
        for policy in POLICY_ORDER:
            if policy not in automation["ai_policies"]:
                filters[f"policy:{policy}"] = "exclude"
        explore.start(room, None, None, filters)
        automation["run"] = explore.run["started_at"]

    if not automation["on"]:
        automation["log"] = (automation["log"] + log)[-LOG_KEPT:]
        if json.dumps(automation) != before:
            AUTOMATION_FILE.write_text(json.dumps(automation, indent=2))
            AUTOMATION_VERSION["version"] += 1
        return

    # Not merging, or No issues for leave_days: archived.
    archived = repos.archived()
    archive = []
    for item in repos.items():
        name = item["full_name"]
        label = labels[name]
        if name in archived or name.lower() in target:
            continue
        if label["label"] == "Not merging" or (label["label"] == "No issues" and label["idle"] >= rules["leave_days"]):
            archive.append(name)
            automation["archived"][name] = at
            log.append({"at": at, "repo": name, "what": "Archived", "why": label["why"]})
    if archive:
        repos.set_archived(archive, True)
        auto_remove_issues()
    # The jobs on their issues that have no PR yet stop; never one on an issue our agents opened.
    opened = []
    for action in inbox.actions():
        if action["kind"] == "issue":
            opened.append(f"{action['sent']['repo']}#{action['sent']['number']}".lower())
    gone = [name.lower() for name in archive]
    with_pr = [pr["job"] for pr in prs if pr["job"] is not None]
    for job in jobs.list():
        if job["kind"] != "fix_issue" or job["repo"] is None or job["repo"].lower() not in gone:
            continue
        if job["issue"] is not None and job["issue"].lower() in opened:
            continue
        if job["status"] in OPEN_JOB and job["id"] not in with_pr:
            agents.stop_job(job["id"], f"{job['repo']} doesn't merge our PRs or has nothing to work on, so Seraph stopped working there.")

    # A repo it archived comes back once one of ours there is merged after that, unless it is still Not merging. One you
    # unarchived or deleted meanwhile is yours again.
    archived = repos.archived()
    for name in list(automation["archived"]):
        if name not in archived or name not in labels:
            del automation["archived"][name]
            continue
        merged_at = merged_last.get(name.lower())
        if labels[name]["label"] == "Not merging" or merged_at is None:
            continue
        if datetime.fromisoformat(merged_at) <= datetime.fromisoformat(automation["archived"][name]):
            continue
        repos.set_archived([name], False)
        del automation["archived"][name]
        log.append({"at": at, "repo": name, "what": "Unarchived", "why": "Merged one of ours after it was archived"})

    # Our PRs still open close_days business days after it archived their repo are closed; never one for an issue our
    # agents opened (the issues it says it fixes, or its job's).
    archived_at = {name.lower(): when for name, when in automation["archived"].items()}
    job_issue = {job["id"]: job["issue"] for job in jobs.list()}
    for pr in prs:
        when = archived_at.get(pr["repo"].lower())
        if pr["state"] != "open" or when is None or pr["id"] in STATE["tried"]:
            continue
        fixes = [f"{pr['repo']}#{issue['number']}".lower() for issue in pr["issues"]]
        fixes.append((job_issue.get(pr["job"]) or "").lower())
        if any(issue_id in opened for issue_id in fixes):
            continue
        day = datetime.fromisoformat(when).date().toordinal() - 1
        if today - ((day // 7) * 5 + min(day % 7, 5)) < rules["close_days"]:
            continue
        STATE["tried"].append(pr["id"])
        pr_tracking.set_agent(pr["id"], "off", None)
        try:
            await asyncio.to_thread(github_account.manage, "close", pr["repo"], pr["number"])
        except SendError as error:
            log.append({"at": at, "repo": pr["repo"], "what": f"Could not close #{pr['number']}", "why": str(error)})
            continue
        automation["closed"].append(pr["id"])
        pr_tracking.wanted = True
        log.append({"at": at, "repo": pr["repo"], "what": f"Closed #{pr['number']}", "why": f"Still open {rules['close_days']} business days after the repo was archived"})

    automation["log"] = (automation["log"] + log)[-LOG_KEPT:]
    if json.dumps(automation) != before:
        AUTOMATION_FILE.write_text(json.dumps(automation, indent=2))
        AUTOMATION_VERSION["version"] += 1
