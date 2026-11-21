"""An agent's chat and its jobs (frontend/src/AgentChat.tsx, opened from a VM's page): archive, unarchive and delete
an agent, chat with it, point it at a VM, give it priority, cancel a job, or skip a job's checks (its PR drafted now,
without passing tests or a reviewer). An agent that made PRs can't be deleted (409), only archived. A cancel goes on
the job's timeline as "Stopped by you" (github_searcher/jobs.py).

Every endpoint is `async def`: Agents lives on the backend's event loop (each
agent is a Claude conversation driven by an asyncio task). The list of agents
reaches the browser through /api/live; an agent's summary there has its
history_length, and the browser fetches the new entries with /history?since=.

keep_token_usage(), which the app runs in the background, adds up the usage log of every Claude run every
TOKEN_USAGE_SECONDS (github_searcher/token_usage.py), for the Dashboard's Tokens chart.
"""

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.shared import agents, jobs, token_usage
from sandbox.vms import VMsError

router = APIRouter(prefix="/api")
TOKEN_USAGE_SECONDS = 60


class MessageRequest(BaseModel):
    text: str


class QueuedRequest(BaseModel):
    index: int  # where it waits among the user's queued messages, oldest first
    text: str  # its text, to make sure it is that one


class TargetRequest(BaseModel):
    vm: str | None = None


class PriorityRequest(BaseModel):
    on: bool


@router.post("/agents/{agent_id}/priority")
async def set_priority(agent_id: str, body: PriorityRequest) -> dict:
    """Gives the agent priority until its tasks are over, or takes it back. 409 for an agent with no tasks going."""
    try:
        agents.set_priority(agent_id, body.on)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No agent {agent_id}")
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    return {}


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str) -> dict:
    """Stops the agent, takes it out of every VM queue and cancels its open jobs."""
    try:
        await agents.delete(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No agent {agent_id}")
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    return {}


@router.post("/agents/{agent_id}/archive")
async def archive_agent(agent_id: str) -> dict:
    """Stops the agent, takes it out of every VM queue and cancels its open jobs; its conversation stays."""
    try:
        await agents.archive(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No agent {agent_id}")
    return {}


@router.post("/agents/{agent_id}/unarchive")
async def unarchive_agent(agent_id: str) -> dict:
    try:
        agents.unarchive(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No agent {agent_id}")
    return {}


@router.get("/agents/{agent_id}/history")
async def agent_history(agent_id: str, since: int = 0) -> dict:
    """The history entries from index `since` on (a negative `since` counts from the end), and how many there are."""
    try:
        entries = agents.history(agent_id, 0)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No agent {agent_id}")
    return {"entries": entries[since:], "total": len(entries)}


@router.post("/agents/{agent_id}/message")
async def send_message(agent_id: str, body: MessageRequest) -> dict:
    """A chat message from the user. While the agent works, it waits as a pending message (10 at most)."""
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="The message is empty.")
    try:
        agents.send(agent_id, body.text)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No agent {agent_id}")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return {}


@router.post("/agents/{agent_id}/queue/cancel")
async def cancel_queued_message(agent_id: str, body: QueuedRequest) -> dict:
    """Takes one of the user's queued messages out before it goes in."""
    try:
        agents.cancel_queued(agent_id, body.index, body.text)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No agent {agent_id}")
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    return {}


@router.post("/agents/{agent_id}/interrupt")
async def interrupt_agent(agent_id: str) -> dict:
    try:
        await agents.interrupt(agent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No agent {agent_id}")
    return {}


@router.put("/agents/{agent_id}/target_vm")
async def set_target_vm(agent_id: str, body: TargetRequest) -> dict:
    """The VM the agent works on next. It can't change while the agent waits for or holds a VM."""
    try:
        agents.set_target_vm(agent_id, body.vm)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No agent {agent_id}")
    except VMsError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    return {}


@router.post("/jobs/{job_id}/skip_checks")
async def skip_checks(job_id: str) -> dict:
    """The user lets the job's PR be drafted now: without its tests passing and without a reviewer (work_tools.py
    draft_pr). The draft still waits for their Approve in the Inbox. Its agent is told, so it drafts at once."""
    try:
        job = jobs.get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No job {job_id}")
    if job["status"] in ("done", "cancelled"):
        raise HTTPException(status_code=409, detail=f"{job_id} is already {job['status']}.")
    jobs.add_timeline(job_id, "status", "Checks skipped by you")
    job = jobs.update(job_id, skip_checks=True)
    agents.notify(
        job["agent"],
        f"The user skipped the checks for {job_id} ({job['title']}): draft its PR now with draft_pr, without waiting for "
        "the tests (stop a test run of it you no longer need with run_stop). It goes straight to the user's Inbox, without a "
        "reviewer, and still waits for their Approve.",
    )
    return job


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict:
    """The user drops a job. Its agent is told, so it stops working on it and moves on."""
    try:
        job = jobs.get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No job {job_id}")
    if job["status"] in ("done", "cancelled"):
        raise HTTPException(status_code=409, detail=f"{job_id} is already {job['status']}.")
    jobs.add_timeline(job_id, "status", "Stopped by you")
    job = jobs.update(job_id, status="cancelled")
    agents.notify(job["agent"], f"The user cancelled {job_id} ({job['title']}). Stop working on it and go on with your other jobs.")
    return job


async def keep_token_usage() -> None:
    """Runs as long as the backend: reads what is new in the usage log (and the agents' conversations from before it)
    every TOKEN_USAGE_SECONDS, in a thread, so nothing waits for it."""
    while True:
        await asyncio.to_thread(token_usage.read)
        await asyncio.sleep(TOKEN_USAGE_SECONDS)
