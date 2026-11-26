"""A repo's automation: what agents do there without asking you, as you. Each repo the Automation adds gets its
new_repos settings (backend/automation_api.py); no page changes a repo's own any more.

The settings, by repo, in SETTINGS_FILE (a repo not in it has DEFAULTS):

    {"owner/name": {"add_issues", "queue_issues", "take_issues", "questions", "comments", "pull_requests",
                    "open_issues": bool, "max_prs_first", "max_prs": int, "levels_first", "levels": ["easy", ...],
                    "instructions": str}, ...}

The Issue levels go by the repo's column on the Repositories page (agents.repo_columns, backend/issues_api.py): Catalog
has its levels_first (Easy), Target and Contributed Medium too, Prioritized its levels (Easy, Medium and Hard).
Settings from before levels_first have Easy for it. Open PRs at once come in two: until one of your PRs on the repo is
merged (max_prs_first: 1), and after, once you are a contributor there (max_prs: 5). Your merged PRs are the ones
pr_tracking.py follows.

and an issue's own level (set from an old page), which goes over its repo's for the drafts of the jobs on that issue, in
ISSUE_SETTINGS_FILE:

    {"owner/name#n": {"questions", "comments", "pull_requests": bool}, ...}

How many agents work at once is the Issues board's (max_agents in backend/issues_api.py, Concurrent agents on the
Automation page), not a repo's.

What each does:
- Add issues: keep_adding() below puts the repo's open issues whose level is among its Issue levels in the Issues list.
- Queue issues: keep_catalog() below puts the repo's issues that fit in the Issues board's Catalog. Settings from
  before it have none: their Take issues says, as Take issues did that then.
- Take issues: agents take the repo's issues from Catalog, from the top, while fewer than the board's max_agents work
  (keep_catalog_agents in backend/issues_api.py).
- Questions, Comments and Pull requests: keep_drafts() below, every DRAFTS_CHECK_SECONDS, looks at the pending drafts in
  the Inbox. A question with a recommended answer that needn't wait for you (inbox.py must_wait) is answered with it at
  once (answered_by "automation"), as the timer would later. A comment is posted on GitHub as you, and a PR (once its
  reviewer passed it) or an edit (a new title and description of your PR or issue) is sent as you, as Approve with
  Send does (github_account.py), then approved, so its agent hears it the same way. One GitHub refuses (or that has to
  wait, like a PR whose claim isn't decided yet, or whose claimed issue isn't assigned to you yet: github_account.py)
  stays in the Inbox, and is tried again after SEND_RETRY_SECONDS. The Automation page (backend/automation_api.py) goes
  over every repo's: Create pull requests off holds every new PR (also one made again in place of an old one), Reply
  to reviews and comments off holds everything a follow-up job drafts on a PR already open (comments, edits, new
  versions), Pull requests per day holds new PRs once that many went out since midnight, and Open pull requests (all
  repos together) and Open pull requests per repository hold new PRs like a repo's Open PRs at once. What is held
  waits in the Inbox and goes once the setting allows it. A claim on an issue goes by its repo's level only.
  Pull requests also lets agents update the branch of your open PRs there (update_branch, work_tools.py).
- Open PRs at once: how many of your PRs may be open on the repo at the same time, max_prs_first until one of yours
  there is merged (1 at first), max_prs after (5). Two places hold to it. Catalog to In progress: agents take no more
  of the repo's Catalog cards while its open PRs and its issues with an open job (from queued to waiting on you) add up
  to it (keep_catalog_agents in backend/issues_api.py). Review to an open PR: keep_drafts sends no new PR there while its
  open PRs are at it; the ones over it wait in the Inbox (the board's Review) until one is merged or closed. New
  versions of open PRs, and a PR made again in place of an old one, always go. No new PR goes to an archived repo
  (the Dashboard's Automation archives the ones that don't merge ours: backend/automation_api.py), but one for an issue
  our agents opened: we never give one of those up.
- Open issues: agents may open new issues on the repo as you, claimed for you (assigned, else your comment saying you
  are on it), where the project's rules allow it (open_issue, work_tools.py); each goes to the top of the Issues
  board's Catalog, before every other card, where another agent takes it first, whatever the repo's Take issues and
  Open PRs at once say (keep_catalog_agents in backend/issues_api.py). Never one out of scope: open_issue refuses it.

A repo in Target (repo_list.py target, the Repositories page's Target column) always gets worked: each round,
keep_adding() first puts it in Repos when it isn't there, takes it out of Archived, and turns on every level of its
automation (TARGET_LEVELS; the Automation's new_repos when it has no settings yet), so one you add with the box over the
cards is read like any other within ADD_CHECK_SECONDS. Its newcomer verdict doesn't keep it out either (below), nor its
other numbers its issues' merge (issue_tags.py): only its AI policy does.

keep_adding() runs in the background, every ADD_CHECK_SECONDS. For each repo in Repos (not archived, not one that
doesn't take AI-made contributions: AI policy no_ai, repo_signals.py, not one closed to outside contributors: its
newcomer verdict, whose issues are all No outside PRs, unless it is in Target, and not one at its Open PRs at once: HELD in
backend/issues_api.py, whose issues can't be taken now, to save GitHub's quota) with Add issues on, column by column
(Prioritized, Target, Contributed, then Catalog; none of Removed; SCAN_AT_ONCE repos at the same time), it reads its
newest open issues from GitHub, every
ADD_REFRESH_SECONDS (at once after Add issues is turned on, or the backend starts): only those opened in the last
SCAN_DAYS days, and at most its column's Issues to scan (the ⚙ of its column on the Repositories page,
backend/automation_api.py; MAX_SCAN when not set). Older ones are never read, but the
ones already on the board stay. Each issue only once: one it added, or that was in the Issues list when it looked, is
kept in ADDED_FILE and never added again, so one you take off stays off (Add in the repo's pop-up on the Repository page
still puts it in Catalog: backend/issues_api.py add_to_catalog); one taken off with the x is skipped too. Nor one
assigned to someone, with an open pull request that closes it, or with one of SKIP_LABELS. The rest are scanned, the
cheapest look first, so few are read in full (a full read costs about a hundred title reads):
1. Titles: Haiku reads the titles (and labels), TITLES_PER_RUN in one run, and keeps the ones worth a closer look: easy
   ones in Catalog, easy or medium in Target and Contributed, any size in Prioritized (its Issue levels, above).
2. Starts: Sonnet reads the ones the titles kept, with START_CHARS of each description and its number of comments,
   STARTS_PER_RUN in one run, and keeps the ones worth reading in full.
3. Full read: what passed both is tagged (issue_tags.py), the newest FULL_READS of the repo a round, the rest in the
   next rounds.
Each look is made once per title and levels (SCANS_FILE, by issue: the basis and each look's answer; a failed run
leaves its issues for the next round), so a repo that moves to a column with other levels is scanned
again. One read in full before and unchanged on GitHub since skips the scan. The ones read in full whose complexity is
among the repo's Issue levels (one out of scope has none) go into the Issues list, on the board's Open column, as read
then, so the Issues board doesn't read them again at once; one tagged in an earlier round is read again from fresh as
it comes in (keep_new_tags in backend/issues_api.py). Then the board's own rules (Remove automatically) decide on it.

keep_catalog() runs in the background right after issues get tagged (TAGGED in backend/issues_api.py, which keep_new_tags
and keep_tags set), and every CATALOG_CHECK_SECONDS anyway, so Open is only where an issue waits for its tags. For each
repo with Queue issues on (not an archived one), its issues on the board with no job (or only cancelled ones), open,
not one our agents opened, once their tags are read: after the issue's last change on GitHub that the app knows of, by
the current rules and since it came in, however long ago (an agent reads them again before it takes one:
take_from_catalog in backend/issues_api.py).
- Claimed: someone else is on it, or it is already fixed (status assigned or fixed, issue_tags.py). It leaves the Issues
  list at once, from Open and Catalog alike.
- Filtered out: on Open, not tagged free with merge likely, or its complexity isn't among the repo's issue levels. It
  leaves the Issues list at once.
- The rest on Open: Claude reads them, up to PER_RUN of one repo in one run with no tools (claude_judge.py), with
  DEFAULT_RULES and the repo's instructions on top, and picks which to take. The picked ones go to the end of Catalog,
  the others leave the Issues list. Each issue is asked about once per basis (the instructions, the levels and its last
  change on GitHub), kept in PICKED_FILE: one you move back from Catalog to Open stays there until one of those changes.
What leaves goes as one undo step on the Issues page; Add issues never adds it again (Add in the repo's pop-up on the
Repository page still does). A failed run is tried again next round.
"""

import asyncio
import copy
import hashlib
import json
import time
import traceback
from datetime import UTC, datetime, timedelta

import httpx

from backend.issues_api import AUTOMATION_VERSION, DASHBOARD_AUTOMATION_FILE, HELD, TAGGED
from backend.shared import agents, explore, github_account, inbox, issue_facts, issue_tags, issues, jobs, pr_tracking, repo_signals, repos
from github_searcher.claude_judge import JudgeError, judge
from github_searcher.claude_models import MODELS
from github_searcher.github_account import SendError
from github_searcher.inbox import AUTOMATION_FILE, ISSUE_AUTOMATION_FILE
from github_searcher.issue_tags import DATA_DIR, RULES_VERSION
from github_searcher.search import get_open_issues, get_repository

SETTINGS_FILE = AUTOMATION_FILE
ISSUE_SETTINGS_FILE = ISSUE_AUTOMATION_FILE
PICKED_FILE = DATA_DIR / "catalog_picks.json"
ADDED_FILE = DATA_DIR / "added_issues.json"
SCANS_FILE = DATA_DIR / "issue_scans.json"
DEFAULTS = {
    "add_issues": False,
    "queue_issues": False,
    "take_issues": False,
    "questions": False,
    "comments": False,
    "pull_requests": False,
    "open_issues": False,
    # How many of your PRs may be open on the repo at once: until one of yours there is merged, and after.
    "max_prs_first": 1,
    "max_prs": 5,
    # Which issues may be taken, by complexity: in Catalog, and in Prioritized (see the top of this file).
    "levels_first": ["easy"],
    "levels": ["easy", "medium", "hard"],
    "instructions": "",
}
# What a repo in Target always has on (add_issues): a repo in Target always gets worked.
TARGET_LEVELS = ["add_issues", "queue_issues", "take_issues", "questions", "comments", "pull_requests"]
# Add issues' scan (see the top of this file): issues opened within SCAN_DAYS, the newest MAX_SCAN at most (a column's
# Issues to scan on the Repositories page says otherwise); TITLES_PER_RUN titles in one Haiku run, STARTS_PER_RUN issues
# in one Sonnet run with START_CHARS of each description; FULL_READS full reads (issue_tags.py) of a repo a round.
SCAN_DAYS = 14
MAX_SCAN = 300
TITLES_PER_RUN = 200
STARTS_PER_RUN = 30
START_CHARS = 1500
FULL_READS = 10
# How many repos Add issues scans at the same time.
SCAN_AT_ONCE = 4
# Labels (in part, without case) that say an issue is no work for us.
SKIP_LABELS = ["duplicate", "wontfix", "won't fix", "invalid", "question", "discussion"]
CATALOG_CHECK_SECONDS = 60
ADD_CHECK_SECONDS = 60
# How often Add issues reads a repo's open issues from GitHub again.
ADD_REFRESH_SECONDS = 10 * 60
DRAFTS_CHECK_SECONDS = 10
# A draft GitHub refused (or that has to wait) is tried again after this long; it waits in the Inbox meanwhile.
SEND_RETRY_SECONDS = 10 * 60
# Issues of one repo in one Claude run.
PER_RUN = 40
# Always, under any repo's instructions, with what the user excludes besides (the Explore dialog's Exclude: theirs, in
# Explore's profile in DATA_DIR, never in the code).
DEFAULT_RULES = "Never take an issue that is unethical or NSFW, or that is anything the user excludes."
SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"number": {"type": "integer"}, "take": {"type": "boolean"}},
                "required": ["number", "take"],
            },
        }
    },
    "required": ["issues"],
}


# When each draft's send last failed, by id (only in memory: a restart tries them all again).
failed_at = {}


async def keep_drafts() -> None:
    """Runs as long as the backend: answers and sends the pending drafts their repo or issue lets go without you (see the
    top of this file)."""
    while True:
        try:
            await act_on_drafts()
        except Exception:
            # A file failed: the next round tries again.
            traceback.print_exc()
        await asyncio.sleep(DRAFTS_CHECK_SECONDS)


async def act_on_drafts() -> None:
    settings = {}
    if SETTINGS_FILE.is_file():
        settings = json.loads(SETTINGS_FILE.read_text())
    by_name = {repo.lower(): rules for repo, rules in settings.items()}
    own = {}
    if ISSUE_SETTINGS_FILE.is_file():
        own = json.loads(ISSUE_SETTINGS_FILE.read_text())
    # The Automation page's settings (backend/automation_api.py).
    automation = {}
    if DASHBOARD_AUTOMATION_FILE.is_file():
        automation = json.loads(DASHBOARD_AUTOMATION_FILE.read_text())
    send_prs = automation.get("send_prs", True)
    send_comments = automation.get("send_comments", True)
    per_repo = automation.get("max_open_per_repo")
    max_open = automation.get("max_open_prs")
    per_day = automation.get("max_prs_per_day")
    # The Repositories page's columns' settings (their ⚙), and each repo's column there (backend/issues_api.py
    # take_from_catalog works it out).
    column_settings = automation.get("columns", {})
    # New PRs sent since midnight here (local time), for Pull requests per day.
    midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC).isoformat()
    sent_today = inbox.new_prs_sent_since(midnight)
    all_jobs = jobs.list()
    issue_of_job = {job["id"]: job["issue"] for job in all_jobs}
    kind_of_job = {job["id"]: job["kind"] for job in all_jobs}
    archived = [name.lower() for name in repos.archived()]
    # The issues our agents opened as you (lower case): a PR for one still goes to an archived repo.
    opened = []
    for action in inbox.actions():
        if action["kind"] == "issue":
            opened.append(f"{action['sent']['repo']}#{action['sent']['number']}".lower())
    # Your PRs open on each repo, and how many of yours it merged (lower case): a new PR waits while the repo has its
    # Open PRs at once.
    open_prs = {}
    merged = {}
    for pr in pr_tracking.summary()["items"]:
        if pr["relation"] == "author" and pr["state"] == "open":
            open_prs[pr["repo"].lower()] = open_prs.get(pr["repo"].lower(), 0) + 1
        if pr["relation"] == "author" and pr["state"] == "merged":
            merged[pr["repo"].lower()] = merged.get(pr["repo"].lower(), 0) + 1

    total_open = sum(open_prs.values())
    for draft in inbox.pending():
        if draft["repo"] is None:
            continue
        rules = by_name.get(draft["repo"].lower(), DEFAULTS)
        level = {"questions": rules["questions"], "comments": rules["comments"], "pull_requests": rules["pull_requests"]}
        # The issue's own level goes over its repo's.
        issue_id = issue_of_job.get(draft["job"])
        if issue_id in own:
            level = own[issue_id]

        if draft["kind"] == "question" and level["questions"] and draft.get("must_wait") is None and draft.get("recommended"):
            try:
                agents.decide(draft["id"], "replied", f"I pick: {draft['recommended']}", answered_by="automation")
            except (KeyError, ValueError):
                pass  # You decided it, or deleted it, in the meantime.
            continue

        send = False
        if draft["kind"] == "comment" and level["comments"]:
            send = True
        if draft["kind"] in ["pr", "edit"] and level["pull_requests"]:
            send = True
        # A PR goes once its reviewer passed it, as it only reaches the Inbox then.
        review = draft.get("review")
        if draft["kind"] == "pr" and review is not None and review["state"] != "passed":
            send = False
        # A new PR (not a new version of an open one, nor one made again in place of one) only while the repo has room:
        # the others wait in Review until one of yours there is merged or closed. Publish on the Pull requests page still
        # sends one by hand.
        name = draft["repo"].lower()
        new_pr = draft["kind"] == "pr" and draft["update_of"] is None and draft["replaces"] is None
        limit = rules.get("max_prs_first", 1)
        if merged.get(name, 0) > 0:
            limit = rules.get("max_prs", 5)
        if per_repo is not None:
            limit = min(limit, per_repo)
        # Its column's Open PRs per repository goes over both.
        column_limit = (column_settings.get(agents.repo_columns.get(name, "")) or {}).get("max_open_per_repo")
        if column_limit is not None:
            limit = column_limit
        if send and new_pr and open_prs.get(name, 0) >= limit:
            send = False
        # The Automation page: Create pull requests is every new PR (also one made again in place of an old one), Reply
        # to reviews and comments everything on a PR already open (a follow-up job's comments and edits, and new
        # versions). A claim on an issue goes by its repo's level only.
        opens_pr = draft["kind"] == "pr" and draft["update_of"] is None
        if opens_pr and not send_prs:
            send = False
        if not opens_pr and kind_of_job.get(draft["job"]) == "follow_up" and not send_comments:
            send = False
        if opens_pr and per_day is not None and sent_today >= per_day:
            send = False
        if send and new_pr and max_open is not None and total_open >= max_open:
            send = False
        # Never a new one to an archived repo, but for an issue we opened: we never give one up.
        if send and new_pr and name in archived and (issue_id or "").lower() not in opened:
            send = False
        if not send or time.time() - failed_at.get(draft["id"], 0) < SEND_RETRY_SECONDS:
            continue
        try:
            await asyncio.to_thread(github_account.send, draft["id"])
            agents.decide(draft["id"], "approved")
            if new_pr:
                open_prs[name] = open_prs.get(name, 0) + 1
                total_open += 1
            if opens_pr:
                sent_today += 1
        except (SendError, KeyError, ValueError):
            failed_at[draft["id"]] = time.time()


# When Add issues last read each repo's open issues, by name (only in memory: a restart reads them all again).
read_at = {}
# When Add issues last finished a repo's scan, by name in lower case (ADDED_FILE's "scanned", kept): the Repositories
# page shows a scanned repo's issues worth doing, 0 too (backend/app.py ready).
SCANNED = {}
if ADDED_FILE.is_file():
    SCANNED = json.loads(ADDED_FILE.read_text()).get("scanned", {})


async def keep_adding() -> None:
    """Runs as long as the backend: puts the repos' open issues that match their Issue levels in the Issues list, each
    once (see the top of this file)."""
    while True:
        try:
            await add_issues()
        except Exception:
            # Claude or a file failed: the next round tries again.
            traceback.print_exc()
        await asyncio.sleep(ADD_CHECK_SECONDS)


async def add_issues() -> None:
    # A repo in Target always gets worked (repo_list.py target): it goes in Repos when it isn't there (Explore's minimums
    # took it out, or it went to Target from a card made from PRs alone), and comes out of Archived.
    listed_names = [item["full_name"].lower() for item in repos.items()]
    for name in repos.target():
        if name.lower() in listed_names:
            continue
        try:
            repo = await asyncio.to_thread(get_repository, name.split("/")[0], name.split("/")[1])
        except (httpx.HTTPError, ValueError):
            continue
        item = {
            "full_name": repo["full_name"],
            "description": repo["description"] or "",
            "stars": repo["stargazers_count"],
            "default_branch": repo["default_branch"],
            "html_url": repo["html_url"],
            "note": "",
            "added_by": "user",
            "added_at": datetime.now(UTC).isoformat(),
        }
        repos.add([item])
    target = [name.lower() for name in repos.target()]
    unarchive = [name for name in repos.archived() if name.lower() in target]
    if unarchive:
        repos.set_archived(unarchive, False)

    settings = {}
    if SETTINGS_FILE.is_file():
        settings = json.loads(SETTINGS_FILE.read_text())
    # And a repo in Target has every level of its automation on: the Automation's new_repos when it has no settings of
    # its own yet (Add to Target gives it none), else TARGET_LEVELS turned on in its own.
    automation = {}
    if DASHBOARD_AUTOMATION_FILE.is_file():
        automation = json.loads(DASHBOARD_AUTOMATION_FILE.read_text())
    before = json.dumps(settings)
    spelled = {repo.lower(): repo for repo in settings}
    for name in repos.target():
        if name.lower() not in spelled:
            settings[name] = copy.deepcopy(automation.get("new_repos", DEFAULTS))
            spelled[name.lower()] = name
        for key in TARGET_LEVELS:
            settings[spelled[name.lower()]][key] = True
    if json.dumps(settings) != before:
        SETTINGS_FILE.write_text(json.dumps(settings, indent=2))
        AUTOMATION_VERSION["version"] += 1
    # Not before the columns are worked out (the backend just started; keep_catalog_agents in backend/issues_api.py):
    # every repo would count as Catalog, with its levels (the next round, ADD_CHECK_SECONDS on).
    if not agents.repo_columns:
        return
    # By repo name in lower case: the settings may spell a name their own way.
    by_name = {repo.lower(): rules for repo, rules in settings.items()}
    added = []
    if ADDED_FILE.is_file():
        added = json.loads(ADDED_FILE.read_text())["added"]
    # Not an archived repo, nor one that doesn't take AI-made contributions (its AI policy, repo_signals.py), nor one that
    # isn't open to outside contributors (its newcomer verdict) unless it is in Target: none of their issues would be
    # merge likely.
    skipped = [name.lower() for name in repos.archived()]
    # Nor a removed one (repo_list.py): no new work there.
    skipped += [name.lower() for name in repos.removed()]
    skipped += [name.lower() for name, each in repo_signals.all().items() if (each.get("ai_policy") or {}).get("tag") == "no_ai"]
    for name, each in repo_signals.all().items():
        if (each.get("newcomer_verdict") or {}).get("verdict") == "closed" and name.lower() not in target:
            skipped.append(name.lower())
    # Nor one at its Open PRs at once: its issues can't be taken now.
    skipped += HELD["repos"]
    names = [item["full_name"] for item in repos.items() if item["full_name"].lower() not in skipped]
    # Column by column, as the Repositories page has them (agents.repo_columns, backend/issues_api.py): Prioritized,
    # Target, Contributed, then Catalog. None of Removed: no new work there. One the columns don't have yet (just put in
    # Repos) goes with Target when in it, else with Catalog.
    by_column = []
    for column in ["prioritized", "target", "contributed", "catalog"]:
        for name in names:
            known = agents.repo_columns.get(name.lower())
            if known is None:
                known = "target" if name.lower() in target else "catalog"
            if known == column:
                by_column.append(name)
    names = by_column
    # Sets, as the lists run to tens of thousands of issues and every open issue of every repo is looked up in them.
    listed = set(item["id"] for item in issues.items())
    dismissed = set(issues.dismissed())
    added_set = set(added)
    # Tags of repos no longer in Repos go (issue_tags.py): only the Issues list's stay.
    issue_tags.forget_repos([item["full_name"] for item in repos.items()], list(listed))

    # Each issue's scan (see the top of this file), and the issues opened since when (SCAN_DAYS ago) that it reads.
    scans = {}
    if SCANS_FILE.is_file():
        scans = json.loads(SCANS_FILE.read_text())
    since = (datetime.now(UTC) - timedelta(days=SCAN_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    column_settings = automation.get("columns", {})

    # The repos due a read: Add issues on, and not read in the last ADD_REFRESH_SECONDS.
    due = []
    for name in names:
        rules = by_name.get(name.lower())
        if rules is None or not rules.get("add_issues") or time.time() - read_at.get(name, 0) < ADD_REFRESH_SECONDS:
            continue
        due.append(name)

    # One repo's scan. SCAN_AT_ONCE run at the same time (below), sharing the lists and files above.
    async def scan(name: str) -> None:
        rules = by_name[name.lower()]
        # Set first: a repo GitHub fails on is tried again after ADD_REFRESH_SECONDS, not every round.
        read_at[name] = time.time()
        # Its column's Issues to scan on the Repositories page (its ⚙; backend/issues_api.py works out the column).
        column = agents.repo_columns.get(name.lower(), "catalog")
        max_scan = (column_settings.get(column) or {}).get("max_scan", MAX_SCAN)
        try:
            nodes = await asyncio.to_thread(get_open_issues, name.split("/")[0], name.split("/")[1], since, max_scan)
        except (httpx.HTTPError, ValueError):
            return
        # Tags of its issues not read any more (closed, or older than the newest it reads) go (issue_tags.py): only the
        # Issues list's stay. So do their scans.
        issue_tags.forget_closed(name, [f"{name}#{node['number']}" for node in nodes], list(listed))
        tags = issue_tags.all()
        ids = [f"{name}#{node['number']}" for node in nodes]
        for key in [key for key in scans if key.startswith(name + "#") and key not in ids]:
            del scans[key]
        # Its Issue levels, by its column (see the top of this file).
        levels = rules.get("levels_first", ["easy"])
        if column == "prioritized":
            levels = rules["levels"]
        elif column in ["target", "contributed"] and "medium" not in levels:
            levels = levels + ["medium"]

        # Not added before, nor assigned, nor with an open pull request that closes it, nor labelled as no work
        # (SKIP_LABELS). One read in full that hasn't changed since needs no new look; the others are scanned, each
        # step once per title and levels.
        waiting = []
        scanning = []
        for node in nodes:
            issue_id = f"{name}#{node['number']}"
            if issue_id in listed and issue_id not in added_set:
                added.append(issue_id)
                added_set.add(issue_id)
            if issue_id in added_set or issue_id in dismissed:
                continue
            if node["assignees"]["totalCount"] > 0 or node["closedByPullRequestsReferences"]["totalCount"] > 0:
                continue
            labels = " ".join(label["name"].lower() for label in node["labels"]["nodes"])
            if any(word in labels for word in SKIP_LABELS):
                continue
            tag = tags.get(issue_id)
            if tag is not None and tag["updated_at"] == node["updatedAt"]:
                waiting.append(node)
                continue
            scanning.append(node)
            basis = hashlib.sha256(json.dumps([node["title"], sorted(levels)]).encode()).hexdigest()[:16]
            if (scans.get(issue_id) or {}).get("basis") != basis:
                scans[issue_id] = {"basis": basis, "title": None, "start": None}

        # What the scan's two looks are for: its Issue levels.
        wanted = "small, self-contained fixes a first-time contributor can finish and prove: clear bugs, wrong docs or messages, small UI fixes"
        if "medium" in levels:
            wanted = "well-defined bugs and small improvements, easy or medium, that one pull request can fix"
        if "hard" in levels:
            wanted = "well-defined bugs and improvements of any size, easy, medium or hard, that one pull request can fix"
        rules_text = f"Rules: {DEFAULT_RULES} What they exclude, in their own words: {explore.profile['exclude'] or 'nothing'}"

        # Its titles alone (Haiku), TITLES_PER_RUN in one run. A failed run leaves its issues for the next round.
        unread = [node for node in scanning if scans[f"{name}#{node['number']}"]["title"] is None]
        for start in range(0, len(unread), TITLES_PER_RUN):
            run = unread[start:start + TITLES_PER_RUN]
            lines = []
            for node in run:
                labels = ", ".join(label["name"] for label in node["labels"]["nodes"])
                lines.append(f"#{node['number']}: {node['title']} [{labels}]")
            prompt = (
                f"Below are the titles of the newest open issues of the GitHub project {name}. We fix issues of outside "
                "projects with AI agents working on a Linux computer, and send the fixes as pull requests. From the title "
                f"alone, pick the ones worth a closer look: {wanted}. Skip feature requests that need the maintainers to "
                "decide on a design, questions, support requests, discussions, plans and tracking issues, and anything that "
                "only happens on Windows, macOS, iOS or Android.\n\n"
                f"{rules_text}\n\n"
                "Answer take true or false for every issue, by its number.\n\n" + "\n".join(lines)
            )
            try:
                answer = await judge(prompt, SCHEMA, "low", "issue_titles", MODELS["issue_titles"])
            except JudgeError:
                break
            answers = {each["number"]: each["take"] for each in answer["issues"]}
            for node in run:
                scans[f"{name}#{node['number']}"]["title"] = answers.get(node["number"])
            SCANS_FILE.write_text(json.dumps(scans))

        # The ones the titles kept: the start of their descriptions (Sonnet), STARTS_PER_RUN in one run.
        kept = [node for node in scanning if scans[f"{name}#{node['number']}"]["title"] is True]
        unread = [node for node in kept if scans[f"{name}#{node['number']}"]["start"] is None]
        for start in range(0, len(unread), STARTS_PER_RUN):
            run = unread[start:start + STARTS_PER_RUN]
            lines = []
            for node in run:
                labels = ", ".join(label["name"] for label in node["labels"]["nodes"])
                body = (node["body"] or "")[:START_CHARS]
                lines.append(f"#{node['number']}: {node['title']}\nLabels: {labels or 'none'}; {node['comments']['totalCount']} comments.\n{body}")
            prompt = (
                f"Below are open issues of the GitHub project {name}, each with the start of its description. We fix issues "
                "of outside projects with AI agents working on a Linux computer, and send the fixes as pull requests. Pick "
                f"the ones worth reading in full: {wanted}, where it is clear what to change, nobody says they are working "
                "on it, and the fix can be shown to work on Linux.\n\n"
                f"{rules_text}\n\n"
                "Answer take true or false for every issue, by its number.\n\n" + "\n\n".join(lines)
            )
            try:
                answer = await judge(prompt, SCHEMA, "medium", "issue_starts", MODELS["issue_starts"])
            except JudgeError:
                break
            answers = {each["number"]: each["take"] for each in answer["issues"]}
            for node in run:
                scans[f"{name}#{node['number']}"]["start"] = answers.get(node["number"])
            SCANS_FILE.write_text(json.dumps(scans))

        # What passed both is read in full (issue_tags.py), the newest FULL_READS a round; the rest in the next rounds.
        passed = [node for node in scanning if scans[f"{name}#{node['number']}"]["start"] is True]
        todo = [f"{name}#{node['number']}" for node in passed][:FULL_READS]
        if todo:
            await issue_tags.tag(todo)
        tags = issue_tags.all()
        waiting += passed

        items = []
        for node in waiting:
            issue_id = f"{name}#{node['number']}"
            tag = tags.get(issue_id)
            # Read in full as it is now (one not read yet waits for its round).
            if tag is None or tag["updated_at"] != node["updatedAt"]:
                continue
            if tag.get("merge") == "out of scope" or tag.get("complexity") not in levels:
                continue
            # One just read comes in as read then, so keep_new_tags (backend/issues_api.py) doesn't read it again.
            added_at = datetime.now(UTC).isoformat()
            if issue_id in todo:
                added_at = tag["judged_at"]
            items.append(
                {
                    "id": issue_id,
                    "repo": name,
                    "number": node["number"],
                    "title": node["title"],
                    "labels": [label["name"] for label in node["labels"]["nodes"]],
                    "state": "OPEN",
                    "comments": node["comments"]["totalCount"],
                    "html_url": node["url"],
                    "note": "",
                    "added_by": "user",
                    "added_at": added_at,
                }
            )
        new = issues.add(items)
        added.extend(new)
        added_set.update(new)
        listed.update(new)
        SCANNED[name.lower()] = datetime.now(UTC).isoformat()
        ADDED_FILE.write_text(json.dumps({"added": added, "scanned": SCANNED}, indent=2))

    # SCAN_AT_ONCE repos at the same time, in the order above.
    for start in range(0, len(due), SCAN_AT_ONCE):
        await asyncio.gather(*[scan(name) for name in due[start:start + SCAN_AT_ONCE]])


async def keep_catalog() -> None:
    """Runs as long as the backend: puts the issues an agent picks into Catalog and takes the claimed and filtered ones
    off the board, right after issues get tagged (see the top of this file)."""
    while True:
        # Cleared first: issues tagged while this round runs bring the next one at once.
        TAGGED.clear()
        try:
            await pick_for_catalog()
        except Exception:
            pass  # Claude or a file failed: the next round tries again.
        try:
            await asyncio.wait_for(TAGGED.wait(), CATALOG_CHECK_SECONDS)
        except TimeoutError:
            pass


async def pick_for_catalog() -> None:
    # Not before the columns are worked out (the backend just started; keep_catalog_agents in backend/issues_api.py):
    # every repo would count as Catalog, and its medium and hard issues would leave the board.
    if not agents.repo_columns:
        return
    settings = {}
    if SETTINGS_FILE.is_file():
        settings = json.loads(SETTINGS_FILE.read_text())
    # By repo name in lower case: an issue's repo may be spelled its own way. An archived or removed repo takes nothing.
    archived = [name.lower() for name in repos.archived()]
    archived += [name.lower() for name in repos.removed()]
    by_name = {repo.lower(): rules for repo, rules in settings.items() if repo.lower() not in archived}
    picked = {}
    if PICKED_FILE.is_file():
        picked = json.loads(PICKED_FILE.read_text())
    tags = issue_tags.all()
    facts = issue_facts.all()
    catalog = issues.board()["catalog"]
    started = [job["issue"] for job in jobs.list() if job["issue"] is not None and job["status"] != "cancelled"]
    # The issues our agents opened as you (lower case): claimed for you, never taken off here.
    opened = []
    for action in inbox.actions():
        if action["kind"] == "issue":
            opened.append(f"{action['sent']['repo']}#{action['sent']['number']}".lower())

    # What fits, by repo: (item, tag, basis); and what leaves the Issues list.
    candidates = {}
    drop = []
    for item in issues.items():
        rules = by_name.get(item["repo"].lower())
        tag = tags.get(item["id"])
        if rules is None or tag is None:
            continue
        # Settings from before Queue issues: their Take issues put issues in Catalog then.
        if not rules.get("queue_issues", rules["take_issues"]):
            continue
        if item["id"] in started or item["state"] == "CLOSED" or item["id"].lower() in opened:
            continue
        # Its tags read: after its last change on GitHub, by the current rules.
        fact = facts.get(item["id"])
        if fact and fact.get("updated_at") is not None and fact["updated_at"] > tag["updated_at"]:
            continue
        judged = tag.get("judged_at")
        if judged is None or tag.get("rules_version") != RULES_VERSION:
            continue
        # Not read again since it came in: keep_new_tags (backend/issues_api.py) does that first.
        if datetime.fromisoformat(judged) < datetime.fromisoformat(item["added_at"]):
            continue
        # Claimed (someone else is on it, or it is fixed): off the board, from Catalog too.
        if tag["status"] in ["assigned", "fixed"]:
            drop.append(item["id"])
            continue
        if item["id"] in catalog:
            continue
        # Filtered out: off the board.
        # Its Issue levels, by its column, as in add_issues.
        column = agents.repo_columns.get(item["repo"].lower(), "catalog")
        levels = rules.get("levels_first", ["easy"])
        if column == "prioritized":
            levels = rules["levels"]
        elif column in ["target", "contributed"] and "medium" not in levels:
            levels = levels + ["medium"]
        if tag["status"] != "free" or tag.get("merge") != "likely" or tag.get("complexity") not in levels:
            drop.append(item["id"])
            continue
        basis = hashlib.sha256(json.dumps([rules["instructions"], sorted(levels), tag["updated_at"]]).encode()).hexdigest()[:16]
        if picked.get(item["id"]) == basis:
            continue
        candidates.setdefault(item["repo"], []).append((item, tag, basis))
    if drop:
        issues.remove(drop)

    for repo, entries in candidates.items():
        rules = by_name[repo.lower()]
        for start in range(0, len(entries), PER_RUN):
            run = entries[start:start + PER_RUN]
            lines = []
            for item, tag, basis in run:
                lines.append(
                    f"#{item['number']}: {tag.get('name') or item['title']} (GitHub title: {item['title']}; {tag.get('kind')}, "
                    f"{tag.get('complexity')}, about {tag.get('lines')} lines). {tag['reason']}"
                )
            instructions = rules["instructions"] or "None."
            prompt = (
                f"Below are open issues of the GitHub project {repo}. We fix issues of outside projects with our own agents, "
                "and these already passed our checks: nobody else is on them, and a pull request from us would likely get "
                "merged. Pick which ones our agents should take on now.\n\n"
                f"Rules: {DEFAULT_RULES} What they exclude, in their own words: {explore.profile['exclude'] or 'nothing'}\n"
                f"The user's instructions for this repo, on top of the rules: {instructions}\n\n"
                "Answer take true or false for every issue, by its number.\n\n" + "\n".join(lines)
            )
            answer = await judge(prompt, SCHEMA, "medium", "catalog_picks")
            take = [each["number"] for each in answer["issues"] if each["take"]]
            answered = [each["number"] for each in answer["issues"]]
            new = []
            declined = []
            for item, tag, basis in run:
                if item["number"] in answered:
                    picked[item["id"]] = basis
                if item["number"] in take:
                    new.append(item["id"])
                if item["number"] in answered and item["number"] not in take:
                    declined.append(item["id"])
            PICKED_FILE.write_text(json.dumps(picked, indent=2))
            # The board as it is now: the user may have moved cards while Claude read.
            board = issues.board()
            added = [issue_id for issue_id in new if issue_id not in board["catalog"]]
            if added:
                issues.set_board(board["catalog"] + added, board["order"], board["held"])
            # The ones it didn't pick leave the board, unless the user moved one to Catalog meanwhile.
            declined = [issue_id for issue_id in declined if issue_id not in board["catalog"]]
            if declined:
                issues.remove(declined)
