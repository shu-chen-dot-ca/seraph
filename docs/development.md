# Development

```text
github_searcher/    search, signals, Explore, lists, agents, jobs, Inbox, sending
  agent/            the agents' prompt and tools
sandbox/            Incus VMs, desktops, the VM queue, images, in-VM tools
backend/            FastAPI: one router per page, and the /api/live websocket
frontend/           React 19, Vite, Tailwind, shadcn/ui
deploy/             live copy install, switch, rollback
remote_access/      Caddy and the SSH tunnel for phone access
docs/               these pages
data/               runtime state, not in git
```

```bash
./run.sh                        # backend and frontend, both reloading
uv run pytest                   # tests
cd frontend && npm run build    # type-check and build
```

**Tests** live in `tests/`, one file per area. They need no network, no tokens, no Incus and no Claude login, and never touch your data: each one points the module it tests at pytest's temporary folder. Many are regression tests named after the incident that made the rule, so the rule can't quietly break again.

**CI** runs on every push to `main` and on pull requests. It builds the frontend, compiles every Python file, and runs the tests.

**Fix problems** (Settings) fixes the agents' problems every day at a set time:

1. Claude Code gets every open problem from the Dashboard's Problems page, in its own clone of the repo (`~/seraph/fixer`), never your working copy.
2. Each fix comes with a regression test, in a Conventional Commit.
3. The fixes must pass the same tests and build as CI, or they are dropped.
4. They are pushed to `main`, the fixed problems are closed, and `main` is released. The live copy installs the release by itself and takes it back if it goes wrong.

Claude Code may only edit files, run the tests and the build, and commit. It gets none of your tokens. Pull before you push: the run pushes to `main` too.

**Commits** follow [Conventional Commits](https://www.conventionalcommits.org/): one line, `type(scope): summary`, and exactly one scope per commit. [`CLAUDE.md`](../CLAUDE.md) has the full conventions.
