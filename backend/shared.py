"""The app's single instances, made once when the backend imports this module.

Every router imports what it needs from here, so all of them work on the same lists (and the facts, difficulty and
signals about their issues and repos), Explore, jobs, the inbox, your GitHub account (which sends the drafts as you),
your PRs on GitHub and how each stands, with the agent that follows each, your repositories (read with your sign-in,
for cloning and for knowing which repos are yours), VMs, their images (and the images' agents), the VM queue, the
agents' artifacts, agents, the tokens the agents used, updates (the live copy's new
releases), the app's own errors and the Feedback page's list. The order matters: the Issues list asks jobs which
issues an agent is working on (those can't be removed), the queue keeps its state on the VM records, and Agents needs
everything else (it also sets the queue's on_grant / on_kick callbacks). Agents only starts its worker tasks in the
app's lifespan (backend/app.py), because they need the running event loop.
"""

from github_searcher.agents import Agents
from github_searcher.artifacts import Artifacts
from github_searcher.crashes import Crashes
from github_searcher.explore import Explore
from github_searcher.github_account import GithubAccount
from github_searcher.inbox import Inbox
from github_searcher.issue_tags import IssueTags
from github_searcher.issue_facts import IssueFacts
from github_searcher.issue_list import IssueList
from github_searcher.jobs import Jobs
from github_searcher.pr_tracking import PRTracking
from github_searcher.problem_fixes import ProblemFixes
from github_searcher.problems import Problems
from github_searcher.repo_list import RepoList
from github_searcher.repo_signals import RepoSignals
from github_searcher.token_usage import TokenUsage
from github_searcher.token_balancer import BALANCER
from github_searcher.updates import Updates
from github_searcher.your_repositories import YourRepositories
from sandbox.image_agent import ImageAgents
from sandbox.images import Images
from sandbox.vm_queue import VMQueue
from sandbox.vms import VMs

# First, so everything after it can report what goes wrong.
crashes = Crashes()
repos = RepoList()
jobs = Jobs()
issues = IssueList(jobs)
issue_facts = IssueFacts()
repo_signals = RepoSignals()
# Explore skips the repos on this old list; nothing adds to it any more.
tracked = RepoList("tracked.json")
explore = Explore(repos, tracked, repo_signals)
inbox = Inbox()
github_account = GithubAccount(inbox)
# A claim whose job ended isn't posted (github_account.py send).
github_account.jobs = jobs
# Its merge reads the repos' numbers and your merged pull requests (by your login).
issue_tags = IssueTags(repo_signals, github_account)
# A Target repo's issues are judged by its AI policy alone (issue_tags.py).
issue_tags.repos = repos
pr_tracking = PRTracking(inbox, github_account)
your_repositories = YourRepositories(github_account)
vms = VMs()
images = Images(vms)
image_agents = ImageAgents(images)
queue = VMQueue(vms)
artifacts = Artifacts()
agents = Agents(repos, issues, jobs, inbox, vms, queue, repo_signals, issue_tags, explore, artifacts, your_repositories, crashes)
# The Feedback page: what the agents report and what the app sees itself, like a GitHub token that stopped working
# (Fix problems in Settings works through them).
problems = Problems()
agents.problems = problems
BALANCER.problems = problems
# The tokens the agents used, per model and over time (the Dashboard's Tokens chart).
token_usage = TokenUsage()
updates = Updates(github_account, crashes)
# Fix problems: the daily run that fixes the problems, pushes the fixes and releases the app (Settings).
problem_fixes = ProblemFixes(problems, github_account, updates, vms, images)
