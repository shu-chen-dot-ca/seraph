/*
The whole app: a 36px header, a left list (Sidebar.tsx) and one page on the right.
The header's left has one tab, Dashboard (#/), in full color with the accent under it. On its right: Restarting… while
the app restarts on a new release, Update once a newer release is ready (UpdateDialog.tsx), Offline while the live feed
is down, then Sign in while you aren't signed in to GitHub (straight to GitHub's sign-in page once sign in is set up,
else Settings on its Account section, which walks you through setting it up), or, signed in, your GitHub picture and
@login, which open Settings on the Account section (Account.tsx), where Sign out is. Last, this repo on GitHub (a new
tab, so the app stays open), found from git's origin remote (vite.config.ts), so no account name is written here; none
when it isn't on GitHub. Settings (SettingsDialog) opens from the bottom of the left list.

Back from GitHub's sign-in page, the backend sends the browser to #/?signed_in=<login> or #/?error=<text>: App says
which in a toast, reloads the account (the "github-account" window event) and takes the query out of the address.

Phone mode, on a narrow screen (under 768px, a phone): no tab and no left list. The header's left has Menu instead and
the open page's name. Menu slides in the left list. Picking a page closes it, and so does a tap beside it. The pages are
the same as on a computer.

The page lives in the URL hash, so refresh and back/forward work and switching pages never reloads:
  #/ (Dashboard.tsx)
  #/repos (RepositoryCards.tsx; takes state=progress|open|merged|closed for the pull requests' tabs, PullRequests.tsx)
  #/blockers (Blockers.tsx)
  #/automation (Automation.tsx)
  #/feedback (Feedback.tsx; takes state=open|closed)
  #/vms  #/vms?tab=images  #/vms?tab=defaults (VMs.tsx)  #/vms/<vm name>  #/vms/<vm name>?tab=notes (VMPage.tsx)
  #/agents/<agent id> (AgentChat.tsx, opened from the VM pages and their notes)
Anything else (also no hash at all) opens the Dashboard. Links are plain <a href="#/..."> everywhere; App only reads the
hash.

A VM page, once visited, stays mounted (hidden) while you are elsewhere, so its desktop iframe keeps its
connection and coming back is instant. It is dropped when that VM no longer exists.
*/

import { Loader2, Menu, WifiOff, X } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import AgentChat from "@/AgentChat";
import Automation from "@/Automation";
import Blockers from "@/Blockers";
import Dashboard from "@/Dashboard";
import Feedback from "@/Feedback";
import RepositoryCards from "@/RepositoryCards";
import SettingsDialog, { type ThemeMode } from "@/SettingsDialog";
import Sidebar from "@/Sidebar";
import UpdateDialog from "@/UpdateDialog";
import VMPage from "@/VMPage";
import VMs from "@/VMs";
import { Button } from "@/components/ui/button";
import { Toaster } from "@/components/ui/sonner";
import TitleTooltips from "@/components/ui/title-tooltips";
import { TooltipProvider } from "@/components/ui/tooltip";
import { api, useConnected, useLive, useLiveValue, useLoaded, type GithubAccountStatus } from "@/live";
import { cn } from "@/lib/utils";

const PAGES = ["repos", "blockers", "automation", "feedback", "vms", "agents"];
// The open page's name in phone mode's header, where there is no left list to show it.
const PAGE_NAMES: Record<string, string> = {
  dashboard: "Dashboard",
  repos: "Repositories",
  blockers: "Blockers",
  vms: "Virtual machines",
  automation: "Automation",
  feedback: "Feedback",
};
// This repo on GitHub, or "": vite.config.ts puts it in from git's origin remote.
declare const __REPO_URL__: string;

export default function App() {
  const [hash, setHash] = useState(window.location.hash);
  const [visitedVMs, setVisitedVMs] = useState<string[]>([]);
  // Theme and accent color, picked in Settings. index.html already put the saved ones on <html> before the first paint.
  const [theme, setTheme] = useState<ThemeMode>(() => {
    try {
      const saved = localStorage.getItem("theme");
      if (saved === "light" || saved === "system") {
        return saved;
      }
    } catch {
      // Storage blocked (private window): the default.
    }
    return "dark";
  });
  const [accent, setAccent] = useState(document.documentElement.dataset.accent ?? "blue");
  const [settingsOpen, setSettingsOpen] = useState(false);
  // The section Settings opens on: "account" from the header, null from the left list.
  const [settingsSection, setSettingsSection] = useState<string | null>(null);
  const [updateOpen, setUpdateOpen] = useState(false);
  // Phone mode's Menu: the left list, slid in from the left.
  const [menuOpen, setMenuOpen] = useState(false);
  // Only the names: App re-renders every page under it, and the VM list changes every second.
  const vmNamesText = useLiveValue((topics) => topics.vms.map((vm) => vm.name).join(" "));
  const vmsLoaded = useLoaded("vms");
  const connected = useConnected();
  // Changes only on a check or an update, so App re-renders seldom for it.
  const updates = useLive("updates");
  // Who you are signed in to GitHub as, for the header's right. Settings → Account signs you in and out.
  const [account, setAccount] = useState<GithubAccountStatus | null>(null);

  useEffect(() => {
    function load() {
      api<GithubAccountStatus>("/api/github_account")
        .then(setAccount)
        .catch(() => {});
    }
    load();
    window.addEventListener("github-account", load);
    return () => window.removeEventListener("github-account", load);
  }, []);

  // Back from GitHub's sign-in page (the callback in backend/github_account_api.py): what came of it, said once.
  useEffect(() => {
    const query = new URLSearchParams(window.location.hash.split("?")[1] ?? "");
    const signedIn = query.get("signed_in");
    const error = query.get("error");
    if (signedIn === null && error === null) {
      return;
    }
    if (signedIn !== null) {
      toast.success(`Signed in as @${signedIn}`);
    }
    if (error !== null) {
      toast.error(`Could not sign in: ${error}`);
    }
    window.dispatchEvent(new Event("github-account"));
    window.location.replace("#/");
  }, []);

  // The header's Sign in: straight to GitHub's sign-in page when sign in is set up, else Settings → Account to set it up.
  async function signIn() {
    if (account === null || !account.can_sign_in) {
      openSettings("account");
      return;
    }
    try {
      const data = await api<{ url: string }>("/api/github_account/sign_in", { method: "POST" });
      window.location.href = data.url;
    } catch (err) {
      toast.error(`Could not sign in: ${err instanceof Error ? err.message : err}`);
    }
  }

  function openSettings(section: string | null) {
    setMenuOpen(false);
    setSettingsSection(section);
    setSettingsOpen(true);
  }

  useEffect(() => {
    function onHashChange() {
      setHash(window.location.hash);
      // A page was picked (also from a button): phone mode's Menu is done.
      setMenuOpen(false);
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  // "#/vms/vm1?x=y" → page "vms", id "vm1", query "x=y". Anything unknown opens the Dashboard.
  const [pathPart, queryPart] = hash.replace(/^#\/?/, "").split("?");
  const parts = pathPart.split("/");
  const id = parts.length > 1 && parts[1] !== "" ? decodeURIComponent(parts.slice(1).join("/")) : null;
  let page = PAGES.includes(parts[0]) ? parts[0] : "dashboard";
  if (page === "agents" && id === null) {
    page = "dashboard";
  }
  const query = new URLSearchParams(queryPart ?? "");
  // Phone mode's header: the open page's name, a VM's own name on its page, an agent's name on its chat.
  const agentName = useLiveValue((topics) => topics.agents.find((agent) => agent.id === id)?.name ?? "Agent");
  let pageName = PAGE_NAMES[page];
  if (page === "vms" && id !== null) {
    pageName = id;
  }
  if (page === "agents") {
    pageName = agentName;
  }

  // Remember every VM page opened, so it stays mounted. (Setting state while rendering is React's
  // pattern for state derived from props; it re-renders at once, before anything is shown.)
  const openVM = page === "vms" && id !== null ? id : null;
  if (openVM !== null && !visitedVMs.includes(openVM)) {
    setVisitedVMs([...visitedVMs, openVM]);
  }
  const vmNames = vmNamesText.split(" ");
  const mountedVMs = visitedVMs.filter((name) => name === openVM || !vmsLoaded || vmNames.includes(name));

  // Put the theme on <html>. System follows the OS, also when the OS switches while the app is open.
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    function apply() {
      const dark = theme === "dark" || (theme === "system" && media.matches);
      document.documentElement.classList.toggle("dark", dark);
    }
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [theme]);

  function changeTheme(next: ThemeMode) {
    setTheme(next);
    try {
      localStorage.setItem("theme", next);
    } catch {
      // Storage blocked (private window): the choice just isn't kept.
    }
  }

  function changeAccent(next: string) {
    document.documentElement.dataset.accent = next;
    setAccent(next);
    try {
      localStorage.setItem("accent", next);
    } catch {
      // Storage blocked (private window): the choice just isn't kept.
    }
  }

  // Panel sizes and folds only live in memory, so a reload resets them. Theme and accent are settings: they stay.
  function resetView() {
    window.location.reload();
  }

  // The header's tab, like line tabs (components/ui/tabs.tsx): in full color with the accent under it, over the
  // header's border.
  const tab = "relative flex h-full items-center gap-1.5 px-2 font-medium text-muted-foreground hover:text-foreground";
  const currentTab = "text-foreground after:absolute after:inset-x-2 after:-bottom-px after:h-0.5 after:rounded-full after:bg-primary";

  return (
    <TooltipProvider>
      <div className="flex h-full flex-col">
        <header className="flex h-9 shrink-0 items-center gap-3 border-b bg-sidebar px-3">
          {/* Phone mode: Menu and the open page's name instead of the tab. */}
          <button
            type="button"
            className="-ml-1.5 flex h-7 shrink-0 items-center gap-1.5 rounded-sm px-1.5 font-medium text-muted-foreground hover:bg-accent hover:text-foreground md:hidden"
            aria-label="Menu"
            onClick={() => setMenuOpen(true)}
          >
            <Menu className="size-4" />
          </button>
          <span className="-ml-1.5 min-w-0 truncate font-medium md:hidden">{pageName}</span>
          <div className="flex h-full items-center max-md:hidden">
            <a href="#/" aria-current="page" className={cn(tab, currentTab)}>
              Dashboard
            </a>
          </div>
          <div className="ml-auto flex items-center gap-1">
            {updates.restarting && (
              <span className="mr-2 flex items-center gap-1.5 text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin" /> Restarting…
              </span>
            )}
            {updates.ready !== null && !updates.restarting && (
              <Button size="xs" className="mr-1" onClick={() => setUpdateOpen(true)} title={`${updates.ready} is ready`}>
                Update
              </Button>
            )}
            {!connected && !updates.restarting && (
              <span className="mr-2 flex shrink-0 items-center gap-1.5 text-destructive">
                <WifiOff className="size-3.5" /> Offline<span className="max-md:hidden">, reconnecting</span>
              </span>
            )}
            {account !== null && !account.connected && (
              <Button size="xs" variant="outline" className="mr-1" onClick={signIn}>
                Sign in
              </Button>
            )}
            {account !== null && account.connected && (
              <button
                type="button"
                className="mr-1 flex h-7 items-center gap-1.5 rounded-sm px-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
                title="Your GitHub account"
                onClick={() => openSettings("account")}
              >
                <img src={`https://github.com/${account.login}.png?size=40`} alt="" className="size-5 rounded-full" />
                {/* Phone mode: only the picture, to leave room for the page's name. */}
                <span className="max-md:hidden">@{account.login}</span>
              </button>
            )}
            {__REPO_URL__ !== "" && (
              <a
                href={__REPO_URL__}
                target="_blank"
                rel="noreferrer"
                className="flex size-7 items-center justify-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground"
                title="This repo on GitHub"
                aria-label="This repo on GitHub"
              >
                {/* GitHub's mark (lucide has no brand icons). */}
                <svg viewBox="0 0 16 16" className="size-4" fill="currentColor" aria-hidden="true">
                  <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
                </svg>
              </a>
            )}
          </div>
        </header>

        <div className="flex min-h-0 flex-1">
          {/* The left list; phone mode has Menu instead. */}
          <div className="flex shrink-0 max-md:hidden">
            <Sidebar page={page} id={id} onOpenSettings={() => openSettings(null)} />
          </div>
          <main className="relative min-w-0 flex-1 overflow-hidden">
            {page === "dashboard" && <Dashboard />}
            {page === "repos" && <RepositoryCards state={query.get("state") ?? ""} />}
            {page === "blockers" && <Blockers />}
            {page === "automation" && <Automation />}
            {page === "feedback" && <Feedback state={query.get("state") ?? "open"} />}
            {page === "agents" && id !== null && <AgentChat key={id} agentId={id} />}
            {page === "vms" && id === null && (
              <VMs tab={query.get("tab") === "images" ? "images" : query.get("tab") === "defaults" ? "defaults" : "vms"} />
            )}
            {mountedVMs.map((name) => (
              <div key={name} className={name === openVM ? "h-full" : "hidden"}>
                <VMPage name={name} active={name === openVM} tab={name === openVM ? query.get("tab") : null} />
              </div>
            ))}
          </main>
        </div>
      </div>
      {/* Phone mode's Menu: the left list, as wide as the menu and as tall as what it holds; the menu scrolls as a whole. */}
      {menuOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 animate-in bg-black/40 duration-200 ease-out fade-in-0 dark:bg-black/60" onClick={() => setMenuOpen(false)} />
          <div
            className="absolute inset-y-0 left-0 w-72 max-w-[85vw] animate-in overflow-y-auto overscroll-contain border-r bg-sidebar text-sidebar-foreground shadow-overlay duration-200 ease-out slide-in-from-left [&>nav]:w-full [&>nav]:border-r-0 [&>nav>div]:flex-none"
            onClick={(event) => {
              // A link closes it at once, also one to the page already open (no hashchange then).
              if ((event.target as Element).closest("a") !== null) {
                setMenuOpen(false);
              }
            }}
          >
            <div className="flex h-9 items-center gap-1.5 border-b px-3">
              <button
                type="button"
                className="-ml-1.5 flex size-7 items-center justify-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground"
                aria-label="Close menu"
                onClick={() => setMenuOpen(false)}
              >
                <X className="size-4" />
              </button>
              <span className="font-medium text-foreground">Menu</span>
            </div>
            <Sidebar page={page} id={id} onOpenSettings={() => openSettings(null)} />
          </div>
        </div>
      )}
      <SettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        section={settingsSection}
        theme={theme}
        onTheme={changeTheme}
        accent={accent}
        onAccent={changeAccent}
        onResetView={resetView}
      />
      <UpdateDialog open={updateOpen} onOpenChange={setUpdateOpen} />
      <Toaster theme={theme} position="bottom-right" />
      <TitleTooltips />
    </TooltipProvider>
  );
}
