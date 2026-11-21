"""Fix all on the Feedback page (frontend/src/Feedback.tsx): a run that fixes the open feedback in Seraph's own VM, pushes
the fixes and releases the app (github_searcher/problem_fixes.py has how it works). Only the button starts one.

GET  /api/problem_fixes       {"runs", "running", "repo", "vm"}
POST /api/problem_fixes/run   Fix all: a run starts at once (400 while one runs)
"""

import asyncio

from fastapi import APIRouter, HTTPException

from backend.shared import problem_fixes

router = APIRouter(prefix="/api")

# The run Fix all started: kept here, so it isn't dropped while it runs.
started = []


@router.get("/problem_fixes")
def problem_fixes_status() -> dict:
    return problem_fixes.status()


@router.post("/problem_fixes/run")
async def fix_all() -> dict:
    if problem_fixes.status()["running"]:
        raise HTTPException(status_code=400, detail="A run is going already.")
    started.clear()
    started.append(asyncio.create_task(asyncio.to_thread(problem_fixes.run)))
    return {"ok": True}
