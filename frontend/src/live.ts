/*
Live data from the backend, and the one fetch helper.

One websocket to /api/live. On connect the server sends every topic, then only the topics that changed:
{"topic": "repos" | "jobs" | "inbox" | "prs" | "agents" | "vms" | "images" | "updates" | "automation", "data": ...}.
Each message replaces that topic in the store, and components read it with useLive(topic), so the page never
polls and never re-fetches lists. When the socket drops it reconnects after a second, and the server sends
everything again. When the app that answers is another version than this page's (an update restarted it, see
UpdateDialog.tsx), the page reloads into the new version, at the same place (the page is in the URL). The page sends nothing back.

The types below mirror the records in the spec (data/*.json and the live summaries).
*/

import { useSyncExternalStore } from "react";

// ---- Records ----

export type RepoItem = {
  full_name: string;
  description: string;
  stars: number;
  default_branch: string;
  html_url: string;
  note: string;
  added_by: string; // "user", "explore" or an agent id
  added_at: string;
};

export type ListData<T> = {
  items: T[];
  can_undo: boolean;
  can_redo: boolean;
};

// Proof an agent shows for its drafts (github_searcher/jobs.py). Files are served by /api/evidence/<name>.
export type EvidenceItem = {
  id: string;
  kind: "screenshot" | "image" | "command";
  topic: string; // pairs a before with its after
  stage: "before" | "after" | "other";
  context?: string; // how to read the comparison, in plain words (missing on early evidence)
  caption: string;
  file: string | null; // screenshot and image: "ev_a1b2c3.jpg"
  command: string | null;
  exit_code: number | null;
  output_file: string | null; // command: the whole output, "ev_a1b2c3.txt"
  output_tail: string; // command: its last lines
  output_size: number; // command: bytes of the whole output
  created_at: string;
};

// paused: the user paused its issue on the Dashboard's Issues board; paused_from is the status it goes back to on Resume.
export type JobStatus = "queued" | "working" | "waiting_on_user" | "waiting_on_maintainers" | "paused" | "done" | "cancelled";

// A job as the jobs topic carries it (backend/app.py): without its evidence and timeline, which no page shows, and a
// finished one with only the start of its notes and no test runs.
export type Job = {
  id: string;
  kind: string; // "fix_issue" | "follow_up" | "review" | "task" | future kinds
  title: string;
  agent: string;
  issue: string | null;
  thread: string | null; // follow_up: the PR or issue on GitHub it answers ("owner/name#n")
  repo: string | null;
  vm: string | null;
  status: JobStatus;
  instructions: string;
  notes: string;
  drafts: string[];
  created_by: string;
  created_at: string;
  updated_at: string;
  // Progress, set by the agent (job_progress). steps are this kind's fixed steps, step the one it is on.
  steps: string[];
  step: string | null;
  step_at: string | null; // when it got to that step
  started_at: string | null; // when the job first became "working"
  vm_seconds: number; // how long its agent held a VM desktop while it was working (counted since 11-20)
  paused_from?: JobStatus | null; // paused: the status Resume puts back
  about: string; // what the job is about, in everyday words
  headline: string; // where it stands now, in everyday words
  detail: string; // the same, technical
  // The project's tests: on the finished change (must pass before a PR), and on the unchanged code only as the agent's
  // last resort.
  tests: { before: TestRun | null; after: TestRun | null };
  skip_checks?: boolean; // you pressed Skip checks: its PR may be drafted now, without passing tests or a reviewer
};

export type TestRun = {
  command: string;
  scope?: "full" | "focused"; // full: the project's official checks; focused: the basic ones, the tests that cover the change. Missing: full
  base: string;
  exit_code: number | null; // null: stopped at the time limit
  passed: boolean;
  diff_hash: string; // the code it ran on ("" for before)
  evidence: string; // the evidence item with its output
  seconds: number;
  at: string;
};

// What a draft is about, in plain words for the user (github_searcher/inbox.py). PRs have problem, cause, fix, risks,
// checklist and also_tested; comments have problem and why. A report on a paper (draft_report) has paper, claims,
// verdict, results, problems and unchecked. An approval has kind (cla: an agreement to sign, or other) and link (the
// page to read or act on, "" when none).
export type DraftOverview = {
  kind?: "cla" | "other";
  link?: string;
  project?: string;
  problem?: string;
  cause?: string;
  fix?: string;
  risks?: string[];
  checklist?: ChecklistPoint[]; // every point that was asked, done or not (PRs from before it have none)
  also_tested?: string[]; // the cases of the same kind the agent ran beyond the asked example
  why?: string;
  paper?: string;
  claims?: string;
  verdict?: string;
  results?: ReportResult[];
  problems?: ReportProblem[];
  unchecked?: string[];
};

// One point a PR draft was asked for (the issue's requirement, or a reviewer's point): whether it does it, and what shows
// it or why not.
export type ChecklistPoint = { item: string; done: boolean; how: string };

// One number of a paper next to the agent's (and what the authors' own code gives, "" when not run).
export type ReportResult = { what: string; paper: string; ours: string; authors: string; note: string };

// A problem the agent found in a paper; evidence is the command run on the job that shows it.
export type ReportProblem = { title: string; what: string; why: string; evidence: string };

export type DraftStatus = "pending" | "approved" | "rejected" | "replied" | "cleared"; // cleared: an approval its agent took back

export type Draft = {
  id: string;
  kind: "pr" | "comment" | "question" | "taken" | "report" | "edit" | "approval"; // taken: old, made by the app when an issue an agent worked on was taken (agents decide that themselves now); report: on a paper; edit: a new title and description for your own PR or issue; approval: a blocker only you can lift, in the Dashboard's Blockers dialog (not the Inbox)
  agent: string;
  job: string | null;
  repo: string | null;
  target: string | null;
  title: string;
  body: string;
  diff: string; // "" in the live feed once it can't go out any more (rejected, answered or sent): GET /api/inbox/<id> has it
  branch: string;
  base: string;
  vm: string | null;
  path: string | null;
  evidence: EvidenceItem[]; // the job's evidence when the draft was made
  overview: DraftOverview; // for the user; {} on drafts from before overviews
  template: string | null; // the repo's PR template the body was checked against
  status: DraftStatus;
  reply: string;
  created_at: string;
  decided_at: string | null;
  base_sha: string; // the commit the diff starts from; "" on drafts from before sending
  commits: DraftCommit[]; // PRs: the branch's commits since base, replayed when it is sent ([]: one commit)
  sent: DraftSent | null; // what went to GitHub as you (github_searcher/github_account.py); null until then
  update_of: string | null; // PR: a new version of your open PR "owner/name#n"; approving pushes it onto that PR
  rebase_of: string | null; // PR update: a rebase, its commits replace the PR's; the PR's commit it replaces (approving force-pushes)
  edited: boolean; // you edited its title or text before deciding
  review: DraftReview | null; // a project's PR: its review (only passed ones reach the Inbox)
  replaces: string | null; // a project's PR made again on the new main: the PR "owner/name#n" it replaces
  previous: { title: string; body: string } | null; // edit: the title and description as they were when drafted
  options: string[]; // question: the answers to pick from, one button each ([]: answer in your own words)
  // A question either has a timer or waits for you. Timed: answer_by is when the app answers with recommended (one of
  // options) if you haven't. Waits: must_wait says why (money, sensitive, github, delete; open: no options to pick).
  recommended: string | null;
  answer_by: string | null;
  must_wait: "money" | "sensitive" | "github" | "delete" | "open" | null;
  answered_by: "user" | "timer" | "automation" | null; // who answered it, once it is answered (automation: its repo's or issue's Level of automation)
};

// A project's PR draft is reviewed by the project's reviewer before it reaches the Inbox (github_searcher/inbox.py).
export type DraftReview = {
  state: "waiting" | "passed" | "changes";
  agent: string | null; // the reviewer
  job: string | null;
  notes: string;
  at: string;
};

// One of a PR branch's commits, sent with your name. own: the agent's (the VM's git address); every commit of a new
// draft is (draft_pr refuses anyone else's), and a draft with someone else's commit isn't sent.
export type DraftCommit = {
  sha: string;
  message: string;
  author: { name: string; email: string; date: string };
  own: boolean;
  vm_email: string;
  diff: string; // "" in the live feed (never shown)
};

// A PR or comment Approve sent to GitHub from your account. PRs keep what following them up will need.
export type DraftSent = {
  kind: "pr" | "comment" | "edit";
  url: string;
  number: number;
  repo: string;
  as: string; // your GitHub login
  at: string;
  fork?: string; // PR: "you/name"
  branch?: string; // PR: its branch in the fork
  base_branch?: string;
  base_sha?: string;
  commit?: string;
  id?: number; // comment: its id on GitHub
  deleted_at?: string; // comment: when you deleted it on the GitHub tab
  title?: string; // edit: the new title it set
  update?: boolean; // PR: a new version pushed onto a PR that was already open
  rebase_of?: string | null; // PR update: the PR's commit a rebase replaced (a force push)
  comment_url?: string | null; // PR update: the comment posted with it (null: none was)
  comment_error?: string | null; // PR update: why GitHub refused the comment, when it did (the push went through)
};

// One of your PRs on GitHub and how it stands (github_searcher/pr_tracking.py): the ones Approve sent, and your
// other PRs on other people's projects. role is GitHub's word for the person (MEMBER, COLLABORATOR, OWNER, ..., BOT).
export type TrackedPR = {
  id: string; // "owner/name#number"
  repo: string;
  number: number;
  title: string;
  url: string;
  author: string;
  state: "open" | "merged" | "closed";
  draft: boolean; // GitHub's draft PR
  opened_at: string;
  updated_at: string;
  closed_at: string | null;
  merged_by: string | null;
  labels: string[];
  checks: "waiting" | "running" | "passed" | "failed" | "none"; // waiting: GitHub Actions waits for a maintainer to approve
  waiting_runs: number;
  review: "approved" | "changes_requested" | "commented" | "none";
  reviewers: { login: string; state: string; at: string; role: string }[]; // each reviewer's latest review
  comments: number;
  last_comment: { login: string; role: string; at: string; text: string } | null;
  issues: { number: number; title: string; url: string; state: "open" | "closed"; reason: string | null; assignees: string[] }[];
  draft_id: string | null; // the Inbox draft it was sent from
  job: string | null;
  agent: string | null; // the agent that follows it: the one you picked, else the one whose draft it was sent from
  agent_mode: AgentMode;
  relation: "author" | "commented"; // you opened it, or only commented on it
  head: { repo: string; branch: string; sha: string } | null; // its branch and newest commit (null: the branch is gone)
  base: string | null; // the branch it goes into
  mergeable: "yes" | "conflicts" | "unknown"; // whether it conflicts with base (unknown while GitHub works it out)
  // The lines it adds and removes and the files it changes; missing until it is read again.
  additions?: number;
  deletions?: number;
  changed_files?: number;
  last_activity: ThreadActivity | null;
  your_last_at: string | null; // your newest comment or review there
  failed_checks?: string[]; // the newest commit's checks that failed, by name
  head_at?: string | null; // when its newest commit was made
  // Your open PR: what it needs from us now (needs: the Issues board's Needs action, always its agent's to do), else how it
  // waits (status: Waiting approval). detail: what Claude found it needs, in words. null otherwise.
  action?: { needs: boolean; reasons: string[]; detail: string; status: string } | null;
  checked_at: string;
  error: string | null; // why the last read failed (the status before stays)
};

// drafts: its agent drafts replies and fixes when someone else writes there or its checks fail, and you approve
// each in the Inbox; off: no drafts. Nothing ever goes to GitHub without your approval.
export type AgentMode = "drafts" | "off";

// The newest comment or review on a PR or issue by someone other than you (bots don't count).
export type ThreadActivity = { login: string; at: string; what: "comment" | "review" };

// One of your issues on GitHub (pr_tracking.py): ones you opened and ones you commented on, on other people's projects.
export type GithubIssue = {
  id: string; // "owner/name#number"
  repo: string;
  number: number;
  title: string;
  url: string;
  author: string;
  state: "open" | "closed";
  reason: string | null; // closed: completed, not_planned or duplicate
  opened_at: string;
  updated_at: string;
  closed_at: string | null;
  labels: string[];
  assignees: string[];
  comments: number;
  last_comment: { login: string; role: string; at: string; text: string } | null;
  relation: "author" | "commented";
  agent: string | null;
  agent_mode: AgentMode;
  last_activity: ThreadActivity | null;
  your_last_at: string | null;
  checked_at: string;
  error: string | null;
};

export type PRsData = {
  items: TrackedPR[]; // the newest change first
  issues: GithubIssue[]; // the newest change first
  checked_at: string | null;
  error: string | null; // why the search for your PRs or issues failed
  refreshing: boolean;
};

// Your GitHub account (GET /api/github_account, Settings → Account), the one the app sends pull requests and comments
// as. Never the token.
export type GithubAccountStatus = {
  connected: boolean;
  // Whether Sign in with GitHub is set up (the app registered on GitHub, its client ID and secret saved).
  can_sign_in?: boolean;
  login?: string;
  name?: string;
  scopes?: string[];
  connected_at?: string;
};

export type AgentStatus = "idle" | "working" | "in_queue" | "using_vm";

export type AgentSummary = {
  id: string;
  name: string;
  target_vm: string | null;
  status: AgentStatus;
  busy: boolean;
  waiting: boolean; // out of its turn with messages waiting: it waits for a place among the agents in a turn
  waiting_for_vm: boolean; // it needs a VM and none takes agents now (none running, or each suspended or shutting down)
  vm: string | null; // the VM it is queued for or holds
  desktop: number | null; // the desktop of that VM it holds or asked for (null: any)
  place: number | null; // 0 = holder, n = place in the queue
  context_used: number;
  context_max: number;
  cost_usd: number;
  compactions: number; // how many times its context was compacted, over its whole life
  tokens_used: number; // the tokens of all its replies over its whole life: what it was given (cached or not) and wrote
  history_length: number;
  pending: number; // user messages waiting for the current turn to end
  queued: string[]; // their texts, oldest first
  activity: string; // the last tool summary or system line
  last_event_at: string | null; // when something last happened in its turn (to tell a slow command from a stuck agent)
  in_tool: boolean; // a tool call is running (a command, the test suite): quiet then is not stuck
  todo_done: number; // from its latest todo list
  todo_total: number;
  created_at: string;
  archived_at: string | null; // archived: stopped, its conversation kept
  prs: number; // PR drafts that wait for you or were approved: it can only be archived, not deleted
  artifacts_stamp: number; // goes up on every change to its artifacts (the Artifacts tab reads its folder again)
  repo: string | null; // a repository's agent (the Workspace tab's Live): the repo it belongs to
  live: LiveSetUp | null; // and how far its set-up is
  project: string | null; // a project's worker or reviewer: the project's repo
  role: "worker" | "reviewer" | "closed_prs" | null;
  model: string; // the Claude model of its turn, or of its last one (github_searcher/claude_models.py)
  workflow: string | null; // one of the Workflow tab's agents: its repository
  workflow_role: "chat" | "worker" | "reviewer" | null;
  priority: boolean; // you gave it priority: its work goes first until its tasks are over
};

// How far a repository's agent's set-up is (github_searcher/agents.py, prepare_live): its VM coming up and the code
// going in, then ready (it has its set_up_repo job), or failed with why (Try again).
export type LiveSetUp = { state: "preparing" | "ready" | "failed"; error: string | null };

export type HistoryEntry =
  | { type: "user"; text: string; time: string }
  | { type: "text"; text: string }
  | { type: "thinking"; text: string }
  | { type: "tool"; id: string; name: string; summary: string; input: Record<string, unknown> }
  | { type: "tool_result"; id: string; text: string; is_error: boolean; image: boolean }
  | { type: "system"; text: string; time: string }
  | { type: "turn_end"; stopped: boolean; cost_usd: number; time: string };

export type VMStatus = "creating" | "running" | "stopping" | "stopped" | "starting" | "failed" | "missing";

// The numbers are null until the first readings after the VM starts (CPU % needs two).
export type VMUsage = {
  on: boolean;
  responding: boolean; // false while it boots, or when it froze or crashed though Incus says Running
  cpu_percent: number | null;
  memory_used_gb: number | null;
  disk_used_gb: number | null;
  net_down_rate: number | null; // internet only (not the desktop or terminals), bytes a second
  net_up_rate: number | null;
};

// Internet use counted since the user last reset it, in bytes. The rest is the backend's bookkeeping.
export type VMTraffic = {
  down: number;
  up: number;
  since: string;
};

// A note on what is set up in a VM, for the next agent (and the user) to know.
export type VMNote = {
  id: string;
  text: string;
  by: string; // an agent id or "user"
  at: string;
  desktop?: number; // the desktop an agent wrote it on (its ~ is that desktop's home); the user's have none
};

// One desktop of a VM: who uses it. Each has its own screen, mouse, keyboard and home folder.
export type VMDesktop = {
  number: number; // fixed: removing a desktop never renumbers the others, and a new one takes the lowest number free
  holder: string | null; // null, "user" or an agent id
};

// A long command an agent left going in a VM (a test suite, a build): it goes on by itself until it ends.
export type VMRun = {
  id: string;
  agent: string; // the agent id
  desktop?: number; // the desktop it runs on (none: desktop 1)
  kind: "bash" | "tests";
  label: string; // the command, as you see it
  started_at: string;
  background: boolean; // false while the agent's tool call still waits for it
  stopped_by_user: boolean;
};

// Where an agent last clicked, dragged or scrolled on a desktop, in pixels of that desktop's screen (width x height).
export type VMPointer = { agent: string; x: number; y: number; width: number; height: number };

export type VMSummary = {
  name: string;
  incus_name: string;
  image: string; // the image's name when the VM was made ("" for older VMs); see image_fingerprint
  image_fingerprint: string; // the exact image it was made from: images can be renamed or rebuilt
  forked_from: string; // the VM this one is a copy of, or ""
  cpus: number;
  memory_gb: number;
  disk_gb: number;
  internet: boolean;
  env_names: string[];
  status: VMStatus;
  created_at: string;
  max_desktops: number; // the most desktops it may have (the user sets it)
  desktops: VMDesktop[]; // lowest number first; agents on different desktops work at the same time
  queue: string[]; // agent ids waiting for a desktop, first = next
  wants: Record<string, number>; // the desktop some of them asked for (the others take the first that frees up)
  runs: VMRun[]; // long commands agents left going in the VM
  usage: VMUsage | null;
  samples: { cpu_percent: number | null; memory_used_gb: number | null; net_down_rate: number | null; net_up_rate: number | null }[];
  traffic: VMTraffic;
  notes: VMNote[]; // what agents and the user set up in it, oldest first
  locked_by: Record<string, "user" | "agent">; // per desktop number: who locked your mouse and keyboard out
  pointers: Record<string, VMPointer>; // per desktop number: where an agent last put the mouse (AgentCursor.tsx)
  error: string | null; // why the last create, start or stop failed
  graceful_shutdown: boolean; // shuts down once the agents on it are done; a start or restart ends it
  suspended: boolean; // Suspend: no agent new to it gets a desktop, the ones on it go on; until Resume
};

// What an image has, listed once in a throwaway VM (sandbox/image/inventory.py). The live feed carries this
// summary; the packages themselves come from GET /api/images/inventory/<fingerprint> (ImageInventory).
export type Probe = { name: string; version: string; raw: string };

export type InventoryHighlights = {
  image: { name: string; fingerprint: string; created_at: string };
  inspected_at: string;
  system: { os: string; kernel: string; arch: string; desktop: string; user: string; disk_used_gb: number };
  languages: Probe[];
  tools: Probe[];
  docker_images: string[];
  models: string[];
  caches: { name: string; path: string; size_gb: number }[];
  counts: Record<string, number>; // packages per kind: apt, pip, npm, cargo, snap, flatpak, vscode, docker, playwright
};

export type Package = { kind: string; name: string; version: string; manual?: boolean };

export type Inventory = Omit<InventoryHighlights, "docker_images" | "counts"> & { packages: Package[] };

export type Image = {
  name: string;
  aliases: string[];
  fingerprint: string;
  size_gb: number;
  created_at: string;
  default: boolean;
  used_by: string[]; // names of the VMs made from this exact image, stopped ones too
  inventory: InventoryHighlights | null; // null until it is inspected
  inspecting: boolean; // a build, save or inspect of it is running
  definition_changed: boolean; // its image.yaml changed since it was built: a Rebuild applies it
  definition_updated_at: number; // when its image.yaml last changed (seconds), so a view of it knows to fetch again
  description: string; // the description in its image.yaml ("" without one)
};

// An image's image.yaml, what defines it (GET /api/images/<name>/definition), and a diff from what it was built
// from ("" when the same, or never built).
export type ImageDefinition = { definition: string; diff: string };

// The mechanical check of an image.yaml or the defaults (POST /api/image-check): what is wrong, or nothing.
export type ImageCheck = { problems: string[] };

// The defaults every new image.yaml starts as (GET /api/image-defaults): the user's, "" before they wrote any.
export type ImageDefaults = { defaults: string };

// What New image offers (GET /api/images/new/options): system ids and labels, desktops (the first is the default,
// the last is "None (terminal only)"), and the system picked first.
export type NewImageOptions = {
  systems: { id: string; label: string }[];
  desktops: string[];
  system: string;
};

// The chat with an image's agent (sandbox/image_agent.py), from GET /api/images/<name>/agent.
export type ImageAgentEntry =
  | { type: "user"; text: string; time: string }
  | { type: "text"; text: string }
  | { type: "system"; text: string; time: string }
  | { type: "tool"; id: string; name: string; summary: string }
  | { type: "tool_result"; id: string; text: string; is_error: boolean }
  | { type: "turn_end"; stopped: boolean; cost_usd: number; time: string };

export type ImageAgentChat = { history: ImageAgentEntry[]; busy: boolean; cost_usd: number };

// A build (Build, Rebuild or the image agent) or an inspect.
// Tasks that worked disappear once their image is listed; failed ones stay until dismissed.
export type ImageTask = {
  id: string;
  kind: "build" | "inspect";
  name: string;
  status: "running" | "failed";
  error: string | null;
  started_at: string;
  log_tail: string[];
};

// An image with an image.yaml (saved by New image) that was never built: no Incus image yet.
export type UnbuiltImage = {
  name: string;
  system: string; // its system's label ("" while image.yaml isn't right)
  description: string; // the description in its image.yaml ("" without one)
  updated_at: number; // when its image.yaml last changed (seconds)
  building: boolean; // its first build is running
};

export type ImagesData = {
  images: Image[];
  unbuilt: UnbuiltImage[];
  default: string;
  tasks: ImageTask[];
};

// ---- One-off responses (fetched with api(), not live) ----

export type VMOptions = {
  cpus: number[];
  cpus_default: number;
  memory_gb: number[];
  memory_gb_default: number;
  disk_gb_min: number;
  disk_gb_max: number;
  disk_gb_default: number;
  max_desktops_default: number; // the most desktops (agents at the same time) a new VM may have
  max_desktops_max: number; // the highest max desktops can be set to
  next_name: string;
};

export type VMSettings = {
  cpus: number;
  memory_gb: number;
  disk_gb: number;
  internet: boolean;
  env: Record<string, string>;
};

// The live copy's updates (github_searcher/updates.py): the version that runs, and a newer release that is ready.
export type UpdatesData = {
  live: boolean; // false in the dev copy (./run.sh): no updates there
  running: string; // the release that runs, e.g. "v0.1.0", or "dev"
  latest: { tag: string; name: string; notes: string; published_at: string; url: string } | null; // on GitHub
  ready: string | null; // a newer release, downloaded and ready: Update in the header
  preparing: string | null; // the release being made ready now
  checking: boolean;
  checked_at: string | null;
  error: string;
  previous: string | null; // the release before this one (Previous version)
  switched_at: string | null; // when this one went live
  failed: string | null; // the release the last update went to, when it didn't start or was taken back
  failed_reason: string; // why ("" when not known)
  restarting: boolean;
};

// Automation's settings (Settings → Automation: Automation.tsx, and ExploreDialog.tsx; backend/automation_api.py; PUT
// /api/automation takes the same). A limit that is null has none.
export type AutomationData = {
  on: boolean; // Manage repositories: finds and adds repositories, archives the ones that don't merge ours
  add_repos: boolean; // Add repositories: off, nothing new is added
  take_new: boolean; // Take new issues
  send_prs: boolean; // Create pull requests
  send_comments: boolean; // Reply to reviews and comments
  max_prs_per_day: number | null;
  max_open_prs: number | null;
  max_open_per_repo: number | null;
  max_agents: number; // at least 1
  ai_policies: string[]; // the AI policies whose repositories may be worked on: "welcome", "disclose", "none", "unclear"
  // Explore's Include and Exclude: the kinds of repositories you want and don't, in your own words (kept in the data,
  // never in the code; PUT sets them only when given).
  include: string;
  exclude: string;
  // The Repositories dialog's column switches (PUT /api/automation/take_from): off, no new issues of its repos.
  take_from: Record<"target" | "prioritized" | "contributed" | "catalog", boolean>;
  // The same columns' settings (their ⚙, PUT /api/automation/column): the most PRs open at once per repo (null: the
  // usual limits), the agents' model ("default": the usual), and how many of each repo's newest issues are scanned
  // (missing in columns saved before it: 300).
  columns: Record<"target" | "prioritized" | "contributed" | "catalog", { max_open_per_repo: number | null; model: string; max_scan?: number }>;
};

// The tokens every Claude run used (github_searcher/token_usage.py), per model, kind of work (claude_models.py; "agent":
// an agent's, from before the usage log) and stretch of time (at: its start). The stretches are 5 minutes for the last
// two hours, an hour for the last 8 days, then a day from local midnight. cost_usd: what they cost.
export type TokensData = { slices: { at: string; model: string; work: string; tokens: number; cost_usd: number }[] };

// The Feedback dialog (FeedbackDialog.tsx; github_searcher/problems.py): what the agents reported, and what the app saw itself (agent
// "seraph"), newest first. closed_at: once Fix all fixed it, found nothing to change or gave up on it.
export type Feedback = {
  id: string;
  at: string;
  agent: string;
  job: string | null;
  about: string | null; // "owner/name#n"
  text: string;
  closed_at: string | null;
};

// What runs besides the agents (backend/app.py, topic "activity"), for the Dashboard's Agents: the images whose agent is
// in a turn, a Fix all run (null: none runs), the checks running now (github_searcher/claude_judge.py, how many by what),
// and the model each of these uses.
export type ActivityData = {
  images: string[];
  fix_all: { started_at: string; items: number; vm: string } | null;
  checks: Record<string, number>;
  models: { checks: string; issue_titles?: string; issue_starts?: string; image: string; fix_all: string };
};

// ---- The live store ----

export type Topics = {
  // archived, removed, prioritized, target (by name: when it went there), restored (by name: when it left Removed): the
  // Repositories dialog (repo_list.py). contributors: how many each listed repo has, by name in lower case (from its
  // signals; null: not known yet, or GitHub won't count them).
  repos: ListData<RepoItem> & {
    archived: string[];
    removed: string[];
    prioritized: string[];
    target: Record<string, string>;
    restored: Record<string, string>;
    contributors: Record<string, number | null>;
  };
  jobs: Job[];
  inbox: Draft[]; // only the approval requests still waiting: the Dashboard's Blockers card and dialog
  prs: PRsData;
  agents: AgentSummary[];
  vms: VMSummary[];
  images: ImagesData;
  updates: UpdatesData;
  automation: AutomationData;
  tokens: TokensData;
  problems: Feedback[];
  activity: ActivityData;
};

// Empty until the first message, so components never deal with "not loaded yet".
// `loaded` says which topics have arrived, for the few places that must tell "empty" from "not yet".
const store = {
  topics: {
    repos: { items: [], can_undo: false, can_redo: false, archived: [], removed: [], prioritized: [], target: {}, restored: {}, contributors: {} },
    jobs: [],
    inbox: [],
    prs: { items: [], issues: [], checked_at: null, error: null, refreshing: false },
    agents: [],
    vms: [],
    images: { images: [], unbuilt: [], default: "", tasks: [] },
    updates: {
      live: false,
      running: "dev",
      latest: null,
      ready: null,
      preparing: null,
      checking: false,
      checked_at: null,
      error: "",
      previous: null,
      switched_at: null,
      failed: null,
      failed_reason: "",
      restarting: false,
    },
    automation: {
      on: false,
      add_repos: false,
      take_new: false,
      send_prs: false,
      send_comments: false,
      max_prs_per_day: null,
      max_open_prs: null,
      max_open_per_repo: null,
      max_agents: 1,
      ai_policies: [],
      include: "",
      exclude: "",
      take_from: { target: true, prioritized: true, contributed: true, catalog: true },
      columns: {
        target: { max_open_per_repo: null, model: "default", max_scan: 300 },
        prioritized: { max_open_per_repo: null, model: "default", max_scan: 300 },
        contributed: { max_open_per_repo: null, model: "default", max_scan: 300 },
        catalog: { max_open_per_repo: null, model: "default", max_scan: 300 },
      },
    },
    tokens: { slices: [] },
    problems: [],
    activity: { images: [], fix_all: null, checks: {}, models: { checks: "", image: "", fix_all: "" } },
  } as Topics,
  loaded: {} as Partial<Record<keyof Topics, boolean>>,
  connected: false,
};

const listeners = new Set<() => void>();

// The version of the app this page came from: the first one the backend says it runs.
let pageVersion: string | null = null;

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function connect() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${window.location.host}/api/live`);

  socket.onopen = () => {
    store.connected = true;
    listeners.forEach((listener) => listener());
  };

  socket.onmessage = (event) => {
    const message = JSON.parse(event.data) as { topic: keyof Topics; data: never };
    // A new topics object (not a mutation), so useSyncExternalStore sees the change.
    store.topics = { ...store.topics, [message.topic]: message.data };
    store.loaded = { ...store.loaded, [message.topic]: true };
    listeners.forEach((listener) => listener());
    // Another version answers now (an update or Previous version restarted the app): load its page.
    if (message.topic === "updates") {
      const running = (message.data as UpdatesData).running;
      if (pageVersion === null) {
        pageVersion = running;
      } else if (running !== pageVersion) {
        window.location.reload();
      }
    }
  };

  // onclose also follows onerror, so this is the one place that reconnects.
  socket.onclose = () => {
    if (store.connected) {
      store.connected = false;
      listeners.forEach((listener) => listener());
    }
    setTimeout(connect, 1000);
  };
}

connect();

// The latest data of one topic. Re-renders only when that topic changes.
export function useLive<K extends keyof Topics>(topic: K): Topics[K] {
  return useSyncExternalStore(subscribe, () => store.topics[topic]);
}

// One value worked out from the topics, for a component that needs only a little of a busy topic: the VM list
// changes every second while a VM runs (its usage samples). select must return a string, number or boolean, so
// the component re-renders only when that value changes, e.g. useLiveValue((topics) => topics.vms.length).
export function useLiveValue<T extends string | number | boolean>(select: (topics: Topics) => T): T {
  return useSyncExternalStore(subscribe, () => select(store.topics));
}

// Whether a topic has arrived at least once since the page loaded.
export function useLoaded(topic: keyof Topics): boolean {
  return useSyncExternalStore(subscribe, () => store.loaded[topic] === true);
}

// Whether the websocket is open right now (the header shows "Offline" when it is not).
export function useConnected(): boolean {
  return useSyncExternalStore(subscribe, () => store.connected);
}

// ---- The fetch helper ----

// api("/api/repos/plan", { method: "POST", body: {...} }), api<GithubAccountStatus>("/api/github_account").
// Sends body as JSON. Returns the parsed JSON (or the text for non-JSON answers).
// Throws Error(detail) on a non-2xx answer, with the backend's HTTPException detail as the message.
export async function api<T = unknown>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const init: RequestInit = { method: options.method ?? "GET" };
  if (options.body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, init);
  const isJson = (response.headers.get("content-type") ?? "").includes("application/json");
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    if (isJson) {
      const body = await response.json().catch(() => null);
      if (body && typeof body.detail === "string") {
        detail = body.detail;
      } else if (body && body.detail !== undefined) {
        detail = JSON.stringify(body.detail);
      }
    }
    throw new Error(detail);
  }
  if (isJson) {
    return (await response.json()) as T;
  }
  return (await response.text()) as T;
}
