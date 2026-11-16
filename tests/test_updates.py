"""The check a new release gets before it goes live (github_searcher/updates.py check_release): it starts the release on
a copy of data/, and reads its health, its page and every topic of its live feed.

Nothing is started here: the release's process, its HTTP answers and its live feed are fakes, and the live copy's
folder (SERAPH_HOME) is pytest's temporary folder."""

import json

import httpx
import pytest

from github_searcher import updates
from github_searcher.updates import TOPICS, Updates


class FakeProcess:
    def poll(self):
        return None

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class FakeFeed:
    """The release's live feed: every topic once, then nothing."""

    def __init__(self):
        self.messages = [json.dumps({"topic": topic, "data": {}}) for topic in TOPICS]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def recv(self, timeout=None):
        if not self.messages:
            raise TimeoutError
        return self.messages.pop(0)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """The live copy's folder: its data/, its .env, and release v0.9.0's folder."""
    (tmp_path / "data").mkdir()
    (tmp_path / ".env").write_text("BACKEND_PORT=8001\nDATA_DIR=/somewhere/data\n")
    (tmp_path / "releases" / "v0.9.0").mkdir(parents=True)
    (tmp_path / "releases" / "v0.9.0" / ".env").symlink_to(tmp_path / ".env")
    monkeypatch.setattr(updates, "HOME", str(tmp_path))
    monkeypatch.setenv("BACKEND_PORT", "8001")
    monkeypatch.setattr(updates.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    def get(url, timeout=None):
        if url.endswith("/api/health"):
            return httpx.Response(200, json={"ok": True, "errors": 0})
        return httpx.Response(200, text="<html></html>")

    monkeypatch.setattr(updates.httpx, "get", get)
    return tmp_path


def test_release_check_reads_a_live_feed_message_over_1_mb(home, monkeypatch):
    # v0.2.0's first check failed: a topic of the real data copy was over the websockets client's 1 MB default
    # (max_size), which the browser doesn't have. The check must read any size.
    opened = []

    def connect(url, **options):
        opened.append({"url": url, **options})
        return FakeFeed()

    monkeypatch.setattr(updates, "connect", connect)

    Updates.check_release(Updates.__new__(Updates), "v0.9.0")

    assert opened == [{"url": "ws://127.0.0.1:8003/api/live", "open_timeout": 30, "max_size": None}]


def test_release_check_puts_the_live_env_back(home, monkeypatch):
    monkeypatch.setattr(updates, "connect", lambda url, **options: FakeFeed())

    Updates.check_release(Updates.__new__(Updates), "v0.9.0")

    env = home / "releases" / "v0.9.0" / ".env"
    assert env.is_symlink()
    assert env.resolve() == (home / ".env").resolve()
    assert not (home / "check-data").exists()
