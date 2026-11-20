/*
Pull requests (#/pulls): four tabs (state= in the address), each a table grouped by repository. A repository's row
(its picture, name and count) folds and unfolds its rows; Expand all and Collapse all do every group of the open tab.
Groups come in the order of their newest row; folds are kept while the app is open.
- In progress (state=progress): fix_issue jobs still open that have no pull request yet. Issue (opens it on GitHub),
  Step, Status, Updated.
- Open (the default): the pull requests you opened that are open. Pull request (opens it on GitHub), Comments, Opened,
  Updated.
- Merged (state=merged): Pull request, Opened, Merged, Merged by.
- Closed (state=closed): Pull request, Opened, Closed, Closed by. Who closed one isn't in the live store, so it is read
  from its timeline (GET /api/github/thread), one at a time while the tab is open, and kept in localStorage: a closed
  pull request's closer doesn't change.
Only reads; nothing here changes anything.
*/

import { ChevronRight } from "lucide-react";
import { Fragment, useEffect, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { JOB_LABEL, JOB_TONE, StatusDot } from "@/components/ui/status-dot";
import { api, useLive } from "@/live";
import { cn } from "@/lib/utils";

const OPEN_JOB = ["queued", "working", "waiting_on_user", "waiting_on_maintainers"];
const TABS = [
  { state: "progress", title: "In progress" },
  { state: "open", title: "Open" },
  { state: "merged", title: "Merged" },
  { state: "closed", title: "Closed" },
];
// "Nov 18, 14:32"
const TIME: Intl.DateTimeFormatOptions = { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" };
const CLOSED_BY_KEY = "pulls-closed-by";

// Who closed each closed pull request, by owner/name#n ("" when GitHub doesn't say), kept across visits.
let closedByCache: Record<string, string> = {};
try {
  closedByCache = JSON.parse(localStorage.getItem(CLOSED_BY_KEY) ?? "{}");
} catch {
  // Storage blocked (private window) or unreadable: read them again.
  closedByCache = {};
}
// The folded groups, "<state>:<owner/name>", kept while the app is open.
let foldedKept: string[] = [];

export default function PullRequests(props: { state: string }) {
  const prs = useLive("prs");
  const jobs = useLive("jobs");
  const [closedBy, setClosedBy] = useState<Record<string, string>>(closedByCache);
  const [folded, setFolded] = useState<string[]>(foldedKept);

  const state = TABS.some((tab) => tab.state === props.state) ? props.state : "open";
  const mine = prs.items.filter((pr) => pr.relation === "author");
  const prJobs = mine.map((pr) => pr.job);
  const inProgress = jobs.filter((job) => job.kind === "fix_issue" && OPEN_JOB.includes(job.status) && !prJobs.includes(job.id));
  inProgress.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  const open = mine.filter((pr) => pr.state === "open");
  open.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  const merged = mine.filter((pr) => pr.state === "merged");
  merged.sort((a, b) => (b.closed_at ?? "").localeCompare(a.closed_at ?? ""));
  const closed = mine.filter((pr) => pr.state === "closed");
  closed.sort((a, b) => (b.closed_at ?? "").localeCompare(a.closed_at ?? ""));
  const counts: Record<string, number> = { progress: inProgress.length, open: open.length, merged: merged.length, closed: closed.length };
  const closedIds = closed.map((pr) => pr.id).join(" ");

  // Read who closed each closed pull request not read yet, one at a time, newest first.
  useEffect(() => {
    if (state !== "closed") {
      return;
    }
    let stopped = false;
    async function load() {
      for (const id of closedIds.split(" ")) {
        if (stopped) {
          return;
        }
        if (id === "" || closedByCache[id] !== undefined) {
          continue;
        }
        let who = "";
        try {
          const thread = await api<{ timeline: { type: string; login?: string; text?: string }[] }>(`/api/github/thread?id=${encodeURIComponent(id)}`);
          for (const item of thread.timeline) {
            if (item.type === "event" && (item.text ?? "").startsWith("closed this")) {
              who = item.login ?? "";
            }
          }
        } catch {
          // Not read this time: tried again on the next visit.
          continue;
        }
        closedByCache[id] = who;
        try {
          localStorage.setItem(CLOSED_BY_KEY, JSON.stringify(closedByCache));
        } catch {
          // Storage blocked: kept until a reload only.
        }
        setClosedBy({ ...closedByCache });
      }
    }
    load();
    return () => {
      stopped = true;
    };
  }, [state, closedIds]);

  function changeFolded(next: string[]) {
    foldedKept = next;
    setFolded(next);
  }

  const muted = "text-muted-foreground tabular-nums";
  const link = "block truncate font-medium hover:underline";

  // The open tab's columns (th: its width) and rows, every row with its repository and one cell per column.
  let columns: { title: string; th: string; td: string }[] = [];
  let rows: { key: string; repo: string; cells: ReactNode[] }[] = [];
  if (state === "progress") {
    columns = [
      { title: "Issue", th: "", td: "" },
      { title: "Step", th: "w-28", td: "" },
      { title: "Status", th: "w-48", td: "" },
      { title: "Updated", th: "w-32", td: muted },
    ];
    rows = inProgress.map((job) => {
      const [repo, number] = (job.issue ?? "").split("#");
      const step = job.step === null ? "" : job.step.charAt(0).toUpperCase() + job.step.slice(1).replace("_", " ");
      return {
        key: job.id,
        repo: job.repo ?? repo,
        cells: [
          <a href={`https://github.com/${repo}/issues/${number}`} target="_blank" rel="noreferrer" className={link}>
            #{number} {job.title}
          </a>,
          step,
          <span className="flex items-center gap-2">
            <StatusDot tone={JOB_TONE[job.status]} />
            {JOB_LABEL[job.status]}
          </span>,
          new Date(job.updated_at).toLocaleString("en", TIME),
        ],
      };
    });
  }
  if (state === "open") {
    columns = [
      { title: "Pull request", th: "", td: "" },
      { title: "Comments", th: "w-24 text-right", td: "text-right tabular-nums" },
      { title: "Opened", th: "w-32", td: muted },
      { title: "Updated", th: "w-32", td: muted },
    ];
    rows = open.map((pr) => ({
      key: pr.id,
      repo: pr.repo,
      cells: [
        <a href={pr.url} target="_blank" rel="noreferrer" className={link}>
          #{pr.number} {pr.title}
        </a>,
        pr.comments,
        new Date(pr.opened_at).toLocaleString("en", TIME),
        new Date(pr.updated_at).toLocaleString("en", TIME),
      ],
    }));
  }
  if (state === "merged") {
    columns = [
      { title: "Pull request", th: "", td: "" },
      { title: "Opened", th: "w-32", td: muted },
      { title: "Merged", th: "w-32", td: muted },
      { title: "Merged by", th: "w-40", td: "truncate" },
    ];
    rows = merged.map((pr) => ({
      key: pr.id,
      repo: pr.repo,
      cells: [
        <a href={pr.url} target="_blank" rel="noreferrer" className={link}>
          #{pr.number} {pr.title}
        </a>,
        new Date(pr.opened_at).toLocaleString("en", TIME),
        pr.closed_at !== null ? new Date(pr.closed_at).toLocaleString("en", TIME) : "",
        pr.merged_by ?? "",
      ],
    }));
  }
  if (state === "closed") {
    columns = [
      { title: "Pull request", th: "", td: "" },
      { title: "Opened", th: "w-32", td: muted },
      { title: "Closed", th: "w-32", td: muted },
      { title: "Closed by", th: "w-40", td: "truncate" },
    ];
    rows = closed.map((pr) => ({
      key: pr.id,
      repo: pr.repo,
      cells: [
        <a href={pr.url} target="_blank" rel="noreferrer" className={link}>
          #{pr.number} {pr.title}
        </a>,
        new Date(pr.opened_at).toLocaleString("en", TIME),
        pr.closed_at !== null ? new Date(pr.closed_at).toLocaleString("en", TIME) : "",
        closedBy[pr.id] === undefined ? <span className="text-muted-foreground">Loading…</span> : closedBy[pr.id] !== "" ? closedBy[pr.id] : "Unknown",
      ],
    }));
  }

  // Group by repository, in the order of each one's newest row.
  const repos: string[] = [];
  const byRepo: Record<string, typeof rows> = {};
  for (const row of rows) {
    if (byRepo[row.repo] === undefined) {
      repos.push(row.repo);
      byRepo[row.repo] = [];
    }
    byRepo[row.repo].push(row);
  }
  const keys = repos.map((repo) => `${state}:${repo}`);

  // Like the header's tabs (App.tsx): quiet until hovered; the open one in full color with the accent under it.
  const tab = "relative flex h-full items-center gap-1.5 px-2 font-medium text-muted-foreground hover:text-foreground";
  const currentTab = "text-foreground after:absolute after:inset-x-2 after:-bottom-px after:h-0.5 after:rounded-full after:bg-primary";
  const th = "sticky top-0 z-10 h-8 border-b bg-background px-3 text-left text-xs font-medium text-muted-foreground";
  const td = "h-9 border-b px-3 whitespace-nowrap";

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-9 shrink-0 items-center border-b px-1">
        {TABS.map((each) => (
          <a
            key={each.state}
            href={`#/pulls?state=${each.state}`}
            aria-current={each.state === state ? "page" : undefined}
            className={cn(tab, each.state === state && currentTab)}
          >
            {each.title}
            <span className="text-muted-foreground tabular-nums">{counts[each.state]}</span>
          </a>
        ))}
        {repos.length > 0 && (
          <div className="ml-auto flex gap-1 pr-2">
            <Button size="xs" variant="ghost" onClick={() => changeFolded(folded.filter((key) => !keys.includes(key)))}>
              Expand all
            </Button>
            <Button size="xs" variant="ghost" onClick={() => changeFolded([...folded.filter((key) => !keys.includes(key)), ...keys])}>
              Collapse all
            </Button>
          </div>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {rows.length === 0 && <div className="p-3 text-muted-foreground">{state === "progress" ? "No issues in progress." : "No pull requests."}</div>}
        {rows.length > 0 && (
          <table className="w-full min-w-[640px] table-fixed">
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column.title} className={cn(th, column.th)}>
                    {column.title}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {repos.map((repo) => {
                const key = `${state}:${repo}`;
                const isFolded = folded.includes(key);
                return (
                  <Fragment key={repo}>
                    <tr className="bg-muted/40">
                      <td colSpan={columns.length} className="h-9 border-b p-0">
                        <button
                          type="button"
                          className="flex h-9 w-full items-center gap-2 px-2 text-left hover:bg-accent/50"
                          aria-expanded={!isFolded}
                          onClick={() => changeFolded(isFolded ? folded.filter((each) => each !== key) : [...folded, key])}
                        >
                          <ChevronRight className={cn("size-3.5 text-muted-foreground transition-transform", !isFolded && "rotate-90")} />
                          <img src={`https://github.com/${repo.split("/")[0]}.png?size=32`} alt="" className="size-4 rounded-sm" />
                          <span className="font-medium">{repo}</span>
                          <span className="text-muted-foreground tabular-nums">{byRepo[repo].length}</span>
                        </button>
                      </td>
                    </tr>
                    {!isFolded &&
                      byRepo[repo].map((row) => (
                        <tr key={row.key} className="hover:bg-accent/50">
                          {row.cells.map((cell, index) => (
                            <td key={columns[index].title} className={cn(td, index === 0 && "pl-9", columns[index].td)}>
                              {cell}
                            </td>
                          ))}
                        </tr>
                      ))}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
