"""Your repositories: every GitHub repo you can push to (your own, ones you collaborate on, your organizations'),
public and private, and the repos you starred, read with your sign-in (github_account.py), never the search tokens:
those can't see private repos.

refresh() reads both lists in one GraphQL request: the 100 most recently pushed repos you can push to (not archived;
viewerPermission ADMIN, MAINTAIN or WRITE) in "repos", and the 100 you starred most recently in "starred" (the ones
you can push to are under "repos" only). A fork says the repo it was forked from (parent), and that repo is in
"parents" when it isn't in either list. It is kept in DATA_DIR/your_repositories.json too (save_list), so after a
restart the last list is there at once. backend/github_api.py (keep_your_repositories) reads it every minute, at once
when you sign in or out, and soon after a change (wanted).

    {"repos": [{"name": "owner/name", "private", "fork", "description", "url", "default_branch", "pushed_at",
                "checks": "passed" | "failed" | "running" | "none", "open_issues", "open_prs", "stars",
                "starred": you starred it, "can_push", "parent": the repo a fork was forked from | None}],
     "starred": [the same],
     "parents": [the same: the repos your forks were forked from, when not in repos or starred],
     "login": your login | None, "checked_at", "error": why the last read failed | None}

is_yours() and is_listed() say whether a repo is in the list; token(), client() and graphql() act as you, for
backend/github_api.py (reading a private repo's thread, your forks, your assigned issues) and profile_readme.py.
labels() is every label of a repo.
"""

import json
import threading
from datetime import UTC, datetime

import httpx

from github_searcher.github_account import DATA_DIR
from github_searcher.pr_tracking import ROLLUP

API = "https://api.github.com"
# viewerPermission that may push.
PUSH = ["ADMIN", "MAINTAIN", "WRITE"]
# The list as last read (save_list).
LIST_PATH = DATA_DIR / "your_repositories.json"

REPOS_QUERY = """
query {
  viewer {
    login
    repositories(first: 100, affiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER],
                 ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER], orderBy: {field: PUSHED_AT, direction: DESC}) {
      nodes { ...RepoFields parent { ...RepoFields } }
    }
    starredRepositories(first: 100, orderBy: {field: STARRED_AT, direction: DESC}) {
      nodes { ...RepoFields }
    }
  }
}
fragment RepoFields on Repository {
  nameWithOwner isPrivate isFork isArchived description url pushedAt viewerPermission viewerHasStarred stargazerCount
  defaultBranchRef { name target { ... on Commit { statusCheckRollup { state } } } }
  issues(states: OPEN) { totalCount }
  pullRequests(states: OPEN) { totalCount }
}
"""

class YourRepositories:
    def __init__(self, github_account):
        self.github_account = github_account
        self.lock = threading.Lock()
        self.version = 0
        self.data = {"repos": [], "starred": [], "parents": [], "login": None, "checked_at": None, "error": None}
        if LIST_PATH.exists():
            self.data = json.loads(LIST_PATH.read_text())
        # A list kept from before forks said where they came from.
        self.data.setdefault("parents", [])
        for each in self.data["repos"] + self.data["starred"]:
            each.setdefault("parent", None)
        # Something changed (a fork deleted): backend/github_api.py reads the list again soon.
        self.wanted = False

    def is_yours(self, repo: str) -> bool:
        """Whether repo (owner/name) is one you can push to."""
        with self.lock:
            names = [each["name"].lower() for each in self.data["repos"]]
        return repo.lower() in names

    def is_listed(self, repo: str) -> bool:
        """Whether repo (owner/name) is one you can push to, one you starred or one you forked: its page may be shown."""
        with self.lock:
            names = [each["name"].lower() for each in self.data["repos"] + self.data["starred"] + self.data["parents"]]
        return repo.lower() in names

    def token(self) -> str | None:
        """Your sign-in's token, for reading one of your repositories (backend/github_api.py's thread pop-up)."""
        account = self.github_account.load()
        if account is None:
            return None
        return account["token"]

    def client(self) -> httpx.Client:
        """A client that acts as you. ValueError when you aren't signed in."""
        token = self.token()
        if token is None:
            raise ValueError("Sign in with GitHub first: Settings, Account.")
        headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"}
        return httpx.Client(base_url=API, headers=headers, timeout=60)

    def graphql(self, query: str, variables: dict) -> dict:
        """One GraphQL query as you. ValueError with GitHub's message when it fails."""
        with self.client() as client:
            response = client.post("/graphql", json={"query": query, "variables": variables})
        if response.status_code == 401:
            raise ValueError("GitHub doesn't accept your sign-in anymore. Sign in with GitHub again: Settings, Account.")
        if response.status_code != 200:
            raise ValueError(f"GitHub answered {response.status_code}: {response.text[:200]}")
        answer = response.json()
        if answer.get("errors"):
            raise ValueError(answer["errors"][0]["message"])
        return answer["data"]

    def refresh(self) -> None:
        """Reads the list again. Not signed in: an empty list. A failure keeps the last list, with why."""
        if self.token() is None:
            with self.lock:
                self.data = {"repos": [], "starred": [], "parents": [], "login": None, "checked_at": None, "error": None}
                self.version += 1
            self.save_list()
            return
        try:
            viewer = self.graphql(REPOS_QUERY, {})["viewer"]
        except (httpx.HTTPError, ValueError) as error:
            with self.lock:
                self.data["error"] = str(error)
                self.data["checked_at"] = datetime.now(UTC).isoformat()
                self.version += 1
            return
        repos = []
        starred = []
        parents = []
        # Yours first: a repo you can push to and starred too is under repos only. Then the repos your forks were
        # forked from, the ones in neither list.
        nodes = []
        for node in viewer["repositories"]["nodes"] + viewer["starredRepositories"]["nodes"]:
            nodes.append((node, False))
        for node in viewer["repositories"]["nodes"]:
            if node.get("parent") is not None:
                nodes.append((node["parent"], True))
        names = []
        for node, is_parent in nodes:
            can_push = node["viewerPermission"] in PUSH and not node["isArchived"]
            if node["nameWithOwner"] in names or (not is_parent and not can_push and not node["viewerHasStarred"]):
                continue
            names.append(node["nameWithOwner"])
            default_branch = ""
            checks = "none"
            branch = node["defaultBranchRef"]
            if branch is not None:
                default_branch = branch["name"]
            if branch is not None and branch["target"] is not None and branch["target"].get("statusCheckRollup") is not None:
                checks = ROLLUP.get(branch["target"]["statusCheckRollup"]["state"], "running")
            item = {
                "name": node["nameWithOwner"],
                "private": node["isPrivate"],
                "fork": node["isFork"],
                "description": node["description"] or "",
                "url": node["url"],
                "default_branch": default_branch,
                "pushed_at": node["pushedAt"],
                "checks": checks,
                "open_issues": node["issues"]["totalCount"],
                "open_prs": node["pullRequests"]["totalCount"],
                "stars": node["stargazerCount"],
                "starred": node["viewerHasStarred"],
                "can_push": can_push,
                "parent": node["parent"]["nameWithOwner"] if node.get("parent") is not None else None,
            }
            if is_parent:
                parents.append(item)
            elif can_push:
                repos.append(item)
            else:
                starred.append(item)
        with self.lock:
            self.data = {
                "repos": repos,
                "starred": starred,
                "parents": parents,
                "login": viewer["login"],
                "checked_at": datetime.now(UTC).isoformat(),
                "error": None,
            }
            self.version += 1
        self.save_list()

    def save_list(self) -> None:
        """Keeps the list in LIST_PATH: written whole, then put in place. A failed read isn't kept (it keeps the list)."""
        with self.lock:
            text = json.dumps(self.data)
        LIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = LIST_PATH.with_suffix(".tmp")
        temporary.write_text(text)
        temporary.replace(LIST_PATH)

    def labels(self, repo: str) -> list[dict]:
        """Every label of the repo, for the thread pop-up's Labels."""
        with self.client() as client:
            response = client.get(f"/repos/{repo}/labels", params={"per_page": 100})
        if response.status_code != 200:
            return []
        return [{"name": label["name"], "color": label["color"]} for label in response.json()]
