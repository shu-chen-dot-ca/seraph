"""The Repos list: the repos agents (or the user) picked to look for good first issues in.

The Tracked list (repos the user wants to keep an eye on for new issues) is the same kind of
list in its own file: RepoList("tracked.json").

One JSON file, DATA_DIR/repos.json:

    {"items": [RepoItem, ...], "undo": [[RepoItem, ...], ...], "redo": [[RepoItem, ...], ...], "archived": [full_name, ...],
     "planned": [full_name, ...], "priority": {full_name: "high" | "low" | "stopped"}, "removed": [full_name, ...]}

    RepoItem = {"full_name", "description", "stars", "default_branch", "html_url",
                "note", "added_by": "user" | "<agent id>", "added_at", "tag"?}

"tag" is the user's own group for a repo; missing or "" when it has none. A repo has one tag on every page: the Repos
list's when it is in it (set from an old page).

Items are kept in the order they were added. Undo/redo is snapshot based, so it undoes an
agent's change the same way as the user's: every change pushes a copy of the whole list onto
"undo" (the last UNDO_LIMIT are kept) and clears "redo".

archived is the repos the user deleted on the Dashboard's Repository page while it has pull requests (open, closed or merged) of
theirs: they stay in the list and show in its Archived section (set_archived). Not an undo step.
planned is the repos the user wants to contribute to, picked on that page (Add to Planned): its Planned section
(set_planned). Not an undo step either.
priority is the button on the right of each card on that page (set_priority), a repo not in it is normal: high
(Prioritized: its work goes first), low (Deprioritized: its work goes last) or stopped (Stopped: no new work there, what
is going finishes). backend/issues_api.py, backend/github_api.py and agents.py act on it. Not an undo step either.
removed is the repos with pull requests of the user's (merged, closed or open) deleted with Delete in the ⋯ of their
card on that page: they stay, in its Removed section, stopped (set_removed, backend/repos_api.py). Not an undo step
either.
The backend keeps one RepoList that the API and every agent share, so each method takes the
lock. version goes up by one on every change; the live feed compares it to see what to send.
"""

import copy
import json
import os
import threading
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
        self.data = {"items": [], "undo": [], "redo": [], "archived": [], "planned": [], "priority": {}, "removed": []}
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
            # Lists from before archived, planned, priority or removed have none.
            self.data.setdefault("archived", [])
            self.data.setdefault("planned", [])
            self.data.setdefault("priority", {})
            self.data.setdefault("removed", [])

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
            "planned": self.data["planned"],
            "priority": self.data["priority"],
            "removed": self.data["removed"],
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

    def planned(self) -> list[str]:
        with self.lock:
            return list(self.data["planned"])

    def set_planned(self, full_names: list[str], planned: bool) -> None:
        with self.lock:
            self.data["planned"] = [name for name in self.data["planned"] if name not in full_names]
            if planned:
                self.data["planned"] += full_names
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

    def priorities(self) -> dict[str, str]:
        with self.lock:
            return dict(self.data["priority"])

    def priority_of(self, full_name: str) -> str:
        """"high", "low", "stopped" or "normal", the name compared without case."""
        with self.lock:
            for name, priority in self.data["priority"].items():
                if name.lower() == full_name.lower():
                    return priority
        return "normal"

    def set_priority(self, full_name: str, priority: str) -> None:
        """"high", "low" or "stopped"; "normal" takes it out."""
        with self.lock:
            self.data["priority"].pop(full_name, None)
            if priority != "normal":
                self.data["priority"][full_name] = priority
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
