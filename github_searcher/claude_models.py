"""Which Claude model each kind of work uses. Every place that runs Claude reads its model here, and every run is logged
with its model, tokens and time (github_searcher/token_usage.py add, the Dashboard's Tokens chart).

The newest of each family, as Claude Code knows them (its model list in claude-agent-sdk 0.2.186). Per million tokens:
in, out and cached read; writing to the cache costs twice the input for an hour.

    Fable 5.2   claude-fable-5-2   $8    $40    $0.20   the most capable
    Opus 5.5    claude-opus-5-5    $4    $20    $0.20
    Sonnet 5.5  claude-sonnet-5-5  $2    $10    $0.10

All three hold 1M tokens. Haiku 5.5 (claude-haiku-5-5, $0.10 in, $0.50 out) only reads issue titles (issue_titles
below). Claude Code makes small side calls of its own on every run with its Haiku model, and those go to SIDE_MODEL
instead (ANTHROPIC_DEFAULT_HAIKU_MODEL in each run's env). Some judgments' runs still show Haiku 5.5.

PRICES has these numbers for the Dashboard's cost (token_usage.py), the same as Claude Code's own cost of a run.

An agent keeps one conversation, and Claude's cache only serves the same model, so an agent's model is picked once per
job (agents.py work), never per step: a switch re-reads the whole conversation at full price.

The kinds of work:
- fix_issue, follow_up: an agent fixing an issue, or following up on its pull request. In a repository with
  BIG_REPO_STARS stars or more, BIG_REPO_MODEL instead: work for the big names is worth the most. Over both, the Model
  of the repo's column on the Repositories page (its settings: COLUMN_MODELS, or Default for these), picked for the
  job's first turn and kept by the job (agents.py work).
- review: the reviewer before a pull request goes out. chat: an agent with no job (talking with you). task: any other
  job.
- judgment: one question answered as JSON with no tools (claude_judge.py): issue tags, repository checks, which pull
  requests need action, Explore's checks.
- issue_titles, issue_starts: Add issues' scan of a repo's newest issues (backend/repo_automation_api.py): first their
  titles alone, then the start of the descriptions of the ones the titles kept. Only what passes both is read in full
  (issue tags, judgment).
- explore: Explore's look at a repository's issues and pull requests; explore_reader: the helpers it hands threads to
  (they only read and report back).
- image: the image agent (sandbox/image_agent.py). fix_problems: Fix all, the run that fixes the app (problem_fixes.py).
"""

FABLE = "claude-fable-5-2"
OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"

# USD per million tokens: in, out and cached read. Writing to the cache is twice the input.
PRICES = {
    FABLE: (8, 40, 0.20),
    OPUS: (4, 20, 0.20),
    SONNET: (2, 10, 0.10),
    HAIKU: (0.10, 0.50, 0.005),
}

MODELS = {
    "fix_issue": OPUS,
    "follow_up": OPUS,
    "review": OPUS,
    "chat": OPUS,
    "task": OPUS,
    "judgment": SONNET,
    "issue_titles": HAIKU,
    "issue_starts": SONNET,
    "explore": OPUS,
    "explore_reader": SONNET,
    "image": OPUS,
    "fix_problems": OPUS,
}
# A column's Model on the Repositories page, by its name there ("default": the ones above).
COLUMN_MODELS = {"fable": FABLE, "opus": OPUS, "sonnet": SONNET}
BIG_REPO_STARS = 20000
BIG_REPO_MODEL = FABLE
SIDE_MODEL = SONNET
