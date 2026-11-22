"""Each repo's record with us, for the Repositories page's cards (frontend/src/RepositoryCards.tsx): how long one round
of its tests takes.

One round: the test run every change there needs by the agents' rules (run_tests, github_searcher/agent/work_tools.py):
the after run on the change, which has to pass before its PR can be drafted, with the scope the agent took from the
project's rules: full (its official checks, what its rules ask to run before a PR) or focused (the tests that cover the
change, when its rules ask for no more). Not a before run: that one is only the agent's last resort. The repo's scope is
the one of the after run its newest job has (a job's tests.after, jobs.py: the run its PR draft was checked on); runs
of the other scope don't count. Every run that ended by itself goes in TEST_RUNS_FILE (DATA_DIR/test_runs.jsonl) as it
ends (finish_tests), one line each:

    {"at", "repo", "job", "when": "before" | "after", "scope": "focused" | "full", "passed": bool,
     "seconds": from its start to its end in the VM, "exact": bool, "cpu_seconds": the CPU its commands used | null}

exact false (or missing, on the first lines): a run started before its start and end were written, whose seconds count
until the app noticed it ended; those don't count here.

A repo's round is the median of those runs: seconds and cpu_seconds. Runs from before the log began are only on their
jobs' timelines (their captions say the scope, before or after, and the time), with times that count until the app
noticed the run ended (sandbox/agent/long_runs.py), often much later: those count only for a repo with none in the
log, and the card shows them as rough (exact false).

summary() is the live "repo_stats" topic: by repo in lower case,

    {"round_seconds", "round_cpu_seconds": int | None, "rounds": runs counted, "exact": bool, "scope": "full" | "focused" | None}

refresh() runs every few minutes (backend/repos_api.py keep_repo_stats); version goes up when the summary changed.
"""

import json
import re
import statistics

from github_searcher.issue_tags import DATA_DIR

TEST_RUNS_FILE = DATA_DIR / "test_runs.jsonl"
# The time a run that ended took, in its caption on the job's timeline (work_tools.py finish_tests): "in 1m 5s"; and
# how the caption says an after run of each scope.
CAPTION_TIME = re.compile(r" in (?:(\d+)m )?(\d+)s")
CAPTION_AFTER = {"full": "the project's official checks with the change", "focused": "the tests that cover the change with the change"}


class RepoStats:
    def __init__(self):
        self.version = 0
        self.stats = {}

    def summary(self) -> dict:
        return self.stats

    def refresh(self, jobs: list[dict]) -> None:
        """Work the summary out again. jobs: every job."""
        # Each repo's scope: its newest job's after run's (one from before scopes is full), by repo in lower case.
        scopes = {}
        newest = {}
        for job in jobs:
            after = (job.get("tests") or {}).get("after")
            if job["repo"] is None or after is None:
                continue
            repo = job["repo"].lower()
            if repo not in newest or job["created_at"] > newest[repo]:
                newest[repo] = job["created_at"]
                scopes[repo] = after.get("scope", "full")
        # One round: the log's after runs of the repo's scope that ended by themselves.
        seconds = {}
        cpu_seconds = {}
        if TEST_RUNS_FILE.is_file():
            for line in TEST_RUNS_FILE.read_text().splitlines():
                if line.strip() == "":
                    continue
                run = json.loads(line)
                repo = run["repo"].lower()
                if not run.get("exact") or run["when"] != "after" or run["scope"] != scopes.get(repo, run["scope"]):
                    continue
                seconds.setdefault(repo, []).append(run["seconds"])
                if run["cpu_seconds"] is not None:
                    cpu_seconds.setdefault(repo, []).append(run["cpu_seconds"])
        # And the rough ones on the timelines, for a repo with none in the log.
        rough = {}
        for job in jobs:
            if job["repo"] is None or job["repo"].lower() in seconds or job["repo"].lower() not in scopes:
                continue
            for entry in job.get("timeline", []):
                if entry["kind"] != "tests" or CAPTION_AFTER[scopes[job["repo"].lower()]] not in entry["text"]:
                    continue
                if not entry["text"].startswith(("Passed", "Failed")):
                    continue
                found = CAPTION_TIME.search(entry["text"])
                if found:
                    rough.setdefault(job["repo"].lower(), []).append(int(found.group(1) or 0) * 60 + int(found.group(2)))

        # The summary, by repo in lower case.
        stats = {}
        for repo in set(seconds) | set(rough):
            runs = seconds.get(repo) or rough[repo]
            stats[repo] = {
                "round_seconds": round(statistics.median(runs)),
                "round_cpu_seconds": round(statistics.median(cpu_seconds[repo])) if repo in cpu_seconds else None,
                "rounds": len(runs),
                "exact": repo in seconds,
                "scope": scopes.get(repo),
            }
        if stats != self.stats:
            self.stats = stats
            self.version += 1
