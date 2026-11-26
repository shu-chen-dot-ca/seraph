/*
The whole app: one page, with no header over it (the Dashboard's own bar shows Live or Offline).
App makes its own buttons, which the Dashboard shows right of its range (appButtons): Restarting… while the app
restarts on a new release, Update once a newer release is ready (UpdateDialog.tsx), then Sign in while you aren't
signed in to GitHub (straight to GitHub's sign-in page once sign in is set up, else Settings on its Account section,
which walks you through setting it up), or, signed in, your GitHub picture and @login, which open Settings on the
Account section (Account.tsx), where Sign out is. Last, this repo on GitHub (a new tab, so the app stays open), found
from git's origin remote (vite.config.ts), so no account name is written here; none when it isn't on GitHub. Settings
(SettingsDialog) also opens from the Dashboard's Settings card.

Back from GitHub's sign-in page, the backend sends the browser to #/?signed_in=<login> or #/?error=<text>: App says
which in a toast, reloads the account (the "github-account" window event) and takes the query out of the address.

The page lives in the URL hash, so refresh and back/forward work and switching pages never reloads:
  #/ (Dashboard.tsx)
  #/vms?tab=images (the Dashboard on the Images tab of its Virtual machines)
  #/vms/<vm name> (the Dashboard with that VM's page, VMPage.tsx, open in a dialog)
  #/vms/<vm name>?desktop=<n> (the same, with desktop n filling the VM page's Overview)
  #/agents/<agent id> (AgentChat.tsx, opened from the VM pages)
Anything else (also no hash at all) opens the Dashboard. Links are plain <a href="#/..."> everywhere; App only reads the
hash.
*/

import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import AgentChat from "@/AgentChat";
import Dashboard from "@/Dashboard";
import SettingsDialog, { type ThemeMode } from "@/SettingsDialog";
import UpdateDialog from "@/UpdateDialog";
import { Button } from "@/components/ui/button";
import { Toaster } from "@/components/ui/sonner";
import TitleTooltips from "@/components/ui/title-tooltips";
import { TooltipProvider } from "@/components/ui/tooltip";
import { api, useLive, type GithubAccountStatus } from "@/live";

const PAGES = ["vms", "agents"];
// This repo on GitHub, or "": vite.config.ts puts it in from git's origin remote.
declare const __REPO_URL__: string;

export default function App() {
  const [hash, setHash] = useState(window.location.hash);
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
  // The section Settings opens on: "account" from the header, "automation" from the Dashboard's Limits title, null
  // from its Settings card.
  const [settingsSection, setSettingsSection] = useState<string | null>(null);
  const [updateOpen, setUpdateOpen] = useState(false);
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
    setSettingsSection(section);
    setSettingsOpen(true);
  }

  useEffect(() => {
    function onHashChange() {
      setHash(window.location.hash);
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
  // #/vms... is the Dashboard: its Virtual machines on Images, or a VM's page in a dialog over it.
  const vmsTabText = query.get("tab");
  let vmsTab: "vms" | "images" = "vms";
  if (page === "vms" && id === null && vmsTabText === "images") {
    vmsTab = vmsTabText;
  }
  // #/vms/vm1?desktop=2: the VM's page opens on desktop 2.
  let vmDesktop: number | null = null;
  if (page === "vms" && id !== null && query.get("desktop") !== null) {
    vmDesktop = Number(query.get("desktop"));
  }

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


  // Restarting… or Update, Sign in or your GitHub account, and this repo on GitHub: the Dashboard shows them right of
  // its range.
  const appButtons = (
    <>
      {updates.restarting && (
        <span className="mr-2 flex items-center gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" /> Restarting…
        </span>
      )}
      {updates.ready !== null && !updates.restarting && (
        <Button size="xs" className="mr-1" onClick={() => setUpdateOpen(true)} title={`${updates.ready} is ready`}>
          Update
        </Button>
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
          <span>@{account.login}</span>
        </button>
      )}
      {__REPO_URL__ !== "" && (
        <a
          href={__REPO_URL__}
          target="_blank"
          rel="noreferrer"
          className="flex size-7 items-center justify-center rounded-sm text-muted-foreground hover-line"
          title="This repo on GitHub"
          aria-label="This repo on GitHub"
        >
          {/* GitHub's mark (lucide has no brand icons). */}
          <svg viewBox="0 0 16 16" className="size-4" fill="currentColor" aria-hidden="true">
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
          </svg>
        </a>
      )}
    </>
  );

  return (
    <TooltipProvider>
      <div className="flex h-full flex-col">
        <main className="relative min-h-0 flex-1 overflow-hidden">
          {(page === "dashboard" || page === "vms") && (
            <Dashboard vm={page === "vms" ? id : null} vmDesktop={vmDesktop} vmsTab={vmsTab} onOpenSettings={openSettings} appButtons={appButtons} />
          )}
          {page === "agents" && id !== null && <AgentChat key={id} agentId={id} />}
        </main>
      </div>
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
