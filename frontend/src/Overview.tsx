/*
The Overview (#/), the page the app opens on, display only. On top, like the other pages, its name and the range for
the pull request numbers: the last 7, 30 or 90 days (kept while the page is open). Under it:
- A row of five cards, all alike: a label, a number and a line about it (empty on the last two). Each opens its page.
  - Open pull requests (#/pulls?state=open): yours open now, and how many of them are failing.
  - Merged (#/pulls?state=merged): yours merged in the range, and how many you opened in it.
  - Merge rate (#/pulls?state=closed): merged of merged and closed in the range, with a ring, and how many were closed.
  - Issues in progress (#/pulls?state=progress): fix_issue jobs still open with no pull request yet.
  - Blockers (#/blockers): approval requests waiting for you (drafts of kind "approval" in the live "inbox" topic).
    Amber while there are any.
- Pull requests: a bar per day of the range, drawn to scale, stacked in GitHub's colors: opened in green at the bottom,
  merged in purple, closed in red on top. Clicking Opened, Merged or Closed in the legend hides or shows it (the scale
  follows what is shown); hovering one fades the other colors. The y axis runs from 0 to a round number (steps of 1, 2,
  5, 10, 20, ...) with a line at each step; the x axis has a date under every day for 7 days, else five dates evenly
  spread, the last one Today. Hovering a day shows its date with its weekday on the right in gray, then its numbers.
- Open pull requests: a donut of the open ones by what they wait on, each counted once, the first that fits: Failing
  (checks failed or conflicts), Changes requested, Approved, else Review required. Only the first three have a color:
  waiting for a review is the usual state, so it is gray. The total is in the middle.
- Agents, across the page: what they do right now, as four numbers: agents working (busy), working on issues
  (fix_issue jobs working), working on pull requests (follow_up jobs working) and issues queued (fix_issue jobs queued).
  On the right Safe to shut down (green) while no agent is busy, else Not safe to shut down (amber).
- Virtual machines, across the page: + in the header opens NewVMDialog to make one here. A table, a row per VM: its
  name (opens its page), status (Not answering in red when it froze), CPU and memory over the last minute as small lines
  from 0 to all of it, storage used now as a small bar, and the desktops in use. A number over 85% turns amber. The
  arrow before a name opens a row per desktop under it (who uses it, its CPU, memory and storage), then Other: what is
  no desktop's (the system, Docker, sudo). Those numbers show – until the backend reads them.
Every panel has the same header: its title, which opens its page, and on the right only a detail that says something.
Charts keep fixed heights, so nothing stretches with the window; the page scrolls when it is short.
Only reads, besides making a VM.
*/

import { ChevronRight, Plus } from "lucide-react";
import { Fragment, useState } from "react";

import { Button } from "@/components/ui/button";
import { StatusDot, VM_TONE } from "@/components/ui/status-dot";
import { useLive } from "@/live";
import { cn } from "@/lib/utils";
import NewVMDialog from "@/NewVMDialog";

const OPEN_JOB = ["queued", "working", "waiting_on_user", "waiting_on_maintainers"];
const RANGES = [7, 30, 90];
const SAMPLES = 60;
// "Nov 18"
const DAY: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
// GitHub's open green, merged purple and closed red: Tailwind's 600 (500 when dark) with 20% less saturation.
const OPENED = "bg-[oklch(62.7%_0.155_149.214)] dark:bg-[oklch(72.3%_0.175_149.579)]";
const MERGED = "bg-[oklch(55.8%_0.23_302.321)] dark:bg-[oklch(62.7%_0.212_303.9)]";
const CLOSED = "bg-[oklch(57.7%_0.196_27.325)] dark:bg-[oklch(63.7%_0.19_25.331)]";
// The Pull requests chart's colors, bottom of the stack first.
const SERIES = [
  { key: "opened", title: "Opened", color: OPENED },
  { key: "merged", title: "Merged", color: MERGED },
  { key: "closed", title: "Closed", color: CLOSED },
] as const;
const PANEL = "rounded-xl border bg-card p-4 max-md:p-3";
const HEADER = "flex min-h-6 items-center gap-3";
const TITLE = "font-semibold hover:underline";
const DETAIL = "ml-auto text-xs text-muted-foreground tabular-nums";

export default function Overview() {
  const prs = useLive("prs");
  const jobs = useLive("jobs");
  const inbox = useLive("inbox");
  const vms = useLive("vms");
  const agents = useLive("agents");
  const [range, setRange] = useState(30);
  const [hovered, setHovered] = useState<number | null>(null);
  // The Pull requests chart: the colors hidden from the legend, and the one the mouse is on there.
  const [hidden, setHidden] = useState<string[]>([]);
  const [focus, setFocus] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  // The VMs whose desktops are shown under them.
  const [expanded, setExpanded] = useState<string[]>([]);

  const mine = prs.items.filter((pr) => pr.relation === "author");
  const prJobs = mine.map((pr) => pr.job);

  const blockers = inbox.filter((draft) => draft.kind === "approval" && draft.status === "pending");

  // Pull requests: a day each, oldest first, today last.
  const days: {
    key: string;
    label: string;
    weekday: string;
    opened: number;
    merged: number;
    closed: number;
    total: number;
  }[] = [];
  for (let back = range - 1; back >= 0; back--) {
    const date = new Date();
    date.setDate(date.getDate() - back);
    days.push({
      key: date.toDateString(),
      label: date.toLocaleDateString("en", DAY),
      weekday: date.toLocaleDateString("en", { weekday: "short" }),
      opened: 0,
      merged: 0,
      closed: 0,
      total: 0,
    });
  }
  const byDay: Record<string, (typeof days)[number]> = {};
  for (const day of days) {
    byDay[day.key] = day;
  }
  for (const pr of mine) {
    const openedOn = byDay[new Date(pr.opened_at).toDateString()];
    if (openedOn !== undefined) {
      openedOn.opened += 1;
    }
    if (pr.state === "open" || pr.closed_at === null) {
      continue;
    }
    const endedOn = byDay[new Date(pr.closed_at).toDateString()];
    if (endedOn !== undefined && pr.state === "merged") {
      endedOn.merged += 1;
    }
    if (endedOn !== undefined && pr.state === "closed") {
      endedOn.closed += 1;
    }
  }
  let opened = 0;
  let merged = 0;
  let closed = 0;
  let tallest = 1;
  for (const day of days) {
    opened += day.opened;
    merged += day.merged;
    closed += day.closed;
    // The bar's height: what is shown of it.
    for (const series of SERIES) {
      if (!hidden.includes(series.key)) {
        day.total += day[series.key];
      }
    }
    tallest = Math.max(tallest, day.total);
  }
  const shown = SERIES.filter((series) => !hidden.includes(series.key));
  const rate = merged + closed > 0 ? Math.round((merged / (merged + closed)) * 100) : null;

  // The y axis: 0 to a round number at or over the tallest bar, in at most four equal steps.
  let step = 1;
  for (const each of [1000, 500, 200, 100, 50, 20, 10, 5, 2, 1]) {
    if (each * 4 >= tallest) {
      step = each;
    }
  }
  const top = Math.ceil(tallest / step) * step;
  const ticks: number[] = [];
  for (let value = 0; value <= top; value += step) {
    ticks.push(value);
  }
  // The x axis: every day of a week, else five days evenly spread, the last one today.
  let dated: number[] = [];
  for (let index = 0; index < days.length; index++) {
    dated.push(index);
  }
  if (days.length > 7) {
    dated = [0, Math.round((days.length - 1) / 4), Math.round((days.length - 1) / 2), Math.round(((days.length - 1) * 3) / 4), days.length - 1];
  }
  const hoveredDay = hovered !== null ? days[hovered] : undefined;

  // Open pull requests, by what they wait on. start: where its piece of the donut begins, of 100.
  const open = mine.filter((pr) => pr.state === "open");
  const waits = [
    {
      title: "Failing",
      color: "text-red-600 dark:text-red-500",
      count: 0,
      start: 0,
    },
    { title: "Changes requested", color: "text-amber-500", count: 0, start: 0 },
    {
      title: "Review required",
      color: "text-foreground/25",
      count: 0,
      start: 0,
    },
    {
      title: "Approved",
      color: "text-green-600 dark:text-green-500",
      count: 0,
      start: 0,
    },
  ];
  for (const pr of open) {
    if (pr.checks === "failed" || pr.mergeable === "conflicts") {
      waits[0].count += 1;
    } else if (pr.review === "changes_requested") {
      waits[1].count += 1;
    } else if (pr.review === "approved") {
      waits[3].count += 1;
    } else {
      waits[2].count += 1;
    }
  }
  let start = 0;
  for (const wait of waits) {
    wait.start = start;
    start += open.length > 0 ? (wait.count / open.length) * 100 : 0;
  }
  // A small gap between the pieces, when there is more than one.
  const gap = waits.filter((wait) => wait.count > 0).length > 1 ? 1 : 0;

  // Issues in progress.
  const openJobs = jobs.filter((job) => OPEN_JOB.includes(job.status));
  const inProgress = openJobs.filter((job) => job.kind === "fix_issue" && !prJobs.includes(job.id));

  // Agents: what they do right now. The computer may be shut down while none is busy.
  const busy = agents.filter((agent) => agent.busy).length;
  const work = [
    { title: "Agents working", count: busy },
    { title: "Working on issues", count: jobs.filter((job) => job.kind === "fix_issue" && job.status === "working").length },
    { title: "Working on pull requests", count: jobs.filter((job) => job.kind === "follow_up" && job.status === "working").length },
    { title: "Issues queued", count: jobs.filter((job) => job.kind === "fix_issue" && job.status === "queued").length },
  ];

  const cards = [
    {
      title: "Open pull requests",
      href: "#/pulls?state=open",
      value: `${open.length}`,
      detail: `${waits[0].count} failing`,
    },
    {
      title: "Merged",
      href: "#/pulls?state=merged",
      value: `${merged}`,
      detail: `${opened} opened`,
    },
    {
      title: "Merge rate",
      href: "#/pulls?state=closed",
      value: rate === null ? "–" : `${rate}%`,
      detail: `${closed} closed`,
    },
    {
      title: "Issues in progress",
      href: "#/pulls?state=progress",
      value: `${inProgress.length}`,
      detail: "",
    },
    {
      title: "Blockers",
      href: "#/blockers",
      value: `${blockers.length}`,
      detail: "",
    },
  ];

  // Virtual machines: each one's CPU and memory over the last minute, as chart points (0-100 both ways).
  const running = vms.filter((vm) => vm.status === "running").length;
  const agentNames: Record<string, string> = {};
  for (const agent of agents) {
    agentNames[agent.id] = agent.name;
  }
  const vmRows = [];
  for (const vm of vms) {
    const on = vm.status === "running";
    const silent = on && vm.usage !== null && vm.usage.on && !vm.usage.responding;
    const cpu = vm.usage?.cpu_percent ?? null;
    const memory = vm.usage?.memory_used_gb ?? null;
    const charts = [
      {
        key: "cpu",
        value: cpu === null ? "–" : `${Math.round(cpu)}%`,
        high: cpu !== null && cpu > 85,
        values: vm.samples.map((sample) => sample.cpu_percent),
        max: 100,
        points: "",
      },
      {
        key: "memory",
        value: memory === null ? "–" : `${memory.toFixed(1)} / ${vm.memory_gb} GB`,
        high: memory !== null && memory > vm.memory_gb * 0.85,
        values: vm.samples.map((sample) => sample.memory_used_gb),
        max: vm.memory_gb,
        points: "",
      },
    ];
    for (const chart of charts) {
      // Samples fill the chart from the right: the newest is at the right edge.
      const offset = SAMPLES - chart.values.length;
      const points: string[] = [];
      chart.values.forEach((value, index) => {
        if (value === null) {
          return;
        }
        const x = ((offset + index) / (SAMPLES - 1)) * 100;
        const y = 100 - Math.min(value / chart.max, 1) * 100;
        points.push(`${x.toFixed(2)},${y.toFixed(2)}`);
      });
      chart.points = points.join(" ");
    }
    // Storage used, only while the VM runs.
    let disk = null;
    if (on) {
      disk = vm.usage?.disk_used_gb ?? null;
    }
    const held = vm.desktops.filter((desktop) => desktop.holder !== null).length;
    // The rows under it: a desktop each, then Other. agent: the agent's id when one uses it, for its link.
    const parts: {
      key: string;
      title: string;
      who: string;
      agent: string | null;
    }[] = [];
    for (const desktop of vm.desktops) {
      let who = "Nobody";
      let agent = null;
      if (desktop.holder === "user") {
        who = "You";
      } else if (desktop.holder !== null) {
        who = agentNames[desktop.holder] ?? desktop.holder;
        agent = desktop.holder;
      }
      parts.push({
        key: `${desktop.number}`,
        title: `Desktop ${desktop.number}`,
        who: who,
        agent: agent,
      });
    }
    parts.push({ key: "other", title: "Other", who: "", agent: null });
    const open = expanded.includes(vm.name);
    vmRows.push({
      vm: vm,
      on: on,
      silent: silent,
      charts: charts,
      disk: disk,
      held: held,
      parts: parts,
      open: open,
    });
  }

  const th = "h-8 border-b px-3 text-left text-xs font-medium whitespace-nowrap text-muted-foreground";
  const td = "h-11 border-b px-3 whitespace-nowrap";

  return (
    <div className="flex h-full flex-col">
      <div className="flex min-h-9 shrink-0 items-center gap-3 border-b px-3 py-1">
        <span className="font-medium">Overview</span>
        <div className="ml-auto flex rounded-md border p-0.5">
          {RANGES.map((each) => (
            <button
              key={each}
              type="button"
              className={cn(
                "h-6 rounded-sm px-2 text-xs font-medium text-muted-foreground tabular-nums hover:text-foreground",
                range === each && "bg-accent text-foreground",
              )}
              onClick={() => setRange(each)}
            >
              {each === 7 ? "7 days" : each === 30 ? "30 days" : "90 days"}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="space-y-4 p-6 max-md:space-y-3 max-md:p-3">
          <div className="grid grid-cols-5 gap-4 max-xl:grid-cols-3 max-md:grid-cols-2 max-md:gap-3">
            {cards.map((card) => (
              <a
                key={card.title}
                href={card.href}
                className={cn(
                  "block min-w-0 rounded-xl border bg-card p-4 hover:bg-accent/40 max-md:p-3",
                  card.title === "Blockers" && blockers.length > 0 && "border-amber-500/40",
                )}
              >
                <div className="truncate text-muted-foreground">{card.title}</div>
                <div className="mt-1 flex items-center gap-2">
                  <span className={cn("text-3xl font-semibold tabular-nums", card.title === "Blockers" && blockers.length > 0 && "text-warn")}>
                    {card.value}
                  </span>
                  {card.title === "Merge rate" && rate !== null && (
                    <svg viewBox="0 0 36 36" className="size-6 -rotate-90">
                      <circle cx="18" cy="18" r="15.9155" fill="none" stroke="currentColor" strokeWidth="6" className="text-foreground/10" />
                      <circle
                        cx="18"
                        cy="18"
                        r="15.9155"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="6"
                        strokeDasharray={`${rate} ${100 - rate}`}
                        className="text-purple-600 dark:text-purple-500"
                      />
                    </svg>
                  )}
                </div>
                {/* Always a line, also an empty one, so the cards stay the same height. */}
                <div className="mt-1 h-4 truncate text-xs text-muted-foreground">{card.detail}</div>
              </a>
            ))}
          </div>

          <div className="grid grid-cols-3 gap-4 max-lg:grid-cols-1 max-md:gap-3">
            <div className={cn(PANEL, "col-span-2 max-lg:col-span-1")}>
              <div className={HEADER}>
                <a href="#/pulls" className={TITLE}>
                  Pull requests
                </a>
                <div className="ml-auto flex items-center gap-4 text-xs text-muted-foreground">
                  {SERIES.map((series) => (
                    <button
                      key={series.key}
                      type="button"
                      className={cn("flex items-center gap-1.5 hover:text-foreground", hidden.includes(series.key) && "opacity-40")}
                      onClick={() => setHidden(hidden.includes(series.key) ? hidden.filter((key) => key !== series.key) : [...hidden, series.key])}
                      onMouseEnter={() => setFocus(series.key)}
                      onMouseLeave={() => setFocus(null)}
                    >
                      <span className={cn("size-2.5 rounded-sm", series.color)} />
                      {series.title}
                    </button>
                  ))}
                </div>
              </div>

              <div className="mt-4 flex h-60 gap-2">
                <div className="relative w-8 shrink-0 text-right text-xs text-muted-foreground tabular-nums">
                  {ticks.map((value) => (
                    <span key={value} className="absolute right-0 translate-y-1/2" style={{ bottom: `${(value / top) * 100}%` }}>
                      {value}
                    </span>
                  ))}
                </div>
                <div className="relative flex-1">
                  {ticks.map((value) => (
                    <div
                      key={value}
                      className={cn("absolute inset-x-0 border-t", value > 0 && "border-border/60")}
                      style={{ bottom: `${(value / top) * 100}%` }}
                    />
                  ))}
                  <div className={cn("absolute inset-0 flex", range === 90 ? "gap-px" : "gap-1")} onMouseLeave={() => setHovered(null)}>
                    {days.map((day, index) => (
                      <div
                        key={day.key}
                        className={cn("flex h-full min-w-0 flex-1 flex-col justify-end rounded-t-sm", hovered === index && "bg-foreground/5")}
                        onMouseEnter={() => setHovered(index)}
                      >
                        {/* The stack, its first color at the bottom. */}
                        <div className="flex flex-col-reverse overflow-hidden rounded-t-sm" style={{ height: `${(day.total / top) * 100}%` }}>
                          {shown.map((series) => (
                            <div
                              key={series.key}
                              className={cn(
                                "shrink-0 transition-opacity",
                                series.color,
                                focus !== null && focus !== series.key && !hidden.includes(focus) && "opacity-25",
                              )}
                              style={{
                                height: day.total === 0 ? 0 : `${(day[series.key] / day.total) * 100}%`,
                              }}
                            />
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                  {hovered !== null && hoveredDay !== undefined && (
                    <div
                      className={cn(
                        "pointer-events-none absolute top-0 z-10 w-36 rounded-md border bg-popover px-2.5 py-2 text-xs shadow-overlay",
                        hovered < days.length / 2 ? "ml-3" : "-ml-3 -translate-x-full",
                      )}
                      style={{
                        left: `${((hovered + 0.5) / days.length) * 100}%`,
                      }}
                    >
                      <div className="flex items-center">
                        <span className="font-medium">{hovered === days.length - 1 ? "Today" : hoveredDay.label}</span>
                        <span className="ml-auto text-muted-foreground">{hoveredDay.weekday}</span>
                      </div>
                      {shown.map((series, order) => (
                        <div key={series.key} className={cn("flex items-center gap-1.5", order === 0 && "mt-1")}>
                          <span className={cn("size-2 rounded-sm", series.color)} />
                          <span className="text-muted-foreground">{series.title}</span>
                          <span className="ml-auto tabular-nums">{hoveredDay[series.key]}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              {/* Under each dated day's bar; the first and last kept inside the chart's edges. */}
              <div className="relative mt-1.5 ml-10 h-4 text-xs text-muted-foreground tabular-nums">
                {dated.map((index) => (
                  <span
                    key={index}
                    className={cn("absolute whitespace-nowrap", index > 0 && index < days.length - 1 && "-translate-x-1/2")}
                    style={index === 0 ? { left: 0 } : index === days.length - 1 ? { right: 0 } : { left: `${((index + 0.5) / days.length) * 100}%` }}
                  >
                    {index === days.length - 1 ? "Today" : days[index].label}
                  </span>
                ))}
              </div>
            </div>

            <div className={cn(PANEL, "flex flex-col")}>
              <div className={HEADER}>
                <a href="#/pulls?state=open" className={TITLE}>
                  Open pull requests
                </a>
              </div>
              <div className="flex flex-1 items-center gap-6 py-4">
                <div className="relative size-36 shrink-0">
                  <svg viewBox="0 0 36 36" className="size-full -rotate-90">
                    <circle cx="18" cy="18" r="15.9155" fill="none" stroke="currentColor" strokeWidth="3" className="text-foreground/10" />
                    {waits.map((wait) => {
                      const length = open.length > 0 ? (wait.count / open.length) * 100 : 0;
                      if (length === 0) {
                        return null;
                      }
                      const drawn = Math.max(length - gap, 0.5);
                      return (
                        <circle
                          key={wait.title}
                          cx="18"
                          cy="18"
                          r="15.9155"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="3"
                          strokeDasharray={`${drawn} ${100 - drawn}`}
                          strokeDashoffset={-wait.start}
                          className={wait.color}
                        />
                      );
                    })}
                  </svg>
                  <div className="absolute inset-0 flex flex-col items-center justify-center">
                    <span className="text-2xl font-semibold tabular-nums">{open.length}</span>
                    <span className="text-xs text-muted-foreground">open</span>
                  </div>
                </div>
                <div className="min-w-0 flex-1 space-y-2.5">
                  {waits.map((wait) => (
                    <div key={wait.title} className="flex items-center gap-2">
                      <span className={cn("size-2 shrink-0 rounded-full bg-current", wait.color)} />
                      <span className="whitespace-nowrap">{wait.title}</span>
                      <span className="ml-auto pl-2 font-medium tabular-nums">{wait.count}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className={PANEL}>
            <div className={HEADER}>
              <a href="#/pulls?state=progress" className={TITLE}>
                Agents
              </a>
              <span className={cn("ml-auto text-xs font-medium", busy === 0 ? "text-ok" : "text-warn")}>
                {busy === 0 ? "Safe to shut down" : "Not safe to shut down"}
              </span>
            </div>
            <div className="mt-3 grid grid-cols-4 gap-4 max-md:grid-cols-2 max-md:gap-3">
              {work.map((each) => (
                <div key={each.title} className="min-w-0">
                  <div className="truncate text-xs text-muted-foreground">{each.title}</div>
                  <div className={cn("mt-1 text-2xl font-semibold tabular-nums", each.count === 0 && "text-muted-foreground")}>{each.count}</div>
                </div>
              ))}
            </div>
          </div>

          <div className={PANEL}>
            <div className={HEADER}>
              <a href="#/vms" className={TITLE}>
                Virtual machines
              </a>
              <span className={DETAIL}>
                {running} of {vms.length} running
              </span>
              <Button variant="ghost" size="icon-xs" title="New VM" aria-label="New VM" onClick={() => setCreating(true)}>
                <Plus />
              </Button>
            </div>
            {vms.length === 0 && <div className="mt-3 text-muted-foreground">No virtual machines.</div>}
            {vms.length > 0 && (
              <div className="-mx-4 mt-3 overflow-x-auto max-md:-mx-3">
                <table className="w-full min-w-[720px]">
                  <thead>
                    <tr>
                      <th className={th}>Name</th>
                      <th className={th}>Status</th>
                      <th className={th}>CPU</th>
                      <th className={th}>Memory</th>
                      <th className={th}>Storage</th>
                      <th className={cn(th, "text-right")}>Desktops in use</th>
                    </tr>
                  </thead>
                  <tbody>
                    {vmRows.map((row) => (
                      <Fragment key={row.vm.name}>
                        <tr className="hover:bg-accent/40 [&:last-child>td]:border-b-0">
                          <td className={td}>
                            <div className="flex items-center gap-1.5">
                              <button
                                type="button"
                                className="-ml-1 flex size-5 shrink-0 items-center justify-center rounded-sm hover:bg-accent"
                                title="Desktops"
                                aria-label="Desktops"
                                aria-expanded={row.open}
                                onClick={() => setExpanded(row.open ? expanded.filter((name) => name !== row.vm.name) : [...expanded, row.vm.name])}
                              >
                                <ChevronRight className={cn("size-3.5 text-muted-foreground transition-transform", row.open && "rotate-90")} />
                              </button>
                              <a href={`#/vms/${encodeURIComponent(row.vm.name)}`} className="flex items-center gap-2 font-medium hover:underline">
                                <StatusDot tone={row.silent ? "red" : VM_TONE[row.vm.status]} />
                                {row.vm.name}
                              </a>
                            </div>
                          </td>
                          <td className={cn(td, row.silent ? "text-destructive" : "text-muted-foreground")}>
                            {row.silent ? "Not answering" : row.vm.status.charAt(0).toUpperCase() + row.vm.status.slice(1)}
                          </td>
                          {row.charts.map((chart) => (
                            <td key={chart.key} className={td}>
                              <div className="flex items-center gap-3">
                                <div className="relative h-6 w-24 shrink-0 border-b">
                                  {chart.points !== "" && (
                                    <svg
                                      viewBox="0 0 100 100"
                                      preserveAspectRatio="none"
                                      className="absolute inset-0 size-full overflow-visible text-sky-600 dark:text-sky-500"
                                    >
                                      <polyline
                                        points={chart.points}
                                        fill="none"
                                        stroke="currentColor"
                                        strokeWidth="1.5"
                                        strokeLinejoin="round"
                                        strokeLinecap="round"
                                        vectorEffect="non-scaling-stroke"
                                      />
                                    </svg>
                                  )}
                                </div>
                                <span className={cn("tabular-nums", chart.high && "text-warn")}>{row.on ? chart.value : "–"}</span>
                              </div>
                            </td>
                          ))}
                          <td className={td}>
                            <div className="flex items-center gap-3">
                              <div className="h-1.5 w-24 shrink-0 overflow-hidden rounded-full bg-muted">
                                <div
                                  className={cn(
                                    "h-full rounded-full",
                                    row.disk !== null && row.disk > row.vm.disk_gb * 0.85 ? "bg-warn" : "bg-sky-600 dark:bg-sky-500",
                                  )}
                                  style={{
                                    width: `${row.disk === null ? 0 : Math.min((row.disk / row.vm.disk_gb) * 100, 100)}%`,
                                  }}
                                />
                              </div>
                              <span className={cn("tabular-nums", row.disk !== null && row.disk > row.vm.disk_gb * 0.85 && "text-warn")}>
                                {row.disk !== null ? `${row.disk.toFixed(1)} / ${row.vm.disk_gb} GB` : "–"}
                              </span>
                            </div>
                          </td>
                          <td className={cn(td, "text-right tabular-nums")}>
                            {row.held} of {row.vm.desktops.length}
                          </td>
                        </tr>
                        {row.open &&
                          row.parts.map((part) => (
                            <tr key={part.key} className="bg-muted/30 [&:last-child>td]:border-b-0">
                              <td className={cn(td, "h-9 pl-12")}>{part.title}</td>
                              <td className={cn(td, "h-9 text-muted-foreground")}>
                                {part.agent !== null && (
                                  <a href={`#/agents/${part.agent}`} className="text-primary hover:underline">
                                    {part.who}
                                  </a>
                                )}
                                {part.agent === null && part.who}
                              </td>
                              <td className={cn(td, "h-9")}>
                                <div className="flex items-center gap-3">
                                  <div className="h-6 w-24 shrink-0 border-b" />
                                  <span className="text-muted-foreground">–</span>
                                </div>
                              </td>
                              <td className={cn(td, "h-9")}>
                                <div className="flex items-center gap-3">
                                  <div className="h-6 w-24 shrink-0 border-b" />
                                  <span className="text-muted-foreground">–</span>
                                </div>
                              </td>
                              <td className={cn(td, "h-9")}>
                                <div className="flex items-center gap-3">
                                  <div className="h-1.5 w-24 shrink-0 rounded-full bg-muted" />
                                  <span className="text-muted-foreground">–</span>
                                </div>
                              </td>
                              <td className={cn(td, "h-9")} />
                            </tr>
                          ))}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
      <NewVMDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}
