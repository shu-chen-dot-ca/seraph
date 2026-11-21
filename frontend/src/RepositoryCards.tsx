/*
The Repositories page (#/repos). On top, its tabs, each with its count: Repositories (the cards below), then your pull
requests' In progress, Open, Merged and Closed (#/repos?state=progress|open|merged|closed), which show those tables
instead (PullRequests.tsx, under these same tabs).
Repositories: the repos in the repo list (repo_list.py) as cards, in five columns side by side, each a list from top to
bottom that scrolls on its own (on a narrow window the columns keep their width and the page scrolls sideways):
- Prioritized: the Contributed ones you moved here (the Repos list's prioritized, repo_list.py). By stars.
- Contributed: repos that merged a pull request of yours. By stars, most first, or by the pick in the column's sort
  menu (Sort by stars, merged PRs, open PRs, closed PRs or in-progress PRs, always the most first; then by stars).
- Target: repos you hunt, to become a contributor there (an NVIDIA one, say), added from Catalog (Add to Target, the
  Repos list's target, with when each went there). Remove from Target takes one back to Catalog; besides, one leaves by
  its PRs: once one of yours is merged there it is in Contributed, and once one is closed without a merge after it went
  there it is rejected: back in Catalog, at the top. Add to Target there puts it back. By stars.
- Catalog: the rest, in three groups: the ones rejected in Target first, then the ones with a PR of yours open or an
  issue in progress, then the others. In each group by owner: the owner with the most starred repo first, an owner's
  repos always together, by stars.
- Removed: the ones you deleted that have pull requests of yours (the Repos list's removed), and every other one with a
  PR of yours closed that isn't in another column (none merged or open, no issue in progress, never in Target). By
  stars.
In every column an owner's repos are together, where its first one comes (in Catalog, within its group).
Every repo with a pull request of yours has a card, also one that isn't in the Repos list (a PR you opened by hand, a
repo taken out of the list): made from its pull requests, so it goes to its column like any other (only closed ones:
Removed). Its stars aren't known (–), and its ⋯ has only the moves (none in Catalog or Removed: no ⋯ there).
A card: the owner's picture as its logo, owner/name, and under it in GitHub's colors: its stars (yellow), then of your
pull requests there how many it merged (purple), closed without a merge (red) and are still open (green). Gray instead:
a closed count of 0, and outside Contributed the stars and every count of 0. Last, only when there are any, the issues
in progress there (yellow, a draft PR icon): fix_issue jobs still open with no pull request on GitHub yet, as the Pull
requests page's In progress has them (from the live "jobs" topic).
A click on a card's owner/name (the text itself, with no tooltip) opens the repo on GitHub in a new tab; elsewhere on a
card it does nothing yet. A card has a ⋯, whose menu opens when the mouse is on it (a tap or click on a phone): Move to
Contributed in Prioritized and back; in Catalog Add to Target, in Target Remove from Target; and outside Removed Delete, or Add to Removed for a repo
with pull requests of yours (merged, closed or open), at once, with no "are you sure?" (POST /api/repos/delete): every
agent working on the repo stops, and one with pull requests of yours goes to Removed, any other leaves the page and the
list. A card with none of these (every one in Removed) has no ⋯.
A card also moves by dragging it with the mouse between Prioritized and Contributed; the column it can go to lights up
while it's dragged.
A move, Add to or Remove from Target (POST /api/repos/move) shows at once, before the live feed has it (the repos topic comes every
few seconds).
Every column but Removed has a switch in its header: on, agents take new issues of its repos; off, they don't, and what
is going there goes on (PUT /api/automation/take_from, the live "automation" topic's take_from). Agents take new issues
column by column: Target, Prioritized, Contributed, then Catalog (backend/issues_api.py take_from_catalog); Removed
never.
Your pull requests are the ones the app follows (github_searcher/pr_tracking.py), from the live "prs" topic, so the
numbers update themselves.
*/

import { ChevronDown, GitMerge, GitPullRequest, GitPullRequestClosed, GitPullRequestDraft, MoreHorizontal, Star } from "lucide-react";
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
import { Switch } from "@/components/ui/switch";
import PullRequests from "@/PullRequests";
import { api, useLive, useLoaded } from "@/live";
import { cn } from "@/lib/utils";

type Sort = "stars" | "merged" | "open" | "closed" | "working";

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

export default function RepositoryCards(props: { state: string }) {
  const repos = useLive("repos");
  const prs = useLive("prs");
  const jobs = useLive("jobs");
  const automation = useLive("automation");
  const loaded = useLoaded("repos");
  // The card whose ⋯ menu is open: the mouse on the ⋯ opens it at once, and it closes once the mouse left both the ⋯
  // and the menu (closeTimer: a tenth of a second, to go from one to the other). A tap or a key opens and closes it as
  // a click does.
  const [menuOpen, setMenuOpen] = useState<string | null>(null);
  const closeTimer = useRef<number | undefined>(undefined);
  // The repos deleted here, until the live feed has it (it comes every few seconds).
  const [deleted, setDeleted] = useState<string[]>([]);
  const [sort, setSort] = useState<Sort>("stars");
  // The cards moved here, by name: the column each went to, until the live feed has it.
  const [moved, setMoved] = useState<Record<string, string>>({});
  // The column switches flipped here, until the live feed has them.
  const [switched, setSwitched] = useState<Record<string, boolean>>({});
  // The card being dragged, and the column it comes from.
  const [dragging, setDragging] = useState<{ name: string; from: string } | null>(null);

  // Once the live feed comes again, it has them.
  useEffect(() => setMoved({}), [repos]);
  useEffect(() => setSwitched({}), [automation]);

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
  // progress, unless they were in Target (rejected there: Catalog).
  const removed = shown.filter(
    (card) =>
      removedNames.includes(card.repo.full_name) ||
      (card.merged === 0 &&
        card.open === 0 &&
        card.working === 0 &&
        card.closed > 0 &&
        !targetNames.includes(card.repo.full_name) &&
        !rejectedNames.includes(card.repo.full_name)),
  );
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
  // Catalog: the rest, in groups (by its name): 0 rejected in Target, 1 a PR of yours open or an issue in progress, 2 the
  // others. In each by owner: each owner's most stars.
  const catalog = shown.filter((card) => !removed.includes(card) && !prioritized.includes(card) && !contributed.includes(card) && !target.includes(card));
  const group: Record<string, number> = {};
  for (const card of catalog) {
    group[card.repo.full_name] = 2;
    if (card.open > 0 || card.working > 0) {
      group[card.repo.full_name] = 1;
    }
    if (rejectedNames.includes(card.repo.full_name)) {
      group[card.repo.full_name] = 0;
    }
  }
  const topStars: Record<string, number> = {};
  for (const card of catalog) {
    const owner = group[card.repo.full_name] + ":" + card.repo.full_name.split("/")[0].toLowerCase();
    topStars[owner] = Math.max(topStars[owner] ?? 0, card.repo.stars);
  }
  catalog.sort((a, b) => {
    if (group[a.repo.full_name] !== group[b.repo.full_name]) {
      return group[a.repo.full_name] - group[b.repo.full_name];
    }
    const ownerA = group[a.repo.full_name] + ":" + a.repo.full_name.split("/")[0].toLowerCase();
    const ownerB = group[b.repo.full_name] + ":" + b.repo.full_name.split("/")[0].toLowerCase();
    if (topStars[ownerA] !== topStars[ownerB]) {
      return topStars[ownerB] - topStars[ownerA];
    }
    if (ownerA !== ownerB) {
      return ownerA < ownerB ? -1 : 1;
    }
    return b.repo.stars - a.repo.stars;
  });
  // moveTo: the column a card here can move to (its ⋯ or a drag), and back. key: its switch in take_from ("" for none).
  const columns = [
    { title: "Prioritized", key: "prioritized", contributed: true, removed: false, moveTo: "Contributed", cards: prioritized },
    { title: "Contributed", key: "contributed", contributed: true, removed: false, moveTo: "Prioritized", cards: contributed },
    { title: "Target", key: "target", contributed: false, removed: false, moveTo: "", cards: target },
    { title: "Catalog", key: "catalog", contributed: false, removed: false, moveTo: "", cards: catalog },
    { title: "Removed", key: "", contributed: false, removed: true, moveTo: "", cards: removed },
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
    <a
      key={each.state}
      href={each.state === "" ? "#/repos" : `#/repos?state=${each.state}`}
      aria-current={each.state === state ? "page" : undefined}
      className={cn(tab, each.state === state && currentTab)}
    >
      {each.title}
      <span className="text-muted-foreground tabular-nums">{counts[each.state]}</span>
    </a>
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

  async function takeFrom(key: string, on: boolean) {
    setSwitched((old) => ({ ...old, [key]: on }));
    try {
      await api("/api/automation/take_from", { method: "PUT", body: { column: key, on: on } });
    } catch (err) {
      setSwitched({});
      toast.error(`Could not save: ${err instanceof Error ? err.message : err}`);
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
            // An owner's repos together, where its first one comes (in Catalog, within its group).
            const owners: string[] = [];
            const byOwner: Record<string, typeof shown> = {};
            for (const card of column.cards) {
              const owner = (group[card.repo.full_name] ?? 0) + ":" + card.repo.full_name.split("/")[0].toLowerCase();
              if (byOwner[owner] === undefined) {
                owners.push(owner);
                byOwner[owner] = [];
              }
              byOwner[owner].push(card);
            }
            const ordered: typeof shown = [];
            for (const owner of owners) {
              ordered.push(...byOwner[owner]);
            }
            // A card dragged from the column this one pairs with can drop here.
            const dropHere = dragging !== null && column.moveTo === dragging.from;

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
                  {ordered.map((card) => {
                    // Its ⋯ has a move, Remove from Target, or Delete or Add to Removed (and in Catalog Add to Target).
                    const menu = column.moveTo !== "" || column.title === "Target" || (card.listed && !column.removed);
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
                          <div className="flex items-center gap-2.5 text-xs text-muted-foreground tabular-nums">
                            <span className={cn("flex items-center gap-0.5", column.contributed && "text-yellow-600 dark:text-yellow-400")} title="Stars">
                              <Star className="size-3" />
                              {card.listed ? card.repo.stars.toLocaleString("en", { notation: "compact" }) : "–"}
                            </span>
                            <span className={cn("flex items-center gap-0.5", card.merged > 0 && "text-violet-500")} title="Your PRs merged">
                              <GitMerge className="size-3" />
                              {card.merged}
                            </span>
                            <span className={cn("flex items-center gap-0.5", card.closed > 0 && "text-destructive")} title="Your PRs closed without a merge">
                              <GitPullRequestClosed className="size-3" />
                              {card.closed}
                            </span>
                            <span className={cn("flex items-center gap-0.5", (column.contributed || card.open > 0) && "text-ok")} title="Your open PRs">
                              <GitPullRequest className="size-3" />
                              {card.open}
                            </span>
                            {card.working > 0 && (
                              <span className="flex items-center gap-0.5 text-yellow-600 dark:text-yellow-400" title="In progress">
                                <GitPullRequestDraft className="size-3" />
                                {card.working}
                              </span>
                            )}
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
                                className="flex size-6 shrink-0 items-center justify-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground data-[state=open]:bg-accent"
                                aria-label={`Settings for ${card.repo.full_name}`}
                                onPointerEnter={(event) => {
                                  if (event.pointerType === "mouse") {
                                    window.clearTimeout(closeTimer.current);
                                    setMenuOpen(card.repo.full_name);
                                  }
                                }}
                                onPointerLeave={(event) => {
                                  if (event.pointerType === "mouse") {
                                    closeTimer.current = window.setTimeout(() => setMenuOpen(null), 100);
                                  }
                                }}
                                onPointerDown={(event) => {
                                  // The mouse opened it already: a click doesn't close it again.
                                  if (event.pointerType === "mouse") {
                                    event.preventDefault();
                                  }
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
                              onPointerLeave={(event) => {
                                if (event.pointerType === "mouse") {
                                  closeTimer.current = window.setTimeout(() => setMenuOpen(null), 100);
                                }
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
    </div>
  );
}
