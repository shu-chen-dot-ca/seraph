/*
Blockers (#/blockers): what only you can do, like signing a contributor agreement. They are the agents' approval
requests (ask_approval, drafts of kind "approval" in the live "inbox" topic) still waiting, newest first, in a table:
Type (Agreement or Other), Repository, Request (its title, and its text under it), Pull request (the one that waits on
it, opens on GitHub), Created, and Open (the link the agent gave: where to sign, for an agreement).
Done (POST /api/inbox/<id>/approve): you did it, the agent goes on. Skip (POST /api/inbox/<id>/reject): the agent gives
the job up. A row's buttons are disabled while its request runs; the row leaves once the live feed drops it.
*/

import { ExternalLink, Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, useLive } from "@/live";
import { cn } from "@/lib/utils";

// "Nov 18, 14:32"
const TIME: Intl.DateTimeFormatOptions = { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" };

export default function Blockers() {
  const inbox = useLive("inbox");
  const blockers = inbox.filter((draft) => draft.kind === "approval" && draft.status === "pending");
  blockers.sort((a, b) => b.created_at.localeCompare(a.created_at));
  // The blockers whose Done or Skip is on its way, by id: "approve" or "reject".
  const [busy, setBusy] = useState<Record<string, string>>({});

  async function decide(id: string, action: "approve" | "reject") {
    setBusy((old) => ({ ...old, [id]: action }));
    try {
      await api(`/api/inbox/${id}/${action}`, { method: "POST" });
      toast.success(action === "approve" ? "Marked done" : "Skipped");
    } catch (err) {
      toast.error(`Could not ${action === "approve" ? "mark it done" : "skip it"}: ${err instanceof Error ? err.message : err}`);
    }
    setBusy((old) => ({ ...old, [id]: "" }));
  }

  const th = "sticky top-0 z-10 h-8 border-b bg-background px-3 text-left text-xs font-medium text-muted-foreground";
  const td = "border-b px-3 py-2 align-top";

  return (
    <div className="flex h-full flex-col">
      <div className="flex min-h-9 shrink-0 items-center border-b px-3 py-1">
        <span className="font-medium">Blockers</span>
        <span className="ml-2 text-muted-foreground tabular-nums">{blockers.length}</span>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {blockers.length === 0 && <div className="p-3 text-muted-foreground">No blockers.</div>}
        {blockers.length > 0 && (
          <table className="w-full min-w-[860px] table-fixed">
            <thead>
              <tr>
                <th className={cn(th, "w-28")}>Type</th>
                <th className={cn(th, "w-52")}>Repository</th>
                <th className={th}>Request</th>
                <th className={cn(th, "w-28")}>Pull request</th>
                <th className={cn(th, "w-32")}>Created</th>
                <th className={cn(th, "w-52")} />
              </tr>
            </thead>
            <tbody>
              {blockers.map((draft) => {
                const [repo, number] = (draft.target ?? "").split("#");
                const link = draft.overview.link ?? "";
                return (
                  <tr key={draft.id}>
                    <td className={td}>
                      <Badge variant={draft.overview.kind === "cla" ? "warn" : "secondary"}>{draft.overview.kind === "cla" ? "Agreement" : "Other"}</Badge>
                    </td>
                    <td className={cn(td, "truncate text-muted-foreground")}>{draft.repo}</td>
                    <td className={td}>
                      <div className="font-medium">{draft.title}</div>
                      <div className="line-clamp-2 text-muted-foreground">{draft.body}</div>
                    </td>
                    <td className={td}>
                      {draft.target !== null && (
                        <a href={`https://github.com/${repo}/issues/${number}`} target="_blank" rel="noreferrer" className="hover:underline">
                          #{number}
                        </a>
                      )}
                    </td>
                    <td className={cn(td, "text-muted-foreground tabular-nums")}>{new Date(draft.created_at).toLocaleString("en", TIME)}</td>
                    <td className={td}>
                      <div className="flex justify-end gap-1.5">
                        {link !== "" && (
                          <Button size="xs" asChild>
                            <a href={link} target="_blank" rel="noreferrer">
                              <ExternalLink className="size-3.5" />
                              Open
                            </a>
                          </Button>
                        )}
                        <Button size="xs" variant="outline" disabled={(busy[draft.id] ?? "") !== ""} onClick={() => decide(draft.id, "approve")}>
                          {busy[draft.id] === "approve" && <Loader2 className="animate-spin" />}
                          Done
                        </Button>
                        <Button size="xs" variant="outline" disabled={(busy[draft.id] ?? "") !== ""} onClick={() => decide(draft.id, "reject")}>
                          {busy[draft.id] === "reject" && <Loader2 className="animate-spin" />}
                          Skip
                        </Button>
                      </div>
                    </td>
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
