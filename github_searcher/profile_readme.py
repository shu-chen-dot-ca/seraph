"""Your GitHub profile's README (the repository github.com/<you>/<you>, shown on your profile page) and Seraph's own
(projects.SELF_REPO, its Merged upstream part): a table of your merged pull requests, kept up to date in both as long as
Seraph runs (backend/github_api.py's keep_profile_readme()).

update(your_repositories) searches GitHub, as you, for every pull request of yours merged into a public repository
that isn't yours (is:pr is:merged is:public author:<you> -user:<you>), and writes how many there are and in how many
repositories ("Seraph has merged 12 PRs across 8 repositories", Seraph a link to SELF_REPO), then a table: one row per
repository with its stars, the most starred first, with a link to each pull request and, in a column of their own, its
lines added (green) and removed (red). Pull requests of fewer than MIN_LINES lines (added and removed together) are left
out, not counted or shown. The table stops after MAX_SHOWN pull requests, in its own order; below it, a line says how
many more there are, with a link to them on GitHub. Only the part between START and END changes; everything else in
README.md
stays as you wrote it. When nothing changed, nothing is committed. A README.md without both markers is left alone.
Both are committed on the repository's default branch, as you: pull before you push Seraph's own.

The first time, when your profile repository isn't there yet, it is made, public, with a README.md that is FIRST_TEXT
and the markers with the table between them.
"""

import base64
from urllib.parse import quote_plus

from github_searcher.projects import SELF_REPO

START = "<!-- merged-prs:start -->"
END = "<!-- merged-prs:end -->"
FIRST_TEXT = "Hi, I'm Shu.\n\n"
# GitHub's search gives at most 1000, 100 a page.
MAX_PAGES = 10
# The table shows this many pull requests at most.
MAX_SHOWN = 50
# Smaller pull requests (lines added and removed together) are left out.
MIN_LINES = 10

SEARCH_QUERY = """
query($query: String!, $after: String) {
  search(query: $query, type: ISSUE, first: 100, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        number url mergedAt additions deletions
        repository { nameWithOwner url stargazerCount }
      }
    }
  }
}
"""


def table(your_repositories, login: str) -> str:
    """The totals line and the table, in Markdown: one row per repository with its stars, the most starred first, each
    one's pull requests newest first."""
    query = f"is:pr is:merged is:public author:{login} -user:{login}"
    nodes = []
    after = None
    for _ in range(MAX_PAGES):
        search = your_repositories.graphql(SEARCH_QUERY, {"query": query, "after": after})["search"]
        nodes.extend(search["nodes"])
        if not search["pageInfo"]["hasNextPage"]:
            break
        after = search["pageInfo"]["endCursor"]
    nodes.sort(key=lambda node: node["mergedAt"], reverse=True)
    # Only the ones of MIN_LINES lines or more.
    nodes = [node for node in nodes if node["additions"] + node["deletions"] >= MIN_LINES]

    # By repository, each one's pull requests newest first.
    repos = {}
    for node in nodes:
        name = node["repository"]["nameWithOwner"]
        if name not in repos:
            repos[name] = {"url": node["repository"]["url"], "stars": node["repository"]["stargazerCount"], "links": [], "lines": []}
        repos[name]["links"].append(f"[#{node['number']}]({node['url']})")
        # Lines added in green, removed in red: GitHub's Markdown has no colors, only its math ($`...`$) does.
        added = "$`\\color{green}\\textsf{+" + f"{node['additions']:,}" + "}`$"
        removed = "$`\\color{red}\\textsf{-" + f"{node['deletions']:,}" + "}`$"
        repos[name]["lines"].append(added + " " + removed)

    if not repos:
        return "No merged pull requests yet."
    # Above the table, the totals of all of them, not only the ones shown. The empty line keeps the table from running
    # into it.
    seraph = "Seraph"
    if SELF_REPO != "":
        seraph = f"[Seraph](https://github.com/{SELF_REPO})"
    prs = f"{len(nodes):,} PRs"
    if len(nodes) == 1:
        prs = "1 PR"
    repositories = f"{len(repos):,} repositories"
    if len(repos) == 1:
        repositories = "1 repository"
    lines = [f"{seraph} has merged {prs} across {repositories}", ""]
    lines.append("| Repository 🚀 | Stars 🌟 | Merged PR | Lines changed |")
    lines.append("| --- | --- | --- | --- |")
    # The most starred first, until MAX_SHOWN pull requests are in the table.
    shown = 0
    for name, repo in sorted(repos.items(), key=lambda item: item[1]["stars"], reverse=True):
        if shown >= MAX_SHOWN:
            break
        room = MAX_SHOWN - shown
        shown += len(repo["links"][:room])
        # A table cell can't hold a new line in Markdown: <br> puts each pull request on its own line.
        links = "<br>".join(repo["links"][:room])
        changed = "<br>".join(repo["lines"][:room])
        lines.append(f"| [{name}]({repo['url']}) 🚀 | {repo['stars']:,} 🌟 | {links} | {changed} |")
    # Below the table, how many more there are. The empty line keeps it out of the table.
    more = len(nodes) - shown
    if more > 0:
        more_prs = f"{more:,} more PRs"
        if more == 1:
            more_prs = "1 more PR"
        url = "https://github.com/search?q=" + quote_plus(query) + "&type=pullrequests"
        lines.append("")
        lines.append(f"And [{more_prs}]({url}).")
    return "\n".join(lines)


def update(your_repositories) -> str:
    """Brings the table up to date in your profile's README.md and in Seraph's own (SELF_REPO). Returns what it did, in
    words. ValueError or httpx.HTTPError when GitHub refuses. Runs in a thread."""
    account = your_repositories.github_account.load()
    if account is None:
        return "Not signed in."
    login = account["login"]
    profile = f"{login}/{login}"
    section = START + "\n" + table(your_repositories, login) + "\n" + END
    # Seraph's own README shows the same table (its Merged upstream part). Not when the app's repo isn't known.
    repos = [profile]
    if SELF_REPO != "":
        repos.append(SELF_REPO)

    done = []
    with your_repositories.client() as client:
        response = client.get(f"/repos/{profile}")
        if response.status_code == 404:
            response = client.post("/user/repos", json={"name": login, "private": False})
        response.raise_for_status()

        for repo in repos:
            response = client.get(f"/repos/{repo}/contents/README.md")
            # No README.md yet in your profile repository (a new repository is empty: also 404).
            if response.status_code == 404 and repo == profile:
                text = FIRST_TEXT + section + "\n"
                body = {"message": "docs(readme): add merged pull requests", "content": base64.b64encode(text.encode()).decode()}
                response = client.put(f"/repos/{repo}/contents/README.md", json=body)
                response.raise_for_status()
                done.append(f"Made {repo}'s README.md.")
                continue
            response.raise_for_status()
            readme = response.json()
            old = base64.b64decode(readme["content"]).decode()
            start = old.find(START)
            end = old.find(END)
            if start == -1 or end < start:
                done.append(f"{repo}'s README.md has no {START} and {END}: left alone.")
                continue
            new = old[:start] + section + old[end + len(END):]
            if new == old:
                done.append(f"{repo}'s README.md is up to date.")
                continue
            body = {
                "message": "docs(readme): update merged pull requests",
                "content": base64.b64encode(new.encode()).decode(),
                "sha": readme["sha"],
            }
            response = client.put(f"/repos/{repo}/contents/README.md", json=body)
            response.raise_for_status()
            done.append(f"Updated {repo}'s README.md.")
    return " ".join(done)
