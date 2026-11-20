"""The token balancer (github_searcher/token_balancer.py): which tokens it uses and in what order, which kind of request
a URL is, which token a request takes, and how a rate-limit answer pauses a token and sends the request again.

GitHub is faked (httpx.request and httpx.get answer from the test), and the tokens are made-up ones set in the
environment by each test: nothing here reaches GitHub or depends on a real token."""

import json
import os
import time

import httpx
import pytest

from github_searcher import token_balancer
from github_searcher.token_balancer import GAP, MAX_WAIT, PAUSE, RUNNING, TokenBalancer

SECONDARY_LIMIT = '{"message": "You have exceeded a secondary rate limit. Please wait a few minutes before you try again."}'


class FakeGitHub:
    """GitHub, faked. request() answers with the next of `answers` (status, headers, body), 200 when none are left,
    or raises like a dropped connection when `fails`. get() answers /rate_limit from `rate_limits` (by token value),
    401 for a token it doesn't know. Every request is kept in `sent`."""

    def __init__(self):
        self.sent = []
        self.answers = []
        self.fails = False
        self.rate_limits = {}

    def request(self, method, url, headers=None, params=None, json=None, timeout=None):
        self.sent.append({"method": method, "url": url, "headers": headers})
        if self.fails:
            raise httpx.ConnectError("no network")
        request = httpx.Request(method, url)
        if self.answers:
            status, answer_headers, body = self.answers.pop(0)
            return httpx.Response(status, headers=answer_headers, text=body, request=request)
        return httpx.Response(200, text="{}", request=request)

    def get(self, url, headers=None, timeout=None):
        self.sent.append({"method": "GET", "url": url, "headers": headers})
        token = headers["Authorization"].removeprefix("Bearer ")
        if token not in self.rate_limits:
            return httpx.Response(401, json={"message": "Bad credentials"})
        return httpx.Response(200, json={"resources": self.rate_limits[token]})


@pytest.fixture(autouse=True)
def no_tokens(monkeypatch):
    """No GITHUB_TOKEN* in the environment: each test sets the ones it needs."""
    for key in list(os.environ):
        if key.startswith("GITHUB_TOKEN"):
            monkeypatch.delenv(key)


@pytest.fixture
def balancer(monkeypatch):
    """A balancer with three made-up tokens."""
    monkeypatch.setenv("GITHUB_TOKEN", "token-one")
    monkeypatch.setenv("GITHUB_TOKEN_2", "token-two")
    monkeypatch.setenv("GITHUB_TOKEN_3", "token-three")
    return TokenBalancer()


@pytest.fixture
def github(monkeypatch):
    """The fake GitHub, where every request of the balancer goes."""
    fake = FakeGitHub()
    monkeypatch.setattr(token_balancer.httpx, "request", fake.request)
    monkeypatch.setattr(token_balancer.httpx, "get", fake.get)
    return fake


def test_tokens_go_in_number_order(monkeypatch):
    # By number, not as text: GITHUB_TOKEN_10 comes after GITHUB_TOKEN_3.
    monkeypatch.setenv("GITHUB_TOKEN_10", "ten")
    monkeypatch.setenv("GITHUB_TOKEN_2", "two")
    monkeypatch.setenv("GITHUB_TOKEN", "one")
    monkeypatch.setenv("GITHUB_TOKEN_3", "three")

    names = [token["name"] for token in TokenBalancer().tokens]

    assert names == ["GITHUB_TOKEN", "GITHUB_TOKEN_2", "GITHUB_TOKEN_3", "GITHUB_TOKEN_10"]


def test_empty_tokens_are_skipped(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "")
    monkeypatch.setenv("GITHUB_TOKEN_2", "   ")
    monkeypatch.setenv("GITHUB_TOKEN_3", " three\n")

    tokens = TokenBalancer().tokens

    assert [token["name"] for token in tokens] == ["GITHUB_TOKEN_3"]
    assert tokens[0]["value"] == "three"


def test_names_without_a_number_are_not_tokens(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "one")
    monkeypatch.setenv("GITHUB_TOKEN_OLD", "old")
    monkeypatch.setenv("GITHUB_TOKEN_2B", "two-b")
    monkeypatch.setenv("GITHUB_TOKENS", "many")

    names = [token["name"] for token in TokenBalancer().tokens]

    assert names == ["GITHUB_TOKEN"]


def test_no_token_at_all_is_an_error(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "")

    with pytest.raises(KeyError, match="GITHUB_TOKEN is not set"):
        TokenBalancer()


def test_slots_are_per_token(balancer):
    assert balancer.slots("core") == RUNNING["core"] * 3
    assert balancer.slots("code_search") == RUNNING["code_search"] * 3


@pytest.mark.parametrize(
    "url, kind",
    [
        ("https://api.github.com/graphql", "graphql"),
        ("https://api.github.com/search/code", "code_search"),
        ("https://api.github.com/search/issues", "search"),
        ("https://api.github.com/search/repositories", "search"),
        ("https://api.github.com/repos/owner/name/issues/12", "core"),
        ("https://api.github.com/repos/owner/graphql-tools/issues", "core"),
    ],
)
def test_which_kind_a_request_is(balancer, github, url, kind):
    github.answers.append((200, {"x-ratelimit-remaining": "41", "x-ratelimit-limit": "60"}, "{}"))

    balancer.request("GET", url)

    kinds = balancer.tokens[0]["kinds"]
    assert kinds[kind]["remaining"] == 41
    assert [name for name in kinds if kinds[name]["remaining"] is not None] == [kind]


def test_request_takes_the_token_with_the_most_quota_left(balancer):
    balancer.tokens[0]["kinds"]["core"]["remaining"] = 10
    balancer.tokens[1]["kinds"]["core"]["remaining"] = 4000
    balancer.tokens[2]["kinds"]["core"]["remaining"] = 50

    token = balancer.take("core", time.monotonic() + 1)

    assert token["name"] == "GITHUB_TOKEN_2"
    assert token["kinds"]["core"]["running"] == 1


def test_token_not_used_yet_counts_as_full(balancer):
    balancer.tokens[0]["kinds"]["core"]["remaining"] = 4999
    balancer.tokens[1]["kinds"]["core"]["remaining"] = 4999

    assert balancer.take("core", time.monotonic() + 1)["name"] == "GITHUB_TOKEN_3"


def test_quota_whose_reset_has_passed_counts_as_full(balancer):
    # Last seen at 0, but its reset time has passed: GitHub filled it again, so it beats a token with 3 left.
    used_up = balancer.tokens[0]["kinds"]["core"]
    used_up["remaining"] = 0
    used_up["limit"] = 5000
    used_up["reset_at"] = time.monotonic() - 1
    nearly_empty = balancer.tokens[1]["kinds"]["core"]
    nearly_empty["remaining"] = 3
    nearly_empty["limit"] = 5000
    nearly_empty["reset_at"] = time.monotonic() + 600
    balancer.tokens[2]["kinds"]["core"]["paused_until"] = time.monotonic() + 600

    assert balancer.take("core", time.monotonic() + 1)["name"] == "GITHUB_TOKEN"


def test_quota_whose_reset_has_not_passed_keeps_its_count(balancer):
    for number, remaining in enumerate([10, 4000, 50]):
        state = balancer.tokens[number]["kinds"]["core"]
        state["remaining"] = remaining
        state["limit"] = 5000
        state["reset_at"] = time.monotonic() + 600

    assert balancer.take("core", time.monotonic() + 1)["name"] == "GITHUB_TOKEN_2"


def test_equal_tokens_go_in_order(balancer):
    assert balancer.take("core", time.monotonic() + 1)["name"] == "GITHUB_TOKEN"


def test_paused_token_is_passed_over(balancer):
    balancer.tokens[0]["kinds"]["core"]["remaining"] = 10
    balancer.tokens[1]["kinds"]["core"]["remaining"] = 4000
    balancer.tokens[1]["kinds"]["core"]["paused_until"] = time.monotonic() + 60
    balancer.tokens[2]["kinds"]["core"]["remaining"] = 50

    assert balancer.take("core", time.monotonic() + 1)["name"] == "GITHUB_TOKEN_3"


def test_token_full_of_running_requests_is_passed_over(balancer):
    balancer.tokens[0]["kinds"]["search"]["running"] = RUNNING["search"]
    balancer.tokens[1]["kinds"]["search"]["remaining"] = 10
    balancer.tokens[2]["kinds"]["search"]["remaining"] = 20

    assert balancer.take("search", time.monotonic() + 1)["name"] == "GITHUB_TOKEN_3"


def test_searches_are_spaced_out_per_token(balancer):
    # Search is 30 a minute per account: one token's next search waits GAP seconds, so the next search takes another.
    first = balancer.take("search", time.monotonic() + 1)
    balancer.done(first, "search", None)

    second = balancer.take("search", time.monotonic() + 1)

    assert GAP["search"] > 0
    assert first["name"] == "GITHUB_TOKEN"
    assert second["name"] == "GITHUB_TOKEN_2"


def test_used_up_quota_waits_until_it_resets(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token-one")
    balancer = TokenBalancer()
    state = balancer.tokens[0]["kinds"]["core"]
    state["remaining"] = 0
    state["reset_at"] = time.monotonic() + 600

    free_at = balancer.take("core", time.monotonic())

    assert isinstance(free_at, float)
    assert 590 < free_at - time.time() <= 600
    assert balancer.waiting["core"] == 0


def test_gives_up_with_a_429_when_every_token_is_paused_too_long(balancer, github):
    for token in balancer.tokens:
        token["kinds"]["search"]["paused_until"] = time.monotonic() + MAX_WAIT + 600

    response = balancer.request("GET", "https://api.github.com/search/issues", params={"q": "label:bug"})

    assert response.status_code == 429
    assert "all 3 tokens are paused for search requests until" in response.json()["message"]
    assert github.sent == []
    assert balancer.waiting["search"] == 0


def test_rate_limited_request_goes_again_with_the_next_token(balancer, github):
    # What the agents hit: a few searches at once right after a burst of GraphQL, and GitHub answers with a
    # secondary limit. The token is paused and the same request goes again with another token.
    github.answers.append((403, {"retry-after": "60"}, SECONDARY_LIMIT))
    github.answers.append((200, {}, '{"items": []}'))

    response = balancer.request("GET", "https://api.github.com/search/issues", params={"q": "label:bug"})

    assert response.status_code == 200
    assert [sent["headers"]["Authorization"] for sent in github.sent] == ["Bearer token-one", "Bearer token-two"]
    assert balancer.tokens[0]["kinds"]["search"]["paused_until"] > time.monotonic() + 50
    assert balancer.tokens[0]["kinds"]["search"]["running"] == 0
    assert balancer.tokens[1]["kinds"]["search"]["running"] == 0


def test_token_github_no_longer_takes_is_left_out_for_every_kind(balancer, github):
    # GITHUB_TOKEN, 2026-11-20: revoked, it answered 401 with no quota, so it looked the fullest and took every GraphQL
    # read while the other tokens waited. Now the request goes again with the next token and it is left out for an hour.
    github.answers.append((401, {}, '{"message": "Bad credentials"}'))
    github.answers.append((200, {}, '{"data": {}}'))

    response = balancer.request("POST", "https://api.github.com/graphql", json={"query": "{ viewer { login } }"})

    assert response.status_code == 200
    assert [sent["headers"]["Authorization"] for sent in github.sent] == ["Bearer token-one", "Bearer token-two"]
    for kind in ["core", "graphql", "search", "code_search"]:
        assert balancer.tokens[0]["kinds"][kind]["paused_until"] > time.monotonic() + 50 * 60
    assert balancer.tokens[0]["kinds"]["graphql"]["running"] == 0


def test_request_that_fails_frees_its_place(balancer, github):
    github.fails = True

    with pytest.raises(httpx.ConnectError):
        balancer.request("GET", "https://api.github.com/repos/owner/name")

    assert balancer.tokens[0]["kinds"]["core"]["running"] == 0


def test_own_token_goes_as_it_is_and_is_not_counted(balancer, github):
    github.answers.append((200, {"x-ratelimit-remaining": "4999"}, "{}"))
    version = balancer.version

    balancer.request("GET", "https://api.github.com/repos/me/private-repo", own_token="gho_mine")

    assert github.sent[0]["headers"]["Authorization"] == "Bearer gho_mine"
    assert balancer.version == version
    for token in balancer.tokens:
        assert token["kinds"]["core"]["remaining"] is None


def test_answer_notes_what_is_left_of_the_quota(balancer):
    token = balancer.take("core", time.monotonic() + 1)
    reset = str(int(time.time()) + 1800)
    response = httpx.Response(200, headers={"x-ratelimit-remaining": "4321", "x-ratelimit-limit": "5000", "x-ratelimit-reset": reset})

    assert balancer.done(token, "core", response) is False

    state = token["kinds"]["core"]
    assert state["remaining"] == 4321
    assert state["limit"] == 5000
    assert 1790 < state["reset_at"] - time.monotonic() <= 1800
    assert state["running"] == 0
    assert state["paused_until"] == 0.0


def test_retry_after_pauses_the_token_that_long(balancer):
    token = balancer.take("core", time.monotonic() + 1)
    response = httpx.Response(429, headers={"retry-after": "30"}, text=SECONDARY_LIMIT)

    assert balancer.done(token, "core", response) is True

    assert 29 < token["kinds"]["core"]["paused_until"] - time.monotonic() <= 30


def test_secondary_limit_without_retry_after_pauses_a_minute(balancer):
    token = balancer.take("core", time.monotonic() + 1)
    response = httpx.Response(403, text=SECONDARY_LIMIT)

    assert balancer.done(token, "core", response) is True

    assert PAUSE - 1 < token["kinds"]["core"]["paused_until"] - time.monotonic() <= PAUSE


def test_used_up_quota_pauses_the_token_until_it_resets(balancer):
    token = balancer.take("core", time.monotonic() + 1)
    reset = str(int(time.time()) + 900)
    headers = {"x-ratelimit-remaining": "0", "x-ratelimit-limit": "5000", "x-ratelimit-reset": reset}
    response = httpx.Response(403, headers=headers, text='{"message": "API rate limit exceeded for user ID 1."}')

    assert balancer.done(token, "core", response) is True

    state = token["kinds"]["core"]
    assert state["paused_until"] == state["reset_at"]
    assert 890 < state["paused_until"] - time.monotonic() <= 900


def test_graphql_used_up_quota_comes_as_a_200(balancer):
    # GraphQL says a used-up quota with a 200 and an error of type RATE_LIMITED.
    token = balancer.take("graphql", time.monotonic() + 1)
    body = json.dumps({"errors": [{"type": "RATE_LIMITED", "message": "API rate limit exceeded"}]})

    assert balancer.done(token, "graphql", httpx.Response(200, text=body)) is True

    assert token["kinds"]["graphql"]["paused_until"] > time.monotonic()


def test_rate_limited_in_a_rest_answers_text_is_not_a_limit(balancer):
    # Only GraphQL says a limit with a 200: an issue that mentions RATE_LIMITED is just an issue.
    token = balancer.take("core", time.monotonic() + 1)
    body = json.dumps({"title": "Handle errors of type \"RATE_LIMITED\""})

    assert balancer.done(token, "core", httpx.Response(200, text=body)) is False

    assert token["kinds"]["core"]["paused_until"] == 0.0


@pytest.mark.parametrize(
    "status, body",
    [
        (403, '{"message": "Resource not accessible by personal access token"}'),
        (404, '{"message": "Not Found"}'),
        (422, '{"message": "Validation Failed"}'),
    ],
)
def test_other_errors_do_not_pause_the_token(balancer, status, body):
    # A 403 that isn't about a rate limit goes back to the caller as it is: pausing would only hold up other requests.
    token = balancer.take("core", time.monotonic() + 1)

    assert balancer.done(token, "core", httpx.Response(status, text=body)) is False

    assert token["kinds"]["core"]["paused_until"] == 0.0


def test_status_names_tokens_and_never_shows_their_values(balancer):
    shown = json.dumps(balancer.status())

    assert "GITHUB_TOKEN_2" in shown
    assert "token-one" not in shown
    assert "token-two" not in shown
    assert "token-three" not in shown


def test_status_shows_a_quota_whose_reset_has_passed_as_full(balancer):
    state = balancer.tokens[0]["kinds"]["core"]
    state["remaining"] = 3
    state["limit"] = 5000
    state["reset_at"] = time.monotonic() - 1

    shown = balancer.status()["core"]["tokens"][0]

    assert shown["remaining"] == 5000
    assert shown["reset_at"] is None


def test_status_shows_when_a_quota_resets_and_a_pause_ends(balancer):
    state = balancer.tokens[0]["kinds"]["search"]
    state["remaining"] = 3
    state["limit"] = 30
    state["reset_at"] = time.monotonic() + 40
    state["paused_until"] = time.monotonic() + 60

    shown = balancer.status()["search"]["tokens"][0]

    assert shown["remaining"] == 3
    assert shown["reset_at"] is not None
    assert shown["paused_until"] is not None
    assert balancer.status()["search"]["tokens"][1]["paused_until"] is None


def test_prime_fills_in_quotas_and_skips_a_token_that_does_not_work(balancer, github):
    reset = int(time.time()) + 3000
    github.rate_limits["token-one"] = {
        "core": {"remaining": 4100, "limit": 5000, "reset": reset},
        "search": {"remaining": 28, "limit": 30, "reset": reset},
    }
    github.rate_limits["token-three"] = {"core": {"remaining": 5000, "limit": 5000, "reset": reset}}

    balancer.prime()

    assert balancer.tokens[0]["kinds"]["core"]["remaining"] == 4100
    assert balancer.tokens[0]["kinds"]["search"]["limit"] == 30
    assert balancer.tokens[0]["kinds"]["graphql"]["remaining"] is None
    assert balancer.tokens[1]["kinds"]["core"]["remaining"] is None
    assert balancer.tokens[2]["kinds"]["core"]["remaining"] == 5000
