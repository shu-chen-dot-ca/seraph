"""Each repo's record with us, for the Repositories page's cards (frontend/src/RepositoryCards.tsx): how long one round
of its tests takes, and, for the repos that merged a PR of ours, a 0-10 rating of how our PRs are received there.

One round: the test run every change there needs by the agents' rules (run_tests, github_searcher/agent/work_tools.py):
the after run on the change, which has to pass before its PR can be drafted, with the scope the agent took from the
project's rules: full (its official checks, what its rules ask to run before a PR) or focused (the tests that cover the
change, when its rules ask for no more). Not a before run: that one is only the agent's last resort. The repo's scope is
the one of the after run its newest job has (a job's tests.after, jobs.py: the run its PR draft was checked on); runs
of the other scope don't count. Every run that ended by itself goes in TEST_RUNS_FILE (DATA_DIR/test_runs.jsonl) as it
ends (finish_tests), one line each:

    {"at", "repo", "job", "when": "before" | "after", "scope": "focused" | "full", "passed": bool,
     "seconds": from its start to its end in the VM, "cpu_seconds": the CPU its commands used | null}

A repo's round is the median of those runs: seconds and cpu_seconds. Runs from before the log began are only on their
jobs' timelines (their captions say the scope, before or after, and the time), with times that count until the app
noticed the run ended (sandbox/agent/long_runs.py), often much later: those count only for a repo with none in the
log, and the card shows them as rough (exact false).

The rating, from our PRs there (pr_tracking.py, the ones we opened), each part 0 to 10 by a fixed scale, the rating
their average (only the parts known):
    First reply      the median time from opening to the first comment or review by a maintainer (role OWNER, MEMBER
                     or COLLABORATOR, not a bot, not us): FIRST_REPLY_HOURS
    Time to merge    the median time from opening to merge: MERGE_DAYS
    Merged           merged / (merged + closed without a merge), times 10
    Change requests  how many times a maintainer asked for changes, per PR of ours they answered: CHANGE_REQUESTS
    Tone             how the maintainers' words to us read, warm and helpful (10) to curt or dismissive (0): Claude's
                     judgment (claude_judge.py), many repos in one run, again only once their PRs changed
Each scale is [(up to, score), ...]: the first whose "up to" the value is at most gives its score, else 0.

What the rating needs from each PR's conversation is read from GitHub (the search tokens), and again whenever the PR
changed (its updated_at), READS_PER_ROUND at most each round, into STATS_FILE (DATA_DIR/repo_stats.json):

    {"threads": {"owner/name#n": {"updated_at", "first_reply_hours": float | None, "change_requests": int,
                                  "answered": bool, "words": ["what a maintainer wrote", ...]}},
     "tone": {"owner/name" (lower case): {"score": int, "why": str, "seen": ["owner/name#n@updated_at", ...]}}}

summary() is the live "repo_stats" topic: by repo in lower case,

    {"round_seconds", "round_cpu_seconds": int | None, "rounds": runs counted, "exact": bool, "scope": "full" | "focused" | None,
     "rating": float | None, "first_reply_hours", "merge_days", "merge_rate", "change_requests", "tone": float | None}

refresh() runs every few minutes (backend/repos_api.py keep_repo_stats); version goes up when the summary changed.
"""

import asyncio
import json
import re
import statistics
from datetime import datetime

from github_searcher.claude_judge import JudgeError, judge
from github_searcher.issue_tags import DATA_DIR
from github_searcher.repo_signals import MAINTAINERS
from github_searcher.search import get_full_thread

TEST_RUNS_FILE = DATA_DIR / "test_runs.jsonl"
STATS_FILE = DATA_DIR / "repo_stats.json"
FIRST_REPLY_HOURS = [(24, 10), (48, 8), (96, 6), (168, 4), (336, 2)]
MERGE_DAYS = [(1, 10), (3, 8), (7, 6), (14, 4), (30, 2)]
CHANGE_REQUESTS = [(0, 10), (0.5, 8), (1, 6), (2, 4), (3, 2)]
READS_PER_ROUND = 20
# What Claude reads per repo for its tone: this many of the maintainers' words, each cut to WORDS_CHARS.
WORDS_PER_PR = 15
WORDS_PER_REPO = 20
WORDS_CHARS = 400
TONE_REPOS_PER_RUN = 15
# The time a run that ended took, in its caption on the job's timeline (work_tools.py finish_tests): "in 1m 5s"; and
# how the caption says an after run of each scope.
CAPTION_TIME = re.compile(r" in (?:(\d+)m )?(\d+)s")
CAPTION_AFTER = {"full": "the project's official checks with the change", "focused": "the tests that cover the change with the change"}
TONE_SCHEMA = {
    "type": "object",
    "properties": {
        "repos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"repo": {"type": "string"}, "score": {"type": "integer", "minimum": 0, "maximum": 10}, "why": {"type": "string"}},
                "required": ["repo", "score", "why"],
            },
        }
    },
    "required": ["repos"],
}


class RepoStats:
    def __init__(self):
        self.version = 0
        self.data = {"threads": {}, "tone": {}}
        if STATS_FILE.is_file():
            self.data = json.loads(STATS_FILE.read_text())
        self.stats = {}

    def summary(self) -> dict:
        return self.stats

    async def refresh(self, prs: list[dict], jobs: list[dict]) -> None:
        """Read what is new and work the summary out again. prs: pr_tracking's items; jobs: every job. On the event loop."""
        mine = [pr for pr in prs if pr["relation"] == "author"]

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
                if run["when"] != "after" or run["scope"] != scopes.get(repo, run["scope"]):
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

        # The rating's PRs: ours in a repo that merged one of ours. Their conversations, the changed ones first read.
        merged_repos = [pr["repo"].lower() for pr in mine if pr["state"] == "merged"]
        to_read = []
        for pr in mine:
            if pr["repo"].lower() not in merged_repos:
                continue
            if self.data["threads"].get(pr["id"], {}).get("updated_at") != pr["updated_at"]:
                to_read.append(pr)
        for pr in to_read[:READS_PER_ROUND]:
            owner, name = pr["repo"].split("/")
            try:
                thread = await asyncio.to_thread(get_full_thread, owner, name, pr["number"])
            except Exception:
                # GitHub or the quota failed: the next round tries again.
                continue
            if thread is None:
                continue
            first = None
            change_requests = 0
            words = []
            for item in thread["timelineItems"]["nodes"]:
                if item is None or item["__typename"] not in ["IssueComment", "PullRequestReview"]:
                    continue
                if item.get("author") is None or item["author"]["__typename"] == "Bot" or item["author"]["login"].endswith("[bot]"):
                    continue
                if item["author"]["login"] == pr["author"] or item["authorAssociation"] not in MAINTAINERS:
                    continue
                if item["__typename"] == "PullRequestReview" and item["state"] == "PENDING":
                    continue
                at = item.get("submittedAt") or item["createdAt"]
                if first is None or at < first:
                    first = at
                if item["__typename"] == "PullRequestReview" and item["state"] == "CHANGES_REQUESTED":
                    change_requests += 1
                texts = [item["body"]]
                if item["__typename"] == "PullRequestReview":
                    texts += [comment["body"] for comment in item["comments"]["nodes"]]
                for text in texts:
                    if text.strip() != "" and len(words) < WORDS_PER_PR:
                        words.append(text.strip()[:WORDS_CHARS])
            first_reply_hours = None
            if first is not None:
                opened = datetime.fromisoformat(pr["opened_at"].replace("Z", "+00:00"))
                first_reply_hours = (datetime.fromisoformat(first.replace("Z", "+00:00")) - opened).total_seconds() / 3600
            self.data["threads"][pr["id"]] = {
                "updated_at": pr["updated_at"],
                "first_reply_hours": first_reply_hours,
                "change_requests": change_requests,
                "answered": first is not None,
                "words": words,
            }

        # Tone: Claude reads the maintainers' words of each repo whose PRs changed since it last did, many at once.
        asking = []
        for repo in sorted(set(merged_repos)):
            ids = [pr["id"] for pr in mine if pr["repo"].lower() == repo and pr["id"] in self.data["threads"]]
            seen = sorted(f"{each}@{self.data['threads'][each]['updated_at']}" for each in ids)
            words = []
            for each in ids:
                words += self.data["threads"][each]["words"]
            if words and self.data["tone"].get(repo, {}).get("seen") != seen:
                asking.append({"repo": repo, "seen": seen, "words": words[:WORDS_PER_REPO]})
        for start in range(0, len(asking), TONE_REPOS_PER_RUN):
            batch = asking[start:start + TONE_REPOS_PER_RUN]
            prompt = (
                "Below are open source projects, each with what its maintainers wrote to one contributor on that "
                "contributor's pull requests (comments and reviews). For each project, rate how the maintainers treat the "
                "contributor, 0 to 10: 10 warm and helpful (thanks, clear guidance, encouragement), 5 neutral and "
                "matter-of-fact, 0 curt, dismissive or hostile. Judge the tone toward the contributor, not whether the "
                "code was accepted. Give each project's repo exactly as written, its score, and why in one short sentence.\n"
            )
            for each in batch:
                prompt += f"\n## {each['repo']}\n"
                for text in each["words"]:
                    prompt += f"<message>\n{text}\n</message>\n"
            try:
                answer = await judge(prompt, TONE_SCHEMA, "low", "repo_tone")
            except JudgeError:
                # The next round asks again.
                continue
            for each in batch:
                for rated in answer["repos"]:
                    if rated["repo"].lower() == each["repo"]:
                        self.data["tone"][each["repo"]] = {"score": rated["score"], "why": rated["why"], "seen": each["seen"]}

        temporary = STATS_FILE.with_name(STATS_FILE.name + ".tmp")
        temporary.write_text(json.dumps(self.data))
        temporary.replace(STATS_FILE)

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
                "rating": None,
                "first_reply_hours": None,
                "merge_days": None,
                "merge_rate": None,
                "change_requests": None,
                "tone": None,
            }
        for repo in set(merged_repos):
            prs_here = [pr for pr in mine if pr["repo"].lower() == repo]
            threads = [self.data["threads"][pr["id"]] for pr in prs_here if pr["id"] in self.data["threads"]]
            replies = [thread["first_reply_hours"] for thread in threads if thread["first_reply_hours"] is not None]
            first_reply = statistics.median(replies) if replies else None
            merge_times = []
            for pr in prs_here:
                if pr["state"] == "merged" and pr["closed_at"] is not None:
                    opened = datetime.fromisoformat(pr["opened_at"].replace("Z", "+00:00"))
                    merge_times.append((datetime.fromisoformat(pr["closed_at"].replace("Z", "+00:00")) - opened).total_seconds() / 86400)
            merge_days = statistics.median(merge_times) if merge_times else None
            merged = len([pr for pr in prs_here if pr["state"] == "merged"])
            closed = len([pr for pr in prs_here if pr["state"] == "closed"])
            merge_rate = merged / (merged + closed)
            answered = [thread for thread in threads if thread["answered"]]
            change_requests = sum(thread["change_requests"] for thread in answered) / len(answered) if answered else None
            tone = self.data["tone"].get(repo, {}).get("score")

            parts = []
            for value, scale in [(first_reply, FIRST_REPLY_HOURS), (merge_days, MERGE_DAYS), (change_requests, CHANGE_REQUESTS)]:
                if value is None:
                    continue
                score = 0
                for limit, points in scale:
                    if value <= limit:
                        score = points
                        break
                parts.append(score)
            parts.append(merge_rate * 10)
            if tone is not None:
                parts.append(tone)

            if repo not in stats:
                stats[repo] = {"round_seconds": None, "round_cpu_seconds": None, "rounds": 0, "exact": False, "scope": None}
            stats[repo]["rating"] = round(sum(parts) / len(parts), 1)
            stats[repo]["first_reply_hours"] = round(first_reply, 1) if first_reply is not None else None
            stats[repo]["merge_days"] = round(merge_days, 1) if merge_days is not None else None
            stats[repo]["merge_rate"] = round(merge_rate, 2)
            stats[repo]["change_requests"] = round(change_requests, 1) if change_requests is not None else None
            stats[repo]["tone"] = tone
        if stats != self.stats:
            self.stats = stats
            self.version += 1
