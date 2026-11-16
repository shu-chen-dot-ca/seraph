"""Fix problems (github_searcher/problem_fixes.py): when the daily run is due, what a run keeps when it fails or is cut
off, and the release it makes (the next version from the commit titles since the last release, and its notes).

Nothing here clones, runs Claude Code or reaches GitHub: the clock is fixed, GitHub is an httpx.MockTransport, and
everything is kept in pytest's temporary folder, never in DATA_DIR."""

import json
from datetime import datetime

import httpx
import pytest

from github_searcher import problem_fixes
from github_searcher.problem_fixes import FixError, ProblemFixes


class At(datetime):
    """datetime whose now() is MOMENT, a time on this computer's clock."""

    moment = datetime(2026, 11, 15, 21, 0).astimezone()

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls.moment.replace(tzinfo=None)
        return cls.moment.astimezone(tz)


class FakeProblems:
    def __init__(self, items):
        self.items = items
        self.closed = []

    def list(self):
        return self.items

    def close(self, ids):
        self.closed = self.closed + ids
        return ids


class FakeUpdates:
    asked = False


@pytest.fixture
def fixes(tmp_path, monkeypatch):
    """Fix problems at 20:00, on, set two days ago, with no runs yet; it is 21:00 now."""
    monkeypatch.setattr(problem_fixes, "DATA_DIR", tmp_path)
    monkeypatch.setattr(problem_fixes, "SELF_REPO", "owner/seraph")
    monkeypatch.setattr(problem_fixes, "datetime", At)
    monkeypatch.setattr(At, "moment", datetime(2026, 11, 15, 21, 0).astimezone())
    fixes = ProblemFixes(FakeProblems([]), None, FakeUpdates())
    fixes.data = {"on": True, "hour": 20, "minute": 0, "changed_at": datetime(2026, 11, 13, 9, 0).astimezone().isoformat(), "runs": []}
    return fixes


def test_due_once_the_time_has_passed(fixes):
    assert fixes.due() is True


def test_off_is_never_due(fixes):
    fixes.data["on"] = False

    assert fixes.due() is False


def test_not_due_before_the_time(fixes, monkeypatch):
    monkeypatch.setattr(At, "moment", datetime(2026, 11, 15, 19, 59).astimezone())

    assert fixes.due() is False


def test_runs_once_a_day(fixes):
    fixes.data["runs"] = [{"started_at": datetime(2026, 11, 15, 20, 0, 30).astimezone().isoformat(), "state": "done"}]

    assert fixes.due() is False


def test_a_day_the_computer_was_off_at_the_time_runs_when_the_app_starts(fixes, monkeypatch):
    monkeypatch.setattr(At, "moment", datetime(2026, 11, 15, 23, 40).astimezone())
    fixes.data["runs"] = [{"started_at": datetime(2026, 11, 14, 20, 0).astimezone().isoformat(), "state": "done"}]

    assert fixes.due() is True


def test_setting_a_time_that_has_passed_waits_for_tomorrow(fixes):
    fixes.data["changed_at"] = datetime(2026, 11, 15, 20, 30).astimezone().isoformat()

    assert fixes.due() is False


@pytest.mark.parametrize("hour, minute", [(24, 0), (-1, 0), (20, 60)])
def test_set_refuses_a_time_that_isnt_one(fixes, hour, minute):
    with pytest.raises(ValueError):
        fixes.set(True, hour, minute)


def test_set_is_kept(fixes, tmp_path):
    fixes.set(True, 8, 30)

    kept = json.loads((tmp_path / "problem_fixes.json").read_text())
    assert (kept["on"], kept["hour"], kept["minute"]) == (True, 8, 30)


def test_a_run_the_restart_cut_off_is_failed_at_start(tmp_path, monkeypatch):
    monkeypatch.setattr(problem_fixes, "DATA_DIR", tmp_path)
    run = {"started_at": "2026-11-15T01:00:00+00:00", "ended_at": None, "state": "running", "pid": None, "error": ""}
    data = {"on": True, "hour": 20, "minute": 0, "changed_at": "2026-11-01T00:00:00+00:00", "runs": [run]}
    (tmp_path / "problem_fixes.json").write_text(json.dumps(data))

    fixes = ProblemFixes(FakeProblems([]), None, FakeUpdates())

    assert fixes.data["runs"][0]["state"] == "failed"
    assert fixes.data["runs"][0]["error"] == "Cut off: the app restarted during the run."
    assert fixes.data["runs"][0]["ended_at"] is not None


def test_a_failed_run_keeps_why_and_the_output(fixes):
    problem = {"id": "prb_a1b2c3", "at": "2026-11-15T10:00:00+00:00", "about": None, "text": "x", "closed_at": None}
    fixes.problems = FakeProblems([problem])

    def fail(run, open_problems):
        raise FixError("uv run pytest -q fails on main, so nothing was released.", "1 failed")

    fixes.fix = fail
    fixes.run()

    run = fixes.data["runs"][0]
    assert run["state"] == "failed"
    assert run["problems"] == ["prb_a1b2c3"]
    assert run["error"] == "uv run pytest -q fails on main, so nothing was released."
    assert run["output"] == "1 failed"
    assert run["ended_at"] is not None


def test_no_second_run_while_one_runs(fixes):
    fixes.data["runs"] = [{"started_at": "2026-11-15T20:00:00+00:00", "state": "running"}]

    def never(run, open_problems):
        raise AssertionError("a second run started")

    fixes.fix = never
    fixes.run()

    assert len(fixes.data["runs"]) == 1


def test_closed_problems_are_not_given_to_a_run(fixes):
    open_one = {"id": "prb_open01", "at": "2026-11-15T10:00:00+00:00", "about": None, "text": "x", "closed_at": None}
    closed_one = {"id": "prb_done01", "at": "2026-11-14T10:00:00+00:00", "about": None, "text": "y", "closed_at": "2026-11-14T12:00:00+00:00"}
    fixes.problems = FakeProblems([open_one, closed_one])
    given = []

    def remember(run, open_problems):
        given.extend(item["id"] for item in open_problems)

    fixes.fix = remember
    fixes.run()

    assert given == ["prb_open01"]
    assert fixes.data["runs"][0]["state"] == "done"


def github(latest, titles, made):
    """A GitHub with release latest (None: no release yet) and these commit titles on main since it. Releases it makes
    go in made."""

    def answer(request):
        path = request.url.path
        if path == "/repos/owner/seraph/releases/latest" and latest is None:
            return httpx.Response(404, json={"message": "Not Found"})
        if path == "/repos/owner/seraph/releases/latest":
            return httpx.Response(200, json={"tag_name": latest})
        if path == f"/repos/owner/seraph/compare/{latest}...main":
            return httpx.Response(200, json={"commits": [{"commit": {"message": title + "\n"}} for title in titles]})
        if path == "/repos/owner/seraph/commits":
            return httpx.Response(200, json=[{"commit": {"message": title}} for title in titles])
        if path == "/repos/owner/seraph/releases" and request.method == "POST":
            made.append(json.loads(request.content))
            return httpx.Response(201, json={"html_url": "https://github.com/owner/seraph/releases/x"})
        return httpx.Response(500, json={"message": f"unexpected {request.method} {path}"})

    return httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(answer))


def test_a_feature_since_the_last_release_is_the_next_minor(fixes):
    made = []
    titles = ["fix(agents): stop claiming a taken issue", "feat(settings): add fix problems", "docs(readme): say so"]

    tag = fixes.release(github("v0.1.0", titles, made))

    assert tag == "v0.2.0"
    assert made[0]["tag_name"] == "v0.2.0"
    assert made[0]["target_commitish"] == "main"
    assert made[0]["body"] == (
        "## Features\n\n- feat(settings): add fix problems\n\n"
        "## Fixes\n\n- fix(agents): stop claiming a taken issue\n\n"
        "## Other changes\n\n- docs(readme): say so"
    )


def test_only_fixes_since_the_last_release_is_the_next_patch(fixes):
    made = []

    tag = fixes.release(github("v0.3.4", ["fix(search): skip archived repos", "test(search): cover archived repos"], made))

    assert tag == "v0.3.5"


def test_nothing_new_since_the_last_release_makes_none(fixes):
    made = []

    tag = fixes.release(github("v0.2.0", [], made))

    assert tag is None
    assert made == []


def test_the_first_release_is_v0_1_0(fixes):
    made = []

    tag = fixes.release(github(None, ["feat(app): first"], made))

    assert tag == "v0.1.0"


def test_github_refusing_the_release_says_so(fixes):
    def answer(request):
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(200, json={"tag_name": "v0.1.0"})
        if "/compare/" in request.url.path:
            return httpx.Response(200, json={"commits": [{"commit": {"message": "fix(app): x"}}]})
        return httpx.Response(422, json={"message": "Validation Failed"})

    client = httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(answer))

    with pytest.raises(FixError, match="GitHub answered 422 for the release v0.1.1"):
        fixes.release(client)
