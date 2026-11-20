"""The app's own repository and how its changes are named, for the daily Fix problems run (problem_fixes.py), the
profile README (profile_readme.py) and draft_pr's title check (agent/work_tools.py).

SELF_REPO is the app's own repo ("owner/name", "" when it isn't on GitHub). Its commit and PR titles are Conventional
Commits (TITLE, at most TITLE_CHARS), and its release notes group them by type (SECTIONS).
"""

import os
import re
import subprocess
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# override: the backend reloads itself on code changes, and .env changes should apply then too.
load_dotenv(PROJECT_ROOT / ".env", override=True)

# Conventional Commits: type(scope): summary, lower case, no period at the end.
TITLE = re.compile(r"(feat|fix|refactor|docs|style|test|chore|perf)\([a-z0-9_.-]+\): [a-z0-9].*[^.]")
TITLE_CHARS = 72
# How the release notes group the changes, by their title's type.
SECTIONS = [("feat", "Features"), ("fix", "Fixes"), ("other", "Other changes")]
# The app's own repo. The live copy has it in .env (deploy/install.sh); the dev copy is a clone, so its origin says it.
SELF_REPO = os.environ.get("SERAPH_REPO", "")
if SELF_REPO == "":
    try:
        result = subprocess.run(["git", "-C", str(PROJECT_ROOT), "remote", "get-url", "origin"], capture_output=True, text=True, timeout=10)
        match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(\.git)?$", result.stdout.strip())
        if match is not None:
            SELF_REPO = match.group(1)
    except (OSError, subprocess.TimeoutExpired):
        pass
