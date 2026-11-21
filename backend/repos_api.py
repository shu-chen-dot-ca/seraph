"""The Repositories page's cards (frontend/src/RepositoryCards.tsx): the moves between Prioritized and Contributed, Add
to Target, Delete (Add to Removed for a repo with PRs of yours), Stop all on its issues in progress and Close all on its
open PRs, and keeping the repos' signals fresh, and their record with us for the cards' test run time and rating
(keep_repo_stats, github_searcher/repo_stats.py).

The list reaches the browser through /api/live (topic "repos"). The Automation fills it (backend/automation_api.py,
through Explore).

The signals (github_searcher/repo_signals.py) are read by keep_signals(), which the app runs in the background: a new
repo gets them within SIGNALS_CHECK_SECONDS, and keeps them. Signals kept from before the totals (commits, open, merged
and closed PRs, open issues) were counted get just those, with one small read each, and those from before the README's
language was checked get that, the README alone.
"""

import asyncio
import re
import time

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.issues_api import auto_remove_issues
from backend.shared import agents, github_account, issues, jobs, pr_tracking, repo_signals, repo_stats, repos
from github_searcher.github_account import SendError
from github_searcher.repo_signals import NEWCOMER_VERSION, NON_LATIN_SHARE, POLICY_VERSION
from github_searcher.search import get_readme, get_repo_totals

router = APIRouter(prefix="/api")

# The job statuses of an issue in progress, as the page counts them (RepositoryCards.tsx OPEN_JOB).
OPEN_JOB = ["queued", "working", "waiting_on_user", "waiting_on_maintainers"]
SIGNALS_CHECK_SECONDS = 10
REPO_STATS_SECONDS = 5 * 60
SIGNALS_RETRY_SECONDS = 60 * 60
# Repos whose signals are fetched at the same time in a full round.
SIGNALS_AT_ONCE = 4


class MoveRequest(BaseModel):
    name: str
    to: str


class RepoRequest(BaseModel):
    name: str


@router.post("/repos/move")
def move_repo(body: MoveRequest) -> dict:
    """Move to Prioritized or Contributed (its ⋯, or a drag), or Add to Target, on the Repositories page: to
    "prioritized" or "target" puts the repo in that list (repo_list.py; Target from now, also again for a rejected one), to
    "contributed" takes it out of Prioritized. Nothing takes one out of Target: the page moves it on by its PRs (merged,
    or closed without a merge). Any name, also a repo with PRs of yours that isn't in the list: the page has a card for
    it too."""
    if body.to == "prioritized":
        repos.set_prioritized([body.name], True)
    elif body.to == "contributed":
        repos.set_prioritized([body.name], False)
    elif body.to == "target":
        repos.set_target([body.name], True)
    else:
        raise HTTPException(status_code=400, detail="A repo moves to prioritized, contributed or target.")
    return {"prioritized": repos.prioritized(), "target": repos.target()}


@router.post("/repos/stop_in_progress")
async def stop_in_progress(body: RepoRequest) -> dict:
    """Stop all, over a card's issues in progress on the Repositories page: every fix_issue job on the repo still open
    with no PR of yours yet stops now (Agents.stop_jobs), and its issue leaves the Issues list for good (dismissed,
    issue_list.py), so no agent takes it again."""
    pr_jobs = [pr["job"] for pr in pr_tracking.summary()["items"] if pr["relation"] == "author"]
    stopping = []
    issue_ids = []
    for job in jobs.list():
        if job["kind"] != "fix_issue" or job["status"] not in OPEN_JOB or job["id"] in pr_jobs:
            continue
        if (job["repo"] or "").lower() != body.name.lower():
            continue
        stopping.append(job["id"])
        if job["issue"] is not None:
            issue_ids.append(job["issue"])
    await agents.stop_jobs(stopping, f"Stop all on the issues in progress in {body.name}")
    issues.dismiss(issue_ids)
    return {"stopped": stopping}


@router.post("/repos/close_prs")
async def close_prs(body: RepoRequest) -> dict:
    """Close all, over a card's open PRs on the Repositories page: every open PR of yours on the repo is closed on
    GitHub, as you. Its agent is set to Off first, so nobody drafts about it, and the open jobs on it stop (the one that
    made it and its follow-ups: Agents.stop_jobs). One GitHub didn't close stays open, and the answer is an error that
    says which."""
    open_prs = []
    for pr in pr_tracking.summary()["items"]:
        if pr["relation"] == "author" and pr["state"] == "open" and pr["repo"].lower() == body.name.lower():
            open_prs.append(pr)
    ids = [pr["id"].lower() for pr in open_prs]
    pr_jobs = [pr["job"] for pr in open_prs]
    stopping = [job["id"] for job in jobs.list() if (job["thread"] or "").lower() in ids or job["id"] in pr_jobs]
    for pr in open_prs:
        pr_tracking.set_agent(pr["id"], "off", None)
    await agents.stop_jobs(stopping, f"Close all on the open pull requests in {body.name}")
    closed = []
    failed = []
    for pr in open_prs:
        try:
            await asyncio.to_thread(github_account.manage, "close", pr["repo"], pr["number"])
        except SendError as error:
            failed.append(f"#{pr['number']}: {error}")
            continue
        closed.append(pr["id"])
    pr_tracking.wanted = True
    if failed:
        raise HTTPException(status_code=502, detail=f"Not closed: {'; '.join(failed)}")
    return {"closed": closed}


@router.post("/repos/delete")
async def delete_repo(body: RepoRequest) -> dict:
    """Delete, or Add to Removed for a repo with pull requests of yours, in the ⋯ of a card on the Repositories page,
    at once, with no "are you sure?". Every agent working on the repo stops now (Agents.stop_repo). A repo with pull
    requests of yours (merged, closed or open) is kept: it moves to the page's Removed section, stopped, so no new work
    starts there (repo_list.py). Any other leaves Repos, and its issues on the Issues board's Open and Catalog go."""
    listed = [item["full_name"] for item in repos.items()]
    if body.name not in listed:
        raise HTTPException(status_code=404, detail=f"{body.name} is not in Repos.")
    await agents.stop_repo(body.name)
    history = [pr for pr in pr_tracking.summary()["items"] if pr["relation"] == "author" and pr["repo"].lower() == body.name.lower()]
    if history:
        repos.set_removed([body.name], True)
        return {"removed": body.name}
    repos.set_prioritized([body.name], False)
    repos.set_target([body.name], False)
    repos.remove([body.name])
    auto_remove_issues()
    return {"deleted": body.name}


async def keep_repo_stats() -> None:
    """Runs as long as the backend: works out each repo's test run time and rating every REPO_STATS_SECONDS
    (repo_stats.py)."""
    while True:
        await repo_stats.refresh(pr_tracking.summary()["items"], jobs.list())
        await asyncio.sleep(REPO_STATS_SECONDS)


async def keep_signals() -> None:
    """Runs as long as the backend: fetches signals for repos that have none, once; they are kept after that.

    A repo that fails (GitHub down, the repo gone or renamed) is tried again after SIGNALS_RETRY_SECONDS.
    Signals of repos that left the list are dropped.
    """
    failed = []
    failed_since = time.monotonic()
    while True:
        if time.monotonic() - failed_since > SIGNALS_RETRY_SECONDS:
            failed = []
            failed_since = time.monotonic()
        names = [item["full_name"] for item in repos.items()]
        repo_signals.forget(names)
        known = repo_signals.all()
        todo = []
        for name in names:
            if name in failed:
                continue
            # Signals from before activity, the 30-day average merge by contributor or the newcomer verdict was counted
            # are as good as missing: every repo is read again once for them.
            if name not in known or "activity" not in known[name] or "merge_authors_30d" not in known[name] or "newcomer_verdict" not in known[name]:
                todo.append(name)
                continue
            # An AI policy read by older rules, or from fewer files, that may mean no_ai now (POLICY_VERSION): read again
            # once. A no_ai one stays.
            policy = known[name].get("ai_policy") or {}
            if policy.get("tag") != "no_ai" and policy.get("version") != POLICY_VERSION:
                todo.append(name)
                continue
            # A welcome newcomer verdict from before it read the PR template and the reviews (NEWCOMER_VERSION): read
            # again once. A closed one stays closed.
            verdict = known[name].get("newcomer_verdict") or {}
            if verdict.get("verdict") == "welcome" and verdict.get("version") != NEWCOMER_VERSION:
                todo.append(name)
        for start in range(0, len(todo), SIGNALS_AT_ONCE):
            batch = todo[start:start + SIGNALS_AT_ONCE]
            results = await asyncio.gather(*[repo_signals.refresh(name) for name in batch], return_exceptions=True)
            for name, result in zip(batch, results):
                if isinstance(result, Exception):
                    failed.append(name)
                    continue
                # Claude didn't give the newcomer verdict (the one before stays): later, not on every round.
                verdict = (repo_signals.get(name) or {}).get("newcomer_verdict") or {}
                if verdict.get("verdict") == "welcome" and verdict.get("version") != NEWCOMER_VERSION:
                    failed.append(name)
        # Signals from before the totals (commits, open, merged and closed PRs, open issues) were counted get them with one
        # small read each, not a whole new read (that asks Claude again).
        known = repo_signals.all()
        for name in names:
            if name in failed or name not in known or "merged_prs_total" in known[name]:
                continue
            try:
                totals = await asyncio.to_thread(get_repo_totals, name.split("/")[0], name.split("/")[1])
            except (httpx.HTTPError, ValueError):
                failed.append(name)
                continue
            repo_signals.update(name, totals)
        # Signals from before the README's language was checked get it with one small read each, the README alone, as
        # repo_signals.py does it (None without a README).
        known = repo_signals.all()
        for name in names:
            if name in failed or name not in known or "readme_english" in known[name]:
                continue
            english = None
            try:
                readme = await asyncio.to_thread(get_readme, name.split("/")[0], name.split("/")[1])
                text = re.sub(r"```.*?```|`[^`]*`|https?://\S+|<[^>]+>", " ", readme, flags=re.S)
                letters = [char for char in text if char.isalpha()]
                other = [char for char in letters if ord(char) > 0x24F]
                english = len(other) <= NON_LATIN_SHARE * len(letters)
            except httpx.HTTPStatusError as error:
                if error.response.status_code != 404:
                    failed.append(name)
                    continue
            except (httpx.HTTPError, ValueError):
                failed.append(name)
                continue
            repo_signals.update(name, {"readme_english": english})
        await asyncio.sleep(SIGNALS_CHECK_SECONDS)
