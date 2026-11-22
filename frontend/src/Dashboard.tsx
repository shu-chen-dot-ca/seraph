/*
The Dashboard (#/), the page the app opens on, display only. On top, its name, Live (or Offline in red while the live
feed is down) with the time your pull requests were last read, and the range every pull request number and chart
follows: 1 hour, 1 day, 7, 30 or 90 days (kept while the page is open). A range is cut into equal periods that start on
the clock (5 minutes for an hour, an hour for a day, 6 hours for 7 days, else a day); the last one is the one now. Every
widget has the same frame: a header with its title, which opens its page, or the Repositories dialog on its tab (Tokens
and cost has none), and on the right a detail. The Repositories dialog (RepositoryCards.tsx) is the cards and your pull
requests' tabs; its own card opens it on the cards, the pull request numbers and charts on Open, Merged or Closed.
Every line is drawn as a curve through its points, not straight lines between them. Every point stays at its real
value; between two points the curve never goes past either one's level (a monotone cubic curve, Steffen's), so it
shows no peak or dip that isn't in the numbers.
Under the top:
- Opened, Merged, Closed, Merge rate, Time to merge (the median from opened to merged) and Tokens and cost (all the
  agents used, the cost in USD above the tokens): a big number, with the change from the previous range of the same
  length a little after it, always at the same place whatever the range, green when it is good, red when it is bad (for
  Tokens and cost, less is good). The previous one on hover.
- Pull requests: opened, merged and closed per period, as three lines in GitHub's colors; Open, the pull requests still
  open at the end of each period (now for the last one), in blue, all on a log scale (0, 1, 3, 10, 30, ...: a count's
  height is log(1 + count), so 0 sits at the bottom); and Merge rate: the 7-day average at the end of each period
  (merged of merged and closed in the 7 days before), dotted gray, on its own 0-100% axis on the right. Open PR limit in
  its header is Automation's Open pull requests limit (PUT /api/automation on Enter or leaving the box; empty:
  no limit). The box takes only 1 to 999: a keystroke or paste that would make it anything else is ignored. Set, it is
  a dashed blue line at that count, and the axis goes up to it. Back to front: Open PR limit, Merge rate, Open, Closed,
  Opened, Merged.
- Tokens and cost: the tokens every Claude run used per period (input, cache written, cache read and output, from the
  usage log: github_searcher/token_usage.py), a line per model, no total; and Cost, what they all cost in USD, as gray
  bars behind the lines on its own axis on the right. Models by their names (Opus 5.5).
  These two share one time axis: hovering a period in one marks it in both, with its numbers.
- Limits, kept small (one short line each, two columns of the row): Automation's limits against what is used now,
  amber from 85%: pull requests opened today, open pull requests, the most open in one repository, agents working, and
  desktops in use of all the running VMs may have. Its title opens Settings on Automation (Automation.tsx).
  On its right in the same row, Repositories: how many repositories have a card (the list's, and those with a pull
  request of yours that aren't in it); Explore: On or Off, its Add repositories; Blockers: how many of the agents'
  approval requests wait for you (amber when any); Feedback: how much is open; and Settings. A click anywhere on one
  opens its dialog (the Repositories dialog on its cards, ExploreDialog.tsx, BlockersDialog.tsx, FeedbackDialog.tsx, and
  SettingsDialog, which App owns: onOpenSettings).
- Virtual machines, with two tabs in its header, the box as tall on both. VMs (#/): every VM's band (VMList.tsx)
  with its CPU, Memory, Internet and Disk cards, how many run, and New VM (NewVMDialog). Images (#/vms?tab=images): the
  images VMs start from (Images.tsx). A VM's name (#/vms/<name>) opens its page (VMPage.tsx: its desktop, Resources
  and Settings) in a dialog over the Dashboard; closing it goes back to #/. App.tsx reads these from the address and passes them in (vm, vmsTab).
- Agents: everything doing something now, a row each, working ones first (the most VM time first), then the waiting
  ones. Type: Fix, Follow-up or Review (the job an agent is on: working, or queued while its agent is in a turn, waits
  for one, or waits in a VM's line), Other (an agent in a turn with no job), Closed PRs (the one agent that reads
  merged and closed PRs: how many it has open), Image (an image's agent in a turn), Fix all (Feedback's run), and the
  checks running now, a row each: the one-off questions to Claude (claude_judge.py). Those that read GitHub, and the
  closed PRs agent, are GitHub, with what they do in the next column (CHECKS); Explore's own planning is Explore. Then
  Issue or pull request (its repository and number only, opens it on GitHub), Step (or why it waits: for a turn, in a
  VM's line, or for a VM while none takes agents: none running, or each suspended or shutting down), VM time (how
  long its agent held a VM desktop for the job: tests, builds and all it did there, counted since 11-20; jobs.py
  vm_seconds; Fix all's since it started), Tokens (all its agent used, in millions), Model (the Claude model it runs
  on), and VM and desktop. What it is doing right now shows on hover. Agents with nothing to do don't show; queued jobs
  whose agent isn't on them yet are only counted in the header.
Charts keep fixed heights; a line breaks where there is no number. Lines are drawn back to front by their layer, each
with a thin edge in the card's color, so where two cross the one in front clearly covers the one behind. Big numbers are short: 1.2K, 3.4M,
and dollars $0.05, $412, $1.23K.
*/

import { Plus, Settings } from "lucide-react";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import ExploreDialog from "@/ExploreDialog";
import BlockersDialog from "@/BlockersDialog";
import FeedbackDialog from "@/FeedbackDialog";
import RepositoryCards from "@/RepositoryCards";
import Images from "@/Images";
import NewVMDialog from "@/NewVMDialog";
import VMList from "@/VMList";
import VMPage from "@/VMPage";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { JobProgressBar, useNow } from "@/components/ui/job-progress";
import { api, useConnected, useLive, useLoaded, type AutomationData, type Job } from "@/live";
import { cn } from "@/lib/utils";

const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const RANGES = [
  { key: "1h", title: "1 h", length: HOUR, period: 5 * MINUTE, per: "Per 5 minutes" },
  { key: "1d", title: "1 d", length: DAY, period: HOUR, per: "Per hour" },
  { key: "7d", title: "7 d", length: 7 * DAY, period: 6 * HOUR, per: "Per 6 hours" },
  { key: "30d", title: "30 d", length: 30 * DAY, period: DAY, per: "Per day" },
  { key: "90d", title: "90 d", length: 90 * DAY, period: DAY, per: "Per day" },
];
// "Nov 18", "Nov 18, 14:05", "14:05" and "14:32:05"
const DATE: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
const DATE_TIME: Intl.DateTimeFormatOptions = { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" };
const TIME: Intl.DateTimeFormatOptions = { hour: "2-digit", minute: "2-digit", hourCycle: "h23" };
const CLOCK: Intl.DateTimeFormatOptions = { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" };
// 1234 → "1.2K", 3400000 → "3.4M"
const SHORT = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });
// 0.05 → "$0.05", 412.37 → "$412", 1234 → "$1.23K"
const USD = new Intl.NumberFormat("en", { style: "currency", currency: "USD", notation: "compact", maximumSignificantDigits: 3 });
// GitHub's open green, merged purple and closed red: Tailwind's 600 (500 when dark) with 20% less saturation.
const OPENED = "text-[oklch(62.7%_0.155_149.214)] dark:text-[oklch(72.3%_0.175_149.579)]";
const MERGED = "text-[oklch(55.8%_0.23_302.321)] dark:text-[oklch(62.7%_0.212_303.9)]";
const CLOSED = "text-[oklch(57.7%_0.196_27.325)] dark:text-[oklch(63.7%_0.19_25.331)]";
// A color per model, in the order they first show up.
const TOKEN_COLORS = ["text-sky-500", "text-amber-500", "text-teal-500", "text-pink-500", "text-lime-500", "text-violet-500", "text-orange-500", "text-rose-500"];
// The Tokens chart's and the Agents table's names for models (others as they are; github_searcher/claude_models.py).
const MODEL_NAMES: Record<string, string> = {
  "claude-fable-5-2": "Fable 5.2",
  "claude-opus-5-5": "Opus 5.5",
  "claude-sonnet-5-5": "Sonnet 5.5",
  "claude-haiku-5-5": "Haiku 5.5",
};
const WIDGET = "flex min-w-0 flex-col rounded-sm border bg-card";
const WIDGET_HEADER = "flex h-9 shrink-0 items-center gap-3 border-b px-3";
const TITLE = "truncate font-medium hover:underline";
const DETAIL = "ml-auto shrink-0 text-xs text-muted-foreground tabular-nums";
// The Agents table's Type, by job kind.
const JOB_TYPES: Record<string, string> = { fix_issue: "Fix", follow_up: "Follow-up", review: "Review" };
// The checks' Type and what they do (github_searcher/claude_judge.py, by what); others are GitHub, by their what.
const CHECKS: Record<string, [string, string]> = {
  issue_tags: ["GitHub", "Issue tags"],
  pr_needs_action: ["GitHub", "PR needs action"],
  catalog_picks: ["GitHub", "Catalog picks"],
  repo_signals: ["GitHub", "Repo signals"],
  ai_policy: ["GitHub", "AI policy"],
  atmosphere: ["GitHub", "Review atmosphere"],
  issue_scope: ["GitHub", "Issue scope"],
  explore_fit: ["GitHub", "Explore"],
  explore_plan: ["Explore", "Search plan"],
  explore_type: ["Explore", "New repository type"],
};

// A row of the Agents table. target: its issue or pull request (url on GitHub), or what else it works on. wait: why it
// waits ("" while it works). tokens: all its agent used (null: not an agent of ours). model: the Claude model it runs on.
type AgentRow = { key: string; type: string; target: string; url: string | null; job: Job | null; wait: string; vmSeconds: number; tokens: number | null; model: string; vm: string; activity: string };

// A chart's line. pieces: its drawing (SVG paths), broken where a value is missing. right: on the chart's right axis.
// stroke: dashed for a limit, dotted for a rate on the right axis, bar for bars instead of a line (Cost), behind every
// line. layer: lines are drawn by it, the highest in front.
type Line = { title: string; color: string; values: (number | null)[]; pieces: string[]; right: boolean; stroke: "solid" | "dashed" | "dotted" | "bar"; layer: number };

// vm: the VM whose page is open in the dialog (#/vms/<name>), or null. vmsTab: the Virtual machines tab open.
export default function Dashboard(props: { vm: string | null; vmsTab: "vms" | "images"; onOpenSettings: (section: string | null) => void; appButtons: ReactNode }) {
  const prs = useLive("prs");
  const jobs = useLive("jobs");
  const vms = useLive("vms");
  const imagesData = useLive("images");
  const agents = useLive("agents");
  const automation = useLive("automation");
  const inbox = useLive("inbox");
  const feedback = useLive("problems");
  const repos = useLive("repos");
  const automationLoaded = useLoaded("automation");
  const usage = useLive("tokens").slices;
  const activity = useLive("activity");
  const connected = useConnected();
  const now = useNow();
  const [rangeKey, setRangeKey] = useState("7d");
  // The period the mouse is on, in both charts.
  const [hovered, setHovered] = useState<number | null>(null);
  const [blockersOpen, setBlockersOpen] = useState(false);
  const [exploreOpen, setExploreOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  // The Repositories dialog's open tab ("": the cards), null while it is closed.
  const [reposTab, setReposTab] = useState<string | null>(null);
  const [creatingVM, setCreatingVM] = useState(false);
  // The Open PR limit as you type it, until the live topic has it (null: the saved one).
  const [limitText, setLimitText] = useState<string | null>(null);
  const openLimit = automation.max_open_prs;
  const limitSaved = openLimit === null ? "" : String(openLimit);
  // Saved: follow the topic again. (Setting state while rendering is React's pattern for state derived from props.)
  if (limitText !== null && limitText === limitSaved) {
    setLimitText(null);
  }

  // The Open PR limit is Automation's Open pull requests limit: the whole settings go back with only it changed.
  async function saveLimit() {
    if (limitText === null) {
      return;
    }
    if (limitText === limitSaved) {
      setLimitText(null);
      return;
    }
    try {
      await api<AutomationData>("/api/automation", { method: "PUT", body: { ...automation, max_open_prs: limitText === "" ? null : Number(limitText) } });
    } catch (err) {
      toast.error(`Could not save: ${err instanceof Error ? err.message : err}`);
      setLimitText(null);
    }
  }

  const range = RANGES.find((each) => each.key === rangeKey) ?? RANGES[2];
  const mine = prs.items.filter((pr) => pr.relation === "author");
  const open = mine.filter((pr) => pr.state === "open");

  // The periods start on the local clock (midnight, 6:00, ...); the last one holds now. The previous range is as long,
  // right before.
  const count = range.length / range.period;
  const offset = new Date().getTimezoneOffset() * MINUTE;
  const end = Math.floor((now - offset) / range.period) * range.period + offset + range.period;
  const start = end - range.length;
  const previousStart = start - range.length;
  const periods: {
    start: number;
    label: string;
    opened: number;
    merged: number;
    closed: number;
    open: number;
    rate: number | null;
    cost: number;
    byModel: Record<string, number>;
  }[] = [];
  for (let index = 0; index < count; index++) {
    const at = start + index * range.period;
    periods.push({
      start: at,
      label: new Date(at).toLocaleString("en", range.period < DAY ? DATE_TIME : DATE),
      opened: 0,
      merged: 0,
      closed: 0,
      open: 0,
      rate: null,
      cost: 0,
      byModel: {},
    });
  }

  // Each period's counts, and the range's and the previous one's: opened, merged, closed, and the days each merged one
  // took.
  let opened = 0;
  let merged = 0;
  let closed = 0;
  let openedBefore = 0;
  let mergedBefore = 0;
  let closedBefore = 0;
  const took: number[] = [];
  const tookBefore: number[] = [];
  for (const pr of mine) {
    const openedAt = new Date(pr.opened_at).getTime();
    const closedAt = pr.closed_at === null ? null : new Date(pr.closed_at).getTime();
    const openedIndex = Math.floor((openedAt - start) / range.period);
    if (openedIndex >= 0 && openedIndex < count) {
      periods[openedIndex].opened += 1;
      opened += 1;
    }
    // Open at the end of each period (now for the last one): opened by then, not closed or merged yet.
    for (const period of periods) {
      const until = Math.min(period.start + range.period, now);
      if (openedAt <= until && (pr.state === "open" || closedAt === null || closedAt > until)) {
        period.open += 1;
      }
    }
    if (openedAt >= previousStart && openedAt < start) {
      openedBefore += 1;
    }
    if (pr.state === "open" || closedAt === null) {
      continue;
    }
    const closedIndex = Math.floor((closedAt - start) / range.period);
    if (closedIndex >= 0 && closedIndex < count && pr.state === "merged") {
      periods[closedIndex].merged += 1;
      merged += 1;
      took.push((closedAt - openedAt) / DAY);
    }
    if (closedIndex >= 0 && closedIndex < count && pr.state === "closed") {
      periods[closedIndex].closed += 1;
      closed += 1;
    }
    if (closedAt >= previousStart && closedAt < start && pr.state === "merged") {
      mergedBefore += 1;
      tookBefore.push((closedAt - openedAt) / DAY);
    }
    if (closedAt >= previousStart && closedAt < start && pr.state === "closed") {
      closedBefore += 1;
    }
  }
  // Merge rate, 7-day average: at the end of each period (now for the last one).
  for (const period of periods) {
    const until = Math.min(period.start + range.period, now);
    let mergedWeek = 0;
    let closedWeek = 0;
    for (const pr of mine) {
      const closedAt = pr.closed_at === null ? null : new Date(pr.closed_at).getTime();
      if (pr.state === "open" || closedAt === null || closedAt <= until - 7 * DAY || closedAt > until) {
        continue;
      }
      if (pr.state === "merged") {
        mergedWeek += 1;
      } else {
        closedWeek += 1;
      }
    }
    period.rate = mergedWeek + closedWeek > 0 ? (mergedWeek / (mergedWeek + closedWeek)) * 100 : null;
  }

  // Tokens Claude runs used and what they cost, per model and stretch of time (at: its start): each stretch
  // added to the period it starts in.
  const models: string[] = [];
  let tokens = 0;
  let tokensBefore = 0;
  let cost = 0;
  let costBefore = 0;
  for (const each of usage) {
    const at = new Date(each.at).getTime();
    if (at >= previousStart && at < start) {
      tokensBefore += each.tokens;
      costBefore += each.cost_usd;
    }
    const index = Math.floor((at - start) / range.period);
    if (index < 0 || index >= count) {
      continue;
    }
    periods[index].cost += each.cost_usd;
    periods[index].byModel[each.model] = (periods[index].byModel[each.model] ?? 0) + each.tokens;
    tokens += each.tokens;
    cost += each.cost_usd;
    if (!models.includes(each.model)) {
      models.push(each.model);
    }
  }

  const rate = merged + closed > 0 ? Math.round((merged / (merged + closed)) * 100) : null;
  const rateBefore = mergedBefore + closedBefore > 0 ? Math.round((mergedBefore / (mergedBefore + closedBefore)) * 100) : null;
  took.sort((a, b) => a - b);
  tookBefore.sort((a, b) => a - b);
  let median: number | null = null;
  if (took.length > 0) {
    median = took.length % 2 === 1 ? took[(took.length - 1) / 2] : (took[took.length / 2 - 1] + took[took.length / 2]) / 2;
  }
  let medianBefore: number | null = null;
  if (tookBefore.length > 0) {
    medianBefore =
      tookBefore.length % 2 === 1
        ? tookBefore[(tookBefore.length - 1) / 2]
        : (tookBefore[tookBefore.length / 2 - 1] + tookBefore[tookBefore.length / 2]) / 2;
  }
  // "18 h" under a day, else "3.1 d".
  let medianText = "–";
  if (median !== null) {
    medianText = median < 1 ? `${Math.round(median * 24)} h` : `${median.toFixed(1)} d`;
  }
  let medianBeforeText = "–";
  if (medianBefore !== null) {
    medianBeforeText = medianBefore < 1 ? `${Math.round(medianBefore * 24)} h` : `${medianBefore.toFixed(1)} d`;
  }
  const medianChange = median !== null && medianBefore !== null ? Number((median - medianBefore).toFixed(1)) : null;
  // The first row's cards: each one big number or more (Tokens and cost: the cost above the tokens). change: from the
  // previous range (null when either has no number); better: which way is good ("": neither, it stays gray). width: the
  // characters the longest value takes, so the change after it stays put whatever the range.
  const numbers = [
    {
      title: "Opened",
      tab: "open",
      better: "up",
      rows: [
        {
          value: `${opened}`,
          width: 4,
          change: opened - openedBefore,
          changeText: `${Math.abs(opened - openedBefore)}`,
          was: `Previous ${range.title}: ${openedBefore}`,
        },
      ],
    },
    {
      title: "Merged",
      tab: "merged",
      better: "up",
      rows: [
        {
          value: `${merged}`,
          width: 4,
          change: merged - mergedBefore,
          changeText: `${Math.abs(merged - mergedBefore)}`,
          was: `Previous ${range.title}: ${mergedBefore}`,
        },
      ],
    },
    {
      title: "Closed",
      tab: "closed",
      better: "down",
      rows: [
        {
          value: `${closed}`,
          width: 4,
          change: closed - closedBefore,
          changeText: `${Math.abs(closed - closedBefore)}`,
          was: `Previous ${range.title}: ${closedBefore}`,
        },
      ],
    },
    {
      title: "Merge rate",
      tab: "closed",
      better: "up",
      rows: [
        {
          value: rate === null ? "–" : `${rate}%`,
          width: 4,
          change: rate !== null && rateBefore !== null ? rate - rateBefore : null,
          changeText: rate !== null && rateBefore !== null ? `${Math.abs(rate - rateBefore)}` : "",
          was: `Previous ${range.title}: ${rateBefore === null ? "–" : `${rateBefore}%`}`,
        },
      ],
    },
    {
      title: "Time to merge",
      tab: "merged",
      better: "down",
      rows: [
        {
          value: medianText,
          width: 6,
          change: medianChange,
          changeText: medianChange === null ? "" : `${Math.abs(medianChange).toFixed(1)} d`,
          was: `Previous ${range.title}: ${medianBeforeText}`,
        },
      ],
    },
    {
      title: "Tokens and cost",
      tab: null,
      better: "down",
      rows: [
        {
          value: USD.format(cost),
          width: 6,
          change: cost - costBefore,
          changeText: USD.format(Math.abs(cost - costBefore)),
          was: `Previous ${range.title}: ${USD.format(costBefore)}`,
        },
        {
          value: SHORT.format(tokens),
          width: 6,
          change: tokens - tokensBefore,
          changeText: SHORT.format(Math.abs(tokens - tokensBefore)),
          was: `Previous ${range.title}: ${SHORT.format(tokensBefore)}`,
        },
      ],
    },
  ];

  // Limits: what is used now against Automation's limits (null: none).
  const todayKey = new Date().toDateString();
  const openedToday = mine.filter((pr) => new Date(pr.opened_at).toDateString() === todayKey).length;
  const perRepo: Record<string, number> = {};
  let busiest = "";
  for (const pr of open) {
    perRepo[pr.repo] = (perRepo[pr.repo] ?? 0) + 1;
    if (busiest === "" || perRepo[pr.repo] > perRepo[busiest]) {
      busiest = pr.repo;
    }
  }
  const busy = agents.filter((agent) => agent.busy).length;
  let desktopsUsed = 0;
  let desktopsAll = 0;
  for (const vm of vms) {
    if (vm.status !== "running") {
      continue;
    }
    desktopsUsed += vm.desktops.filter((desktop) => desktop.holder !== null).length;
    desktopsAll += vm.max_desktops;
  }
  const limits = [
    { title: "Pull requests today", used: openedToday, limit: automation.max_prs_per_day, about: "" },
    { title: "Open pull requests", used: open.length, limit: automation.max_open_prs, about: "" },
    { title: "Per repository", used: busiest === "" ? 0 : perRepo[busiest], limit: automation.max_open_per_repo, about: busiest },
    { title: "Agents", used: busy, limit: automation.max_agents, about: "" },
    { title: "Desktops in use", used: desktopsUsed, limit: desktopsAll, about: "" },
  ];

  // Repositories: the repo list's, and those with a pull request of yours that aren't in it (they have cards too).
  const repoNames = repos.items.map((repo) => repo.full_name.toLowerCase());
  for (const pr of mine) {
    if (!repoNames.includes(pr.repo.toLowerCase())) {
      repoNames.push(pr.repo.toLowerCase());
    }
  }

  // Feedback: what is still open.
  const feedbackOpenCount = feedback.filter((item) => item.closed_at === null).length;

  // Blockers: the agents' approval requests still waiting for you.
  const blockers = inbox.filter((draft) => draft.kind === "approval" && draft.status === "pending").length;

  // Virtual machines' tabs. Each has its own address (App.tsx), so a link can open one: VMs is the Dashboard's own.
  const vmsTabs = (
    <Tabs
      value={props.vmsTab}
      onValueChange={(value) => {
        window.location.hash = value === "vms" ? "#/" : `#/vms?tab=${value}`;
      }}
    >
      <TabsList>
        <TabsTrigger value="vms" className="px-2.5">
          VMs
          <span className="text-xs text-muted-foreground tabular-nums">{vms.length}</span>
        </TabsTrigger>
        <TabsTrigger value="images" className="px-2.5">
          Images
          <span className="text-xs text-muted-foreground tabular-nums">{imagesData.images.length}</span>
        </TabsTrigger>
      </TabsList>
    </Tabs>
  );

  // Agents: everything doing something now, a row each (the module docstring). An agent's job is its working one, else its
  // oldest queued one, found in one pass over the jobs.
  const jobOf: Record<string, Job> = {};
  for (const job of jobs) {
    if (job.status !== "working" && job.status !== "queued") {
      continue;
    }
    const had = jobOf[job.agent];
    if (had === undefined || (had.status === "queued" && (job.status === "working" || job.created_at < had.created_at))) {
      jobOf[job.agent] = job;
    }
  }
  const agentRows: AgentRow[] = [];
  // Queued jobs whose agent isn't on anything yet: only counted.
  let queued = 0;
  for (const agent of agents) {
    if (agent.archived_at !== null) {
      continue;
    }
    const job = jobOf[agent.id];
    let wait = "";
    if (agent.waiting) {
      wait = "Waiting for a turn";
    }
    if (agent.place !== null && agent.place > 0) {
      wait = `Waiting for ${agent.vm}, #${agent.place} in line`;
    }
    if (agent.waiting_for_vm) {
      wait = "Waiting for a VM";
    }
    const active = agent.busy || wait !== "" || job?.status === "working";
    if (!active) {
      if (job !== undefined) {
        queued += 1;
      }
      continue;
    }
    // The closed PRs agent: one row for all the merged and closed PRs it reads.
    if (agent.role === "closed_prs") {
      const open = jobs.filter((each) => each.agent === agent.id && (each.status === "working" || each.status === "queued")).length;
      agentRows.push({ key: agent.id, type: "GitHub", target: `Closed PRs · ${open} PRs`, url: null, job: null, wait: wait, vmSeconds: 0, tokens: agent.tokens_used, model: agent.model, vm: "–", activity: agent.activity });
      continue;
    }
    let type = agent.role === "reviewer" ? "Review" : "Other";
    let target = "–";
    let url: string | null = null;
    if (job !== undefined) {
      type = JOB_TYPES[job.kind] ?? type;
      const [repo, number] = (job.issue ?? job.thread ?? "").split("#");
      if (number !== undefined) {
        target = `${repo} #${number}`;
        url = `https://github.com/${repo}/issues/${number}`;
      }
    }
    let vm = agent.vm ?? job?.vm ?? "–";
    if (agent.vm !== null && agent.desktop !== null) {
      vm += ` · ${agent.desktop}`;
    }
    agentRows.push({ key: agent.id, type: type, target: target, url: url, job: job ?? null, wait: wait, vmSeconds: job?.vm_seconds ?? 0, tokens: agent.tokens_used, model: agent.model, vm: vm, activity: agent.activity });
  }
  for (const name of activity.images) {
    agentRows.push({ key: `image:${name}`, type: "Image", target: name, url: null, job: null, wait: "", vmSeconds: 0, tokens: null, model: activity.models.image, vm: "–", activity: `Changing ${name}'s image.yaml` });
  }
  // The checks running now, a row each.
  for (const [what, count] of Object.entries(activity.checks)) {
    const [type, role] = CHECKS[what] ?? ["GitHub", what.replaceAll("_", " ")];
    for (let i = 0; i < count; i++) {
      agentRows.push({ key: `check:${what}:${i}`, type: type, target: role, url: null, job: null, wait: "", vmSeconds: 0, tokens: null, model: activity.models.checks, vm: "–", activity: "" });
    }
  }
  if (activity.fix_all !== null) {
    const fixAll = activity.fix_all;
    agentRows.push({
      key: "fix_all",
      type: "Fix all",
      target: `${fixAll.items} feedback items`,
      url: null,
      job: null,
      wait: "",
      vmSeconds: Math.max(0, (now - Date.parse(fixAll.started_at)) / 1000),
      tokens: null,
      model: activity.models.fix_all,
      vm: fixAll.vm,
      activity: `Fixing ${fixAll.items} feedback items in ${fixAll.vm}`,
    });
  }
  // Working ones first, the most VM time first; then the waiting ones.
  agentRows.sort((a, b) => (a.wait === "" ? 0 : 1) - (b.wait === "" ? 0 : 1) || b.vmSeconds - a.vmSeconds);
  const waitingRows = agentRows.filter((row) => row.wait !== "").length;
  const agentsDetail = [`${agentRows.length - waitingRows} working`, `${waitingRows} waiting`];
  if (queued > 0) {
    agentsDetail.push(`${queued} queued`);
  }

  // The Pull requests chart's y axis, a log scale: 0, then 1, 3, 10, 30, ... up to the first at or over the highest.
  let highest = 1;
  for (const period of periods) {
    highest = Math.max(highest, period.opened, period.merged, period.closed, period.open);
  }
  // The Open PR limit stays in view.
  if (openLimit !== null) {
    highest = Math.max(highest, openLimit);
  }
  const prTicks = [0, 1];
  while (prTicks[prTicks.length - 1] < highest) {
    const last = prTicks[prTicks.length - 1];
    prTicks.push(String(last).startsWith("1") ? last * 3 : (last / 3) * 10);
  }
  const prTop = prTicks[prTicks.length - 1];
  // The Tokens chart's y axis: 0 to a round number (1, 2 or 5 times a power of ten a step) at or over the highest, in at
  // most four equal steps.
  let tokenHighest = 1;
  for (const period of periods) {
    const values = Object.values(period.byModel);
    tokenHighest = Math.max(tokenHighest, ...values);
  }
  const power = Math.pow(10, Math.max(0, Math.floor(Math.log10(tokenHighest / 4))));
  const step = [power, 2 * power, 5 * power, 10 * power].find((each) => each * 4 >= tokenHighest) ?? 10 * power;
  const tokenTop = Math.ceil(tokenHighest / step) * step;
  const tokenTicks: number[] = [];
  for (let value = 0; value <= tokenTop; value += step) {
    tokenTicks.push(value);
  }
  // The cost axis on its right: the same, counted in cents so the steps stay whole numbers.
  let centsHighest = 1;
  for (const period of periods) {
    centsHighest = Math.max(centsHighest, Math.ceil(period.cost * 100));
  }
  const centsPower = Math.pow(10, Math.max(0, Math.floor(Math.log10(centsHighest / 4))));
  const centsStep = [centsPower, 2 * centsPower, 5 * centsPower, 10 * centsPower].find((each) => each * 4 >= centsHighest) ?? 10 * centsPower;
  const centsTop = Math.ceil(centsHighest / centsStep) * centsStep;
  const costTicks: number[] = [];
  for (let value = 0; value <= centsTop; value += centsStep) {
    costTicks.push(value / 100);
  }
  // The x axes: five labels evenly spread, the last one Now. Under a day, times only.
  const prAxis = [0, Math.round((count - 1) / 4), Math.round((count - 1) / 2), Math.round(((count - 1) * 3) / 4), count - 1].map((index) => ({
    index: index,
    text: index === count - 1 ? "Now" : new Date(periods[index].start).toLocaleString("en", range.length <= DAY ? TIME : DATE),
  }));
  // The tokens' lines: one per model, and Cost's bars behind them. None before the first tokens arrive.
  const tokenLines: Line[] = [];
  models.forEach((model, index) => {
    tokenLines.push({
      title: MODEL_NAMES[model] ?? model,
      color: TOKEN_COLORS[index % TOKEN_COLORS.length],
      values: periods.map((period) => period.byModel[model] ?? 0),
      pieces: [],
      right: false,
      stroke: "solid",
      layer: 1,
    });
  });
  if (usage.length > 0) {
    tokenLines.push({
      title: "Cost",
      color: "text-foreground/25",
      values: periods.map((period) => period.cost),
      pieces: [],
      right: true,
      stroke: "bar",
      layer: 0,
    });
  }
  // The pull requests' lines, and the Open PR limit when there is one.
  const prLines: Line[] = [
    { title: "Opened", color: OPENED, values: periods.map((period) => period.opened), pieces: [], right: false, stroke: "solid", layer: 4 },
    { title: "Merged", color: MERGED, values: periods.map((period) => period.merged), pieces: [], right: false, stroke: "solid", layer: 5 },
    { title: "Closed", color: CLOSED, values: periods.map((period) => period.closed), pieces: [], right: false, stroke: "solid", layer: 3 },
    { title: "Open", color: "text-sky-600 dark:text-sky-500", values: periods.map((period) => period.open), pieces: [], right: false, stroke: "solid", layer: 2 },
    { title: "Merge rate", color: "text-foreground/60", values: periods.map((period) => period.rate), pieces: [], right: true, stroke: "dotted", layer: 1 },
  ];
  if (openLimit !== null) {
    prLines.push({ title: "Open PR limit", color: "text-sky-600 dark:text-sky-500", values: periods.map(() => openLimit), pieces: [], right: false, stroke: "dashed", layer: 0 });
  }

  const percentTicks = [0, 25, 50, 75, 100];
  // A chart: its lines on the left axis (top, ticks, unit; log: a log scale, log(1 + value)), and those marked right on
  // the right axis (none without rightTicks; rightFormat writes its numbers). empty: what it says without lines.
  const charts: {
    key: string;
    title: string;
    tab: string | null;
    detail: string;
    top: number;
    ticks: number[];
    unit: string;
    log: boolean;
    rightTop: number;
    rightTicks: number[];
    rightFormat: (value: number) => string;
    labels: string[];
    axis: { index: number; text: string }[];
    lines: Line[];
    empty: string;
  }[] = [
    {
      key: "prs",
      title: "Pull requests",
      tab: "open",
      detail: range.per,
      top: prTop,
      ticks: prTicks,
      unit: "",
      log: true,
      rightTop: 100,
      rightTicks: percentTicks,
      rightFormat: (value) => `${Math.round(value)}%`,
      labels: periods.map((period) => period.label),
      axis: prAxis,
      lines: prLines,
      empty: "",
    },
    {
      key: "tokens",
      title: "Tokens and cost",
      tab: null,
      detail: range.per,
      top: tokenTop,
      ticks: tokenTicks,
      unit: "",
      log: false,
      rightTop: centsTop / 100,
      rightTicks: usage.length > 0 ? costTicks : [],
      rightFormat: (value) => USD.format(value),
      labels: periods.map((period) => period.label),
      axis: prAxis,
      lines: tokenLines,
      empty: "No tokens used.",
    },
  ];
  // Each line's points, at the middle of their column, in runs broken where a value is missing; each run a path. A
  // lone point is a dot. A run of three or more is a curve through its points: a cubic between each two, its
  // slope at a point Steffen's (0 at a peak or a dip, else no steeper than the gentler side allows), so it stays
  // between the two points' levels; at the ends, the slope that keeps the end segment's shape.
  for (const chart of charts) {
    for (const line of chart.lines) {
      const top = line.right ? chart.rightTop : chart.top;
      // Bars are boxes, not paths: drawn under the lines, below.
      if (line.stroke === "bar") {
        continue;
      }
      const runs: { x: number; y: number }[][] = [];
      let run: { x: number; y: number }[] = [];
      line.values.forEach((value, index) => {
        if (value === null) {
          if (run.length > 0) {
            runs.push(run);
          }
          run = [];
          return;
        }
        const share = chart.log && !line.right ? Math.log1p(value) / Math.log1p(top) : value / top;
        run.push({ x: ((index + 0.5) / line.values.length) * 100, y: 100 - Math.min(share, 1) * 100 });
      });
      if (run.length > 0) {
        runs.push(run);
      }
      for (const points of runs) {
        let path = `M${points[0].x.toFixed(2)},${points[0].y.toFixed(2)}`;
        if (points.length === 1) {
          line.pieces.push(`${path} L${points[0].x.toFixed(2)},${points[0].y.toFixed(2)}`);
          continue;
        }
        if (points.length === 2) {
          for (const point of points.slice(1)) {
            path += ` L${point.x.toFixed(2)},${point.y.toFixed(2)}`;
          }
          line.pieces.push(path);
          continue;
        }
        // Each segment's slope, then each point's.
        const slopes: number[] = [];
        for (let index = 0; index < points.length - 1; index++) {
          slopes.push((points[index + 1].y - points[index].y) / (points[index + 1].x - points[index].x));
        }
        const tangents: number[] = [];
        for (let index = 1; index < points.length - 1; index++) {
          const left = slopes[index - 1];
          const right = slopes[index];
          const width = points[index].x - points[index - 1].x;
          const next = points[index + 1].x - points[index].x;
          const average = (left * next + right * width) / (width + next);
          tangents[index] = (Math.sign(left) + Math.sign(right)) * Math.min(Math.abs(left), Math.abs(right), 0.5 * Math.abs(average));
        }
        tangents[0] = (3 * slopes[0] - tangents[1]) / 2;
        tangents[points.length - 1] = (3 * slopes[slopes.length - 1] - tangents[points.length - 2]) / 2;
        for (let index = 0; index < points.length - 1; index++) {
          const from = points[index];
          const to = points[index + 1];
          const third = (to.x - from.x) / 3;
          path += ` C${(from.x + third).toFixed(2)},${(from.y + third * tangents[index]).toFixed(2)}`;
          path += ` ${(to.x - third).toFixed(2)},${(to.y - third * tangents[index + 1]).toFixed(2)}`;
          path += ` ${to.x.toFixed(2)},${to.y.toFixed(2)}`;
        }
        line.pieces.push(path);
      }
    }
  }

  const th = "h-8 border-b px-3 text-left text-xs font-medium whitespace-nowrap text-muted-foreground";
  const td = "h-10 border-b px-3 whitespace-nowrap";

  // The two charts side by side: drawn the same way, only their data differs.
  const drawn = (
    <div className="grid grid-cols-2 gap-3 max-lg:grid-cols-1">
      {charts.map((chart) => {
        return (
          <div key={chart.key} className={WIDGET}>
            <div className={WIDGET_HEADER}>
              {chart.tab !== null && (
                <button type="button" className={TITLE} onClick={() => setReposTab(chart.tab)}>
                  {chart.title}
                </button>
              )}
              {chart.tab === null && <span className="truncate font-medium">{chart.title}</span>}
              {chart.key === "prs" && (
                <label className="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
                  Open PR limit
                  <input
                    type="text"
                    inputMode="numeric"
                    placeholder="–"
                    value={limitText ?? limitSaved}
                    disabled={!automationLoaded}
                    className="h-6 w-12 rounded-sm border bg-transparent px-1.5 text-right font-mono text-xs text-foreground tabular-nums outline-none placeholder:text-muted-foreground focus:border-ring"
                    onChange={(event) => {
                      // Only 1 to 999 goes in (or nothing: no limit); any other keystroke or paste is ignored.
                      if (/^([1-9][0-9]{0,2})?$/.test(event.target.value)) {
                        setLimitText(event.target.value);
                      }
                    }}
                    onBlur={saveLimit}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.currentTarget.blur();
                      }
                    }}
                  />
                </label>
              )}
              <span className={DETAIL}>{chart.detail}</span>
            </div>
            <div className="p-3">
              <div className="flex h-44 gap-2">
                <div className="relative w-9 shrink-0 text-right font-mono text-xs text-muted-foreground tabular-nums">
                  {chart.ticks.map((value) => (
                    <span
                      key={value}
                      className="absolute right-0 translate-y-1/2"
                      style={{ bottom: `${(chart.log ? Math.log1p(value) / Math.log1p(chart.top) : value / chart.top) * 100}%` }}
                    >
                      {SHORT.format(value)}
                      {chart.unit}
                    </span>
                  ))}
                </div>
                <div className="relative flex-1">
                  {chart.ticks.map((value) => (
                    <div
                      key={value}
                      className={cn("absolute inset-x-0 border-t", value > 0 && "border-dashed border-border/60")}
                      style={{ bottom: `${(chart.log ? Math.log1p(value) / Math.log1p(chart.top) : value / chart.top) * 100}%` }}
                    />
                  ))}
                  {/* Bars, behind every line: one per period, the middle 90% of its column, rounded on top. */}
                  {chart.lines
                    .filter((line) => line.stroke === "bar")
                    .map((line) => (
                      <div key={line.title} className={cn("pointer-events-none absolute inset-0", line.color)}>
                        {line.values.map((value, index) => (
                          <div
                            key={index}
                            className="absolute bottom-0 rounded-t-[3px] bg-current"
                            style={{
                              left: `${((index + 0.05) / line.values.length) * 100}%`,
                              width: `${(0.9 / line.values.length) * 100}%`,
                              height: `${Math.min((value ?? 0) / (line.right ? chart.rightTop : chart.top), 1) * 100}%`,
                            }}
                          />
                        ))}
                      </div>
                    ))}
                  {chart.lines
                    .filter((line) => line.stroke !== "bar")
                    .sort((a, b) => a.layer - b.layer)
                    .map((line) => (
                      <svg
                        key={line.title}
                        viewBox="0 0 100 100"
                        preserveAspectRatio="none"
                        className={cn("pointer-events-none absolute inset-0 size-full overflow-visible", line.color)}
                      >
                        {line.pieces.map((piece, index) => (
                          <path
                            key={`edge-${index}`}
                            d={piece}
                            fill="none"
                            className="stroke-card"
                            strokeWidth="4"
                            strokeLinejoin="round"
                            strokeLinecap="round"
                            vectorEffect="non-scaling-stroke"
                          />
                        ))}
                        {line.pieces.map((piece, index) => (
                          <path
                            key={index}
                            d={piece}
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="1.5"
                            strokeDasharray={line.stroke === "dashed" ? "4 3" : line.stroke === "dotted" ? "1 3" : undefined}
                            strokeLinejoin="round"
                            strokeLinecap="round"
                            vectorEffect="non-scaling-stroke"
                          />
                        ))}
                      </svg>
                    ))}
                  {chart.lines.length === 0 && <div className="absolute inset-0 flex items-center justify-center text-muted-foreground">{chart.empty}</div>}
                  <div className="absolute inset-0 flex" onMouseLeave={() => setHovered(null)}>
                    {chart.labels.map((_, index) => (
                      <div key={index} className="relative h-full min-w-0 flex-1" onMouseEnter={() => setHovered(index)}>
                        {hovered === index && <div className="absolute inset-y-0 left-1/2 w-px bg-foreground/40" />}
                      </div>
                    ))}
                  </div>
                  {hovered !== null && chart.lines.length > 0 && (
                    <div
                      className={cn(
                        "pointer-events-none absolute top-0 z-10 w-44 rounded-md border bg-popover px-2.5 py-2 text-xs shadow-overlay",
                        hovered < chart.labels.length / 2 ? "ml-3" : "-ml-3 -translate-x-full",
                      )}
                      style={{ left: `${((hovered + 0.5) / chart.labels.length) * 100}%` }}
                    >
                      <div className="font-medium">{chart.labels[hovered]}</div>
                      {chart.lines.map((line) => (
                        <div key={line.title} className="mt-1 flex items-center gap-1.5">
                          <span className={cn("size-2 shrink-0 rounded-full bg-current", line.color)} />
                          <span className="truncate text-muted-foreground">{line.title}</span>
                          <span className="ml-auto font-mono tabular-nums">
                            {line.values[hovered] === null && "–"}
                            {line.values[hovered] !== null && line.right && chart.rightFormat(line.values[hovered] ?? 0)}
                            {line.values[hovered] !== null && !line.right && `${SHORT.format(Math.round(line.values[hovered] ?? 0))}${chart.unit}`}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                {chart.rightTicks.length > 0 && (
                  <div className="relative w-12 shrink-0 font-mono text-xs text-muted-foreground tabular-nums">
                    {chart.rightTicks.map((value) => (
                      <span key={value} className="absolute left-0 translate-y-1/2" style={{ bottom: `${(value / chart.rightTop) * 100}%` }}>
                        {chart.rightFormat(value)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              {/* Under each labeled column; the first and last kept inside the chart's edges. */}
              <div className={cn("relative mt-1.5 ml-11 h-4 text-xs text-muted-foreground tabular-nums", chart.rightTicks.length > 0 && "mr-14")}>
                {chart.axis.map((each) => (
                  <span
                    key={each.index}
                    className={cn("absolute whitespace-nowrap", each.index > 0 && each.index < chart.labels.length - 1 && "-translate-x-1/2")}
                    style={
                      each.index === 0
                        ? { left: 0 }
                        : each.index === chart.labels.length - 1
                          ? { right: 0 }
                          : { left: `${((each.index + 0.5) / chart.labels.length) * 100}%` }
                    }
                  >
                    {each.text}
                  </span>
                ))}
              </div>
              <div className="mt-2 ml-11 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                {chart.lines.map((line) => (
                  <span key={line.title} className="flex items-center gap-1.5">
                    <span className={cn("h-0.5 w-3 rounded-full bg-current", line.color, line.stroke === "dashed" && "h-0 rounded-none border-t-2 border-dashed border-current bg-transparent", line.stroke === "dotted" && "h-0 rounded-none border-t-2 border-dotted border-current bg-transparent", line.stroke === "bar" && "h-2.5 w-2.5 rounded-[2px]")} />
                    {line.title}
                  </span>
                ))}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex min-h-9 shrink-0 items-center gap-3 border-b px-3 py-1">
        <span className="font-medium">Dashboard</span>
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground tabular-nums">
          <span className={cn("size-1.5 rounded-full", connected ? "bg-ok" : "bg-destructive")} />
          <span className={cn(!connected && "text-destructive")}>{connected ? "Live" : "Offline"}</span>
          {prs.checked_at !== null && <span>· Updated {new Date(prs.checked_at).toLocaleTimeString("en", CLOCK)}</span>}
        </span>
        <div className="ml-auto flex overflow-hidden rounded-sm border">
          {RANGES.map((each) => (
            <button
              key={each.key}
              type="button"
              className={cn(
                "h-7 border-l px-2.5 text-xs font-medium text-muted-foreground tabular-nums first:border-l-0 hover-line",
                rangeKey === each.key && "bg-selected text-foreground",
              )}
              onClick={() => setRangeKey(each.key)}
            >
              {each.title}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1">{props.appButtons}</div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto bg-muted/40">
        <div className="space-y-3 p-3">
          <div className="grid grid-cols-6 gap-3 max-2xl:grid-cols-3">
            {numbers.map((number) => (
              <div key={number.title} className={WIDGET}>
                <div className={WIDGET_HEADER}>
                  {number.tab !== null && (
                    <button type="button" className={TITLE} onClick={() => setReposTab(number.tab)}>
                      {number.title}
                    </button>
                  )}
                  {number.tab === null && <span className="truncate font-medium">{number.title}</span>}
                  <span className={DETAIL}>{range.title}</span>
                </div>
                <div className="flex flex-1 flex-col justify-end gap-2 px-3 pt-4 pb-3">
                  {number.rows.map((row, index) => (
                    <div key={index} className="flex items-end gap-x-3">
                      <span className="font-mono text-3xl font-light whitespace-nowrap tabular-nums" style={{ minWidth: `${row.width}ch` }}>
                        {row.value}
                      </span>
                      {row.change !== null && (
                        <span
                          title={row.was}
                          className={cn(
                            "mb-1 shrink-0 font-mono text-sm whitespace-nowrap tabular-nums",
                            row.change === 0 || number.better === ""
                              ? "text-muted-foreground"
                              : (row.change > 0) === (number.better === "up")
                                ? "text-ok"
                                : "text-destructive",
                          )}
                        >
                          {row.change > 0 ? "▲ " : row.change < 0 ? "▼ " : ""}
                          {row.changeText}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {drawn}

          <div className="grid grid-cols-7 gap-3 max-xl:grid-cols-5">
            <div className={cn(WIDGET, "col-span-2 max-xl:col-span-5")}>
              <div className={WIDGET_HEADER}>
                <button type="button" className={TITLE} onClick={() => props.onOpenSettings("automation")}>
                  Limits
                </button>
              </div>
              <div className="grid flex-1 content-center gap-x-6 gap-y-1.5 px-3 py-2 text-xs max-xl:grid-cols-3">
                {limits.map((each) => {
                  const full = each.limit !== null && each.limit > 0 ? each.used / each.limit : 0;
                  return (
                    <div key={each.title} className="flex min-w-0 items-center gap-2" title={each.about}>
                      <span className="w-32 shrink-0 truncate">{each.title}</span>
                      {each.limit !== null && (
                        <div className="h-1 min-w-0 flex-1 overflow-hidden rounded-full bg-muted">
                          <div className={cn("h-full rounded-full", full >= 0.85 ? "bg-warn" : "bg-foreground/40")} style={{ width: `${Math.min(full, 1) * 100}%` }} />
                        </div>
                      )}
                      {each.limit === null && <span className="min-w-0 flex-1 text-muted-foreground">No limit</span>}
                      <span className={cn("shrink-0 font-mono tabular-nums", full >= 0.85 && "text-warn")}>
                        {each.used}
                        {each.limit !== null && ` / ${each.limit}`}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
            <button type="button" className={cn(WIDGET, "text-left hover-line")} onClick={() => setReposTab("")}>
              <div className={WIDGET_HEADER}>
                <span className="truncate font-medium">Repositories</span>
              </div>
              <div className="flex flex-1 flex-col justify-end px-3 pt-4 pb-3">
                <span className="font-mono text-3xl font-light tabular-nums">{repoNames.length}</span>
              </div>
            </button>
            <button type="button" className={cn(WIDGET, "text-left hover-line")} onClick={() => setExploreOpen(true)}>
              <div className={WIDGET_HEADER}>
                <span className="truncate font-medium">Explore</span>
              </div>
              <div className="flex flex-1 flex-col justify-end px-3 pt-4 pb-3">
                <span className="font-mono text-3xl font-light">{automation.add_repos ? "On" : "Off"}</span>
              </div>
            </button>
            <button type="button" className={cn(WIDGET, "text-left hover-line")} onClick={() => setBlockersOpen(true)}>
              <div className={WIDGET_HEADER}>
                <span className="truncate font-medium">Blockers</span>
              </div>
              <div className="flex flex-1 flex-col justify-end px-3 pt-4 pb-3">
                <span className={cn("font-mono text-3xl font-light tabular-nums", blockers > 0 && "text-warn")}>{blockers}</span>
              </div>
            </button>
            <button type="button" className={cn(WIDGET, "text-left hover-line")} onClick={() => setFeedbackOpen(true)}>
              <div className={WIDGET_HEADER}>
                <span className="truncate font-medium">Feedback</span>
                <span className={DETAIL}>Open</span>
              </div>
              <div className="flex flex-1 flex-col justify-end px-3 pt-4 pb-3">
                <span className="font-mono text-3xl font-light tabular-nums">{feedbackOpenCount}</span>
              </div>
            </button>
            <button type="button" className={cn(WIDGET, "text-left hover-line")} onClick={() => props.onOpenSettings(null)}>
              <div className={WIDGET_HEADER}>
                <span className="truncate font-medium">Settings</span>
              </div>
              <div className="flex flex-1 flex-col justify-end px-3 pt-4 pb-3">
                <Settings className="size-8 stroke-[1.5] text-muted-foreground" />
              </div>
            </button>
          </div>

          {/* VMs and Images share one cell, the other one hidden, so the box is as tall on both tabs: the taller of the
              two. Images brings its own header row, with these tabs in it. */}
          <div className={cn(WIDGET, "grid")}>
            <div className={cn("col-start-1 row-start-1 min-w-0", props.vmsTab !== "vms" && "invisible")}>
              <div className={WIDGET_HEADER}>
                {vmsTabs}
                <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                  {vms.filter((vm) => vm.status === "running").length} of {vms.length} running
                </span>
                <Button size="sm" className="ml-auto" onClick={() => setCreatingVM(true)}>
                  <Plus /> New VM
                </Button>
              </div>
              {vms.length === 0 && <div className="p-3 text-muted-foreground">No VMs yet.</div>}
              <div className="[&>div:last-child]:border-b-0">
                <VMList />
              </div>
            </div>
            <div className={cn("col-start-1 row-start-1 min-w-0", props.vmsTab !== "images" && "invisible")}>
              <Images tabs={vmsTabs} />
            </div>
          </div>

          <div className={WIDGET}>
            <div className={WIDGET_HEADER}>
              <span className="truncate font-medium">Agents</span>
              <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{agentsDetail.join(" · ")}</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px]">
                <thead>
                  <tr>
                    <th className={th}>Type</th>
                    <th className={th}>Issue or pull request</th>
                    <th className={th}>Step</th>
                    <th className={cn(th, "text-right")}>VM time</th>
                    <th className={cn(th, "text-right")}>Tokens</th>
                    <th className={th}>Model</th>
                    <th className={th}>VM</th>
                  </tr>
                </thead>
                <tbody className="[&>tr:last-child>td]:border-b-0">
                  {agentRows.length === 0 && (
                    <tr>
                      <td colSpan={7} className={cn(td, "text-muted-foreground")}>
                        No agent is working.
                      </td>
                    </tr>
                  )}
                  {agentRows.map((row) => {
                    // "12m", or "2h 15m" from an hour; none for what has no VM time.
                    const vmMinutes = Math.floor(row.vmSeconds / 60);
                    let vmTime = vmMinutes < 60 ? `${vmMinutes}m` : `${Math.floor(vmMinutes / 60)}h ${vmMinutes % 60}m`;
                    if (row.job === null && row.key !== "fix_all") {
                      vmTime = "–";
                    }
                    return (
                      // What it is doing right now, on hover.
                      <tr key={row.key} className="hover:bg-accent/40" title={row.activity || undefined}>
                        <td className={cn(td, "text-muted-foreground")}>{row.type}</td>
                        <td className={cn(td, "max-w-96 truncate")}>
                          {row.url === null && row.target}
                          {row.url !== null && (
                            <a href={row.url} target="_blank" rel="noreferrer" className="hover:underline">
                              {row.target.split(" #")[0]} <span className="font-mono tabular-nums">#{row.target.split(" #")[1]}</span>
                            </a>
                          )}
                        </td>
                        <td className={td}>
                          {row.wait !== "" && <span className="text-xs text-muted-foreground">{row.wait}</span>}
                          {row.wait === "" && row.job !== null && <JobProgressBar job={row.job} />}
                          {row.wait === "" && row.job === null && <span className="text-muted-foreground">–</span>}
                        </td>
                        <td className={cn(td, "text-right font-mono text-xs tabular-nums")}>{vmTime}</td>
                        <td className={cn(td, "text-right font-mono text-xs tabular-nums")}>
                          {row.tokens === null ? "–" : `${(row.tokens / 1_000_000).toFixed(1)}M`}
                        </td>
                        <td className={cn(td, "text-xs text-muted-foreground")}>{row.model === "" ? "–" : (MODEL_NAMES[row.model] ?? row.model)}</td>
                        <td className={cn(td, "font-mono text-xs text-muted-foreground tabular-nums")}>{row.vm}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
      <Dialog
        open={reposTab !== null}
        onOpenChange={(open) => {
          if (!open) {
            setReposTab(null);
          }
        }}
      >
        <DialogContent className="flex h-[90vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-[95vw]" aria-describedby={undefined}>
          <DialogTitle className="sr-only">Repositories</DialogTitle>
          <div className="min-h-0 flex-1">
            <RepositoryCards state={reposTab ?? ""} onState={setReposTab} />
          </div>
        </DialogContent>
      </Dialog>
      <ExploreDialog open={exploreOpen} onOpenChange={setExploreOpen} />
      <FeedbackDialog open={feedbackOpen} onOpenChange={setFeedbackOpen} />
      <BlockersDialog open={blockersOpen} onOpenChange={setBlockersOpen} />
      <NewVMDialog open={creatingVM} onOpenChange={setCreatingVM} />
      {/* The close button sits in the VM page's header row, right of its tabs (VMPage.tsx leaves room for it). */}
      <Dialog
        open={props.vm !== null}
        onOpenChange={(open) => {
          if (!open) {
            window.location.hash = "#/";
          }
        }}
      >
        <DialogContent className="flex h-[90vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-[95vw]" aria-describedby={undefined}>
          <DialogTitle className="sr-only">{props.vm}</DialogTitle>
          {props.vm !== null && <VMPage name={props.vm} />}
        </DialogContent>
      </Dialog>
    </div>
  );
}
