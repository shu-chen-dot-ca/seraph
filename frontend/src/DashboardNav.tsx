/*
The Dashboard tab's left list, with the same rows as Home's (Sidebar.tsx). Every line is a link to a page; the open one
is marked:
- Repository (#/dashboard/repos, also #/dashboard, RepositoryCards.tsx): the repos on the Repos page as cards, with how
  many are there.
- Virtual Machine: the VMs page (#/vms), with running / all; the chevron folds its VMs. One child per VM, with its
  status (off, busy or free) like on Home; a click opens its page (#/vms/<name>). The VM pages are the same as Home's
  and stay on this tab when opened from here (App.tsx).
In phone mode (App.tsx) the list is in the Menu instead, above Home's.
*/

import { BookMarked, ChevronRight, Monitor } from "lucide-react";
import { useState } from "react";

import { StatusDot, VM_TONE } from "@/components/ui/status-dot";
import { useLive } from "@/live";
import { cn } from "@/lib/utils";

export default function DashboardNav(props: { page: string; id: string | null }) {
  const [vmsOpen, setVMsOpen] = useState(true);
  const repos = useLive("repos");
  const vms = useLive("vms");
  const running = vms.filter((vm) => vm.status === "running").length;

  // The same rows as the sidebar's (Sidebar.tsx).
  const row = "flex h-8 items-center gap-2 rounded-md px-2 font-medium hover:bg-sidebar-accent hover:text-foreground";
  const selected = "bg-selected text-foreground ring-1 ring-primary/15 ring-inset hover:bg-selected [&>a>svg]:text-primary [&>svg]:text-primary";

  return (
    <nav className="flex w-56 shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground select-none">
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        <a href="#/dashboard/repos" className={cn(row, "pl-6", props.page === "dashboard" && selected)}>
          <BookMarked className="size-4 text-muted-foreground" />
          Repository
          <span className="ml-auto text-muted-foreground tabular-nums">{repos.items.length}</span>
        </a>

        <div className={cn(row, "gap-0 px-0", props.page === "vms" && props.id === null && selected)}>
          <button
            type="button"
            className="flex h-8 w-6 shrink-0 items-center justify-center text-muted-foreground"
            aria-label={vmsOpen ? "Fold VMs" : "Unfold VMs"}
            onClick={() => setVMsOpen(!vmsOpen)}
          >
            <ChevronRight className={cn("size-3.5 transition-transform", vmsOpen && "rotate-90")} />
          </button>
          <a href="#/vms" className="flex h-8 min-w-0 flex-1 items-center gap-2 pr-2">
            <Monitor className="size-4 text-muted-foreground" />
            Virtual Machine
            <span className="ml-auto text-muted-foreground tabular-nums">
              {running}/{vms.length}
            </span>
          </a>
        </div>
        {vmsOpen &&
          vms.map((vm) => (
            <a
              key={vm.name}
              href={`#/vms/${encodeURIComponent(vm.name)}`}
              className={cn(row, "pl-6", props.page === "vms" && props.id === vm.name && selected)}
            >
              <StatusDot tone={VM_TONE[vm.status]} />
              <span className="truncate">{vm.name}</span>
              <span className="ml-auto text-muted-foreground tabular-nums">
                {vm.status !== "running" ? "off" : vm.desktops.every((desktop) => desktop.holder !== null) ? "busy" : "free"}
              </span>
            </a>
          ))}
      </div>
    </nav>
  );
}
