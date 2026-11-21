"""The Repos list: the repos agents (or the user) picked to look for good first issues in.

The Tracked list (repos the user wants to keep an eye on for new issues) is the same kind of
list in its own file: RepoList("tracked.json").

One JSON file, DATA_DIR/repos.json:

    {"items": [RepoItem, ...], "undo": [[RepoItem, ...], ...], "redo": [[RepoItem, ...], ...], "archived": [full_name, ...],
     "removed": [full_name, ...], "prioritized": [full_name, ...], "target": {full_name: when it went there, ...}}

    RepoItem = {"full_name", "description", "stars", "default_branch", "html_url",
                "note", "added_by": "user" | "<agent id>", "added_at", "tag"?}

"tag" is the user's own group for a repo; missing or "" when it has none. A repo has one tag on every page: the Repos
list's when it is in it (set from an old page).

Items are kept in the order they were added. Undo/redo is snapshot based, so it undoes an
agent's change the same way as the user's: every change pushes a copy of the whole list onto
"undo" (the last UNDO_LIMIT are kept) and clears "redo".

archived is the repos the user deleted on the Dashboard's Repository page while it has pull requests (open, closed or merged) of
theirs: they stay in the list and show in its Archived section (set_archived). Not an undo step.
prioritized is the repos with a merged PR of the user's moved from that page's Contributed to its Prioritized (Move to
Prioritized, set_prioritized). target is the repos the user hunts, to become a contributor there, added from its Catalog
(Add to Target, set_target), each with when it went there (GitHub's time format, so it compares as text with a PR's
closed_at): the page shows one in Target until a PR of the user's there is merged (Contributed) or closed without a merge
after that time (rejected: the top of Catalog). Agents take new issues from Target first, then Prioritized
(backend/issues_api.py take_from_catalog). Not undo steps either.
removed is the repos with pull requests of the user's (merged, closed or open) deleted with Delete in the ⋯ of their
card on that page: they stay, in its Removed section, stopped: no new work there, what is going finishes (set_removed,
backend/repos_api.py). backend/issues_api.py, backend/repo_automation_api.py and agents.py act on it. Not an undo step
either.
The backend keeps one RepoList that the API and every agent share, so each method takes the
lock. version goes up by one on every change; the live feed compares it to see what to send.
"""

import copy
import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# override: the backend reloads itself on code changes, and .env changes should apply then too.
load_dotenv(PROJECT_ROOT / ".env", override=True)

DATA_DIR = PROJECT_ROOT / os.environ["DATA_DIR"]
UNDO_LIMIT = 100
# Only the last few undo/redo steps go into the file: with a long list, all UNDO_LIMIT copies
# make it tens of MB, written on every change. The others last until the backend restarts.
SAVED_STEPS = 10


class RepoList:
    def __init__(self, filename: str = "repos.json"):
        self.path = DATA_DIR / filename
        self.lock = threading.Lock()
        self.version = 0
        self.data = {"items": [], "undo": [], "redo": [], "archived": [], "removed": [], "prioritized": [], "target": {}}
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
            # Lists from before archived, removed, prioritized or target have none.
            self.data.setdefault("archived", [])
            self.data.setdefault("removed", [])
            self.data.setdefault("prioritized", [])
            self.data.setdefault("target", {})
            # target was a list of names for a few hours on 2026-11-20, before its times were kept: each from now.
            if isinstance(self.data["target"], list):
                now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                self.data["target"] = {name: now for name in self.data["target"]}

    def save(self) -> None:
        """Write the list to disk. Called with the lock held, after every change."""
        self.version += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write, then rename: a crash never leaves half a file. No indent: the undo
        # snapshots make the file big.
        saved = {
            "items": self.data["items"],
            "undo": self.data["undo"][-SAVED_STEPS:],
            "redo": self.data["redo"][-SAVED_STEPS:],
            "archived": self.data["archived"],
            "removed": self.data["removed"],
            "prioritized": self.data["prioritized"],
            "target": self.data["target"],
        }
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(saved))
        temporary.replace(self.path)

    def items(self) -> list[dict]:
        with self.lock:
            return copy.deepcopy(self.data["items"])

    def archived(self) -> list[str]:
        with self.lock:
            return list(self.data["archived"])

    def set_archived(self, full_names: list[str], archived: bool) -> None:
        with self.lock:
            self.data["archived"] = [name for name in self.data["archived"] if name not in full_names]
            if archived:
                self.data["archived"] += full_names
            self.save()

    def removed(self) -> list[str]:
        with self.lock:
            return list(self.data["removed"])

    def set_removed(self, full_names: list[str], removed: bool) -> None:
        with self.lock:
            self.data["removed"] = [name for name in self.data["removed"] if name not in full_names]
            if removed:
                self.data["removed"] += full_names
            self.save()

    def prioritized(self) -> list[str]:
        with self.lock:
            return list(self.data["prioritized"])

    def set_prioritized(self, full_names: list[str], prioritized: bool) -> None:
        with self.lock:
            self.data["prioritized"] = [name for name in self.data["prioritized"] if name not in full_names]
            if prioritized:
                self.data["prioritized"] += full_names
            self.save()

    def target(self) -> dict[str, str]:
        with self.lock:
            return dict(self.data["target"])

    def set_target(self, full_names: list[str], target: bool) -> None:
        """Add to Target (target True), from now on, also again for one already there; or take them out."""
        with self.lock:
            now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            for name in full_names:
                self.data["target"].pop(name, None)
                if target:
                    self.data["target"][name] = now
            self.save()

    def can_undo(self) -> bool:
        with self.lock:
            return len(self.data["undo"]) > 0

    def can_redo(self) -> bool:
        with self.lock:
            return len(self.data["redo"]) > 0

    def add(self, items: list[dict]) -> list[str]:
        """Add filled RepoItems as one undo step. Names already in the list are skipped, compared without case as GitHub
        does (Acme/Tool is acme/tool).

        Returns the names that were added.
        """
        with self.lock:
            names = [item["full_name"].lower() for item in self.data["items"]]
            new = []
            for item in items:
                # Also skips a name given twice in the same call.
                if item["full_name"].lower() in names:
                    continue
                names.append(item["full_name"].lower())
                new.append(copy.deepcopy(item))
            if not new:
                return []

            self.data["undo"].append(copy.deepcopy(self.data["items"]))
            self.data["undo"] = self.data["undo"][-UNDO_LIMIT:]
            self.data["redo"] = []
            self.data["items"] = self.data["items"] + new
            self.save()
            return [item["full_name"] for item in new]

    def remove(self, full_names: list[str]) -> list[str]:
        """Remove repos as one undo step. Returns the names that were in the list."""
        with self.lock:
            removed = [item["full_name"] for item in self.data["items"] if item["full_name"] in full_names]
            if not removed:
                return []

            self.data["undo"].append(copy.deepcopy(self.data["items"]))
            self.data["undo"] = self.data["undo"][-UNDO_LIMIT:]
            self.data["redo"] = []
            self.data["items"] = [item for item in self.data["items"] if item["full_name"] not in full_names]
            self.save()
            return removed

    def set_note(self, full_name: str, note: str) -> None:
        """Replace a repo's note as one undo step. KeyError if the repo is not in the list."""
        with self.lock:
            matches = [item for item in self.data["items"] if item["full_name"] == full_name]
            if not matches:
                raise KeyError(f"{full_name} is not in the list")

            # The snapshot is a deep copy, so changing the item below does not change it.
            self.data["undo"].append(copy.deepcopy(self.data["items"]))
            self.data["undo"] = self.data["undo"][-UNDO_LIMIT:]
            self.data["redo"] = []
            matches[0]["note"] = note
            self.save()

    def set_tag(self, full_names: list[str], tag: str) -> list[str]:
        """Put repos under a tag as one undo step ("" takes them out of theirs). Names are compared without case, as the
        other list may spell one its own way (GitHub's). Returns the names that were in the list, spelled as it has them."""
        with self.lock:
            lowered = [name.lower() for name in full_names]
            matches = [item for item in self.data["items"] if item["full_name"].lower() in lowered]
            if not matches:
                return []

            self.data["undo"].append(copy.deepcopy(self.data["items"]))
            self.data["undo"] = self.data["undo"][-UNDO_LIMIT:]
            self.data["redo"] = []
            for item in matches:
                item["tag"] = tag
            self.save()
            return [item["full_name"] for item in matches]

    def undo(self) -> bool:
        """Go back one step. False when there is nothing to undo."""
        with self.lock:
            if not self.data["undo"]:
                return False
            # The lists move between the stacks, nothing is shared, so no copy is needed.
            self.data["redo"].append(self.data["items"])
            self.data["redo"] = self.data["redo"][-UNDO_LIMIT:]
            self.data["items"] = self.data["undo"].pop()
            self.save()
            return True

    def redo(self) -> bool:
        """Go forward one undone step. False when there is nothing to redo."""
        with self.lock:
            if not self.data["redo"]:
                return False
            self.data["undo"].append(self.data["items"])
            self.data["undo"] = self.data["undo"][-UNDO_LIMIT:]
            self.data["items"] = self.data["redo"].pop()
            self.save()
            return True
