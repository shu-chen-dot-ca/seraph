/*
The Dashboard (#/), the page the app opens on, display only. On top, its name, Live (or Offline in red while the live
feed is down) with the time your pull requests were last read, and the range every pull request number and chart
follows: 1 hour, 1 day, 7, 30 or 90 days (kept while the page is open). A range is cut into equal periods that start on
the clock (5 minutes for an hour, an hour for a day, 6 hours for 7 days, else a day); the last one is the one now. Every
widget has the same frame: a header with its title, which opens its page (Tokens has none), and on the right a detail.
Smooth, left of the range (on at first, kept while the page is open), draws every line as a curve through its points
instead of straight lines between them. Every point stays at its real value; between two points the curve never goes
past either one's level (a monotone cubic curve, Steffen's), so it shows no peak or dip that isn't in the numbers.
Under the top:
- Opened, Merged, Closed, Merge rate, Time to merge (the median from opened to merged) and Tokens (all the agents used):
  a big number, with the change from the previous range of the same length, green when it is good, red when it is bad
  (Tokens' stays gray). The previous one on hover.
- Limits: the Automation page's limits against what is used now, amber from 85%: pull requests opened today, open pull
  requests, the most open in one repository, agents working, and desktops in use of all the running VMs may have.
- Pull requests: opened, merged and closed per period, as three lines in GitHub's colors; Open, the pull requests still
  open at the end of each period (now for the last one), in blue, all on a log scale (0, 1, 3, 10, 30, ...: a count's
  height is log(1 + count), so 0 sits at the bottom); and Merge rate: the 7-day average at the end of each period
  (merged of merged and closed in the 7 days before), dashed, on its own 0-100% axis on the right. Back to front:
  Merge rate, Open, Closed, Opened, Merged.
- Tokens: the tokens every Claude run used per period (input, cache written, cache read and output, from the usage log:
  github_searcher/token_usage.py), a line per model (Model, the default) or per kind of work (Work), picked in its
  header, and Total in front of them. Models by their names (Opus 5.5), kinds of work in plain words; Agents is the
  agents' work from before the log, when its kind wasn't kept.
  These two share one time axis: hovering a period in one marks it in both, with its numbers.
- In progress: the fix_issue and follow_up jobs working now, longest on its step first: Issue or pull request (opens it
  on GitHub), Step, On step, Agent (opens its chat), VM and desktop. The header counts working and queued, and says
  Safe to shut down while no agent is busy (nothing otherwise).
- CPU and Memory: a line per running VM over the last minute, the only VM history the live feed has (its detail says
  so), as a share of the VM's CPUs and of its memory. Hovering a second marks it in both.
Charts keep fixed heights; a line breaks where there is no number. Lines are drawn back to front by their layer, each
with a thin edge in the card's color, so where two cross the one in front clearly covers the one behind. Big numbers are short: 1.2K, 3.4M.
*/

import { useState } from "react";

import { JobProgressBar, since, useNow } from "@/components/ui/job-progress";
import { useConnected, useLive } from "@/live";
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
const SAMPLES = 60;
// "Nov 18", "Nov 18, 14:05", "14:05" and "14:32:05"
const DATE: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
const DATE_TIME: Intl.DateTimeFormatOptions = { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" };
const TIME: Intl.DateTimeFormatOptions = { hour: "2-digit", minute: "2-digit", hourCycle: "h23" };
const CLOCK: Intl.DateTimeFormatOptions = { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" };
// 1234 → "1.2K", 3400000 → "3.4M"
const SHORT = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });
// GitHub's open green, merged purple and closed red: Tailwind's 600 (500 when dark) with 20% less saturation.
const OPENED = "text-[oklch(62.7%_0.155_149.214)] dark:text-[oklch(72.3%_0.175_149.579)]";
const MERGED = "text-[oklch(55.8%_0.23_302.321)] dark:text-[oklch(62.7%_0.212_303.9)]";
const CLOSED = "text-[oklch(57.7%_0.196_27.325)] dark:text-[oklch(63.7%_0.19_25.331)]";
// A color per running VM, in the VM list's order, and per model or kind of work, in the order they first show up.
const VM_COLORS = ["text-sky-500", "text-violet-500", "text-teal-500", "text-orange-500", "text-pink-500", "text-lime-500"];
const TOKEN_COLORS = ["text-sky-500", "text-amber-500", "text-teal-500", "text-pink-500", "text-lime-500", "text-violet-500", "text-orange-500", "text-rose-500"];
// The Tokens chart's names: models (others as they are) and kinds of work (github_searcher/claude_models.py).
const MODEL_NAMES: Record<string, string> = {
  "claude-fable-5-2": "Fable 5.2",
  "claude-opus-5-5": "Opus 5.5",
  "claude-sonnet-5-5": "Sonnet 5.5",
  "claude-haiku-5-5": "Haiku 5.5",
};
const WORK_NAMES: Record<string, string> = {
  fix_issue: "Fixing issues",
  follow_up: "Follow-ups",
  review: "Reviews",
  chat: "Chat",
  task: "Other jobs",
  judgment: "Judgments",
  explore: "Explore",
  explore_reader: "Explore readers",
  image: "Images",
  fix_problems: "Fix problems",
  agent: "Agents",
};
const WIDGET = "flex min-w-0 flex-col rounded-sm border bg-card";
const WIDGET_HEADER = "flex h-9 shrink-0 items-center gap-3 border-b px-3";
const TITLE = "truncate font-medium hover:underline";
const DETAIL = "ml-auto shrink-0 text-xs text-muted-foreground tabular-nums";

// A chart's line. pieces: its drawing (SVG paths), broken where a value is missing. right: on the chart's right axis,
// dashed. layer: lines are drawn by it, the highest in front.
type Line = { title: string; color: string; values: (number | null)[]; pieces: string[]; right: boolean; layer: number };

export default function Dashboard() {
  const prs = useLive("prs");
  const jobs = useLive("jobs");
  const vms = useLive("vms");
  const agents = useLive("agents");
  const automation = useLive("automation");
  const usage = useLive("tokens").slices;
  const connected = useConnected();
  const now = useNow();
  const [rangeKey, setRangeKey] = useState("7d");
  const [smooth, setSmooth] = useState(true);
  // The Tokens chart's lines: per "model" or per "work".
  const [tokensBy, setTokensBy] = useState("model");
  // What the mouse is on, and in which charts: a period ("prs") or a VM second ("vms").
  const [hovered, setHovered] = useState<{ group: string; index: number } | null>(null);

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
    tokens: number;
    byModel: Record<string, number>;
    byWork: Record<string, number>;
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
      tokens: 0,
      byModel: {},
      byWork: {},
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

  // Tokens Claude runs used, per model, kind of work and stretch of time (at: its start): each stretch added to the period
  // it starts in.
  const models: string[] = [];
  const works: string[] = [];
  let tokens = 0;
  let tokensBefore = 0;
  for (const each of usage) {
    const at = new Date(each.at).getTime();
    if (at >= previousStart && at < start) {
      tokensBefore += each.tokens;
    }
    const index = Math.floor((at - start) / range.period);
    if (index < 0 || index >= count) {
      continue;
    }
    periods[index].tokens += each.tokens;
    periods[index].byModel[each.model] = (periods[index].byModel[each.model] ?? 0) + each.tokens;
    periods[index].byWork[each.work] = (periods[index].byWork[each.work] ?? 0) + each.tokens;
    tokens += each.tokens;
    if (!models.includes(each.model)) {
      models.push(each.model);
    }
    if (!works.includes(each.work)) {
      works.push(each.work);
    }
  }

  // The numbers. change: from the previous range (null when either has no number); better: which way is good.
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
  const numbers = [
    {
      title: "Opened",
      href: "#/pulls?state=open",
      value: `${opened}`,
      change: opened - openedBefore,
      changeText: `${Math.abs(opened - openedBefore)}`,
      better: "up",
      was: `Previous ${range.title}: ${openedBefore}`,
    },
    {
      title: "Merged",
      href: "#/pulls?state=merged",
      value: `${merged}`,
      change: merged - mergedBefore,
      changeText: `${Math.abs(merged - mergedBefore)}`,
      better: "up",
      was: `Previous ${range.title}: ${mergedBefore}`,
    },
    {
      title: "Closed",
      href: "#/pulls?state=closed",
      value: `${closed}`,
      change: closed - closedBefore,
      changeText: `${Math.abs(closed - closedBefore)}`,
      better: "down",
      was: `Previous ${range.title}: ${closedBefore}`,
    },
    {
      title: "Merge rate",
      href: "#/pulls?state=closed",
      value: rate === null ? "–" : `${rate}%`,
      change: rate !== null && rateBefore !== null ? rate - rateBefore : null,
      changeText: rate !== null && rateBefore !== null ? `${Math.abs(rate - rateBefore)}` : "",
      better: "up",
      was: `Previous ${range.title}: ${rateBefore === null ? "–" : `${rateBefore}%`}`,
    },
    {
      title: "Time to merge",
      href: "#/pulls?state=merged",
      value: medianText,
      change: medianChange,
      changeText: medianChange === null ? "" : `${Math.abs(medianChange).toFixed(1)} d`,
      better: "down",
      was: `Previous ${range.title}: ${medianBeforeText}`,
    },
    {
      title: "Tokens",
      href: "",
      value: SHORT.format(tokens),
      change: tokens - tokensBefore,
      changeText: SHORT.format(Math.abs(tokens - tokensBefore)),
      better: "",
      was: `Previous ${range.title}: ${SHORT.format(tokensBefore)}`,
    },
  ];

  // Limits: what is used now against the Automation page's limits (null: none).
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

  // In progress: the jobs agents work on now, longest on its step first.
  const agentById: Record<string, (typeof agents)[number]> = {};
  for (const agent of agents) {
    agentById[agent.id] = agent;
  }
  const agentJobs = jobs.filter((job) => job.kind === "fix_issue" || job.kind === "follow_up");
  const working = agentJobs.filter((job) => job.status === "working");
  working.sort((a, b) => (a.step_at ?? a.updated_at).localeCompare(b.step_at ?? b.updated_at));
  const queued = agentJobs.filter((job) => job.status === "queued").length;

  // The Pull requests chart's y axis, a log scale: 0, then 1, 3, 10, 30, ... up to the first at or over the highest.
  let highest = 1;
  for (const period of periods) {
    highest = Math.max(highest, period.opened, period.merged, period.closed, period.open);
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
    tokenHighest = Math.max(tokenHighest, period.tokens);
  }
  const power = Math.pow(10, Math.max(0, Math.floor(Math.log10(tokenHighest / 4))));
  const step = [power, 2 * power, 5 * power, 10 * power].find((each) => each * 4 >= tokenHighest) ?? 10 * power;
  const tokenTop = Math.ceil(tokenHighest / step) * step;
  const tokenTicks: number[] = [];
  for (let value = 0; value <= tokenTop; value += step) {
    tokenTicks.push(value);
  }
  // The x axes: five labels evenly spread, the last one Now. Under a day, times only.
  const prAxis = [0, Math.round((count - 1) / 4), Math.round((count - 1) / 2), Math.round(((count - 1) * 3) / 4), count - 1].map((index) => ({
    index: index,
    text: index === count - 1 ? "Now" : new Date(periods[index].start).toLocaleString("en", range.length <= DAY ? TIME : DATE),
  }));
  const vmLabels: string[] = [];
  for (let index = 0; index < SAMPLES; index++) {
    vmLabels.push(index === SAMPLES - 1 ? "Now" : `${SAMPLES - 1 - index} s ago`);
  }
  const vmAxis = [
    { index: 0, text: "1 min ago" },
    { index: SAMPLES / 2 - 1, text: "30 s ago" },
    { index: SAMPLES - 1, text: "Now" },
  ];

  // The VMs' lines: each running VM's last minute, the newest sample at the right edge.
  const cpuLines: Line[] = [];
  const memoryLines: Line[] = [];
  vms
    .filter((vm) => vm.status === "running")
    .forEach((vm, index) => {
      const cpu: (number | null)[] = [];
      const memory: (number | null)[] = [];
      for (let missing = vm.samples.length; missing < SAMPLES; missing++) {
        cpu.push(null);
        memory.push(null);
      }
      for (const sample of vm.samples.slice(-SAMPLES)) {
        cpu.push(sample.cpu_percent);
        memory.push(sample.memory_used_gb === null ? null : (sample.memory_used_gb / vm.memory_gb) * 100);
      }
      const color = VM_COLORS[index % VM_COLORS.length];
      cpuLines.push({ title: vm.name, color: color, values: cpu, pieces: [], right: false, layer: 0 });
      memoryLines.push({ title: vm.name, color: color, values: memory, pieces: [], right: false, layer: 0 });
    });
  // The tokens' lines: Total, then a line per model or per kind of work. None before the first tokens arrive.
  const tokenLines: Line[] = [];
  if (usage.length > 0) {
    tokenLines.push({ title: "Total", color: "text-foreground/70", values: periods.map((period) => period.tokens), pieces: [], right: false, layer: 1 });
  }
  if (tokensBy === "model") {
    models.forEach((model, index) => {
      tokenLines.push({
        title: MODEL_NAMES[model] ?? model,
        color: TOKEN_COLORS[index % TOKEN_COLORS.length],
        values: periods.map((period) => period.byModel[model] ?? 0),
        pieces: [],
        right: false,
        layer: 0,
      });
    });
  }
  if (tokensBy === "work") {
    works.forEach((work, index) => {
      tokenLines.push({
        title: WORK_NAMES[work] ?? work,
        color: TOKEN_COLORS[index % TOKEN_COLORS.length],
        values: periods.map((period) => period.byWork[work] ?? 0),
        pieces: [],
        right: false,
        layer: 0,
      });
    });
  }

  const percentTicks = [0, 25, 50, 75, 100];
  // A chart: its lines on the left axis (top, ticks, unit; log: a log scale, log(1 + value)), and those marked right on
  // the right axis (none without rightTicks). empty: what it says without lines.
  const charts: {
    key: string;
    group: string;
    title: string;
    href: string;
    detail: string;
    top: number;
    ticks: number[];
    unit: string;
    log: boolean;
    rightTop: number;
    rightTicks: number[];
    rightUnit: string;
    labels: string[];
    axis: { index: number; text: string }[];
    lines: Line[];
    empty: string;
  }[] = [
    {
      key: "prs",
      group: "prs",
      title: "Pull requests",
      href: "#/pulls",
      detail: range.per,
      top: prTop,
      ticks: prTicks,
      unit: "",
      log: true,
      rightTop: 100,
      rightTicks: percentTicks,
      rightUnit: "%",
      labels: periods.map((period) => period.label),
      axis: prAxis,
      lines: [
        { title: "Opened", color: OPENED, values: periods.map((period) => period.opened), pieces: [], right: false, layer: 3 },
        { title: "Merged", color: MERGED, values: periods.map((period) => period.merged), pieces: [], right: false, layer: 4 },
        { title: "Closed", color: CLOSED, values: periods.map((period) => period.closed), pieces: [], right: false, layer: 2 },
        { title: "Open", color: "text-sky-600 dark:text-sky-500", values: periods.map((period) => period.open), pieces: [], right: false, layer: 1 },
        { title: "Merge rate", color: "text-foreground/60", values: periods.map((period) => period.rate), pieces: [], right: true, layer: 0 },
      ],
      empty: "",
    },
    {
      key: "tokens",
      group: "prs",
      title: "Tokens",
      href: "",
      detail: range.per,
      top: tokenTop,
      ticks: tokenTicks,
      unit: "",
      log: false,
      rightTop: 100,
      rightTicks: [],
      rightUnit: "",
      labels: periods.map((period) => period.label),
      axis: prAxis,
      lines: tokenLines,
      empty: "No tokens used.",
    },
    {
      key: "cpu",
      group: "vms",
      title: "CPU",
      href: "#/vms",
      detail: "Last minute",
      top: 100,
      ticks: percentTicks,
      unit: "%",
      log: false,
      rightTop: 100,
      rightTicks: [],
      rightUnit: "",
      labels: vmLabels,
      axis: vmAxis,
      lines: cpuLines,
      empty: "No running virtual machines.",
    },
    {
      key: "memory",
      group: "vms",
      title: "Memory",
      href: "#/vms",
      detail: "Last minute",
      top: 100,
      ticks: percentTicks,
      unit: "%",
      log: false,
      rightTop: 100,
      rightTicks: [],
      rightUnit: "",
      labels: vmLabels,
      axis: vmAxis,
      lines: memoryLines,
      empty: "No running virtual machines.",
    },
  ];
  // Each line's points, at the middle of their column, in runs broken where a value is missing; each run a path. A
  // lone point is a dot. Smoothed, a run of three or more is a curve through its points: a cubic between each two, its
  // slope at a point Steffen's (0 at a peak or a dip, else no steeper than the gentler side allows), so it stays
  // between the two points' levels; at the ends, the slope that keeps the end segment's shape.
  for (const chart of charts) {
    for (const line of chart.lines) {
      const top = line.right ? chart.rightTop : chart.top;
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
        if (!smooth || points.length === 2) {
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

  // A pair of charts side by side (pull requests and tokens, or the VMs'): drawn the same way, only their data differs.
  const chartPairs = [charts.slice(0, 2), charts.slice(2, 4)];
  const drawn = chartPairs.map((pair) => (
    <div key={pair[0].key} className="grid grid-cols-2 gap-3 max-lg:grid-cols-1">
      {pair.map((chart) => {
        const at = hovered !== null && hovered.group === chart.group ? hovered.index : null;
        return (
          <div key={chart.key} className={WIDGET}>
            <div className={WIDGET_HEADER}>
              {chart.href !== "" && (
                <a href={chart.href} className={TITLE}>
                  {chart.title}
                </a>
              )}
              {chart.href === "" && <span className="truncate font-medium">{chart.title}</span>}
              <span className={DETAIL}>{chart.detail}</span>
              {chart.key === "tokens" && (
                <div className="flex shrink-0 overflow-hidden rounded-sm border">
                  {[
                    { key: "model", title: "Model" },
                    { key: "work", title: "Work" },
                  ].map((each) => (
                    <button
                      key={each.key}
                      type="button"
                      className={cn(
                        "h-6 border-l px-2 text-xs font-medium text-muted-foreground first:border-l-0 hover:bg-accent hover:text-foreground",
                        tokensBy === each.key && "bg-selected text-foreground hover:bg-selected",
                      )}
                      onClick={() => setTokensBy(each.key)}
                    >
                      {each.title}
                    </button>
                  ))}
                </div>
              )}
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
                  {[...chart.lines]
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
                            strokeDasharray={line.right ? "4 3" : undefined}
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
                      <div key={index} className="relative h-full min-w-0 flex-1" onMouseEnter={() => setHovered({ group: chart.group, index: index })}>
                        {at === index && <div className="absolute inset-y-0 left-1/2 w-px bg-foreground/40" />}
                      </div>
                    ))}
                  </div>
                  {at !== null && chart.lines.length > 0 && (
                    <div
                      className={cn(
                        "pointer-events-none absolute top-0 z-10 w-44 rounded-md border bg-popover px-2.5 py-2 text-xs shadow-overlay",
                        at < chart.labels.length / 2 ? "ml-3" : "-ml-3 -translate-x-full",
                      )}
                      style={{ left: `${((at + 0.5) / chart.labels.length) * 100}%` }}
                    >
                      <div className="font-medium">{chart.labels[at]}</div>
                      {chart.lines.map((line) => (
                        <div key={line.title} className="mt-1 flex items-center gap-1.5">
                          <span className={cn("size-2 shrink-0 rounded-full bg-current", line.color)} />
                          <span className="truncate text-muted-foreground">{line.title}</span>
                          <span className="ml-auto font-mono tabular-nums">
                            {line.values[at] === null ? "–" : `${SHORT.format(Math.round(line.values[at] ?? 0))}${line.right ? chart.rightUnit : chart.unit}`}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                {chart.rightTicks.length > 0 && (
                  <div className="relative w-9 shrink-0 font-mono text-xs text-muted-foreground tabular-nums">
                    {chart.rightTicks.map((value) => (
                      <span key={value} className="absolute left-0 translate-y-1/2" style={{ bottom: `${(value / chart.rightTop) * 100}%` }}>
                        {value}
                        {chart.rightUnit}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              {/* Under each labeled column; the first and last kept inside the chart's edges. */}
              <div className={cn("relative mt-1.5 ml-11 h-4 text-xs text-muted-foreground tabular-nums", chart.rightTicks.length > 0 && "mr-11")}>
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
                    <span className={cn("h-0.5 w-3 rounded-full bg-current", line.color, line.right && "h-0 rounded-none border-t-2 border-dashed border-current bg-transparent")} />
                    {line.title}
                  </span>
                ))}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  ));

  return (
    <div className="flex h-full flex-col">
      <div className="flex min-h-9 shrink-0 items-center gap-3 border-b px-3 py-1">
        <span className="font-medium">Dashboard</span>
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground tabular-nums">
          <span className={cn("size-1.5 rounded-full", connected ? "bg-ok" : "bg-destructive")} />
          <span className={cn(!connected && "text-destructive")}>{connected ? "Live" : "Offline"}</span>
          {prs.checked_at !== null && <span className="max-md:hidden">· Updated {new Date(prs.checked_at).toLocaleTimeString("en", CLOCK)}</span>}
        </span>
        <button
          type="button"
          aria-pressed={smooth}
          className={cn(
            "ml-auto h-7 rounded-sm border px-2.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground",
            smooth && "bg-selected text-foreground hover:bg-selected",
          )}
          onClick={() => setSmooth(!smooth)}
        >
          Smooth
        </button>
        <div className="flex overflow-hidden rounded-sm border">
          {RANGES.map((each) => (
            <button
              key={each.key}
              type="button"
              className={cn(
                "h-7 border-l px-2.5 text-xs font-medium text-muted-foreground tabular-nums first:border-l-0 hover:bg-accent hover:text-foreground",
                rangeKey === each.key && "bg-selected text-foreground hover:bg-selected",
              )}
              onClick={() => setRangeKey(each.key)}
            >
              {each.title}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto bg-muted/40">
        <div className="space-y-3 p-3">
          <div className="grid grid-cols-8 gap-3 max-2xl:grid-cols-4 max-md:grid-cols-2">
            {numbers.map((number) => (
              <div key={number.title} className={WIDGET}>
                <div className={WIDGET_HEADER}>
                  {number.href !== "" && (
                    <a href={number.href} className={TITLE}>
                      {number.title}
                    </a>
                  )}
                  {number.href === "" && <span className="truncate font-medium">{number.title}</span>}
                  <span className={DETAIL}>{range.title}</span>
                </div>
                <div className="flex flex-1 flex-wrap items-end gap-x-3 px-3 pt-4 pb-3">
                  <span className="font-mono text-3xl font-light tabular-nums">{number.value}</span>
                  {number.change !== null && (
                    <span
                      title={number.was}
                      className={cn(
                        "mb-1 font-mono text-sm whitespace-nowrap tabular-nums",
                        number.change === 0 || number.better === ""
                          ? "text-muted-foreground"
                          : (number.change > 0) === (number.better === "up")
                            ? "text-ok"
                            : "text-destructive",
                      )}
                    >
                      {number.change > 0 ? "▲ " : number.change < 0 ? "▼ " : ""}
                      {number.changeText}
                    </span>
                  )}
                </div>
              </div>
            ))}
            <div className={cn(WIDGET, "col-span-2")}>
              <div className={WIDGET_HEADER}>
                <a href="#/automation" className={TITLE}>
                  Limits
                </a>
              </div>
              <div className="flex flex-1 flex-col justify-evenly gap-2 px-3 py-2">
                {limits.map((each) => {
                  const full = each.limit !== null && each.limit > 0 ? each.used / each.limit : 0;
                  return (
                    <div key={each.title} className="flex items-center gap-3" title={each.about}>
                      <span className="w-36 shrink-0 truncate">{each.title}</span>
                      {each.limit !== null && (
                        <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-muted">
                          <div className={cn("h-full rounded-full", full >= 0.85 ? "bg-warn" : "bg-foreground/40")} style={{ width: `${Math.min(full, 1) * 100}%` }} />
                        </div>
                      )}
                      {each.limit === null && <span className="min-w-0 flex-1 text-xs text-muted-foreground">No limit</span>}
                      <span className={cn("w-14 shrink-0 text-right font-mono text-xs tabular-nums", full >= 0.85 && "text-warn")}>
                        {each.used}
                        {each.limit !== null && ` / ${each.limit}`}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {drawn[0]}

          <div className={WIDGET}>
            <div className={WIDGET_HEADER}>
              <a href="#/pulls?state=progress" className={TITLE}>
                In progress
              </a>
              <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                {working.length} working · {queued} queued
              </span>
              {busy === 0 && <span className="ml-auto shrink-0 text-xs font-medium text-ok">Safe to shut down</span>}
            </div>
            {working.length === 0 && <div className="p-3 text-muted-foreground">No agent is working.</div>}
            {working.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px]">
                  <thead>
                    <tr>
                      <th className={th}>Issue or pull request</th>
                      <th className={th}>Step</th>
                      <th className={cn(th, "text-right")}>On step</th>
                      <th className={th}>Agent</th>
                      <th className={th}>VM</th>
                    </tr>
                  </thead>
                  <tbody>
                    {working.map((job) => {
                      const [repo, number] = (job.issue ?? job.thread ?? "").split("#");
                      const agent = agentById[job.agent];
                      const vm = agent?.vm ?? job.vm;
                      return (
                        <tr key={job.id} className="hover:bg-accent/40 [&:last-child>td]:border-b-0">
                          <td className={cn(td, "max-w-96 truncate")}>
                            <a href={`https://github.com/${repo}/issues/${number}`} target="_blank" rel="noreferrer" className="hover:underline">
                              <span className="text-muted-foreground">{repo}</span> <span className="font-mono text-muted-foreground tabular-nums">#{number}</span>{" "}
                              {job.title}
                            </a>
                          </td>
                          <td className={td}>
                            <JobProgressBar job={job} />
                          </td>
                          <td className={cn(td, "text-right font-mono text-xs tabular-nums")}>{since(job.step_at ?? job.started_at, now)}</td>
                          <td className={td}>
                            <a href={`#/agents/${job.agent}`} className="text-primary hover:underline">
                              {agent?.name ?? job.agent}
                            </a>
                          </td>
                          <td className={cn(td, "font-mono text-xs text-muted-foreground tabular-nums")}>
                            {vm ?? "–"}
                            {vm !== null && agent !== undefined && agent.desktop !== null && ` · ${agent.desktop}`}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {drawn[1]}
        </div>
      </div>
    </div>
  );
}
