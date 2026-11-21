/*
One VM's page, in a dialog over the Dashboard (#/vms/<name>, Dashboard.tsx): a header with its state and power
buttons, and three tabs. The header leaves room on its right for the dialog's close button.

Overview is the VM's desktop (noVNC in an iframe), the whole page.

A VM has one desktop or more, up to its max desktops (Settings). Each has its own screen, mouse, keyboard and home folder, so agents on different
desktops work at the same time without getting in each other's way. Each keeps its number: removing desktop 1 leaves
desktops 2 and 3 as they are, and the next new one is desktop 1 again (the lowest number free). With more than one,
buttons Desktop 1, Desktop 2, ... above the desktop pick which one the desktop area and its Lock are about; each
button's tooltip says who holds it, and its dot is green while the desktop is free, amber while someone (an agent or
you) holds it. × removes the desktop shown (it asks first). + after them adds a desktop and shows it once it is up
(while the VM runs it is set up right away: under a minute the first time; it is gone once the VM has its max
desktops). Both work running or not. A desktop's iframe stays mounted once opened, so switching back is instant.
Resources is VMResources: copy files and folders between this computer and the VM (only you; agents can't).
Settings is VMSettings. Fork (only while stopped) makes a new VM that starts as a copy of this one (ForkVMDialog).

The Overview stays mounted while the Resources or Settings tab is open, so the desktop iframe doesn't reload; the
dialog opens on the Overview every time. The iframe only
exists while the VM runs; its address comes from GET /api/vms/{name}/viewer?desktop=n, asked again (every 3 s)
until the VM has one. A VM from a terminal-only image has no desktop: the same area shows its terminal (ttyd).

When the desktop is locked (by an agent while it works, or by you), a cover stops clicks and keys from reaching it,
with an Unlock button. Over the desktop, the agent's cursor (AgentCursor.tsx) shows where the agent on it clicks, with
its name: white while it works, gray while it doesn't.

When the VM runs but doesn't answer (still booting, or frozen: Incus still says Running), a notice over
the desktop says so and offers Restart. Once it answers again after more than a few seconds, the desktop
reloads by itself: noVNC's own reconnect can't recover a page that failed to load while the VM was down.
*/

import { Copy, ExternalLink, Loader2, Lock, Monitor, Play, Plus, Power, RotateCw, Square, Unlock, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import AgentCursor from "@/AgentCursor";
import ForkVMDialog from "@/ForkVMDialog";
import VMResources from "@/VMResources";
import VMSettings from "@/VMSettings";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
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

export default function VMPage(props: { name: string }) {
  const vms = useLive("vms");
  const loaded = useLoaded("vms");
  const imagesData = useLive("images");
  const agents = useLive("agents");
  const [tab, setTab] = useState("overview");
  // Each desktop's noVNC page by its number (1, 2, 3), once known.
  const [desktopUrls, setDesktopUrls] = useState<Record<number, string>>({});
  // The VM has no desktop (a terminal-only image): desktopUrls[1] is its terminal.
  const [terminalOnly, setTerminalOnly] = useState(false);
  // The desktop shown, and the ones opened since the page loaded (their iframes stay, so switching back is instant).
  const [desk, setDesk] = useState(1);
  const [opened, setOpened] = useState<number[]>([1]);
  const [viewerError, setViewerError] = useState("");
  // Bumped by Reconnect: a new iframe key loads the desktop again.
  const [reload, setReload] = useState(0);
  // The button whose request is on its way, e.g. "start" or "lock".
  const [busy, setBusy] = useState("");
  // × after the last desktop asks "are you sure?" now.
  const [confirmRemove, setConfirmRemove] = useState(false);
  const frameRef = useRef<HTMLIFrameElement>(null);
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
  // A desktop that went away falls back to the VM's first one.
  const shown = numbers.includes(desk) ? desk : numbers[0];
  // The number the next new desktop gets: the lowest one free.
  let nextNumber = 1;
  while (numbers.includes(nextNumber)) {
    nextNumber++;
  }
  const lockedBy = vm !== undefined ? (vm.locked_by[shown] ?? null) : null;
  const locked = lockedBy !== null;
  const desktopUrl = desktopUrls[shown] ?? null;
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

  // When the desktop gets locked, take the keyboard away from it too.
  useEffect(() => {
    if (locked && frameRef.current !== null && document.activeElement === frameRef.current) {
      frameRef.current.blur();
    }
  }, [locked]);

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

  async function setLock(enabled: boolean) {
    if (enabled && frameRef.current !== null) {
      frameRef.current.blur();
    }
    setBusy("lock");
    try {
      await api(`/api/vms/${encodeURIComponent(name)}/lock`, { method: "PUT", body: { enabled: enabled, desktop: shown } });
    } catch (err) {
      toast.error(`Could not ${enabled ? "lock" : "unlock"} the desktop: ${err instanceof Error ? err.message : err}`);
    }
    setBusy("");
  }

  const canStart = vm.status === "stopped" || vm.status === "failed";

  function showDesktop(number: number) {
    setDesk(number);
    if (!opened.includes(number)) {
      setOpened([...opened, number]);
    }
  }

  // Answers once the new desktop is up, then shows it.
  async function addDesktop() {
    setBusy("add_desktop");
    try {
      const answer = await api<{ desktop: number }>(`/api/vms/${encodeURIComponent(name)}/desktops`, { method: "POST" });
      showDesktop(answer.desktop);
    } catch (err) {
      toast.error(`Could not add desktop ${nextNumber}: ${err instanceof Error ? err.message : err}`);
    }
    setBusy("");
  }

  async function removeDesktop(number: number) {
    setBusy("remove_desktop");
    try {
      await api(`/api/vms/${encodeURIComponent(name)}/desktops/${number}`, { method: "DELETE" });
    } catch (err) {
      toast.error(`Could not remove desktop ${number}: ${err instanceof Error ? err.message : err}`);
    }
    setBusy("");
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-9 shrink-0 items-center gap-2 border-b pr-10 pl-3 max-md:h-auto max-md:min-h-9 max-md:flex-wrap max-md:py-1">
        <Monitor className="size-4 text-muted-foreground" />
        <h1 className="font-semibold">{vm.name}</h1>
        <Badge variant="secondary" title={error ?? undefined}>
          <StatusDot tone={VM_TONE[vm.status]} />
          {STATUS_TEXT[vm.status] ?? vm.status}
        </Badge>
        <span className="text-muted-foreground max-md:hidden">
          {imageName}
          {vm.forked_from !== "" && ` · forked from ${vm.forked_from}`}
          {vm.internet ? "" : " · no internet"}
        </span>
        <div className="ml-2 flex items-center gap-1 max-md:ml-0">
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
        <Tabs value={tab} onValueChange={setTab} className="ml-auto max-w-full overflow-x-auto max-md:ml-0">
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

      {/* Hidden, not unmounted, while another tab is open: the desktop keeps its connection. */}
      <div className={tab === "overview" ? "flex min-h-0 flex-1 flex-col" : "hidden"}>
        <div className="flex h-7 shrink-0 items-center gap-1 border-b bg-muted/40 px-2 text-xs">
          {terminalOnly && <span className="font-medium text-muted-foreground">Terminal</span>}
          {!terminalOnly && count === 1 && (
            <span
              className="flex items-center gap-1.5 font-medium text-muted-foreground"
              title={vm.desktops[0].holder === null ? "Free" : "Held"}
            >
              <span className={cn("size-2 shrink-0 rounded-full", vm.desktops[0].holder === null ? "bg-ok" : "bg-warn")} />
              {numbers[0] === 1 ? "Desktop" : `Desktop ${numbers[0]}`}
            </span>
          )}
          {!terminalOnly &&
            count > 1 &&
            vm.desktops.map((each) => {
              const number = each.number;
              let heldBy = "Free";
              if (each.holder === "user") {
                heldBy = "Held by you";
              }
              if (each.holder !== null && each.holder !== "user") {
                heldBy = `Held by ${agentById[each.holder]?.name ?? each.holder}`;
              }
              return (
                <Button
                  key={number}
                  variant={number === shown ? "secondary" : "ghost"}
                  size="xs"
                  title={heldBy}
                  onClick={() => showDesktop(number)}
                >
                  <span className={cn("size-2 shrink-0 rounded-full", each.holder === null ? "bg-ok" : "bg-warn")} />
                  Desktop {number}
                </Button>
              );
            })}
          {!terminalOnly && count > 1 && (
            <Button
              variant="ghost"
              size="icon-xs"
              title={`Remove desktop ${shown}`}
              aria-label={`Remove desktop ${shown}`}
              disabled={busy !== ""}
              onClick={() => setConfirmRemove(true)}
            >
              {busy === "remove_desktop" ? <Loader2 className="animate-spin" /> : <X />}
            </Button>
          )}
          {!terminalOnly && count < vm.max_desktops && (
            <Button
              variant="ghost"
              size="icon-xs"
              title={busy === "add_desktop" ? `Setting up desktop ${nextNumber}…` : "New desktop"}
              aria-label="New desktop"
              disabled={busy !== ""}
              onClick={addDesktop}
            >
              {busy === "add_desktop" ? <Loader2 className="animate-spin" /> : <Plus />}
            </Button>
          )}
          {running && desktopUrl !== null && (
            <div className="ml-auto flex items-center gap-0.5">
              {!terminalOnly && (
                <Button variant="ghost" size="xs" disabled={busy === "lock"} onClick={() => setLock(!locked)}>
                  {locked ? <Unlock /> : <Lock />}
                  {locked ? "Unlock" : "Lock"}
                </Button>
              )}
              <Button variant="ghost" size="xs" title="Connect again" onClick={() => setReload(reload + 1)}>
                <RotateCw /> Reconnect
              </Button>
              <Button variant="ghost" size="xs" asChild>
                <a href={desktopUrl} target="_blank" rel="noreferrer" title="Open it in its own tab">
                  <ExternalLink /> New tab
                </a>
              </Button>
            </div>
          )}
        </div>
        <div className="relative min-h-0 flex-1 bg-muted/30">
          {running &&
            (opened.includes(shown) ? opened : [...opened, shown]).map((number) => {
              const url = desktopUrls[number];
              if (url === undefined || !numbers.includes(number)) {
                return null;
              }
              return (
                <iframe
                  key={`${url}-${reload}`}
                  ref={number === shown ? frameRef : undefined}
                  src={url}
                  title={terminalOnly ? `Terminal of ${vm.name}` : `Desktop ${number} of ${vm.name}`}
                  allow="clipboard-write"
                  className={cn("absolute inset-0 size-full border-0 bg-black", number !== shown && "hidden")}
                />
              );
            })}

          {/* The agent's cursor where it clicks; a new one for each desktop, so switching doesn't glide. */}
          {running && desktopUrl !== null && !terminalOnly && <AgentCursor key={shown} vm={vm} desktop={shown} />}

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

          {running && desktopUrl !== null && locked && !terminalOnly && (
            <div className="absolute inset-0 cursor-not-allowed">
              <div className="absolute top-2 left-1/2 flex -translate-x-1/2 items-center gap-2 rounded-md border bg-background py-1 pr-1 pl-2.5 whitespace-nowrap">
                <Lock className="size-3.5 text-warn" />
                {lockedBy === "agent" ? "Locked by the agent while it works" : "You locked your mouse and keyboard out"}
                <Button size="xs" variant="outline" disabled={busy === "lock"} onClick={() => setLock(false)}>
                  <Unlock /> Unlock
                </Button>
              </div>
            </div>
          )}

          {running && desktopUrl === null && (
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

      <AlertDialog open={confirmRemove} onOpenChange={setConfirmRemove}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove desktop {shown} of {vm.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              {running && "Its windows close. "}
              The other desktops keep their numbers. Its home folder stays, with everything in it, for when {vm.name} gets
              a desktop {shown} again.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => removeDesktop(shown)}>Remove</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {forking && <ForkVMDialog vm={vm.name} onClose={() => setForking(false)} />}
    </div>
  );
}
