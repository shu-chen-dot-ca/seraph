# Development

```text
github_searcher/    search, signals, Explore, lists, agents, jobs, Inbox, sending
  agent/            the agents' prompt and tools
sandbox/            Incus VMs, desktops, the VM queue, images, in-VM tools
backend/            FastAPI: one router per page, and the /api/live websocket
frontend/           React 19, Vite, Tailwind, shadcn/ui
deploy/             live copy install, switch, rollback
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

**Fix all** (the Feedback page) fixes all the open feedback when you click it. Nothing else starts it.

1. Claude Code gets every open item at once, in one session, in Seraph's own VM (`seraph`): a clone of `main`, a copy of your data without the VMs or secrets, and your Claude Code memory of this repo. It can run the tests, the build and the app (`SERAPH_CHECK=1 ./run.sh`). A terminal on the VM's desktop shows what it does.
2. Each fix comes with a regression test, in a Conventional Commit. Items that aren't real problems are closed with why; an item still open after two runs is closed too.
3. The fixes must keep to the scope: no change to `deploy/`, `live.sh`, CI, `CLAUDE.md`, `.env` files, the packages or the release and fix machinery, no deleted or fewer tests, and no fix aimed at only the repo a report was about. Otherwise they are all dropped.
4. They must pass the same tests and build as CI, run on this computer, or they are dropped.
5. They are pushed to `main`, the fixed items are closed, and `main` is released. The live copy installs the release by itself and takes it back if it goes wrong. With no open feedback, Fix all just releases what you pushed.

Its Claude Code logs in with its own token, `CLAUDE_CODE_OAUTH_TOKEN_VM` (from `claude setup-token`, kept with the other secrets), handed only to that one process. The VM can't push; the run pushes from this computer. Pull before you push: the run pushes to `main` too.

**Commits** follow [Conventional Commits](https://www.conventionalcommits.org/): one line, `type(scope): summary`, and exactly one scope per commit. [`CLAUDE.md`](../CLAUDE.md) has the full conventions.
