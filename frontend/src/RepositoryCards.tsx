/*
The Repositories dialog, from the Dashboard (Dashboard.tsx owns it): its Repositories card opens it on the cards, the
pull request numbers and charts and In progress on their tab. On top, its tabs, each with its count: Repositories (the
cards below), then your pull requests' In progress, Open, Merged and Closed (state progress|open|merged|closed), which
show those tables instead (PullRequests.tsx, under these same tabs).
Repositories: the repos in the repo list (repo_list.py) as cards, in five columns side by side, each a list from top to
bottom that scrolls on its own (on a narrow window the columns keep their width and the page scrolls sideways):
- Prioritized: the Contributed ones you moved here (the Repos list's prioritized, repo_list.py). By stars.
- Contributed: repos that merged a pull request of yours. By stars, most first, or by the pick in the column's sort
  menu (Sort by stars, merged PRs, open PRs, closed PRs or in-progress PRs, always the most first; then by stars).
- Target: repos you hunt, to become a contributor there (an NVIDIA one, say), added from Catalog (Add to Target, the
  Repos list's target, with when each went there). Remove from Target takes one back to Catalog; besides, one leaves by
  its PRs: once one of yours is merged there it is in Contributed, and once one is closed without a merge after it went
  there it is rejected: back in Catalog. Add to Target there puts it back. By stars.
- Catalog: the rest. By stars.
- Removed: the ones you deleted that have pull requests of yours (the Repos list's removed), and every other one with a
  PR of yours closed that isn't in another column (none merged or open, no issue in progress, never in Target). By
  stars. Its ⋯ takes one out with another chance (POST /api/repos/restore, the Repos list's restored, with when): Add to
  Catalog or Add to Target, or Add to Contributed for one with a merged PR. The same rules put it back, but only its PRs
  closed without a merge after that count.
Every repo with a pull request of yours has a card, also one that isn't in the Repos list (a PR you opened by hand, a
repo taken out of the list): made from its pull requests, so it goes to its column like any other (only closed ones:
Removed). Its stars aren't known (–), so it comes last in its column, and its ⋯ has only the moves (none in Catalog: no ⋯ there).
A card: the owner's picture as its logo, owner/name, and under it in color: its stars (yellow), then of your pull
requests there how many it merged (purple), closed without a merge (red) and are still open (green), then the issues in
progress there (yellow, a draft PR icon: fix_issue jobs still open with no pull request on GitHub yet, as the Pull
requests page's In progress has them, from the live "jobs" topic); a count of 0 isn't shown. The mouse on the open
count opens a menu with Close all (every open PR of yours there closed on GitHub, POST /api/repos/close_prs), on the
in-progress one Stop all (those jobs stopped and their issues dropped, POST /api/repos/stop_in_progress), as the ⋯
opens. None of these has a tooltip.
A click on a card's owner/name (the text itself, with no tooltip) opens the repo on GitHub in a new tab; elsewhere on a
card it does nothing yet. A card has a ⋯, whose menu opens when the mouse is on it: Move to
Contributed in Prioritized and back; in Catalog Add to Target, in Target Remove from Target; in Removed Add to Catalog
and Add to Target (or Add to Contributed); and outside Removed Delete, or Add to Removed for a repo
with pull requests of yours (merged, closed or open), at once, with no "are you sure?" (POST /api/repos/delete): every
agent working on the repo stops, and one with pull requests of yours goes to Removed, any other leaves the page and the
list. A card with none of these has no ⋯.
A card also moves by dragging it with the mouse between Prioritized and Contributed; the column it can go to lights up
while it's dragged.
A move, Add to or Remove from Target (POST /api/repos/move) or out of Removed shows at once, before the live feed has it
(the repos topic comes every few seconds).
Every column but Removed has a ⚙ right after its count, which opens its settings in a pop-up (a dialog over the page,
titled "<column> settings"; Save sends them, PUT /api/automation/column, the live "automation" topic's columns;
backend/automation_api.py): Open PRs per repository (the most PRs of ours open at once in each of its repos; empty: the
usual limits; else a whole number from 1) and Model (Default, Fable, Opus or Sonnet: the agents fixing issues and
following up on PRs in its repos, for new jobs).
Every column but Removed has a switch in its header: on, agents take new issues of its repos; off, they don't, and what
is going there goes on (PUT /api/automation/take_from, the live "automation" topic's take_from). Agents take new issues
column by column: Target, Prioritized, Contributed, then Catalog (backend/issues_api.py take_from_catalog); Removed
never.
Your pull requests are the ones the app follows (github_searcher/pr_tracking.py), from the live "prs" topic, so the
numbers update themselves.
*/

import { ChevronDown, GitMerge, GitPullRequest, GitPullRequestClosed, GitPullRequestDraft, MoreHorizontal, Settings, Star } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import PullRequests from "@/PullRequests";
import { api, useLive, useLoaded } from "@/live";
import { cn } from "@/lib/utils";

type Sort = "stars" | "merged" | "open" | "closed" | "working";
// A column's settings (its ⚙), and the models it can pick.
type ColumnSetting = { max_open_per_repo: number | null; model: string };
const MODEL_CHOICES = [
  { value: "default", title: "Default" },
  { value: "fable", title: "Fable" },
  { value: "opus", title: "Opus" },
  { value: "sonnet", title: "Sonnet" },
];

const OPEN_JOB = ["queued", "working", "waiting_on_user", "waiting_on_maintainers"];
// The page's tabs: the cards (state "") and the pull requests' tables.
const TABS = [
  { state: "", title: "Repositories" },
  { state: "progress", title: "In progress" },
  { state: "open", title: "Open" },
  { state: "merged", title: "Merged" },
  { state: "closed", title: "Closed" },
];

// The Contributed column's sort menu.
const SORT_TITLE: Record<Sort, string> = {
  stars: "Sort by stars",
  merged: "Sort by merged PRs",
  open: "Sort by open PRs",
  closed: "Sort by closed PRs",
  working: "Sort by in-progress PRs",
};

export default function RepositoryCards(props: { state: string; onState: (state: string) => void }) {
  const repos = useLive("repos");
  const prs = useLive("prs");
  const jobs = useLive("jobs");
  const automation = useLive("automation");
  const loaded = useLoaded("repos");
  // The card whose ⋯ menu is open: the mouse on the ⋯ opens it at once, and it closes once the mouse left both the ⋯
  // and the menu (closeTimer: a tenth of a second, to go from one to the other). A key opens and closes it as a click
  // does.
  const [menuOpen, setMenuOpen] = useState<string | null>(null);
  const closeTimer = useRef<number | undefined>(undefined);
  // The repos deleted here, until the live feed has it (it comes every few seconds).
  const [deleted, setDeleted] = useState<string[]>([]);
  const [sort, setSort] = useState<Sort>("stars");
  // The cards moved here, by name: the column each went to, until the live feed has it.
  const [moved, setMoved] = useState<Record<string, string>>({});
  // The cards taken out of Removed here, until the live feed has it.
  const [restored, setRestored] = useState<string[]>([]);
  // The column switches flipped here, until the live feed has them.
  const [switched, setSwitched] = useState<Record<string, boolean>>({});
  // The column settings saved here, until the live feed has them; the column whose settings pop-up is open ("": none),
  // and what its Open PRs per repository box and Model say.
  const [columnEdits, setColumnEdits] = useState<Record<string, ColumnSetting>>({});
  const [settingsFor, setSettingsFor] = useState("");
  const [limitText, setLimitText] = useState("");
  const [modelPick, setModelPick] = useState("default");
  // The card being dragged, and the column it comes from.
  const [dragging, setDragging] = useState<{ name: string; from: string } | null>(null);

  // Once the live feed comes again, it has them.
  useEffect(() => {
    setMoved({});
    setRestored([]);
  }, [repos]);
  useEffect(() => {
    setSwitched({});
    setColumnEdits({});
  }, [automation]);

  // Your pull requests in each repo, by its name in lower case: merged, closed without a merge (and when the last one
  // of those closed), and open.
  const merged: Record<string, number> = {};
  const closed: Record<string, number> = {};
  const lastClosed: Record<string, string> = {};
  const open: Record<string, number> = {};
  for (const pr of prs.items) {
    const key = pr.repo.toLowerCase();
    if (pr.relation === "author" && pr.state === "merged") {
      merged[key] = (merged[key] ?? 0) + 1;
    }
    if (pr.relation === "author" && pr.state === "closed") {
      closed[key] = (closed[key] ?? 0) + 1;
      if (pr.closed_at !== null && pr.closed_at > (lastClosed[key] ?? "")) {
        lastClosed[key] = pr.closed_at;
      }
    }
    if (pr.relation === "author" && pr.state === "open") {
      open[key] = (open[key] ?? 0) + 1;
    }
  }

  // Prioritized: the live list, with the moves made here on top.
  const prioritizedNames = repos.prioritized.filter((name) => moved[name] !== "Contributed");
  // Target the same, but one with a PR of yours closed without a merge after it went there is rejected (not one added
  // again here).
  const targetNames: string[] = [];
  const rejectedNames: string[] = [];
  for (const name of Object.keys(repos.target)) {
    // Removed from Target here.
    if (moved[name] === "Catalog") {
      continue;
    }
    if (moved[name] !== "Target" && (lastClosed[name.toLowerCase()] ?? "") > repos.target[name]) {
      rejectedNames.push(name);
    } else {
      targetNames.push(name);
    }
  }
  for (const name of Object.keys(moved)) {
    if (moved[name] === "Prioritized" && !prioritizedNames.includes(name)) {
      prioritizedNames.push(name);
    }
    if (moved[name] === "Target" && !targetNames.includes(name)) {
      targetNames.push(name);
    }
  }

  // The issues in progress, in all and in each repo: fix_issue jobs still open with no pull request yet.
  const prJobs = prs.items.filter((pr) => pr.relation === "author").map((pr) => pr.job);
  const working: Record<string, number> = {};
  let inProgress = 0;
  for (const job of jobs) {
    if (job.kind !== "fix_issue" || !OPEN_JOB.includes(job.status) || prJobs.includes(job.id)) {
      continue;
    }
    inProgress += 1;
    if (job.repo === null) {
      continue;
    }
    const key = job.repo.toLowerCase();
    working[key] = (working[key] ?? 0) + 1;
  }

  const cards = repos.items.map((repo) => {
    const key = repo.full_name.toLowerCase();
    return { repo: repo, listed: true, merged: merged[key] ?? 0, closed: closed[key] ?? 0, open: open[key] ?? 0, working: working[key] ?? 0 };
  });
  // A repo with pull requests of yours that isn't in the list: a card of its own, made from its pull requests.
  const listedNames = repos.items.map((repo) => repo.full_name.toLowerCase());
  for (const pr of prs.items) {
    const key = pr.repo.toLowerCase();
    if (pr.relation !== "author" || listedNames.includes(key)) {
      continue;
    }
    listedNames.push(key);
    const repo = {
      full_name: pr.repo,
      description: "",
      stars: 0,
      default_branch: "",
      html_url: `https://github.com/${pr.repo}`,
      note: "",
      added_by: "",
      added_at: "",
    };
    cards.push({ repo: repo, listed: false, merged: merged[key] ?? 0, closed: closed[key] ?? 0, open: open[key] ?? 0, working: working[key] ?? 0 });
  }
  cards.sort((a, b) => b.repo.stars - a.repo.stars);
  // A repo deleted here with no pull requests of yours is gone; one with some goes to Removed.
  const shown = cards.filter((card) => !deleted.includes(card.repo.full_name) || card.merged + card.closed + card.open > 0);
  const removedNames = [...repos.removed, ...deleted];
  // Removed: the ones you deleted, and the ones where every PR of ours was closed, none merged or open and no issue in
  // progress, unless they were in Target (rejected there: Catalog), or taken out of Removed with none closed since
  // (another chance).
  const removed = shown.filter((card) => {
    const name = card.repo.full_name;
    if (restored.includes(name)) {
      return false;
    }
    if (removedNames.includes(name)) {
      return true;
    }
    if (repos.restored[name] !== undefined && (lastClosed[name.toLowerCase()] ?? "") <= repos.restored[name]) {
      return false;
    }
    return (
      card.merged === 0 && card.open === 0 && card.working === 0 && card.closed > 0 && !targetNames.includes(name) && !rejectedNames.includes(name)
    );
  });
  // Prioritized: merged ones you moved there.
  const prioritized = shown.filter((card) => card.merged > 0 && !removed.includes(card) && prioritizedNames.includes(card.repo.full_name));
  // Contributed by the sort menu's pick, the most first, then by stars (cards are by stars already).
  const contributed = shown.filter((card) => card.merged > 0 && !removed.includes(card) && !prioritized.includes(card));
  contributed.sort((a, b) => {
    if (sort === "merged") {
      return b.merged - a.merged;
    }
    if (sort === "open") {
      return b.open - a.open;
    }
    if (sort === "closed") {
      return b.closed - a.closed;
    }
    if (sort === "working") {
      return b.working - a.working;
    }
    return 0;
  });
  // Target: none merged, and you added it there (not rejected).
  const target = shown.filter((card) => card.merged === 0 && !removed.includes(card) && targetNames.includes(card.repo.full_name));
  // Catalog: the rest, by stars.
  const catalog = shown.filter((card) => !removed.includes(card) && !prioritized.includes(card) && !contributed.includes(card) && !target.includes(card));
  // moveTo: the column a card here can move to (its ⋯ or a drag), and back. key: its switch in take_from ("" for none).
  const columns = [
    { title: "Prioritized", key: "prioritized", removed: false, moveTo: "Contributed", cards: prioritized },
    { title: "Contributed", key: "contributed", removed: false, moveTo: "Prioritized", cards: contributed },
    { title: "Target", key: "target", removed: false, moveTo: "", cards: target },
    { title: "Catalog", key: "catalog", removed: false, moveTo: "", cards: catalog },
    { title: "Removed", key: "", removed: true, moveTo: "", cards: removed },
  ];

  // The tabs, each with its count. Like the header's tabs (App.tsx): quiet until hovered; the open one in full color
  // with the accent under it.
  const state = TABS.some((each) => each.state === props.state) ? props.state : "";
  const mine = prs.items.filter((pr) => pr.relation === "author");
  const counts: Record<string, number> = {
    "": shown.length,
    progress: inProgress,
    open: mine.filter((pr) => pr.state === "open").length,
    merged: mine.filter((pr) => pr.state === "merged").length,
    closed: mine.filter((pr) => pr.state === "closed").length,
  };
  const tab = "relative flex h-full items-center gap-1.5 px-2 font-medium whitespace-nowrap text-muted-foreground hover:text-foreground";
  const currentTab = "text-foreground after:absolute after:inset-x-2 after:-bottom-px after:h-0.5 after:rounded-full after:bg-primary";
  const tabs = TABS.map((each) => (
    <button
      key={each.state}
      type="button"
      aria-current={each.state === state ? "page" : undefined}
      className={cn(tab, each.state === state && currentTab)}
      onClick={() => props.onState(each.state)}
    >
      {each.title}
      <span className="text-muted-foreground tabular-nums">{counts[each.state]}</span>
    </button>
  ));

  async function move(name: string, to: string) {
    setMoved((old) => ({ ...old, [name]: to }));
    try {
      await api("/api/repos/move", { method: "POST", body: { name: name, to: to.toLowerCase() } });
    } catch (err) {
      setMoved((old) => {
        const next = { ...old };
        delete next[name];
        return next;
      });
      toast.error(`Could not move ${name}: ${err instanceof Error ? err.message : err}`);
    }
  }

  // Out of Removed, to Catalog, Target or Contributed: shown there at once, as a move is.
  async function restore(name: string, to: string) {
    setRestored((old) => [...old, name]);
    setDeleted((old) => old.filter((each) => each !== name));
    setMoved((old) => ({ ...old, [name]: to }));
    try {
      await api("/api/repos/restore", { method: "POST", body: { name: name, to: to.toLowerCase() } });
    } catch (err) {
      setRestored((old) => old.filter((each) => each !== name));
      setMoved((old) => {
        const next = { ...old };
        delete next[name];
        return next;
      });
      toast.error(`Could not move ${name}: ${err instanceof Error ? err.message : err}`);
    }
  }

  async function takeFrom(key: string, on: boolean) {
    setSwitched((old) => ({ ...old, [key]: on }));
    try {
      await api("/api/automation/take_from", { method: "PUT", body: { column: key, on: on } });
    } catch (err) {
      setSwitched({});
      toast.error(`Could not save: ${err instanceof Error ? err.message : err}`);
    }
  }

  async function saveColumn(key: string, setting: ColumnSetting) {
    setColumnEdits((old) => ({ ...old, [key]: setting }));
    try {
      await api("/api/automation/column", { method: "PUT", body: { column: key, ...setting } });
    } catch (err) {
      setColumnEdits({});
      toast.error(`Could not save: ${err instanceof Error ? err.message : err}`);
    }
  }

  // The settings pop-up's Open PRs per repository: empty is none, else a whole number from 1 (NaN: not one).
  const limitTyped = limitText.trim() === "" ? null : Number(limitText.trim());
  const limitValid = limitTyped === null || (Number.isInteger(limitTyped) && limitTyped >= 1);

  function saveSettings() {
    if (!limitValid) {
      return;
    }
    saveColumn(settingsFor, { max_open_per_repo: limitTyped, model: modelPick });
    setSettingsFor("");
  }

  async function stopInProgress(name: string) {
    try {
      await api("/api/repos/stop_in_progress", { method: "POST", body: { name: name } });
    } catch (err) {
      toast.error(`Could not stop ${name}: ${err instanceof Error ? err.message : err}`);
    }
  }

  async function closePRs(name: string) {
    try {
      await api("/api/repos/close_prs", { method: "POST", body: { name: name } });
    } catch (err) {
      toast.error(`Could not close ${name}'s pull requests: ${err instanceof Error ? err.message : err}`);
    }
  }

  async function deleteRepo(name: string) {
    setDeleted((old) => [...old, name]);
    try {
      await api("/api/repos/delete", { method: "POST", body: { name: name } });
    } catch (err) {
      setDeleted((old) => old.filter((each) => each !== name));
      toast.error(`Could not change ${name}: ${err instanceof Error ? err.message : err}`);
    }
  }

  if (state !== "") {
    return <PullRequests state={state} tabs={tabs} />;
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-9 shrink-0 items-center border-b px-1">{tabs}</div>

      {loaded && shown.length === 0 && <div className="p-3 text-muted-foreground">No repositories yet.</div>}
      {shown.length > 0 && (
        <div className="flex min-h-0 flex-1 gap-3 overflow-x-auto p-3">
          {columns.map((column) => {
            // A card dragged from the column this one pairs with can drop here.
            const dropHere = dragging !== null && column.moveTo === dragging.from;
            // Its settings (none for Removed): saved here, else the live feed's, else none.
            const none: ColumnSetting = { max_open_per_repo: null, model: "default" };
            const setting = columnEdits[column.key] ?? automation.columns?.[column.key as keyof typeof automation.columns] ?? none;

            return (
              <section
                key={column.title}
                className={cn("flex min-h-0 min-w-64 flex-1 flex-col rounded-md", dropHere && "bg-accent/50")}
                onDragOver={(event) => {
                  if (dropHere) {
                    event.preventDefault();
                  }
                }}
                onDrop={(event) => {
                  event.preventDefault();
                  if (dragging !== null) {
                    move(dragging.name, column.title);
                  }
                  setDragging(null);
                }}
              >
                <h2 className="mb-2 flex h-6 shrink-0 items-center gap-2 text-xs font-medium text-muted-foreground">
                  {column.title}
                  <span className="tabular-nums">{column.cards.length}</span>
                  {/* Its settings, in a pop-up. */}
                  {column.key !== "" && (
                    <button
                      type="button"
                      className="-ml-1 flex size-5 items-center justify-center rounded-sm hover:text-foreground"
                      aria-label={`${column.title} settings`}
                      onClick={() => {
                        setLimitText(setting.max_open_per_repo === null ? "" : String(setting.max_open_per_repo));
                        setModelPick(setting.model);
                        setSettingsFor(column.key);
                      }}
                    >
                      <Settings className="size-3.5" />
                    </button>
                  )}
                  <span className="flex-1" />
                  {column.title === "Contributed" && (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button
                          type="button"
                          className="flex h-6 items-center gap-1 rounded-sm px-1.5 font-normal hover:bg-accent hover:text-foreground data-[state=open]:bg-accent"
                        >
                          {SORT_TITLE[sort]}
                          <ChevronDown className="size-3.5" />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuRadioGroup value={sort} onValueChange={(value) => setSort(value as Sort)}>
                          <DropdownMenuRadioItem value="stars">{SORT_TITLE.stars}</DropdownMenuRadioItem>
                          <DropdownMenuRadioItem value="merged">{SORT_TITLE.merged}</DropdownMenuRadioItem>
                          <DropdownMenuRadioItem value="open">{SORT_TITLE.open}</DropdownMenuRadioItem>
                          <DropdownMenuRadioItem value="closed">{SORT_TITLE.closed}</DropdownMenuRadioItem>
                          <DropdownMenuRadioItem value="working">{SORT_TITLE.working}</DropdownMenuRadioItem>
                        </DropdownMenuRadioGroup>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  )}
                  {column.key !== "" && (
                    <Switch
                      checked={switched[column.key] ?? automation.take_from?.[column.key as keyof typeof automation.take_from] ?? true}
                      onCheckedChange={(on) => takeFrom(column.key, on)}
                      title="Take new issues"
                      aria-label={`Take new issues from ${column.title}`}
                    />
                  )}
                </h2>
                <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto">
                  {column.cards.map((card) => {
                    // Its ⋯ has a move, Remove from Target, or Delete or Add to Removed (and in Catalog Add to Target), or in Removed
                    // the way back.
                    const menu = column.moveTo !== "" || column.title === "Target" || column.removed || card.listed;
                    return (
                      <div
                        key={card.repo.full_name}
                        title={card.repo.full_name}
                        className="flex min-w-0 shrink-0 items-center gap-2 rounded-md border bg-card px-2 py-1.5"
                        draggable={column.moveTo !== ""}
                        onDragStart={(event) => {
                          // Firefox starts a drag only with some data in it.
                          event.dataTransfer.setData("text/plain", card.repo.full_name);
                          setDragging({ name: card.repo.full_name, from: column.title });
                        }}
                        onDragEnd={() => setDragging(null)}
                      >
                        <img
                          src={`https://github.com/${card.repo.full_name.split("/")[0]}.png?size=64`}
                          alt=""
                          draggable={false}
                          className="size-8 shrink-0 rounded"
                        />
                        <div className="min-w-0 flex-1">
                          {/* The link is the text only. draggable false: dragging the name drags the card, not the link. title="": no
                          tooltip (the card's name) over it. */}
                          <div className="truncate font-medium text-foreground">
                            <a href={card.repo.html_url} target="_blank" rel="noreferrer" draggable={false} title="" className="hover:underline">
                              {card.repo.full_name}
                            </a>
                          </div>
                          {/* title="": no tooltip (the card's name) over the counts. */}
                          <div className="flex items-center gap-2.5 text-xs text-muted-foreground tabular-nums" title="">
                            <span className="flex items-center gap-0.5 text-yellow-600 dark:text-yellow-400">
                              <Star className="size-3" />
                              {card.listed ? card.repo.stars.toLocaleString("en", { notation: "compact" }) : "–"}
                            </span>
                            {card.merged > 0 && (
                              <span className="flex items-center gap-0.5 text-violet-500">
                                <GitMerge className="size-3" />
                                {card.merged}
                              </span>
                            )}
                            {card.closed > 0 && (
                              <span className="flex items-center gap-0.5 text-destructive">
                                <GitPullRequestClosed className="size-3" />
                                {card.closed}
                              </span>
                            )}
                            {/* Open and in progress: the mouse on one opens its menu, Close all or Stop all, as the ⋯ does. */}
                            {[
                              { key: "open", count: card.open, icon: GitPullRequest, color: "text-ok", title: "Your open PRs", action: "Close all" },
                              {
                                key: "working",
                                count: card.working,
                                icon: GitPullRequestDraft,
                                color: "text-yellow-600 dark:text-yellow-400",
                                title: "In progress",
                                action: "Stop all",
                              },
                            ]
                              .filter((each) => each.count > 0)
                              .map((each) => (
                                <DropdownMenu
                                  key={each.key}
                                  modal={false}
                                  open={menuOpen === `${card.repo.full_name}:${each.key}`}
                                  onOpenChange={(open) => setMenuOpen(open ? `${card.repo.full_name}:${each.key}` : null)}
                                >
                                  <DropdownMenuTrigger asChild>
                                    {/* title="": its menu shows instead of a tooltip. */}
                                    <button
                                      type="button"
                                      title=""
                                      className={cn("-mx-0.5 flex items-center gap-0.5 rounded-sm px-0.5 hover:bg-accent data-[state=open]:bg-accent", each.color)}
                                      aria-label={each.title}
                                      onPointerEnter={() => {
                                        window.clearTimeout(closeTimer.current);
                                        setMenuOpen(`${card.repo.full_name}:${each.key}`);
                                      }}
                                      onPointerLeave={() => {
                                        closeTimer.current = window.setTimeout(() => setMenuOpen(null), 100);
                                      }}
                                      onPointerDown={(event) => {
                                        event.preventDefault();
                                      }}
                                    >
                                      <each.icon className="size-3" />
                                      {each.count}
                                    </button>
                                  </DropdownMenuTrigger>
                                  <DropdownMenuContent
                                    align="start"
                                    sideOffset={0}
                                    style={{ animation: "none" }}
                                    onPointerEnter={() => window.clearTimeout(closeTimer.current)}
                                    onPointerLeave={() => {
                                      closeTimer.current = window.setTimeout(() => setMenuOpen(null), 100);
                                    }}
                                  >
                                    <DropdownMenuItem
                                      variant="destructive"
                                      onSelect={() => (each.key === "open" ? closePRs(card.repo.full_name) : stopInProgress(card.repo.full_name))}
                                    >
                                      {each.action}
                                    </DropdownMenuItem>
                                  </DropdownMenuContent>
                                </DropdownMenu>
                              ))}
                          </div>
                        </div>
                        {menu && (
                          <DropdownMenu
                            modal={false}
                            open={menuOpen === card.repo.full_name}
                            onOpenChange={(open) => setMenuOpen(open ? card.repo.full_name : null)}
                          >
                            <DropdownMenuTrigger asChild>
                              {/* title="": no tooltip (the card's name) over the ⋯, its menu shows instead. */}
                              <button
                                type="button"
                                title=""
                                className="flex size-6 shrink-0 items-center justify-center rounded-sm text-muted-foreground hover-line data-[state=open]:bg-accent"
                                aria-label={`Settings for ${card.repo.full_name}`}
                                onPointerEnter={() => {
                                  window.clearTimeout(closeTimer.current);
                                  setMenuOpen(card.repo.full_name);
                                }}
                                onPointerLeave={() => {
                                  closeTimer.current = window.setTimeout(() => setMenuOpen(null), 100);
                                }}
                                onPointerDown={(event) => {
                                  // The mouse opened it already: a click doesn't close it again.
                                  event.preventDefault();
                                }}
                              >
                                <MoreHorizontal className="size-4" />
                              </button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent
                              align="end"
                              sideOffset={0}
                              // At once, with no fade or zoom in or out.
                              style={{ animation: "none" }}
                              onPointerEnter={() => window.clearTimeout(closeTimer.current)}
                              onPointerLeave={() => {
                                closeTimer.current = window.setTimeout(() => setMenuOpen(null), 100);
                              }}
                            >
                              {column.moveTo !== "" && (
                                <DropdownMenuItem onSelect={() => move(card.repo.full_name, column.moveTo)}>Move to {column.moveTo}</DropdownMenuItem>
                              )}
                              {card.listed && column.title === "Catalog" && (
                                <DropdownMenuItem onSelect={() => move(card.repo.full_name, "Target")}>Add to Target</DropdownMenuItem>
                              )}
                              {column.title === "Target" && (
                                <DropdownMenuItem onSelect={() => move(card.repo.full_name, "Catalog")}>Remove from Target</DropdownMenuItem>
                              )}
                              {column.removed && card.merged === 0 && (
                                <DropdownMenuItem onSelect={() => restore(card.repo.full_name, "Catalog")}>Add to Catalog</DropdownMenuItem>
                              )}
                              {column.removed && card.merged === 0 && (
                                <DropdownMenuItem onSelect={() => restore(card.repo.full_name, "Target")}>Add to Target</DropdownMenuItem>
                              )}
                              {column.removed && card.merged > 0 && (
                                <DropdownMenuItem onSelect={() => restore(card.repo.full_name, "Contributed")}>Add to Contributed</DropdownMenuItem>
                              )}
                              {card.listed && !column.removed && (
                                <DropdownMenuItem variant="destructive" onSelect={() => deleteRepo(card.repo.full_name)}>
                                  {card.merged + card.closed + card.open > 0 ? "Add to Removed" : "Delete"}
                                </DropdownMenuItem>
                              )}
                            </DropdownMenuContent>
                          </DropdownMenu>
                        )}
                      </div>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
      )}

      {/* A column's settings (its ⚙). */}
      <Dialog
        open={settingsFor !== ""}
        onOpenChange={(open) => {
          if (!open) {
            setSettingsFor("");
          }
        }}
      >
        <DialogContent className="sm:max-w-md" aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>{columns.find((each) => each.key === settingsFor)?.title} settings</DialogTitle>
          </DialogHeader>
          <form
            className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] items-center gap-x-3 gap-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              saveSettings();
            }}
          >
            <label htmlFor="column-open-prs" className="text-muted-foreground">
              Open PRs per repository
            </label>
            <Input
              id="column-open-prs"
              type="number"
              min={1}
              step={1}
              value={limitText}
              placeholder="Default"
              autoFocus
              aria-invalid={!limitValid}
              onChange={(event) => setLimitText(event.target.value)}
            />
            {!limitValid && <p className="col-start-2 text-xs text-destructive">A whole number from 1.</p>}
            <label htmlFor="column-model" className="text-muted-foreground">
              Model
            </label>
            <Select value={modelPick} onValueChange={setModelPick}>
              <SelectTrigger id="column-model" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {MODEL_CHOICES.map((each) => (
                  <SelectItem key={each.value} value={each.value}>
                    {each.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <button type="submit" className="hidden" />
          </form>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSettingsFor("")}>
              Cancel
            </Button>
            <Button onClick={saveSettings} disabled={!limitValid}>
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
