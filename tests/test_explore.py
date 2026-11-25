"""Finding repos (github_searcher/explore.py) and the lists they go into (github_searcher/repo_list.py): which repos
Explore skips before any heavy work, which it keeps out for good (Explore's minimums, the numbers that say a PR of ours
would go nowhere, the quick look's verdict), how the run's filters work, how searches stay over 1k stars, how the
profile's types share the finds, and the Repos list's undo, redo, tags and archive.

Claude, GitHub and the signals are fakes with hand-made answers; the closer look (Claude Code with tools) is never
started: the quick look calls every repo here a weak fit, which skips it. Every file is kept in pytest's temporary
folder, never in DATA_DIR."""

import asyncio
import copy
import json

import pytest

from github_searcher import explore, repo_list
from github_searcher.explore import DEFAULT_PROFILE, Explore
from github_searcher.repo_list import SAVED_STEPS, RepoList

# A repo that passes every minimum: its numbers as repo_signals.fetch(judged=False) gives them.
GOOD_ACTIVITY = {"prs_opened_month": 40, "prs_merged_month": 30, "issues_opened_month": 30, "commits_month": 25, "trend": "flat"}
GOOD_REPO = {
    "stars": 4000,
    "description": "Checks data files",
    "topics": ["cli"],
    "language": "Rust",
    "archived": False,
    "fork": False,
    "contributors_total": 120,
    "open_prs_total": 40,
    "merged_prs_total": 900,
    "closed_prs_total": 200,
    "open_issues_total": 120,
    "readme_english": True,
    "commits_30d": 25,
    "outside_merged_90d": 12,
    "outside_merge_rate": 0.7,
    "median_days_to_first_reply": 1.5,
    "pr_window_days": 90,
    "active_mergers_30d": 3,
    "stale_outside_prs": 0,
    "unclaimed_beginner_issues": 2,
    "newcomers": {"tag": "ok"},
    "reviewers": {"agent": 0, "both": 1, "human": 4, "tag": "human"},
    "activity": GOOD_ACTIVITY,
    "community": {"contributing": True},
    "ai_policy": None,
    "atmosphere": None,
}


class FakeSignals:
    """What Explore uses of repo_signals.RepoSignals, for one hand-made repo: its numbers (signals), then Claude's reading
    of its AI policy (policy) and reviews. kept lists the repos whose signals were kept."""

    def __init__(self):
        self.signals = copy.deepcopy(GOOD_REPO)
        self.policy = "welcome"
        self.kept = []

    async def fetch(self, name, judged=True):
        return copy.deepcopy(self.signals)

    async def complete(self, name, signals):
        return {**signals, "ai_policy": {"tag": self.policy}, "atmosphere": {"tone": "warm", "summary": "Friendly, quick reviews."}}

    def put(self, name, signals):
        self.kept.append(name)


@pytest.fixture
def answers(monkeypatch):
    """What Claude and GitHub answer Explore: the quick look's verdict, the searches Claude plans for the profile's types,
    the new type it names, and a search's results. readmes and searches list what was read."""
    answers = {
        "verdict": {"is_project": True, "agent_can_do": True, "harmless": True, "excluded": False, "type": "Dev tools", "fit": "weak", "note": "A CLI that checks data files."},
        "plan": {"types": []},
        "new_type": {"name": "Data tools", "about": "Libraries that read and write data files.", "queries": ["topic:csv stars:1001..15000"]},
        "results": {"items": []},
        "readmes": [],
        "searches": [],
    }

    async def judge(prompt, schema, effort, what=""):
        if "types" in schema["properties"]:
            return answers["plan"]
        if "queries" in schema["properties"]:
            return answers["new_type"]
        return answers["verdict"]

    def get_readme(owner, repo):
        answers["readmes"].append(f"{owner}/{repo}")
        return "# Tool\n\nChecks data files.\n"

    def get_repository(owner, repo):
        return {"full_name": f"{owner}/{repo}", "description": "Checks data files", "stargazers_count": 4000, "default_branch": "main", "html_url": f"https://github.com/{owner}/{repo}"}

    def search_repositories(q, page):
        answers["searches"].append(q)
        return answers["results"]

    def query(prompt, options):
        raise AssertionError("The closer look is never started here")

    monkeypatch.setattr(explore, "judge", judge)
    monkeypatch.setattr(explore, "get_readme", get_readme)
    monkeypatch.setattr(explore, "get_repository", get_repository)
    monkeypatch.setattr(explore, "search_repositories", search_repositories)
    monkeypatch.setattr(explore, "query", query)
    return answers


@pytest.fixture
def finder(answers, tmp_path, monkeypatch):
    """Explore with the default profile and a run going on (no task: the tests call its steps), its files and the Repos
    and Tracked lists in pytest's temporary folder."""
    monkeypatch.setattr(explore, "DATA_DIR", tmp_path)
    monkeypatch.setattr(repo_list, "DATA_DIR", tmp_path)
    finder = Explore(RepoList(), RepoList("tracked.json"), FakeSignals())
    lanes = {lane["id"]: {"label": lane["label"], "share": lane["share"], "have": 0, "found": 0, "in_flight": 0, "exhausted": False} for lane in DEFAULT_PROFILE["lanes"]}
    finder.run = {"status": "running", "count": None, "filters": {}, "found": 0, "looked_at": 0, "lanes": lanes, "checking": [], "skipped": {}, "errors": []}
    return finder


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """An empty Repos list, its repos.json in pytest's temporary folder."""
    monkeypatch.setattr(repo_list, "DATA_DIR", tmp_path)
    return RepoList()


# Checking one repo.


@pytest.mark.parametrize(
    "change, reason",
    [
        ({"stars": 1000}, "1k stars or fewer"),
        ({"contributors_total": 39}, "Under 40 contributors"),
        ({"merged_prs_total": 300, "closed_prs_total": 100}, "400 closed PRs or fewer"),
        ({"open_issues_total": 10}, "10 open issues or fewer"),
        ({"archived": True}, "Archived"),
        ({"fork": True}, "A fork"),
        ({"commits_30d": 0}, "No commits in 30 days"),
        ({"outside_merged_90d": 0}, "No outside PR merged in 90 days"),
        ({"outside_merge_rate": 0.25}, "Most outside PRs closed unmerged"),
        # 500 of its 1,140 PRs ever were closed without a merge.
        ({"merged_prs_total": 600, "closed_prs_total": 500}, "Many PRs closed unmerged"),
        # 2 a month is under 0.1 a day.
        ({"activity": {**GOOD_ACTIVITY, "prs_merged_month": 2}}, "Merges under 0.1 PR a day"),
        ({"newcomers": {"tag": "turned_away"}}, "Turns newcomers away"),
        ({"newcomers": {"tag": "left_waiting"}}, "Leaves newcomers waiting"),
    ],
)
def test_a_repo_short_of_the_minimums_is_kept_out_for_good(finder, answers, tmp_path, change, reason):
    finder.repo_signals.signals.update(change)

    asyncio.run(finder.check("dev-tools", "Acme/Tool"))

    assert finder.run["skipped"] == {reason: 1}
    assert finder.found == []
    # Kept as checked, by its name in lower case, so no later run goes over it again; Claude never read its README.
    assert json.loads((tmp_path / "explore_checked.json").read_text())["acme/tool"]["reason"] == reason
    assert answers["readmes"] == []


def test_a_repo_that_passes_is_found_with_its_tags(finder, answers):
    # A huge history GitHub won't count contributors for passes, and so does a slow first reply alone (over a week).
    finder.repo_signals.signals.update({"contributors_total": None, "median_days_to_first_reply": 10})

    asyncio.run(finder.check("dev-tools", "acme/tool"))

    assert finder.run["skipped"] == {}
    assert finder.run["found"] == 1
    assert finder.run["lanes"]["dev-tools"]["found"] == 1
    assert finder.checked == {}
    found = finder.found[0]
    assert found["name"] == "acme/tool"
    assert found["lane"] == "dev-tools"
    assert found["fit"] == 0.25
    assert found["ai_policy"] == "welcome"
    assert found["newcomers"] == "ok"
    assert found["tone"] == "warm"
    assert found["note"] == "A CLI that checks data files."
    assert answers["readmes"] == ["acme/tool"]


def test_a_repo_counts_for_the_type_claude_put_it_under(finder, answers):
    # It came up in the Dev tools searches, but Claude says it is AI & harness.
    answers["verdict"]["type"] = "AI & harness"

    asyncio.run(finder.check("dev-tools", "acme/tool"))

    assert finder.found[0]["lane"] == "ai"
    assert finder.run["lanes"]["ai"]["found"] == 1
    assert finder.run["lanes"]["dev-tools"]["found"] == 0


@pytest.mark.parametrize(
    "answer, reason",
    [
        ("is_project", "Not a code project"),
        ("agent_can_do", "An agent can't do it alone"),
        # Made to harm people or systems, or takes no outside contributions: out of scope.
        ("harmless", "Out of scope"),
    ],
)
def test_the_quick_look_keeps_a_repo_out_for_good(finder, answers, answer, reason):
    answers["verdict"][answer] = False

    asyncio.run(finder.check("dev-tools", "acme/tool"))

    assert finder.run["skipped"] == {reason: 1}
    assert finder.checked["acme/tool"]["reason"] == reason
    assert finder.found == []


def test_what_the_exclude_names_is_skipped_but_not_kept(finder, answers):
    # The Exclude may change, so the repo can be checked again later.
    answers["verdict"]["excluded"] = True

    asyncio.run(finder.check("dev-tools", "acme/tool"))

    assert finder.run["skipped"] == {"Excluded": 1}
    assert "acme/tool" not in finder.checked
    assert finder.found == []


def test_an_include_filter_skips_for_this_run_only(finder, answers):
    # In a section with included tags, a repo needs one of them.
    finder.run["filters"] = {"reply:fast": "include", "reply:week": "include"}
    finder.repo_signals.signals["median_days_to_first_reply"] = 10

    asyncio.run(finder.check("dev-tools", "acme/tool"))

    assert finder.run["skipped"] == {"Not Replies in 2 days or Replies in a week": 1}
    assert finder.checked == {}


def test_an_excluded_tag_always_skips(finder):
    finder.run["filters"] = {"other:one_maintainer": "exclude"}
    finder.repo_signals.signals["active_mergers_30d"] = 1

    asyncio.run(finder.check("dev-tools", "acme/tool"))

    assert finder.run["skipped"] == {"1 maintainer": 1}


def test_a_policy_filter_is_read_before_the_readme(finder, answers):
    # The AI policy needs Claude: it is read first, and only a repo that passes gets its README judged.
    finder.run["filters"] = {"policy:disclose": "include"}

    asyncio.run(finder.check("dev-tools", "acme/tool"))

    assert finder.run["skipped"] == {"Not AI: disclose": 1}
    assert answers["readmes"] == []


def test_a_repo_that_bans_ai_made_contributions_is_kept_out_for_good(finder, answers):
    # The Dashboard's Automation runs Explore with policy:no_ai excluded: our agents write the code and the text.
    finder.run["filters"] = {"policy:no_ai": "exclude"}
    finder.repo_signals.policy = "no_ai"

    asyncio.run(finder.check("dev-tools", "acme/tool"))

    assert finder.run["skipped"] == {"No AI": 1}
    assert finder.checked["acme/tool"]["reason"] == "No AI"
    assert answers["readmes"] == []


def test_a_check_that_ends_after_the_run_found_enough_is_dropped(finder):
    finder.run["count"] = 1
    finder.run["found"] = 1

    asyncio.run(finder.check("dev-tools", "acme/tool"))

    assert finder.found == []


# Candidates and searches.


def test_candidates_already_known_are_skipped_before_any_work(finder):
    finder.repos.add([{"full_name": "acme/listed"}])
    finder.tracked.add([{"full_name": "acme/watched"}])
    finder.found = [{"name": "acme/waiting"}]
    finder.checked = {"acme/checked": {"at": "2026-11-01T12:00:00+00:00", "reason": "Archived"}}
    finder.cursors["dev-tools"] = {
        "pending": [
            {"name": "acme/old", "archived": True, "fork": False},
            {"name": "acme/copy", "archived": False, "fork": True},
            {"name": "ACME/Listed"},
            {"name": "acme/watched"},
            {"name": "acme/waiting"},
            {"name": "acme/checked"},
            {"name": "acme/new"},
        ],
        "query": 0,
        "page": 1,
    }

    name = asyncio.run(finder.next_candidate("dev-tools"))

    assert name == "acme/new"
    assert finder.run["looked_at"] == 7
    assert finder.run["skipped"] == {
        "Archived": 1,
        "A fork": 1,
        "Already in Repos": 1,
        "Tracked": 1,
        "Found before, waiting for you": 1,
        "Checked before": 1,
    }


def test_a_repo_two_searches_find_is_looked_at_once(finder):
    finder.cursors["dev-tools"] = {"pending": [{"name": "acme/tool"}, {"name": "Acme/Tool"}, {"name": "acme/other"}], "query": 0, "page": 1}

    first = asyncio.run(finder.next_candidate("dev-tools"))
    second = asyncio.run(finder.next_candidate("dev-tools"))

    assert [first, second] == ["acme/tool", "acme/other"]
    assert finder.run["looked_at"] == 2


def test_searches_never_go_to_1k_stars_or_under(finder, answers):
    queries = ["topic:cli stars:500..15000", "topic:cli language:Rust", "topic:cli stars:2000..9000"]
    finder.run_profile = {"include": "", "exclude": "", "lanes": [{"id": "cli", "label": "CLI", "about": "", "share": 100, "queries": queries}]}
    finder.cursors = {"cli": {"pending": [], "query": 0, "page": 1}}

    assert asyncio.run(finder.next_candidate("cli")) is None

    assert answers["searches"][0].startswith("topic:cli stars:1001..15000 archived:false pushed:>")
    assert answers["searches"][1].endswith(" stars:>1000")
    assert answers["searches"][2].startswith("topic:cli stars:2000..9000 archived:false pushed:>")


@pytest.mark.parametrize(
    "count, minutes, workers, filters, problem",
    [
        (0, None, None, {}, "Find 1 to 999 repos"),
        (None, 601, None, {}, "Run 1 to 600 minutes"),
        (None, None, 17, {}, "1 to 16 workers"),
        (None, None, None, {"policy:maybe": "include"}, "Unknown filter"),
        (None, None, None, {"policy:no_ai": "skip"}, "include or exclude"),
    ],
)
def test_a_run_with_limits_off_does_not_start(finder, count, minutes, workers, filters, problem):
    finder.run = None

    with pytest.raises(ValueError, match=problem):
        finder.start(count, minutes, workers, filters)


def test_a_second_run_does_not_start_while_one_runs(finder):
    with pytest.raises(ValueError, match="already running"):
        finder.start(None, None, None, {})


# The profile's types.


def test_types_share_the_finds_evenly_and_keep_their_ids(finder, answers):
    answers["plan"] = {
        "types": [
            {"name": "dev Tools", "queries": ["topic:cli stars:1001..15000", " "]},
            {"name": "Data & Science", "queries": ["topic:data stars:1001..15000"]},
            {"name": "Docs", "queries": []},
        ]
    }
    types = [{"label": "dev Tools", "about": "CLIs"}, {"label": "Data & Science", "about": "Data tools"}, {"label": "Docs", "about": "Doc sites"}]

    asyncio.run(finder.set_profile("I fix bugs in command line tools.", types))

    lanes = finder.profile["lanes"]
    # A type that keeps its name (in any case) keeps its id, so the repos tagged with it keep their tag.
    assert [lane["id"] for lane in lanes] == ["dev-tools", "data-science", "docs"]
    # The first types get what doesn't divide.
    assert [lane["share"] for lane in lanes] == [34, 33, 33]
    assert lanes[0]["queries"] == ["topic:cli stars:1001..15000"]


def test_two_types_with_one_name_are_refused(finder):
    with pytest.raises(ValueError, match="two types named"):
        asyncio.run(finder.set_profile("I fix bugs.", [{"label": "CLIs", "about": "a"}, {"label": "clis", "about": "b"}]))


def test_a_plan_with_nothing_to_search_keeps_the_profile(finder, answers):
    answers["plan"] = {"types": [{"name": "CLIs", "queries": [" "]}]}

    with pytest.raises(ValueError, match="nothing to search"):
        asyncio.run(finder.set_profile("I fix bugs.", [{"label": "CLIs", "about": "Command line tools"}]))

    assert finder.profile == DEFAULT_PROFILE


def test_add_type_looks_wider_and_shares_again(finder, answers):
    assert asyncio.run(finder.add_type()) == "Data tools"

    lanes = finder.profile["lanes"]
    assert lanes[-1]["id"] == "data-tools"
    assert [lane["share"] for lane in lanes] == [20, 20, 20, 20, 20]

    # Claude names a type the profile has already.
    answers["new_type"] = {"name": "DEV TOOLS", "about": "CLIs", "queries": ["topic:cli"]}
    assert asyncio.run(finder.add_type()) is None
    assert len(finder.profile["lanes"]) == 5


# The found list.


def test_approve_moves_found_repos_into_repos_with_their_signals(finder):
    asyncio.run(finder.check("dev-tools", "acme/tool"))

    added = asyncio.run(finder.approve(["acme/tool"]))

    assert added == ["acme/tool"]
    item = finder.repos.items()[0]
    assert item["full_name"] == "acme/tool"
    assert item["added_by"] == "explore"
    assert item["lane"] == "dev-tools"
    assert item["fit"] == 0.25
    assert finder.repo_signals.kept == ["acme/tool"]
    assert finder.found == []


def test_a_found_repo_an_agent_listed_meanwhile_just_leaves_the_found_list(finder):
    asyncio.run(finder.check("dev-tools", "acme/tool"))
    finder.repos.add([{"full_name": "acme/tool", "added_by": "agent_1"}])

    added = asyncio.run(finder.approve(["acme/tool"]))

    assert added == []
    assert finder.repo_signals.kept == []
    assert finder.found == []


def test_summary_leaves_signals_out_but_keeps_a_few_numbers(finder):
    asyncio.run(finder.check("dev-tools", "acme/tool"))

    shown = finder.summary()["found"][0]

    assert "signals" not in shown
    assert shown["merged"] == 0.7
    assert shown["maintainers"] == 3
    assert shown["unanswered"] == 0
    assert shown["reviewers"]["tag"] == "human"


# The Repos list.


def test_add_skips_names_already_listed_or_given_twice(repos):
    assert repos.add([{"full_name": "acme/tool"}, {"full_name": "acme/cli"}, {"full_name": "acme/tool"}]) == ["acme/tool", "acme/cli"]
    assert repos.add([{"full_name": "acme/cli"}]) == []

    # One undo step for the whole add.
    assert repos.undo() is True
    assert repos.items() == []
    assert repos.can_undo() is False


def test_add_skips_a_name_listed_in_another_case(repos):
    # GitHub's names don't care about case: Acme/Tool and acme/tool are one repo.
    repos.add([{"full_name": "Acme/Tool"}])

    assert repos.add([{"full_name": "acme/tool"}, {"full_name": "acme/cli"}, {"full_name": "ACME/CLI"}]) == ["acme/cli"]
    assert [item["full_name"] for item in repos.items()] == ["Acme/Tool", "acme/cli"]


def test_undo_redo_and_a_new_change_clears_redo(repos):
    repos.add([{"full_name": "acme/tool", "note": ""}])
    repos.set_note("acme/tool", "Good first issues every week")

    repos.undo()
    assert repos.items()[0]["note"] == ""
    repos.redo()
    assert repos.items()[0]["note"] == "Good first issues every week"

    repos.undo()
    repos.remove(["acme/tool"])
    assert repos.can_redo() is False
    assert repos.redo() is False


def test_remove_and_set_note_only_touch_listed_repos(repos):
    repos.add([{"full_name": "acme/tool"}])

    assert repos.remove(["acme/other"]) == []
    with pytest.raises(KeyError):
        repos.set_note("acme/other", "note")
    assert repos.remove(["acme/tool", "acme/other"]) == ["acme/tool"]


def test_set_tag_matches_names_without_case(repos):
    repos.add([{"full_name": "Acme/Tool"}])

    assert repos.set_tag(["acme/tool"], "Work") == ["Acme/Tool"]
    assert repos.items()[0]["tag"] == "Work"
    assert repos.set_tag(["acme/missing"], "Work") == []


def test_archiving_is_not_an_undo_step(repos):
    repos.add([{"full_name": "acme/tool"}])
    repos.set_archived(["acme/tool"], True)
    repos.set_archived(["acme/tool"], True)
    assert repos.archived() == ["acme/tool"]

    repos.undo()
    assert repos.items() == []
    assert repos.archived() == ["acme/tool"]

    repos.set_archived(["acme/tool"], False)
    assert repos.archived() == []


def test_the_file_keeps_only_the_last_undo_steps(repos, tmp_path):
    for number in range(15):
        repos.add([{"full_name": f"acme/repo{number}"}])

    saved = json.loads((tmp_path / "repos.json").read_text())
    assert len(saved["undo"]) == SAVED_STEPS
    assert len(repos.data["undo"]) == 15

    again = RepoList()
    assert len(again.items()) == 15
    assert len(again.data["undo"]) == SAVED_STEPS


def test_a_list_from_before_archived_has_none(tmp_path, monkeypatch):
    monkeypatch.setattr(repo_list, "DATA_DIR", tmp_path)
    (tmp_path / "tracked.json").write_text(json.dumps({"items": [{"full_name": "acme/tool"}], "undo": [], "redo": []}))

    assert RepoList("tracked.json").archived() == []
