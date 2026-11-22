/*
Every VM's band, on the Dashboard's Virtual machines (its VMs tab), split by a line. On top, the VM's name (#/vms/<name>:
the Dashboard opens its page in a dialog, App.tsx), Halt, Shutdown or Start, and a ⋯ that opens the VM's settings
(VMSettings, as on its page's Settings tab) in a dialog, titled with the VM's name and, in gray, the image it was made
from (its name now, as images can be renamed).
- Halt stops agents new to the VM from getting a desktop (the ones on it go on; record.suspended in the backend). The
  button then says Halting while anyone still holds a desktop or a run still goes, and Halted once nothing does, both
  solid gray. Clicking either takes the halt off. Not on Seraph's own VM (FIX_VM): no agent gets it anyway.
- Shutdown (red) while it runs, Start (green) while it's off or failed; each spins while it goes.
All solid with white text, the size of New VM (Dashboard.tsx), like the app's other buttons.
Under it a row of cards, all the same size, side by side (the row scrolls sideways when the page is narrow):
- CPU, Memory and Internet: the number now and a chart of the last minute. Internet also has the total since it
  was last reset.
- Disk: space used, with a bar that turns amber at 90%.

Everything comes from the live "vms" topic (the backend samples usage about once a second), so the numbers move on
their own.
*/

import { Loader2, MoreHorizontal, Pause, Play, Power } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import VMSettings from "@/VMSettings";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { api, useLive } from "@/live";
import { cn } from "@/lib/utils";

// Seraph's own VM (sandbox/vms.py FIX_VM).
const FIX_VM = "seraph";
const SAMPLES = 60;
// The internet chart never scales below this, so an idle VM's few packets don't look like a busy line.
const INTERNET_CHART_MIN = 100_000;
// Every card in a VM's row: the same size.
const CARD = "h-36 rounded-lg border bg-card";

// Data in the units a phone's data counter uses: 1 MB = 1,000,000 bytes.
function formatBytes(bytes: number): string {
  if (bytes >= 1e9) {
    return `${(bytes / 1e9).toFixed(2)} GB`;
  }
  if (bytes >= 1e6) {
    return `${(bytes / 1e6).toFixed(1)} MB`;
  }
  if (bytes >= 1e3) {
    return `${Math.round(bytes / 1e3)} KB`;
  }
  return `${Math.round(bytes)} B`;
}

export default function VMList() {
  const vms = useLive("vms");
  const imagesData = useLive("images");
  // The VM whose settings are open from its ⋯, or null.
  const [settingsFor, setSettingsFor] = useState<string | null>(null);
  // The VM whose Halt (or taking it off) is on its way, or "".
  const [halting, setHalting] = useState("");
  // The VM whose Start or Shutdown is on its way, or "".
  const [powering, setPowering] = useState("");

  async function setHalted(name: string, enabled: boolean) {
    setHalting(name);
    try {
      await api(`/api/vms/${encodeURIComponent(name)}/suspend`, { method: "PUT", body: { enabled: enabled } });
    } catch (err) {
      toast.error(`Could not ${enabled ? "halt" : "take the halt off"} ${name}: ${err instanceof Error ? err.message : err}`);
    }
    setHalting("");
  }

  async function power(name: string, action: "start" | "stop") {
    setPowering(name);
    try {
      await api(`/api/vms/${encodeURIComponent(name)}/${action}`, { method: "POST" });
    } catch (err) {
      toast.error(`Could not ${action === "start" ? "start" : "shut down"} ${name}: ${err instanceof Error ? err.message : err}`);
    }
    setPowering("");
  }

  // The image the VM whose settings are open was made from: its name now, or the one it had then.
  const settingsVM = vms.find((each) => each.name === settingsFor);
  let settingsImage = "";
  if (settingsVM !== undefined) {
    settingsImage = imagesData.images.find((image) => image.fingerprint === settingsVM.image_fingerprint)?.name ?? settingsVM.image;
  }

  return (
    <>
      {vms.map((vm) => {
        const page = `#/vms/${encodeURIComponent(vm.name)}`;
        const on = vm.status === "running";
        // The usage numbers are null until the first sample after a start (disk until the VM's agent runs).
        const cpu = vm.usage?.cpu_percent ?? null;
        const memory = vm.usage?.memory_used_gb ?? null;
        const disk = vm.usage?.disk_used_gb ?? null;
        const down = vm.usage?.net_down_rate ?? null;
        const up = vm.usage?.net_up_rate ?? null;
        // Someone still holds a desktop or a run still goes: Halting until neither does.
        const working = vm.desktops.some((each) => each.holder !== null) || vm.runs.length > 0;

        // The internet chart shows download and upload together: it is all data used.
        const internetValues = vm.samples.map((sample) => {
          if (sample.net_down_rate === null || sample.net_up_rate === null) {
            return null;
          }
          return sample.net_down_rate + sample.net_up_rate;
        });
        let internetMax = INTERNET_CHART_MIN;
        for (const value of internetValues) {
          if (value !== null && value > internetMax) {
            internetMax = value;
          }
        }
        const charts = [
          {
            key: "cpu",
            label: "CPU",
            value: cpu === null ? "–" : `${Math.round(cpu)}%`,
            detail: `${vm.cpus} CPUs`,
            values: vm.samples.map((sample) => sample.cpu_percent),
            max: 100,
            extra: "",
          },
          {
            key: "memory",
            label: "Memory",
            value: memory === null ? "–" : `${memory.toFixed(1)} GB`,
            detail: `of ${vm.memory_gb} GB`,
            values: vm.samples.map((sample) => sample.memory_used_gb),
            max: vm.memory_gb,
            extra: "",
          },
          {
            key: "internet",
            label: "Internet",
            value: down === null || up === null ? "–" : `${formatBytes(down + up)}/s`,
            detail: vm.internet ? "" : "off",
            values: internetValues,
            max: internetMax,
            extra: `${formatBytes(vm.traffic.down + vm.traffic.up)} since reset`,
          },
        ];

        return (
          <div key={vm.name} className="border-b px-3 py-2.5">
            <div className="flex min-w-0 items-center gap-2">
              <a href={page} className="truncate font-medium hover:underline">
                {vm.name}
              </a>
              {vm.name !== FIX_VM && !vm.suspended && (
                <Button size="sm" disabled={halting === vm.name} onClick={() => setHalted(vm.name, true)}>
                  {halting === vm.name ? <Loader2 className="animate-spin" /> : <Pause />} Halt
                </Button>
              )}
              {vm.name !== FIX_VM && vm.suspended && (
                <Button
                  size="sm"
                  className="bg-neutral-500 text-white shadow-none hover:bg-neutral-500/90 hover:shadow-none"
                  title="Take the halt off"
                  disabled={halting === vm.name}
                  onClick={() => setHalted(vm.name, false)}
                >
                  {halting === vm.name ? <Loader2 className="animate-spin" /> : <Pause />}
                  {working ? "Halting" : "Halted"}
                </Button>
              )}
              {(on || vm.status === "stopping") && (
                <Button
                  variant="destructive"
                  size="sm"
                  disabled={powering === vm.name || vm.status === "stopping"}
                  onClick={() => power(vm.name, "stop")}
                >
                  {powering === vm.name || vm.status === "stopping" ? <Loader2 className="animate-spin" /> : <Power />} Shutdown
                </Button>
              )}
              {!on && vm.status !== "stopping" && (
                <Button
                  size="sm"
                  className="bg-green-600 text-white shadow-none hover:bg-green-600/90 hover:shadow-none"
                  disabled={powering === vm.name || (vm.status !== "stopped" && vm.status !== "failed")}
                  onClick={() => power(vm.name, "start")}
                >
                  {powering === vm.name || vm.status === "starting" || vm.status === "creating" ? <Loader2 className="animate-spin" /> : <Play />} Start
                </Button>
              )}
              {vm.error !== null && (
                <span className="truncate text-xs text-destructive" title={vm.error}>
                  {vm.error}
                </span>
              )}
              <Button
                variant="icon"
                size="icon-xs"
                className="ml-auto shrink-0"
                aria-label={`${vm.name} settings`}
                title="Settings"
                onClick={() => setSettingsFor(vm.name)}
              >
                <MoreHorizontal />
              </Button>
            </div>

            {/* Equal columns that fill the width, and scroll sideways once they would get narrower than 13rem. */}
            <div className="mt-2 grid auto-cols-[minmax(13rem,1fr)] grid-flow-col gap-2 overflow-x-auto pb-1">
              {charts.map((chart) => {
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
                const first = points.length > 0 ? points[0].split(",")[0] : "0";
                const last = points.length > 0 ? points[points.length - 1].split(",")[0] : "0";
                return (
                  <div key={chart.key} className={cn(CARD, "flex min-w-0 flex-col p-2.5")}>
                    <div className="text-muted-foreground">{chart.label}</div>
                    <div className="flex items-baseline gap-1.5">
                      <span className="text-lg font-medium tabular-nums">{chart.value}</span>
                      <span className="text-xs text-muted-foreground">{chart.detail}</span>
                    </div>
                    <div className="relative mt-auto h-12 border-b">
                      {points.length === 0 && (
                        <span className="absolute inset-0 flex items-center justify-center text-xs text-muted-foreground">{on ? "Waiting…" : "Off"}</span>
                      )}
                      {points.length > 0 && (
                        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 size-full overflow-visible text-primary">
                          <polygon points={`${first},100 ${points.join(" ")} ${last},100`} fill="currentColor" opacity="0.12" />
                          <polyline
                            points={points.join(" ")}
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            strokeLinejoin="round"
                            strokeLinecap="round"
                            vectorEffect="non-scaling-stroke"
                          />
                        </svg>
                      )}
                    </div>
                    {chart.extra !== "" && <div className="mt-1 truncate text-xs text-muted-foreground tabular-nums">{chart.extra}</div>}
                  </div>
                );
              })}

              <div className={cn(CARD, "flex min-w-0 flex-col p-2.5")}>
                <div className="text-muted-foreground">Disk</div>
                <div className="flex items-baseline gap-1.5">
                  <span className="text-lg font-medium tabular-nums">{disk === null ? "–" : `${disk.toFixed(1)} GB`}</span>
                  <span className="text-xs text-muted-foreground">of {vm.disk_gb} GB</span>
                </div>
                {/* Gray, amber once the disk is 90% full (the VM starts failing when it fills). */}
                <div className="mt-auto mb-1 h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className={cn("h-full rounded-full", disk !== null && disk >= vm.disk_gb * 0.9 ? "bg-warn" : "bg-muted-foreground/70")}
                    style={{ width: `${disk === null ? 0 : Math.min((disk / vm.disk_gb) * 100, 100)}%` }}
                  />
                </div>
              </div>
            </div>
          </div>
        );
      })}

      {/* A VM's ⋯: the same settings as its page's Settings tab. */}
      <Dialog
        open={settingsFor !== null}
        onOpenChange={(open) => {
          if (!open) {
            setSettingsFor(null);
          }
        }}
      >
        <DialogContent className="gap-0 p-0 sm:max-w-2xl">
          <DialogTitle className="px-4 pt-4">
            {settingsFor} <span className="font-normal text-muted-foreground">{settingsImage}</span>
          </DialogTitle>
          <div className="max-h-[75vh] overflow-auto">{settingsFor !== null && <VMSettings name={settingsFor} />}</div>
        </DialogContent>
      </Dialog>
    </>
  );
}
