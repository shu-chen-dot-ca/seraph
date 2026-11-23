"""The backend: one FastAPI app that serves everything under /api.

The pieces are made once in backend/shared.py (the Repos and Issues lists, jobs, the inbox, your GitHub account, your
PRs, the VMs, the VM queue and the agents), and each part of the app has its own router in backend/*_api.py.
topic_data() is each topic of the live feed below.

The browser never polls. It keeps one websocket open on /api/live, gets every topic when it connects, then only the
topics that changed. Every store has a `version` number that goes up on each change, so finding the changes is a
cheap comparison every 250 ms. The big topics go at most every BIG_TOPIC_SECONDS, with all their changes since. The
topics are only what the pages show (TOPICS): the repos, your PRs, jobs, the blockers waiting for you, agents, VMs,
images, updates, the Automation's settings, the tokens the agents used, the Feedback page's list and what runs besides
the agents (activity). A topic is read and encoded once per change, and that same text goes to
every open browser (TEXTS).

Only this machine's own pages may use the API: the Host must be localhost or
127.0.0.1 (no DNS rebinding), and a request or websocket with an Origin must
come from a page on localhost or 127.0.0.1 (the Vite dev server, on whatever
port it picked). Pages from anywhere else, like a VM's desktop page (which the
agent controls) or another website, get 403.

The page itself comes from Vite in the dev copy (./run.sh). The live copy (deploy/, SERAPH_HOME set) serves its own
built page (frontend/dist) from here, at /, so it needs no Vite.

Every exception nobody caught (in a request, a background task on the event loop, or a thread) is reported to the app's
own errors (github_searcher/crashes.py). A background keeper that fails starts again a minute later (keep_alive), so the
app carries on by itself after the internet comes back; at start it waits for its secrets the same way
(github_searcher/secret_vault.py).

SERAPH_CHECK=1 in .env is the check a new release gets before it goes live (github_searcher/updates.py): it runs on a
copy of data/, and nothing in the background starts (no agents, no keepers), so it never acts on anything; it only
answers, and its live feed sends every topic once.
"""

import asyncio
import json
import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnect, WebSocketDisconnected

from backend import agents_api, artifacts_api, automation_api, errors_api, github_account_api, github_api, images_api, inbox_api, issues_api, problem_fixes_api, repo_automation_api, repos_api, secrets_api, updates_api, vms_api
from backend.shared import agents, crashes, explore, image_agents, images, inbox, issue_tags, jobs, pr_tracking, problem_fixes, problems, repos, token_usage, updates, vms
from github_searcher import claude_judge
from github_searcher.claude_models import MODELS
from github_searcher.token_balancer import BALANCER
from sandbox.vms import VMsError
from github_searcher.updates import HOME

# override: the backend reloads itself on code changes, and .env changes should apply then too.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

# The hosts the API answers: this computer only.
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
THREADS = 64
# The live feed ends for a browser that takes nothing for this long (feed).
SEND_SECONDS = 30
# The big topics (repos, jobs, inbox, prs, agents) go to a browser at most this often (feed): while
# GitHub is read again they change every second or two, one issue or PR at a time, and each change sent the whole
# topic again (over 1 MB a second all day long, the page's memory grew until the computer ran out).
BIG_TOPIC_SECONDS = 5
# How much of a finished job's notes the jobs topic carries (the agent chat shows three lines of them).
FINISHED_NOTES_CHARS = 400
# A background keeper that failed starts again this much later (keep_alive).
KEEPER_RETRY_SECONDS = 60
# A new release's check before it goes live (module docstring).
CHECK = os.environ.get("SERAPH_CHECK", "") == "1"


async def keep_alive(keeper) -> None:
    """Runs one of the background keepers (the list in lifespan) as long as the backend runs. One that fails with an
    error it doesn't handle itself (the internet down after a power cut, GitHub or Claude not answering) is one of the
    app's errors, and starts again KEEPER_RETRY_SECONDS later instead of staying stopped until the next restart. One that
    ends by itself (keep_updates in the dev copy) stays ended."""
    while True:
        try:
            await keeper()
            return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            crashes.add("backend", f"{keeper.__name__} stopped: {type(error).__name__}: {error}", traceback.format_exc())
        await asyncio.sleep(KEEPER_RETRY_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The threads asyncio.to_thread uses (the agents' VM tools, Explore, the signals, every GitHub call). A GitHub call
    # can wait up to two minutes for a rate limit (token_balancer.py); with only the default 20 threads, a burst of
    # those took them all and everything else stalled behind them.
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=THREADS))

    # What fails in a background task or a thread is one of the app's errors too, as well as in the log as before.
    def loop_error(loop, context: dict) -> None:
        error = context.get("exception")
        detail = ""
        if error is not None:
            detail = "".join(traceback.format_exception(error))
        crashes.add("backend", context.get("message", "") + (f": {type(error).__name__}: {error}" if error is not None else ""), detail)
        loop.default_exception_handler(context)

    loop.set_exception_handler(loop_error)
    thread_hook = threading.excepthook

    def thread_error(args) -> None:
        detail = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        crashes.add("backend", f"A thread failed: {args.exc_type.__name__}: {args.exc_value}", detail)
        thread_hook(args)

    threading.excepthook = thread_error

    if CHECK:
        yield
        return
    # The VMs come back as Seraph left them (their "on", sandbox/vms.py): one that was on and is off now (the computer
    # restarted, or it went off while Seraph was closed) starts again. One the user shut down stays off.
    for record in vms.list():
        if record.on and record.status == "stopped":
            try:
                vms.start_in_background(record.name)
            except VMsError:
                # Busy: a start or stop goes on already.
                pass
    # Agents run on this event loop, so they start here and not at import.
    await agents.start()
    # An Explore run the restart cut off goes on, when only the code reloaded.
    explore.resume()
    keepers = [
        # What is left of every GitHub quota, so Explore's first run knows how many workers it may have.
        asyncio.create_task(asyncio.to_thread(BALANCER.prime)),
        asyncio.create_task(keep_alive(issues_api.keep_facts)),
        asyncio.create_task(keep_alive(issues_api.keep_tags)),
        asyncio.create_task(keep_alive(issues_api.keep_new_tags)),
        asyncio.create_task(keep_alive(repo_automation_api.keep_adding)),
        asyncio.create_task(keep_alive(repo_automation_api.keep_catalog)),
        asyncio.create_task(keep_alive(repo_automation_api.keep_drafts)),
        asyncio.create_task(keep_alive(automation_api.keep_automation)),
        asyncio.create_task(keep_alive(issues_api.keep_catalog_agents)),
        asyncio.create_task(keep_alive(issues_api.keep_stale_prs)),
        asyncio.create_task(keep_alive(repos_api.keep_signals)),
        asyncio.create_task(keep_alive(github_api.keep_prs)),
        asyncio.create_task(keep_alive(github_api.keep_branches_clean)),
        asyncio.create_task(keep_alive(github_api.keep_forks_trimmed)),
        asyncio.create_task(keep_alive(github_api.keep_assignments_released)),
        asyncio.create_task(keep_alive(github_api.keep_profile_readme)),
        asyncio.create_task(keep_alive(github_api.keep_your_repositories)),
        asyncio.create_task(keep_alive(updates_api.keep_updates)),
        asyncio.create_task(keep_alive(agents_api.keep_token_usage)),
    ]
    yield
    explore.save_for_restart()
    for keeper in keepers:
        keeper.cancel()
    # The tags not written yet (issue_tags.py writes them at most every SAVE_SECONDS).
    issue_tags.flush(now=True)
    await agents.stop()


app = FastAPI(lifespan=lifespan)
ROUTERS = [inbox_api.router, automation_api.router, github_api.router, github_account_api.router, repos_api.router, agents_api.router, vms_api.router, images_api.router, artifacts_api.router, secrets_api.router, updates_api.router, problem_fixes_api.router, errors_api.router]
for router in ROUTERS:
    app.include_router(router)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


@app.middleware("http")
async def check_origin(request: Request, call_next):
    """Browsers send Origin with every POST, PUT and DELETE (also no-cors ones): only local pages may call."""
    origin = request.headers.get("origin")
    if origin is not None and urlsplit(origin).hostname not in ALLOWED_HOSTS:
        return JSONResponse(status_code=403, content={"detail": "Only pages on this machine may use the API."})
    return await call_next(request)


@app.exception_handler(httpx.HTTPStatusError)
def github_error(request: Request, error: httpx.HTTPStatusError) -> JSONResponse:
    """GitHub's own message (rate limit, not found, ...) instead of a bare 500."""
    try:
        message = error.response.json().get("message", "GitHub request failed.")
    except ValueError:
        message = "GitHub request failed."
    return JSONResponse(status_code=error.response.status_code, content={"detail": message})


@app.exception_handler(Exception)
def app_error(request: Request, error: Exception) -> JSONResponse:
    """A request that failed with an exception nobody caught: one of the app's errors (crashes.py), then the usual 500."""
    detail = "".join(traceback.format_exception(error))
    crashes.add("backend", f"{request.method} {request.url.path}: {type(error).__name__}: {error}", detail)
    return JSONResponse(status_code=500, content={"detail": f"Something went wrong in the app: {type(error).__name__}: {error}"})


@app.websocket("/api/live")
async def live(websocket: WebSocket) -> None:
    """Sends every topic once, then each topic again whenever its version changes."""
    # Websockets skip the http middleware, and browsers let any page open one: checked here.
    origin = websocket.headers.get("origin")
    if origin is not None and urlsplit(origin).hostname not in ALLOWED_HOSTS:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    await feed(websocket)


# The live feed's topics, by name: what the pages show.
TOPICS = ["repos", "jobs", "inbox", "prs", "agents", "vms", "images", "updates", "automation", "tokens", "problems", "activity"]
# Topics older releases had. The live copy checks a new release with its own list of topics (updates.py TOPICS), so in
# that check these go once too, empty, or a live copy from before the trim would refuse every new release.
OLD_TOPICS = ["issues", "tracked", "explore", "github", "issue_drafts", "your_repos", "notifications", "resource", "projects", "crashes", "repo_stats"]
# Each topic's message as last made, by topic: (its version, the JSON text). Every browser's feed sends the same text,
# so a topic is read and encoded once per change however many browsers are open.
TEXTS = {}


def topic_data(topic: str):
    """One topic of the live feed as the pages get it."""
    # The Repositories cards: the list, and which are archived, removed, prioritized, target or restored.
    if topic == "repos":
        return {
            "items": repos.items(),
            "can_undo": repos.can_undo(),
            "can_redo": repos.can_redo(),
            "archived": repos.archived(),
            "removed": repos.removed(),
            "prioritized": repos.prioritized(),
            "target": repos.target(),
            "restored": repos.restored(),
        }
    # Jobs without what no page shows (their evidence and timeline: half the topic), and a finished one with only the
    # start of its notes and no test runs: the topic goes out again on every change, and the jobs only grow.
    if topic == "jobs":
        items = jobs.list()
        for job in items:
            job.pop("evidence", None)
            job.pop("timeline", None)
            if job["status"] in ["done", "cancelled"]:
                job["notes"] = job["notes"][:FINISHED_NOTES_CHARS]
                job["tests"] = {"before": None, "after": None}
        return items
    # Only the blockers still waiting for you (approval drafts, inbox.py): every other draft goes to GitHub by itself
    # (repo_automation_api.py keep_drafts) and no page shows it.
    if topic == "inbox":
        return [draft for draft in inbox.pending() if draft["kind"] == "approval"]
    # Your PRs on GitHub and how each stands (pr_tracking.py).
    if topic == "prs":
        return pr_tracking.summary()
    if topic == "agents":
        return agents.summaries()
    if topic == "vms":
        return [vms.summary(record) for record in vms.list()]
    if topic == "images":
        return images.summary()
    # The live copy's updates (updates_api.py): the version that runs, and a newer one that is ready.
    if topic == "updates":
        return updates.summary()
    # The Automation page (automation_api.py): its settings, its repos' labels and what it did.
    if topic == "automation":
        return automation_api.summary()
    # The tokens the agents used, per model and over time (token_usage.py): the Dashboard's Tokens chart.
    if topic == "tokens":
        return token_usage.summary()
    # The Feedback page: what the agents reported and what the app saw itself, open and closed (problems.py).
    if topic == "problems":
        return problems.list()
    # What runs besides the agents, for the Dashboard's Agents: the images whose agent is in a turn, a Fix all run
    # (problem_fixes.py: when it started, how many feedback items it was given, its VM), the checks running now
    # (claude_judge.py), and the model each of these uses (claude_models.py).
    if topic == "activity":
        fixes = problem_fixes.status()
        fix_all = None
        if fixes["running"]:
            run = fixes["runs"][0]
            fix_all = {"started_at": run["started_at"], "items": len(run["problems"]), "vm": fixes["vm"]}
        models = {"checks": MODELS["judgment"], "image": MODELS["image"], "fix_all": MODELS["fix_problems"]}
        return {"images": sorted(image_agents.running), "fix_all": fix_all, "checks": claude_judge.activity(), "models": models}
    raise ValueError(f"No topic {topic}: one of {', '.join(TOPICS)}")


async def feed(websocket: WebSocket) -> None:
    """The live feed of one browser, until it goes away."""
    # The version of each topic this browser has; None until it is sent.
    sent = {"repos": None, "jobs": None, "inbox": None, "prs": None, "agents": None, "vms": None, "images": None, "updates": None, "automation": None, "tokens": None, "problems": None, "activity": None}
    # When each big topic last went (time.monotonic()): again only BIG_TOPIC_SECONDS later, with every change since.
    sent_at = {"repos": 0.0, "jobs": 0.0, "inbox": 0.0, "prs": 0.0, "agents": 0.0, "problems": 0.0}
    if CHECK:
        for topic in OLD_TOPICS:
            await websocket.send_json({"topic": topic, "data": None})
    while True:
        # Each topic's version now. Images say which VMs were made from each, so they are sent again when the VM list
        # changes too; not on every usage sample though: only the number of VMs and their images matter.
        vm_images = [(record.name, record.image_fingerprint) for record in vms.list()]
        versions = {
            "repos": repos.version,
            "jobs": jobs.version,
            "inbox": inbox.version,
            "prs": pr_tracking.version,
            "agents": agents.version,
            "vms": vms.version,
            "images": (images.version, vm_images),
            "updates": updates.version,
            "automation": issues_api.AUTOMATION_VERSION["version"],
            "tokens": token_usage.version,
            "problems": problems.version,
            "activity": (
                tuple(image_agents.running),
                bool(problem_fixes.data["runs"]) and problem_fixes.data["runs"][0]["state"] == "running",
                claude_judge.COUNTS["version"],
            ),
        }
        # The version is noted before the data is read: a change in between is sent again next tick, never lost.
        messages = []
        now = time.monotonic()
        for topic in TOPICS:
            if sent[topic] == versions[topic]:
                continue
            if topic in sent_at and now - sent_at[topic] < BIG_TOPIC_SECONDS:
                continue
            sent[topic] = versions[topic]
            if topic in sent_at:
                sent_at[topic] = now
            # Read and encoded once per version for every open browser (TEXTS), not once per browser.
            if topic not in TEXTS or TEXTS[topic][0] != versions[topic]:
                TEXTS[topic] = (versions[topic], json.dumps({"topic": topic, "data": topic_data(topic)}, separators=(",", ":"), ensure_ascii=False))
            messages.append(TEXTS[topic][1])

        # A browser that takes nothing for SEND_SECONDS is gone (its tab or the dev server's proxy stopped reading): the
        # feed ends, and a page still open connects again.
        try:
            for message in messages:
                await asyncio.wait_for(websocket.send_text(message), timeout=SEND_SECONDS)
        except (TimeoutError, WebSocketDisconnect, WebSocketDisconnected):
            return
        try:
            # Waiting for a message from the browser is the 250 ms tick; it also notices a closed tab at once. The
            # browser sends nothing else.
            received = await asyncio.wait_for(websocket.receive(), timeout=0.25)
        except TimeoutError:
            continue
        except (WebSocketDisconnect, WebSocketDisconnected):
            return
        if received["type"] == "websocket.disconnect":
            return


class Page(StaticFiles):
    """The live copy's built page. index.html is asked for again on every load (no-cache), so the reload after an
    update gets the new one; the files in assets/ have a hash of their content in their names."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if not path.startswith("assets/"):
            response.headers["Cache-Control"] = "no-cache"
        return response


# Last, so every /api route comes first.
if HOME != "":
    app.mount("/", Page(directory=Path(__file__).resolve().parent.parent / "frontend" / "dist", html=True), name="page")
