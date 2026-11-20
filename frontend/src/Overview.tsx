/*
The Overview (#/), the page the app opens on, display only. On top, like the other pages, its name and the range for
the pull request numbers: the last 7, 30 or 90 days (kept while the page is open). Under it:
- A row of five cards, all alike: a label, a number and one line about it. Each opens its page.
  - Open pull requests (#/pulls?state=open): yours open now, and how many of them are failing.
  - Merged (#/pulls?state=merged): yours merged in the range, and how many you opened in it.
  - Merge rate (#/pulls?state=closed): merged of merged and closed in the range, with a ring, and how many were closed.
  - Issues in progress (#/pulls?state=progress): fix_issue jobs still open with no pull request yet, and the open
    follow-ups and reviews.
  - Blockers (#/blockers): approval requests waiting for you (drafts of kind "approval" in the live "inbox" topic), and
    the newest one's title. Amber while there are any.
- Pull requests: a bar per day of the range, drawn to scale. Opened in light gray, merged in GitHub's purple in front of
  it. The y axis runs from 0 to a round number (steps of 1, 2, 5, 10, 20, ...) with a line at each step; the x axis has
  a date under every day for 7 days, else five dates evenly spread, the last one Today. Hovering a day shows its
  opened, merged and closed.
- Open pull requests: a donut of the open ones by what they wait on, each counted once, the first that fits: Failing
  (checks failed or conflicts), Changes requested, Approved, else Review required. Only the first three have a color:
  waiting for a review is the usual state, so it is gray. The total is in the middle.
- Issues in progress, across the page: the fix_issue steps side by side, each with its number and a bar, Not started
  (no step yet) in gray, then the steps in one blue.
- Virtual machines, across the page: a table, a row per VM: its name (opens its page), status (Not answering in red
  when it froze), CPU and memory over the last minute as small lines from 0 to all of it, the desktops in use, how many
  wait for one, and the tests and builds running. A number over 85% turns amber.
Every panel has the same header: its title, which opens its page, and on the right only a detail that says something.
Charts keep fixed heights, so nothing stretches with the window; the page scrolls when it is short.
Only reads; nothing here changes anything.
*/

import { useState } from "react";

import { StatusDot, VM_TONE } from "@/components/ui/status-dot";
import { useLive } from "@/live";
import { cn } from "@/lib/utils";

const OPEN_JOB = ["queued", "working", "waiting_on_user", "waiting_on_maintainers"];
const RANGES = [7, 30, 90];
const SAMPLES = 60;
// "Nov 18"
const DAY: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
const OPENED = "bg-foreground/15";
// GitHub's merged purple.
const MERGED = "bg-purple-600 dark:bg-purple-500";
// The fix_issue steps (github_searcher/jobs.py).
const STEPS = [
  { step: null, title: "Not started" },
  { step: "understand", title: "Understand" },
  { step: "set_up", title: "Set up" },
  { step: "reproduce", title: "Reproduce" },
  { step: "fix", title: "Fix" },
  { step: "test", title: "Test" },
  { step: "draft", title: "Draft" },
];
const PANEL = "rounded-xl border bg-card p-4 max-md:p-3";
const HEADER = "flex min-h-6 items-center gap-3";
const TITLE = "font-semibold hover:underline";
const DETAIL = "ml-auto text-xs text-muted-foreground tabular-nums";

export default function Overview() {
  const prs = useLive("prs");
  const jobs = useLive("jobs");
  const inbox = useLive("inbox");
  const vms = useLive("vms");
  const [range, setRange] = useState(30);
  const [hovered, setHovered] = useState<number | null>(null);

  const mine = prs.items.filter((pr) => pr.relation === "author");
  const prJobs = mine.map((pr) => pr.job);

  // Blockers, newest first.
  const blockers = inbox.filter((draft) => draft.kind === "approval" && draft.status === "pending");
  blockers.sort((a, b) => b.created_at.localeCompare(a.created_at));

  // Pull requests: a day each, oldest first, today last.
  const days: {
    key: string;
    label: string;
    opened: number;
    merged: number;
    closed: number;
  }[] = [];
  for (let back = range - 1; back >= 0; back--) {
    const date = new Date();
    date.setDate(date.getDate() - back);
    days.push({
      key: date.toDateString(),
      label: date.toLocaleDateString("en", DAY),
      opened: 0,
      merged: 0,
      closed: 0,
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
    tallest = Math.max(tallest, day.opened, day.merged);
  }
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

  // Issues in progress, by step; follow-ups and reviews.
  const openJobs = jobs.filter((job) => OPEN_JOB.includes(job.status));
  const inProgress = openJobs.filter((job) => job.kind === "fix_issue" && !prJobs.includes(job.id));
  const steps = STEPS.map((each) => ({
    ...each,
    count: inProgress.filter((job) => job.step === each.step).length,
  }));
  const widest = Math.max(1, ...steps.map((each) => each.count));
  const followUps = openJobs.filter((job) => job.kind === "follow_up").length;
  const reviews = openJobs.filter((job) => job.kind === "review").length;

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
      detail: `${followUps} ${followUps === 1 ? "follow-up" : "follow-ups"}, ${reviews} ${reviews === 1 ? "review" : "reviews"}`,
    },
    {
      title: "Blockers",
      href: "#/blockers",
      value: `${blockers.length}`,
      detail: blockers.length > 0 ? blockers[0].title : "",
    },
  ];

  // Virtual machines: each one's CPU and memory over the last minute, as chart points (0-100 both ways).
  const running = vms.filter((vm) => vm.status === "running").length;
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
    const held = vm.desktops.filter((desktop) => desktop.holder !== null).length;
    vmRows.push({ vm: vm, on: on, silent: silent, charts: charts, held: held });
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
                  <span className="flex items-center gap-1.5">
                    <span className={cn("size-2.5 rounded-sm", OPENED)} />
                    Opened
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className={cn("size-2.5 rounded-sm", MERGED)} />
                    Merged
                  </span>
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
                        className={cn("relative h-full min-w-0 flex-1 rounded-t-sm", hovered === index && "bg-foreground/5")}
                        onMouseEnter={() => setHovered(index)}
                      >
                        <div className={cn("absolute inset-x-0 bottom-0 rounded-t-sm", OPENED)} style={{ height: `${(day.opened / top) * 100}%` }} />
                        <div className={cn("absolute inset-x-0 bottom-0 rounded-t-sm", MERGED)} style={{ height: `${(day.merged / top) * 100}%` }} />
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
                      <div className="font-medium">{hovered === days.length - 1 ? "Today" : hoveredDay.label}</div>
                      <div className="mt-1 flex items-center gap-1.5">
                        <span className={cn("size-2 rounded-sm", OPENED)} />
                        <span className="text-muted-foreground">Opened</span>
                        <span className="ml-auto tabular-nums">{hoveredDay.opened}</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className={cn("size-2 rounded-sm", MERGED)} />
                        <span className="text-muted-foreground">Merged</span>
                        <span className="ml-auto tabular-nums">{hoveredDay.merged}</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className="size-2" />
                        <span className="text-muted-foreground">Closed</span>
                        <span className="ml-auto tabular-nums">{hoveredDay.closed}</span>
                      </div>
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
                Issues in progress
              </a>
            </div>
            <div className="mt-3 grid grid-cols-7 gap-4 max-md:grid-cols-4 max-md:gap-3">
              {steps.map((each) => (
                <div key={each.title} className="min-w-0">
                  <div className="truncate text-xs text-muted-foreground">{each.title}</div>
                  <div className={cn("mt-1 text-xl font-semibold tabular-nums", each.count === 0 && "text-muted-foreground")}>{each.count}</div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-foreground/5">
                    <div
                      className={cn("h-full rounded-full", each.step === null ? "bg-foreground/25" : "bg-sky-600 dark:bg-sky-500")}
                      style={{ width: `${(each.count / widest) * 100}%` }}
                    />
                  </div>
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
                      <th className={cn(th, "text-right")}>Desktops in use</th>
                      <th className={cn(th, "text-right")}>Waiting</th>
                      <th className={cn(th, "text-right")}>Tests and builds</th>
                    </tr>
                  </thead>
                  <tbody>
                    {vmRows.map((row) => (
                      <tr key={row.vm.name} className="hover:bg-accent/40 [&:last-child>td]:border-b-0">
                        <td className={td}>
                          <a href={`#/vms/${encodeURIComponent(row.vm.name)}`} className="flex items-center gap-2 font-medium hover:underline">
                            <StatusDot tone={row.silent ? "red" : VM_TONE[row.vm.status]} />
                            {row.vm.name}
                          </a>
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
                        <td className={cn(td, "text-right tabular-nums")}>
                          {row.held} of {row.vm.desktops.length}
                        </td>
                        <td className={cn(td, "text-right tabular-nums", row.vm.queue.length === 0 && "text-muted-foreground")}>{row.vm.queue.length}</td>
                        <td className={cn(td, "text-right tabular-nums", row.vm.runs.length === 0 && "text-muted-foreground")}>{row.vm.runs.length}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
