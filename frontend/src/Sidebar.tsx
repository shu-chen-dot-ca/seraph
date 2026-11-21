/*
The left list (App.tsx): one place for the whole app. Every line is a link to a page; the open one is marked:
- Dashboard (#/, Dashboard.tsx): numbers, limits, charts and tables.
- Pull requests (#/pulls, PullRequests.tsx), with how many of yours are open.
- Repositories (#/repos): the repositories as cards (RepositoryCards.tsx), with how many.
- Blockers (#/blockers, Blockers.tsx), with how many wait for you.
- Virtual machines: the VMs page (#/vms) and one child per VM (#/vms/<name>), which folds.
- Automation (#/automation, Automation.tsx).
Feedback (#/feedback, Feedback.tsx), with how many are open, and Settings stay pinned at the bottom; Settings opens
SettingsDialog, which App owns.
*/

import { BookMarked, ChevronRight, Gauge, GitPullRequest, LayoutDashboard, MessageSquareWarning, Monitor, OctagonAlert, Settings } from "lucide-react";
import { useState } from "react";

import { StatusDot, VM_TONE } from "@/components/ui/status-dot";
import { useLive } from "@/live";
import { cn } from "@/lib/utils";

export default function Sidebar(props: { page: string; id: string | null; onOpenSettings: () => void }) {
  const [vmsOpen, setVMsOpen] = useState(true);
  const repos = useLive("repos");
  const vms = useLive("vms");
  const prs = useLive("prs");
  const inbox = useLive("inbox");
  const feedback = useLive("problems");
  const running = vms.filter((vm) => vm.status === "running").length;
  const openPRs = prs.items.filter((pr) => pr.relation === "author" && pr.state === "open").length;
  const blockers = inbox.filter((draft) => draft.kind === "approval" && draft.status === "pending").length;

  const row = "flex h-8 items-center gap-2 rounded-md px-2 font-medium hover:bg-sidebar-accent hover:text-foreground";
  const selected = "bg-selected text-foreground ring-1 ring-primary/15 ring-inset hover:bg-selected [&>a>svg]:text-primary [&>svg]:text-primary";

  return (
    <nav className="flex w-56 shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground select-none">
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        <a href="#/" className={cn(row, "pl-6", props.page === "dashboard" && selected)}>
          <LayoutDashboard className="size-4 text-muted-foreground" />
          Dashboard
        </a>

        <a href="#/pulls" className={cn(row, "pl-6", props.page === "pulls" && selected)}>
          <GitPullRequest className="size-4 text-muted-foreground" />
          Pull requests
          <span className="ml-auto text-muted-foreground tabular-nums">{openPRs}</span>
        </a>

        <a href="#/repos" className={cn(row, "pl-6", props.page === "repos" && selected)}>
          <BookMarked className="size-4 text-muted-foreground" />
          Repositories
          <span className="ml-auto text-muted-foreground tabular-nums">{repos.items.length}</span>
        </a>

        <a href="#/blockers" className={cn(row, "pl-6", props.page === "blockers" && selected)}>
          <OctagonAlert className="size-4 text-muted-foreground" />
          Blockers
          {/* Like the Inbox's own count: a filled pill, as these wait for you. */}
          {blockers > 0 && (
            <span className="ml-auto min-w-4.5 rounded-full bg-primary px-1.5 text-center text-xs leading-4.5 font-medium text-primary-foreground tabular-nums">
              {blockers}
            </span>
          )}
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
            Virtual machines
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
              {vm.status !== "running" && <span className="ml-auto text-muted-foreground">off</span>}
            </a>
          ))}

        <a href="#/automation" className={cn(row, "pl-6", props.page === "automation" && selected)}>
          <Gauge className="size-4 text-muted-foreground" />
          Automation
        </a>
      </div>

      <div className="border-t p-2">
        <a href="#/feedback" className={cn(row, "pl-6", props.page === "feedback" && selected)}>
          <MessageSquareWarning className="size-4 text-muted-foreground" />
          Feedback
          <span className="ml-auto text-muted-foreground tabular-nums">{feedback.filter((item) => item.closed_at === null).length}</span>
        </a>
        <button type="button" className={cn(row, "w-full pl-6")} onClick={props.onOpenSettings}>
          <Settings className="size-4 text-muted-foreground" />
          Settings
        </button>
      </div>
    </nav>
  );
}
