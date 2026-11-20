"""The Blockers page (frontend/src/Blockers.tsx): the user lifts or skips what only they can do, the agents' approval
drafts (a contributor agreement to sign and the like; inbox.py). Done is Approve: the agent goes on (signs it the way
the project asks). Skip is Reject: the agent gives the job up. Every other draft goes to GitHub by itself
(backend/repo_automation_api.py keep_drafts).

Every decision goes through Agents.decide, which also puts the draft's job back in the queue and wakes the agent, so
those endpoints run on the event loop (`async def`). The blockers reach the browser through /api/live (topic "inbox").

A draft's evidence (screenshots, images, command output) is files in EVIDENCE_DIR, served by name (the agent chat shows
them). Names are only ever ones the agent tools made (ev_<hex>.<ext>), so a request can't reach any other file.
"""

import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.shared import agents, inbox
from github_searcher.jobs import EVIDENCE_DIR

router = APIRouter(prefix="/api")

EVIDENCE_TYPES = {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp", "txt": "text/plain; charset=utf-8"}


class ReplyRequest(BaseModel):
    text: str = ""


@router.post("/inbox/{draft_id}/approve")
async def approve(draft_id: str, body: ReplyRequest | None = None) -> dict:
    """Done on the Blockers page. A note can come along; without one the body can be left out."""
    reply = ""
    if body is not None:
        reply = body.text
    try:
        # Only a blocker: the other drafts go to GitHub by themselves.
        if inbox.get(draft_id)["kind"] != "approval":
            raise ValueError(f"{draft_id} isn't a blocker.")
        return agents.decide(draft_id, "approved", reply)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No draft {draft_id}")
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))


@router.post("/inbox/{draft_id}/reject")
async def reject(draft_id: str, body: ReplyRequest | None = None) -> dict:
    """Skip on the Blockers page. A reason can come along, like approve's note."""
    reply = ""
    if body is not None:
        reply = body.text
    try:
        # Only a blocker: the other drafts go to GitHub by themselves.
        if inbox.get(draft_id)["kind"] != "approval":
            raise ValueError(f"{draft_id} isn't a blocker.")
        return agents.decide(draft_id, "rejected", reply)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No draft {draft_id}")
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))


@router.get("/evidence/{name}")
def evidence_file(name: str) -> FileResponse:
    """One evidence file. They never change once written, so the browser may keep them."""
    match = re.fullmatch(r"ev_[0-9a-f]{6}\.(jpg|png|gif|webp|txt)", name)
    if match is None:
        raise HTTPException(status_code=404, detail="No such evidence.")
    path = EVIDENCE_DIR / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No such evidence.")
    # nosniff: the browser takes the type as given, so a text file is never run as a page.
    headers = {"Cache-Control": "private, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"}
    return FileResponse(path, media_type=EVIDENCE_TYPES[match.group(1)], headers=headers)
