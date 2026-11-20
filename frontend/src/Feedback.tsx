/*
Feedback (#/feedback): anything that went wrong or could go better, so Seraph gets better (github_searcher/problems.py,
the live "problems" topic). The agents report it themselves (report_problem: the app's rules and tools, a maintainer
who was unhappy with us, an issue that was already taken, a VM that ran out of memory, ...), and the app adds what it
sees on its own, like a GitHub token that stopped working (From: Seraph). Fix problems in Settings works through the
open ones every day and closes them.

Two tabs (state= in the address): Open (the default) and Closed. A table, newest first: About (the issue or pull
request, opens on GitHub), Feedback (its text, three lines until clicked), From (the agent, opens its chat), Reported,
and Closed on the Closed tab. Only reads; nothing here changes anything.
*/

import { useState } from "react";

import { useLive } from "@/live";
import { cn } from "@/lib/utils";

// "Nov 18, 14:32"
const TIME: Intl.DateTimeFormatOptions = { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" };

export default function Feedback(props: { state: string }) {
  const items = useLive("problems");
  const agents = useLive("agents");
  // The rows whose whole text shows, by id.
  const [expanded, setExpanded] = useState<string[]>([]);

  const closed = props.state === "closed";
  const openItems = items.filter((item) => item.closed_at === null);
  const closedItems = items.filter((item) => item.closed_at !== null);
  const rows = closed ? closedItems : openItems;

  // Like the Pull requests page's tabs: quiet until hovered; the open one in full color with the accent under it.
  const tab = "relative flex h-full items-center gap-1.5 px-2 font-medium text-muted-foreground hover:text-foreground";
  const currentTab = "text-foreground after:absolute after:inset-x-2 after:-bottom-px after:h-0.5 after:rounded-full after:bg-primary";
  const th = "sticky top-0 z-10 h-8 border-b bg-background px-3 text-left text-xs font-medium text-muted-foreground";
  const td = "border-b px-3 py-2 align-top";

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-9 shrink-0 items-center border-b px-1">
        <a href="#/feedback" aria-current={!closed ? "page" : undefined} className={cn(tab, !closed && currentTab)}>
          Open
          <span className="text-muted-foreground tabular-nums">{openItems.length}</span>
        </a>
        <a href="#/feedback?state=closed" aria-current={closed ? "page" : undefined} className={cn(tab, closed && currentTab)}>
          Closed
          <span className="text-muted-foreground tabular-nums">{closedItems.length}</span>
        </a>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {rows.length === 0 && <div className="p-3 text-muted-foreground">No feedback.</div>}
        {rows.length > 0 && (
          <table className="w-full min-w-[860px] table-fixed">
            <thead>
              <tr>
                <th className={cn(th, "w-52")}>About</th>
                <th className={th}>Feedback</th>
                <th className={cn(th, "w-36")}>From</th>
                <th className={cn(th, "w-32")}>Reported</th>
                {closed && <th className={cn(th, "w-32")}>Closed</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((item) => {
                const [repo, number] = (item.about ?? "").split("#");
                const agent = agents.find((each) => each.id === item.agent);
                const whole = expanded.includes(item.id);
                return (
                  <tr key={item.id}>
                    <td className={cn(td, "truncate")}>
                      {item.about !== null && number !== undefined && (
                        <a href={`https://github.com/${repo}/issues/${number}`} target="_blank" rel="noreferrer" className="hover:underline">
                          {item.about}
                        </a>
                      )}
                      {item.about !== null && number === undefined && <span>{item.about}</span>}
                    </td>
                    <td className={td}>
                      <div
                        className={cn("cursor-pointer whitespace-pre-wrap", !whole && "line-clamp-3")}
                        onClick={() => setExpanded(whole ? expanded.filter((id) => id !== item.id) : [...expanded, item.id])}
                      >
                        {item.text}
                      </div>
                    </td>
                    <td className={cn(td, "truncate text-muted-foreground")}>
                      {item.agent === "seraph" && "Seraph"}
                      {item.agent !== "seraph" && (
                        <a href={`#/agents/${encodeURIComponent(item.agent)}`} className="hover:underline">
                          {agent?.name ?? item.agent}
                        </a>
                      )}
                    </td>
                    <td className={cn(td, "text-muted-foreground tabular-nums")}>{new Date(item.at).toLocaleString("en", TIME)}</td>
                    {closed && (
                      <td className={cn(td, "text-muted-foreground tabular-nums")}>
                        {item.closed_at !== null && new Date(item.closed_at).toLocaleString("en", TIME)}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
