"""Tokens: every Claude run the app makes, logged, and added up for the Dashboard's Tokens chart (backend/app.py, the
"tokens" topic; backend/agents_api.py keep_token_usage reads what is new every minute).

The log, DATA_DIR/claude_usage.jsonl, one line per agent reply and per model of every other run (a judgment, Explore's
look, an image agent's turn, Fix problems), written by add() as it happens:

    {"at": when (ISO, UTC), "work": the kind of work (claude_models.py), "what": which judgment or run ("issue_tags", ...;
     "" for an agent's reply), "model", "effort": what the run asked for ("" for the model's default),
     "input", "cache_write", "cache_read", "output": its tokens,
     "cost_usd": what Claude Code says it cost (null for an agent's reply: Claude Code counts cost per turn),
     "seconds": how long the run took (null for an agent's reply),
     "agent", "job", "repo": what it was for (null when nothing)}

The tokens are input, cache written, cache read and output, as the agents' own count has them (agents.py tokens_used).

Before the log began, only the agents' tokens are known: Claude Code keeps every conversation the agents have in files
of its own, one JSON line per block of a reply, in ~/.claude/projects/<AGENT_HOME as a folder name>/<session>.jsonl.
Each assistant line has the reply's id, its model, its time and its usage so far; a reply's blocks come one after the
other, so a reply counts once: when the next line is the same reply, only what grew is added. Lines with no model of
Claude's ("<synthetic>": Claude Code's own messages) use no tokens. These count as work "agent", and only up to the
log's first line: after it the log has every reply.

Both are added up per model and kind of work in SLICE_SECONDS slices of time, kept in DATA_DIR/token_usage.json with how
far each file was read, so a start reads only what is new (the very first read goes through every file once):

    {"log_offset": bytes of the log read, "log_start": the log's first time (ISO) or null,
     "files": {"<session>.jsonl": {"offset": bytes read, "reply": the last reply's id, "counted": its tokens so far}},
     "slices": {"<slice start, ISO in UTC>": {"<model>": {"<work>": tokens}}}}

A line still being written (no newline yet) waits for the next read. Slices older than KEEP_DAYS are dropped.

summary() is the topic: the slices as the page adds them up, coarser the further back so the topic stays small:
SLICE_SECONDS for the last FINE_HOURS, hours for the last HOURLY_DAYS, then local days (from midnight).
"""

import json
import os
import re
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# override: the backend reloads itself on code changes, and .env changes should apply then too.
load_dotenv(PROJECT_ROOT / ".env", override=True)

DATA_DIR = PROJECT_ROOT / os.environ["DATA_DIR"]
# Where the agents run Claude Code (as agent/agent.py has it; not imported from there, which logs here).
AGENT_HOME = DATA_DIR / "agent_home"
LOG = DATA_DIR / "claude_usage.jsonl"
LOG_LOCK = threading.Lock()
SLICE_SECONDS = 300
KEEP_DAYS = 91
FINE_HOURS = 2
HOURLY_DAYS = 8


def add(work: str, model: str, usage: dict, what: str = "", effort: str = "", cost_usd: float | None = None,
        seconds: float | None = None, agent: str | None = None, job: str | None = None, repo: str | None = None) -> None:
    """Logs one run (or one agent reply). usage: Claude's own names, input_tokens, cache_creation_input_tokens,
    cache_read_input_tokens and output_tokens, or Claude Code's per-model ones (inputTokens, cacheCreationInputTokens,
    cacheReadInputTokens, outputTokens). A run that used no tokens isn't logged."""
    entry = {
        "at": datetime.now(UTC).isoformat(),
        "work": work,
        "what": what,
        "model": model,
        "effort": effort,
        "input": usage.get("input_tokens") or usage.get("inputTokens") or 0,
        "cache_write": usage.get("cache_creation_input_tokens") or usage.get("cacheCreationInputTokens") or 0,
        "cache_read": usage.get("cache_read_input_tokens") or usage.get("cacheReadInputTokens") or 0,
        "output": usage.get("output_tokens") or usage.get("outputTokens") or 0,
        "cost_usd": cost_usd,
        "seconds": seconds,
        "agent": agent,
        "job": job,
        "repo": repo,
    }
    if entry["input"] + entry["cache_write"] + entry["cache_read"] + entry["output"] == 0:
        return
    with LOG_LOCK:
        with LOG.open("a") as file:
            file.write(json.dumps(entry, separators=(",", ":")) + "\n")


class TokenUsage:
    def __init__(self):
        self.path = DATA_DIR / "token_usage.json"
        # Where Claude Code keeps the agents' conversations (as agents.py finds them).
        self.folder = Path.home() / ".claude" / "projects" / re.sub(r"[^a-zA-Z0-9]", "-", str(AGENT_HOME))
        self.lock = threading.Lock()
        self.version = 0
        self.log_offset = 0
        self.log_start: str | None = None
        self.files: dict[str, dict] = {}
        self.slices: dict[str, dict[str, dict[str, int]]] = {}
        if self.path.exists():
            saved = json.loads(self.path.read_text())
            self.log_offset = saved.get("log_offset", 0)
            self.log_start = saved.get("log_start")
            self.files = saved["files"]
            self.slices = saved["slices"]
        # Saved before the kinds of work were kept: all of it was the agents'.
        for models in self.slices.values():
            for model, tokens in list(models.items()):
                if isinstance(tokens, int):
                    models[model] = {"agent": tokens}

    def read(self) -> None:
        """Reads what is new in the log, then in the agents' conversation files from before it, and adds it up; saves
        when anything was new."""
        changed = False
        # The log first, so its start is known before the conversation files are read.
        if LOG.exists() and LOG.stat().st_size > self.log_offset:
            with LOG.open("rb") as file:
                file.seek(self.log_offset)
                for line in file:
                    if not line.endswith(b"\n"):
                        break
                    self.log_offset += len(line)
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if self.log_start is None:
                        self.log_start = entry["at"]
                    tokens = entry["input"] + entry["cache_write"] + entry["cache_read"] + entry["output"]
                    start = int(datetime.fromisoformat(entry["at"]).timestamp()) // SLICE_SECONDS * SLICE_SECONDS
                    key = datetime.fromtimestamp(start, UTC).isoformat()
                    with self.lock:
                        works = self.slices.setdefault(key, {}).setdefault(entry["model"], {})
                        works[entry["work"]] = works.get(entry["work"], 0) + tokens
            changed = True
        log_start = datetime.fromisoformat(self.log_start) if self.log_start is not None else None

        paths = []
        if self.folder.is_dir():
            paths = sorted(self.folder.glob("*.jsonl"))
        for path in paths:
            state = self.files.get(path.name, {"offset": 0, "reply": None, "counted": 0})
            size = path.stat().st_size
            if size == state["offset"]:
                continue
            # Smaller than what was read: a new file under the old name, read from the start.
            if size < state["offset"]:
                state = {"offset": 0, "reply": None, "counted": 0}
            with path.open("rb") as file:
                file.seek(state["offset"])
                for line in file:
                    if not line.endswith(b"\n"):
                        break
                    state["offset"] += len(line)
                    if b'"usage"' not in line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    message = entry.get("message")
                    if entry.get("type") != "assistant" or not isinstance(message, dict) or not message.get("usage"):
                        continue
                    model = message.get("model") or ""
                    if model == "" or model.startswith("<"):
                        continue
                    usage = message["usage"]
                    tokens = (
                        (usage.get("input_tokens") or 0)
                        + (usage.get("cache_creation_input_tokens") or 0)
                        + (usage.get("cache_read_input_tokens") or 0)
                        + (usage.get("output_tokens") or 0)
                    )
                    # The same reply as the line before: only what grew since.
                    grown = tokens
                    if message.get("id") is not None and message.get("id") == state["reply"]:
                        grown = tokens - state["counted"]
                    else:
                        state["reply"] = message.get("id")
                        state["counted"] = 0
                    state["counted"] = max(state["counted"], tokens)
                    if grown <= 0 or "timestamp" not in entry:
                        continue
                    at = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
                    # From the log's start on, the log has this reply.
                    if log_start is not None and at >= log_start:
                        continue
                    start = int(at.timestamp()) // SLICE_SECONDS * SLICE_SECONDS
                    key = datetime.fromtimestamp(start, UTC).isoformat()
                    with self.lock:
                        works = self.slices.setdefault(key, {}).setdefault(model, {})
                        works["agent"] = works.get("agent", 0) + grown
            self.files[path.name] = state
            changed = True
        if not changed:
            return
        cutoff = datetime.now(UTC) - timedelta(days=KEEP_DAYS)
        with self.lock:
            for key in list(self.slices):
                if datetime.fromisoformat(key) < cutoff:
                    del self.slices[key]
            saved = {"log_offset": self.log_offset, "log_start": self.log_start, "files": self.files, "slices": self.slices}
            text = json.dumps(saved, separators=(",", ":"))
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(text)
        temporary.replace(self.path)
        self.version += 1

    def summary(self) -> dict:
        """The "tokens" topic: {"slices": [{"at": the slice's start (ISO), "model", "work", "tokens"}]}, oldest first.
        SLICE_SECONDS slices for the last FINE_HOURS, hours for the last HOURLY_DAYS, then local days."""
        now = datetime.now(UTC)
        with self.lock:
            items = [(key, json.loads(json.dumps(models))) for key, models in self.slices.items()]
        merged: dict[tuple[str, str, str], int] = {}
        for key, models in items:
            at = datetime.fromisoformat(key)
            start = at
            if now - at >= timedelta(hours=FINE_HOURS):
                start = at.replace(minute=0, second=0)
            if now - at >= timedelta(days=HOURLY_DAYS):
                start = at.astimezone().replace(hour=0, minute=0, second=0)
            for model, works in models.items():
                for work, tokens in works.items():
                    merged[(start.isoformat(), model, work)] = merged.get((start.isoformat(), model, work), 0) + tokens
        slices = []
        for (at, model, work), tokens in merged.items():
            slices.append({"at": at, "model": model, "work": work, "tokens": tokens})
        slices.sort(key=lambda each: datetime.fromisoformat(each["at"]))
        return {"slices": slices}
