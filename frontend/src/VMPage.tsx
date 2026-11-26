/*
One VM's page, in a dialog over the Dashboard (#/vms/<name>, Dashboard.tsx): a header with its state and power
buttons, and three tabs. The header leaves room on its right for the dialog's close button.

Overview is the VM's desktops, the whole page. A VM has one desktop or more, up to its max desktops (Settings). The
app adds and removes them by itself (github_searcher/agents.py): one is added when an agent needs one and none is free,
and one nobody used for a while shuts down (its home stays). Each has its own screen, mouse, keyboard and home folder,
so agents on different desktops work at the same time without getting in each other's way. Each keeps its number:
removing desktop 1 leaves desktops 2 and 3 as they are.

With more than one, the Overview shows them all, two to a row, live and view-only (LiveDesktop.tsx, at most 30
updates a second). Each one's caption has its dot (green while free, amber while someone, an agent or you, holds it),
who holds it, and a lock while it is locked. Clicking one fills the Overview with it, on the same connection, and gives
it your mouse and keyboard; the left arrow above it goes back to all of them. With one desktop, the Overview is that
desktop. A dropped connection comes back by itself (LiveDesktop.tsx tries again every 2 seconds).
Resources is VMResources: copy files and folders between this computer and the VM (only you; agents can't).
Settings is VMSettings. Fork (only while stopped) makes a new VM that starts as a copy of this one (ForkVMDialog).

Desktops are connected only while they are on screen: closing the dialog, opening Resources or Settings, or filling
the Overview with one desktop disconnects the others. The dialog opens on the Overview every time: the grid, or, from
#/vms/<name>?desktop=n (the Dashboard's Agents table), desktop n filling it. Desktops exist only
while the VM runs; their addresses come from GET /api/vms/{name}/viewer?desktop=n, asked again (every 3 s) until the
VM has them. A VM from a terminal-only image has no desktop: the Overview shows its terminal (ttyd, in an iframe).

When the desktop filling the Overview is locked (by an agent while it works), a cover stops clicks and keys from
reaching it, with an Unlock button. Over each desktop, the agent's cursor (AgentCursor.tsx) shows where the agent on it clicks, with
its name: white while it works, gray while it doesn't.

When the VM runs but doesn't answer (still booting, or frozen: Incus still says Running), a notice over
the desktop says so and offers Restart. Once it answers again after more than a few seconds, the desktop
reconnects by itself: a connection the VM dropped while it was down can wait forever without noticing.
*/

import { ArrowLeft, Copy, Loader2, Lock, Monitor, Play, Power, RotateCw, Square, Unlock } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import AgentCursor from "@/AgentCursor";
import ForkVMDialog from "@/ForkVMDialog";
import LiveDesktop from "@/LiveDesktop";
import VMResources from "@/VMResources";
import VMSettings from "@/VMSettings";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatusDot, VM_TONE } from "@/components/ui/status-dot";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, useLive, useLoaded } from "@/live";
import { cn } from "@/lib/utils";

const STATUS_TEXT: Record<string, string> = {
  creating: "Creating",
  running: "Running",
  stopping: "Stopping",
  stopped: "Stopped",
  starting: "Starting",
  failed: "Failed",
  missing: "Missing",
};

export default function VMPage(props: { name: string; desktop: number | null }) {
  const vms = useLive("vms");
  const loaded = useLoaded("vms");
  const imagesData = useLive("images");
  const agents = useLive("agents");
  const [tab, setTab] = useState("overview");
  // Each desktop's noVNC page by its number (1, 2, 3), once known.
  const [desktopUrls, setDesktopUrls] = useState<Record<number, string>>({});
  // The VM has no desktop (a terminal-only image): desktopUrls[1] is its terminal.
  const [terminalOnly, setTerminalOnly] = useState(false);
  // The desktop clicked in the grid, filling the Overview, or null for the grid.
  const [open, setOpen] = useState<number | null>(props.desktop);
  const [viewerError, setViewerError] = useState("");
  // Bumped when the VM answers again after a while: a new key connects the desktops again.
  const [reload, setReload] = useState(0);
  // The button whose request is on its way, e.g. "start" or "unlock".
  const [busy, setBusy] = useState("");
  const [forking, setForking] = useState(false);
  // When the VM stopped answering (Date.now()), or null while it answers.
  const silentSince = useRef<number | null>(null);

  const name = props.name;
  const vm = vms.find((each) => each.name === name);
  const running = vm !== undefined && vm.status === "running";
  const count = vm !== undefined ? vm.desktops.length : 1;
  // The VM's desktops by number, e.g. [2, 3] after desktop 1 was removed.
  const numbers = vm !== undefined ? vm.desktops.map((each) => each.number) : [1];
  const numbersKey = numbers.join(",");
  // The desktop filling the Overview: the only one, or the one clicked (while it's still there). null: the grid.
  let full: number | null = null;
  if (count === 1) {
    full = numbers[0];
  }
  if (count > 1 && open !== null && numbers.includes(open)) {
    full = open;
  }
  const fullUrl = full !== null ? (desktopUrls[full] ?? null) : null;
  const ready = Object.keys(desktopUrls).length > 0;
  const silent = running && vm.usage !== null && vm.usage.on && !vm.usage.responding;

  // Ask where each desktop is once the VM runs; forget them when it stops.
  useEffect(() => {
    if (!running) {
      setDesktopUrls({});
      setViewerError("");
      return;
    }
    let stopped = false;
    let timer = 0;
    async function load() {
      try {
        const urls: Record<number, string> = {};
        let terminal = false;
        for (const number of numbersKey.split(",").map(Number)) {
          const answer = await api<{ desktop: string | null; terminal: string | null }>(
            `/api/vms/${encodeURIComponent(name)}/viewer?desktop=${number}`,
          );
          urls[number] = answer.desktop ?? answer.terminal ?? "";
          terminal = answer.desktop === null;
          // A terminal-only image has no desktops: its one terminal is all there is.
          if (terminal) {
            break;
          }
        }
        if (stopped) {
          return;
        }
        setDesktopUrls(urls);
        setTerminalOnly(terminal);
        setViewerError("");
      } catch (err) {
        if (stopped) {
          return;
        }
        // Right after a start the VM has no address yet: try again shortly.
        setViewerError(err instanceof Error ? err.message : String(err));
        timer = window.setTimeout(load, 3000);
      }
    }
    load();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [name, running, numbersKey]);

  // Reload the desktop when the VM answers again after a while (a blip of a second or two doesn't count).
  useEffect(() => {
    if (silent) {
      silentSince.current = Date.now();
      return;
    }
    if (silentSince.current !== null && Date.now() - silentSince.current > 5000) {
      setReload((current) => current + 1);
    }
    silentSince.current = null;
  }, [silent]);

  if (!loaded) {
    return <div className="p-3 text-muted-foreground">Loading…</div>;
  }
  if (vm === undefined) {
    return (
      <div className="p-3 text-muted-foreground">
        There is no VM named {name}.{" "}
        <a href="#/vms" className="text-primary hover:underline">
          All VMs
        </a>
      </div>
    );
  }

  const agentById: Record<string, (typeof agents)[number]> = {};
  for (const agent of agents) {
    agentById[agent.id] = agent;
  }
  // Who holds each desktop, by its number: "" while it's free.
  const holders: Record<number, string> = {};
  for (const each of vm.desktops) {
    holders[each.number] = "";
    if (each.holder === "user") {
      holders[each.number] = "You";
    }
    if (each.holder !== null && each.holder !== "user") {
      holders[each.number] = agentById[each.holder]?.name ?? each.holder;
    }
  }
  const error = vm.error;
  // The image's name now (it may have been renamed since), or the name it was made with.
  const madeFrom = imagesData.images.find((image) => image.fingerprint === vm.image_fingerprint);
  const imageName = madeFrom !== undefined ? madeFrom.name : vm.image || "unknown image";

  async function power(action: "start" | "stop" | "restart") {
    setBusy(action);
    try {
      await api(`/api/vms/${encodeURIComponent(name)}/${action}`, { method: "POST" });
    } catch (err) {
      toast.error(`Could not ${action} ${name}: ${err instanceof Error ? err.message : err}`);
    }
    setBusy("");
  }

  async function unlock() {
    setBusy("unlock");
    try {
      await api(`/api/vms/${encodeURIComponent(name)}/lock`, { method: "PUT", body: { enabled: false, desktop: full } });
    } catch (err) {
      toast.error(`Could not unlock the desktop: ${err instanceof Error ? err.message : err}`);
    }
    setBusy("");
  }

  const canStart = vm.status === "stopped" || vm.status === "failed";

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-9 shrink-0 items-center gap-2 border-b pr-10 pl-3">
        <Monitor className="size-4 text-muted-foreground" />
        <h1 className="font-semibold">{vm.name}</h1>
        <Badge variant="secondary" title={error ?? undefined}>
          <StatusDot tone={VM_TONE[vm.status]} />
          {STATUS_TEXT[vm.status] ?? vm.status}
        </Badge>
        <span className="text-muted-foreground">
          {imageName}
          {vm.forked_from !== "" && ` · forked from ${vm.forked_from}`}
          {vm.internet ? "" : " · no internet"}
        </span>
        <div className="ml-2 flex items-center gap-1">
          <Button variant="outline" size="sm" disabled={!canStart || busy !== ""} onClick={() => power("start")}>
            {busy === "start" ? <Loader2 className="animate-spin" /> : <Play />} Start
          </Button>
          <Button variant="outline" size="sm" disabled={!running || busy !== ""} onClick={() => power("stop")}>
            {busy === "stop" ? <Loader2 className="animate-spin" /> : <Square />} Stop
          </Button>
          <Button variant="outline" size="sm" disabled={!running || busy !== ""} onClick={() => power("restart")}>
            {busy === "restart" ? <Loader2 className="animate-spin" /> : <RotateCw />} Restart
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={vm.status !== "stopped" || busy !== ""}
            title={vm.status === "stopped" ? `A new VM that starts as a copy of ${vm.name}` : `Stop ${vm.name} to fork it`}
            onClick={() => setForking(true)}
          >
            <Copy /> Fork
          </Button>
        </div>
        <Tabs value={tab} onValueChange={setTab} className="ml-auto max-w-full overflow-x-auto">
          <TabsList>
            <TabsTrigger value="overview" className="px-2.5">
              Overview
            </TabsTrigger>
            <TabsTrigger value="resources" className="px-2.5">
              Resources
            </TabsTrigger>
            <TabsTrigger value="settings" className="px-2.5">
              Settings
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {/* Only while the Overview is open: the desktops connect when it shows and disconnect when it doesn't. */}
      {tab === "overview" && (
        <div className="flex min-h-0 flex-1 flex-col">
          {full !== null && count > 1 && (
            <div className="flex h-7 shrink-0 items-center border-b bg-muted/40 px-1">
              <Button variant="icon" size="icon-xs" title="All desktops" aria-label="All desktops" onClick={() => setOpen(null)}>
                <ArrowLeft />
              </Button>
            </div>
          )}
          <div className="relative min-h-0 flex-1 bg-muted/30">
            {running && terminalOnly && fullUrl !== null && (
              <iframe
                key={`${fullUrl}-${reload}`}
                src={fullUrl}
                title={`Terminal of ${vm.name}`}
                allow="clipboard-write"
                className="absolute inset-0 size-full border-0 bg-black"
              />
            )}

            {/* The grid, or the one desktop filling it. The same element either way, so opening one keeps its connection. */}
            {running && !terminalOnly && (
              <div className={full === null ? "absolute inset-0 grid grid-cols-2 content-start gap-3 overflow-y-auto p-3" : "absolute inset-0"}>
                {numbers.map((number) => {
                  const url = desktopUrls[number];
                  if (url === undefined || (full !== null && number !== full)) {
                    return null;
                  }
                  const lockedBy = vm.locked_by[number];
                  const holder = holders[number];
                  return (
                    <div
                      key={number}
                      className={full === null ? "group flex min-w-0 cursor-pointer flex-col gap-1" : "h-full"}
                      onClick={full === null ? () => setOpen(number) : undefined}
                    >
                      {full === null && (
                        <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                          <span className={cn("size-2 shrink-0 rounded-full", holder === "" ? "bg-ok" : "bg-warn")} />
                          Desktop {number}
                          {holder !== "" && <span className="truncate font-normal">· {holder}</span>}
                          {lockedBy !== undefined && <Lock className="size-3 shrink-0 text-warn" />}
                        </div>
                      )}
                      <div
                        className={
                          full === null
                            ? "relative aspect-[16/10] overflow-hidden rounded-md border bg-black group-hover:ring-2 group-hover:ring-primary"
                            : "relative h-full"
                        }
                      >
                        <LiveDesktop
                          key={reload}
                          url={`ws://${new URL(url).host}/websockify`}
                          viewOnly={full === null || lockedBy !== undefined}
                          className={cn("absolute inset-0 bg-black", full === null && "pointer-events-none")}
                        />
                        <AgentCursor vm={vm} desktop={number} />
                        {full !== null && lockedBy !== undefined && (
                          <div className="absolute inset-0 cursor-not-allowed">
                            <div className="absolute top-2 left-1/2 flex -translate-x-1/2 items-center gap-2 rounded-md border bg-background py-1 pr-1 pl-2.5 whitespace-nowrap">
                              <Lock className="size-3.5 text-warn" />
                              {lockedBy === "agent" ? "Locked by the agent while it works" : "You locked your mouse and keyboard out"}
                              <Button size="xs" variant="outline" disabled={busy === "unlock"} onClick={unlock}>
                                <Unlock /> Unlock
                              </Button>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {silent && (
              <div className="absolute inset-x-0 top-2 z-10 flex justify-center px-2">
                <div className="flex items-center gap-2 rounded-md border bg-background py-1 pr-1 pl-2.5">
                  <Loader2 className="size-3.5 animate-spin text-warn" />
                  {vm.name} isn't answering: it is still booting, or it froze.
                  <Button size="xs" variant="outline" disabled={busy !== ""} onClick={() => power("restart")}>
                    <RotateCw /> Restart
                  </Button>
                </div>
              </div>
            )}

            {running && !ready && (
              <div className="flex h-full flex-col items-center justify-center gap-1 text-muted-foreground">
                <span className="flex items-center gap-2">
                  <Loader2 className="size-3.5 animate-spin" /> Connecting…
                </span>
                {viewerError !== "" && <span className="text-xs">{viewerError} Trying again.</span>}
              </div>
            )}

            {!running && (
              <div className="flex h-full flex-col items-center justify-center gap-2 px-4 text-center text-muted-foreground">
                {(vm.status === "creating" || vm.status === "starting" || vm.status === "stopping") && (
                  <span className="flex items-center gap-2">
                    <Loader2 className="size-3.5 animate-spin" />
                    {vm.status === "creating" && `Creating ${vm.name}. This takes about a minute.`}
                    {vm.status === "starting" && `Starting ${vm.name}…`}
                    {vm.status === "stopping" && `Stopping ${vm.name}…`}
                  </span>
                )}
                {(vm.status === "stopped" || vm.status === "failed") && (
                  <>
                    <Power className="size-6" />
                    <span>{vm.status === "stopped" ? `${vm.name} is off.` : `${vm.name} failed.`}</span>
                    {error !== null && <span className="max-w-lg text-xs text-destructive">{error}</span>}
                    <Button size="sm" disabled={busy !== ""} onClick={() => power("start")}>
                      {busy === "start" ? <Loader2 className="animate-spin" /> : <Play />} Start
                    </Button>
                  </>
                )}
                {vm.status === "missing" && (
                  <span>
                    The Incus VM {vm.incus_name} is gone. Delete {vm.name} in Settings, or bring the Incus VM back.
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "resources" && (
        <div className="min-h-0 flex-1">
          <VMResources name={vm.name} />
        </div>
      )}

      {tab === "settings" && (
        <div className="min-h-0 flex-1">
          <VMSettings name={vm.name} />
        </div>
      )}

      {forking && <ForkVMDialog vm={vm.name} onClose={() => setForking(false)} />}
    </div>
  );
}
