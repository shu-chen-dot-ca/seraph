"""Settings → Fix problems (frontend/src/ProblemFixes.tsx): the daily run that fixes the agents' problems, pushes the
fixes and releases the app (github_searcher/problem_fixes.py has how it works).

GET  /api/problem_fixes       {"on", "hour", "minute", "runs", "running", "repo"}
PUT  /api/problem_fixes       {"on", "hour", "minute"}: answers like GET; 400 for a time that isn't one
POST /api/problem_fixes/run   Fix now: a run starts at once (400 while one runs)

keep_problem_fixes(), which the app runs in the background, starts the day's run when it is due, checked every
CHECK_SECONDS.
"""

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.shared import problem_fixes

router = APIRouter(prefix="/api")

CHECK_SECONDS = 60
# The run Fix now started: kept here, so it isn't dropped while it runs.
started = []


class SettingsRequest(BaseModel):
    on: bool
    hour: int
    minute: int


@router.get("/problem_fixes")
def problem_fixes_status() -> dict:
    return problem_fixes.status()


@router.put("/problem_fixes")
def set_problem_fixes(body: SettingsRequest) -> dict:
    try:
        return problem_fixes.set(body.on, body.hour, body.minute)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/problem_fixes/run")
async def fix_now() -> dict:
    if problem_fixes.status()["running"]:
        raise HTTPException(status_code=400, detail="A run is going already.")
    started.clear()
    started.append(asyncio.create_task(asyncio.to_thread(problem_fixes.run)))
    return {"ok": True}


async def keep_problem_fixes() -> None:
    """Runs as long as the backend: the day's run, once it is due."""
    while True:
        await asyncio.sleep(CHECK_SECONDS)
        if problem_fixes.due():
            await asyncio.to_thread(problem_fixes.run)
