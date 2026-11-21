/*
Feedback → Runs: Fix all's runs, newest first (github_searcher/problem_fixes.py). Each: when, how it went (fixed,
released, or why not), the commits pushed, the items it closed with no change needed, the ones it left open and the ones
it closed after too many tries, each with why. A run going on links to Seraph's VM, where its terminal shows what Claude
Code does.

Only reads: Feedback.tsx asks for the runs and passes them in.
*/

import { Loader2 } from "lucide-react";

import { timeAgo } from "@/lib/utils";

export type Run = {
  started_at: string;
  ended_at: string | null;
  state: "running" | "done" | "failed";
  problems: string[];
  fixed: string[];
  no_change?: { id: string; why: string }[]; // closed with nothing to change in the app (not on runs from before)
  not_fixed: { id: string; why: string }[];
  given_up?: { id: string; why: string }[]; // closed after too many runs (not on runs from before)
  commits: string[];
  release: string | null;
  error: string;
  output: string;
  cost_usd: number | null;
};

export default function FeedbackRuns(props: { runs: Run[]; vm: string }) {
  if (props.runs.length === 0) {
    return <div className="p-3 text-muted-foreground">No runs.</div>;
  }
  return (
    <div className="space-y-2 p-3">
      {props.runs.map((run) => (
        <div key={run.started_at} className="space-y-1 rounded-lg border p-2.5">
          <div className="flex items-center gap-2">
            <span>{timeAgo(run.started_at)}</span>
            {run.state === "running" && (
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin" /> Running, {run.problems.length} items, in
                <a href={`#/vms/${encodeURIComponent(props.vm)}`} className="text-primary hover:underline">
                  {props.vm}
                </a>
              </span>
            )}
            {run.state === "done" && (
              <span className="text-muted-foreground">
                Fixed {run.fixed.length} of {run.problems.length}
                {run.release !== null ? `, released ${run.release}` : ", nothing new to release"}
              </span>
            )}
            {run.state === "failed" && <span className="text-destructive">Failed</span>}
            {run.cost_usd !== null && <span className="ml-auto text-xs text-muted-foreground">${run.cost_usd.toFixed(2)}</span>}
          </div>
          {run.error !== "" && <p className={run.state === "failed" ? "text-destructive" : "text-warn"}>{run.error}</p>}
          {run.output !== "" && (
            <pre className="max-h-32 overflow-auto rounded bg-muted p-2 font-mono text-xs whitespace-pre-wrap">{run.output}</pre>
          )}
          {run.commits.length > 0 && (
            <div className="font-mono text-xs text-muted-foreground">
              {run.commits.map((commit) => (
                <div key={commit} className="truncate">
                  {commit}
                </div>
              ))}
            </div>
          )}
          {(run.no_change ?? []).length > 0 && (
            <div className="text-xs text-muted-foreground">
              {(run.no_change ?? []).map((each) => (
                <div key={each.id}>
                  Closed with no change {each.id}: {each.why}
                </div>
              ))}
            </div>
          )}
          {run.not_fixed.length > 0 && (
            <div className="text-xs text-muted-foreground">
              {run.not_fixed.map((each) => (
                <div key={each.id}>
                  Left open {each.id}: {each.why}
                </div>
              ))}
            </div>
          )}
          {(run.given_up ?? []).length > 0 && (
            <div className="text-xs text-muted-foreground">
              {(run.given_up ?? []).map((each) => (
                <div key={each.id}>
                  Closed {each.id}: {each.why}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
