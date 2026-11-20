/*
Settings → Fix problems: every day at a set time, Claude Code works through the open feedback on the Feedback page
(github_searcher/problems.py), each fix with a regression test; the fixes that pass the tests are pushed to main, main is released, and the live
copy installs the release by itself (github_searcher/problem_fixes.py has how it works).

The switch turns the daily run on or off, and the time (this computer's) says when; each change is saved at once. Fix
now starts a run straight away. Below, the last runs: when, how it went (fixed, released, or why not), the commits
pushed, the ones it closed with no change needed and the ones it left open, each with why.

GET /api/problem_fixes each time Settings opens and after every change.
*/

import { Loader2, Play } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { api } from "@/live";
import { timeAgo } from "@/lib/utils";

type Run = {
  started_at: string;
  ended_at: string | null;
  state: "running" | "done" | "failed";
  problems: string[];
  fixed: string[];
  no_change?: { id: string; why: string }[]; // closed with nothing to change in the app (not on runs from before)
  not_fixed: { id: string; why: string }[];
  commits: string[];
  release: string | null;
  error: string;
  output: string;
  cost_usd: number | null;
};

type Status = { on: boolean; hour: number; minute: number; runs: Run[]; running: boolean; repo: string };

// How many of the last runs show.
const SHOWN_RUNS = 5;

export default function ProblemFixes(props: { open: boolean }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState("");
  // Goes up after each change, so the status is asked again.
  const [changed, setChanged] = useState(0);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    if (!props.open) {
      return;
    }
    let stopped = false;
    api<Status>("/api/problem_fixes")
      .then((data) => {
        if (!stopped) {
          setStatus(data);
        }
      })
      .catch((err) => {
        if (!stopped) {
          setError(`Could not load Fix problems: ${err instanceof Error ? err.message : err}`);
        }
      });
    return () => {
      stopped = true;
    };
  }, [props.open, changed]);

  async function save(on: boolean, time: string) {
    const [hour, minute] = time.split(":").map(Number);
    setError("");
    try {
      setStatus(await api<Status>("/api/problem_fixes", { method: "PUT", body: { on: on, hour: hour, minute: minute } }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function fixNow() {
    setStarting(true);
    setError("");
    try {
      await api("/api/problem_fixes/run", { method: "POST" });
      toast.success("Fixing the problems now. It can take an hour or more.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
    setStarting(false);
    setChanged(changed + 1);
  }

  const time = status === null ? "" : `${String(status.hour).padStart(2, "0")}:${String(status.minute).padStart(2, "0")}`;

  return (
    <section>
      <div className="mb-2 font-medium">Fix problems</div>
      {error !== "" && <p className="mb-2 border border-destructive/40 bg-destructive/10 px-3 py-1.5 text-destructive">{error}</p>}
      {status === null && error === "" && (
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" /> Loading…
        </div>
      )}
      {status !== null && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Switch checked={status.on} onCheckedChange={(on) => save(on, time)} />
            <span>Every day at</span>
            <Input
              type="time"
              className="w-28"
              value={time}
              onChange={(event) => {
                if (event.target.value !== "") {
                  save(status.on, event.target.value);
                }
              }}
            />
            <Button variant="outline" size="sm" className="ml-auto" onClick={fixNow} disabled={starting || status.running}>
              {starting || status.running ? <Loader2 className="animate-spin" /> : <Play />} Fix now
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Claude Code fixes every open problem, each with a regression test. Fixes that pass the tests and the build are pushed to{" "}
            {status.repo || "the app's repo"}, main is released, and this copy installs the release by itself (a bad one is taken back).
          </p>

          {status.runs.slice(0, SHOWN_RUNS).map((run) => (
            <div key={run.started_at} className="space-y-1 rounded-lg border p-2.5">
              <div className="flex items-center gap-2">
                <span>{timeAgo(run.started_at)}</span>
                {run.state === "running" && (
                  <span className="flex items-center gap-1.5 text-muted-foreground">
                    <Loader2 className="size-3.5 animate-spin" /> Running, {run.problems.length} problems
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
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
