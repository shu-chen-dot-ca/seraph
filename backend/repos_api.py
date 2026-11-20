"""The Repositories page's cards (frontend/src/RepositoryCards.tsx): Planned, Delete and the priority button, and keeping
the repos' signals fresh.

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
from backend.shared import agents, pr_tracking, repo_signals, repos
from github_searcher.repo_signals import NEWCOMER_VERSION, NON_LATIN_SHARE, POLICY_VERSION
from github_searcher.search import get_readme, get_repo_totals

router = APIRouter(prefix="/api")

SIGNALS_CHECK_SECONDS = 10
SIGNALS_RETRY_SECONDS = 60 * 60
# Repos whose signals are fetched at the same time in a full round.
SIGNALS_AT_ONCE = 4


class PlanRequest(BaseModel):
    names: list[str]
    planned: bool


class DeleteRequest(BaseModel):
    name: str


class PriorityRequest(BaseModel):
    name: str
    priority: str  # "high", "low", "stopped" or "normal"


@router.post("/repos/plan")
def plan_repos(body: PlanRequest) -> dict:
    """Add to Planned (planned true) or Remove from Planned (false) on the Repositories page: the repos you
    want to contribute to. Repos not in the list are left out."""
    listed = [item["full_name"] for item in repos.items()]
    names = [name for name in body.names if name in listed]
    repos.set_planned(names, body.planned)
    return {"planned": repos.planned()}


@router.post("/repos/delete")
async def delete_repo(body: DeleteRequest) -> dict:
    """Delete in the ⋯ of a card on the Repositories page, at once, with no "are you sure?". Every agent working
    on the repo stops now (Agents.stop_repo). A repo with pull requests of yours (merged, closed or open) is kept: it
    moves to the page's Removed section, stopped, so no new work starts there (repo_list.py). Any other leaves Repos,
    and its issues on the Issues board's Open and Catalog go."""
    listed = [item["full_name"] for item in repos.items()]
    if body.name not in listed:
        raise HTTPException(status_code=404, detail=f"{body.name} is not in Repos.")
    await agents.stop_repo(body.name)
    history = [pr for pr in pr_tracking.summary()["items"] if pr["relation"] == "author" and pr["repo"].lower() == body.name.lower()]
    if history:
        repos.set_removed([body.name], True)
        repos.set_priority(body.name, "stopped")
        return {"removed": body.name}
    repos.set_planned([body.name], False)
    repos.set_priority(body.name, "normal")
    repos.remove([body.name])
    auto_remove_issues()
    return {"deleted": body.name}


@router.post("/repos/priority")
def set_repo_priority(body: PriorityRequest) -> dict:
    """The button on the right of a card on the Repositories page: Prioritized (high), Deprioritized (low),
    Stopped, or back to normal (repo_list.py)."""
    if body.priority not in ["high", "low", "stopped", "normal"]:
        raise HTTPException(status_code=400, detail="priority must be high, low, stopped or normal.")
    listed = [item["full_name"] for item in repos.items()]
    if body.name not in listed:
        raise HTTPException(status_code=404, detail=f"{body.name} is not in Repos.")
    repos.set_priority(body.name, body.priority)
    return {"priority": repos.priorities()}


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
