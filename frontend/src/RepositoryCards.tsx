/*
The Repositories page (#/repos): the repos in the repo list (repo_list.py) as cards, in four columns side by side,
each a list from top to bottom that scrolls on its own (on a narrow window the columns keep their width and the page
scrolls sideways):
- Contributed: repos that merged a pull request of yours. By stars, most first, or by the pick in the column's sort
  menu (Sort by stars, merged PRs, open PRs or closed PRs, always the most first; then by stars).
- Planned: repos you want to contribute to, none of yours merged yet: the ones you picked (Add to Planned, kept in the
  Repos list's planned, repo_list.py), and the ones where a PR of yours is open. By stars.
- Catalog: the rest, grouped by owner: the owners with the most repos here first, an owner's repos always together, by
  stars, and owners with as many by their most starred repo.
- Removed: the ones you deleted that have pull requests of yours (the Repos list's removed), and the ones where every PR
  of ours was closed, none merged or open (unless you picked them for Planned). By stars.
In every column an owner's repos are together, where its first one comes. An owner with more than one there gets a card
of its own above them, with how many: a click folds them away, and another unfolds them (open at first, not kept).
A card: the owner's picture as its logo, owner/name, and under it in GitHub's colors: its stars (yellow), then of your
pull requests there how many it merged (purple), closed without a merge (red) and are still open (green). Gray instead:
a closed count of 0, and outside Contributed the stars and every count of 0.
A click on a card does nothing yet. Every card has a ⋯, whose menu opens when the mouse is on it (a tap or click on a
phone): Open on GitHub; in Planned and Catalog Add to Planned, or Remove from Planned for one you picked (POST
/api/repos/plan); and outside Removed Delete, at once, with no "are you sure?" (POST /api/repos/delete): every agent
working on the repo stops, and one with pull requests of yours (merged, closed or open) goes to Removed, any other leaves
the page and the list.
The button on the right of every card, always shown, sets how agents treat the repo (POST /api/repos/priority,
repo_list.py), one click at a time: Prioritize (green, a star: its work goes first), Deprioritize (red, a down arrow:
its work goes last), Stop (red, a circle with a line: no new work there, what is going finishes), and back to normal (the
star with no color).
Your pull requests are the ones the app follows (github_searcher/pr_tracking.py), from the live "prs" topic, so the
numbers update themselves.
*/

import { ArrowDown, Ban, ChevronDown, ChevronRight, GitMerge, GitPullRequest, GitPullRequestClosed, MoreHorizontal, Star } from "lucide-react";
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
import { api, useLive, useLoaded } from "@/live";
import { cn } from "@/lib/utils";

type Priority = "normal" | "high" | "low" | "stopped";

// What the next click on the button sets, and what it does, for screen readers (it has no tooltip).
const NEXT: Record<Priority, Priority> = { normal: "high", high: "low", low: "stopped", stopped: "normal" };
const PRIORITY_TITLE: Record<Priority, string> = {
  normal: "Prioritize",
  high: "Prioritized. Click to deprioritize",
  low: "Deprioritized. Click to stop",
  stopped: "Stopped: no new work. Click to reset",
};

type Sort = "stars" | "merged" | "open" | "closed";

// The Contributed column's sort menu.
const SORT_TITLE: Record<Sort, string> = {
  stars: "Sort by stars",
  merged: "Sort by merged PRs",
  open: "Sort by open PRs",
  closed: "Sort by closed PRs",
};

export default function RepositoryCards() {
  const repos = useLive("repos");
  const prs = useLive("prs");
  const loaded = useLoaded("repos");
  // What the button was clicked to, by repo, until the live feed says the same (it comes every few seconds), so clicks
  // in a row go on from the last one.
  const [picked, setPicked] = useState<Record<string, Priority>>({});
  // The card whose ⋯ menu is open: the mouse on the ⋯ opens it at once, and it closes once the mouse left both the ⋯
  // and the menu (closeTimer: a tenth of a second, to go from one to the other). A tap or a key opens and closes it as
  // a click does.
  const [menuOpen, setMenuOpen] = useState<string | null>(null);
  const closeTimer = useRef<number | undefined>(undefined);
  // The repos deleted here, until the live feed has it (it comes every few seconds).
  const [deleted, setDeleted] = useState<string[]>([]);
  const [sort, setSort] = useState<Sort>("stars");
  // The owners folded away, as "<column>:<owner in lower case>".
  const [folded, setFolded] = useState<string[]>([]);

  useEffect(() => {
    setPicked((old) => {
      const kept: Record<string, Priority> = {};
      for (const [name, value] of Object.entries(old)) {
        if ((repos.priority[name] ?? "normal") !== value) {
          kept[name] = value;
        }
      }
      return kept;
    });
  }, [repos.priority]);

  // Your pull requests in each repo, by its name in lower case: merged, closed without a merge, and open.
  const merged: Record<string, number> = {};
  const closed: Record<string, number> = {};
  const open: Record<string, number> = {};
  for (const pr of prs.items) {
    const key = pr.repo.toLowerCase();
    if (pr.relation === "author" && pr.state === "merged") {
      merged[key] = (merged[key] ?? 0) + 1;
    }
    if (pr.relation === "author" && pr.state === "closed") {
      closed[key] = (closed[key] ?? 0) + 1;
    }
    if (pr.relation === "author" && pr.state === "open") {
      open[key] = (open[key] ?? 0) + 1;
    }
  }

  const cards = repos.items.map((repo) => {
    const key = repo.full_name.toLowerCase();
    return { repo: repo, merged: merged[key] ?? 0, closed: closed[key] ?? 0, open: open[key] ?? 0 };
  });
  cards.sort((a, b) => b.repo.stars - a.repo.stars);
  // A repo deleted here with no pull requests of yours is gone; one with some goes to Removed.
  const shown = cards.filter((card) => !deleted.includes(card.repo.full_name) || card.merged + card.closed + card.open > 0);
  const removedNames = [...repos.removed, ...deleted];
  // Removed: the ones you deleted, and the ones where every PR of ours was closed, none merged or open, unless you
  // picked them for Planned.
  const removed = shown.filter(
    (card) =>
      removedNames.includes(card.repo.full_name) ||
      (card.merged === 0 && card.open === 0 && card.closed > 0 && !repos.planned.includes(card.repo.full_name)),
  );
  // Contributed by the sort menu's pick, the most first, then by stars (cards are by stars already).
  const contributed = shown.filter((card) => card.merged > 0 && !removed.includes(card));
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
    return 0;
  });
  // Planned: none merged, and you picked it, or a PR of yours is open there.
  const planned = shown.filter(
    (card) => card.merged === 0 && !removed.includes(card) && (repos.planned.includes(card.repo.full_name) || card.open > 0),
  );
  // Catalog by owner: how many repos each owner has here, and its most stars.
  const catalog = shown.filter((card) => !removed.includes(card) && !contributed.includes(card) && !planned.includes(card));
  const owned: Record<string, number> = {};
  const topStars: Record<string, number> = {};
  for (const card of catalog) {
    const owner = card.repo.full_name.split("/")[0].toLowerCase();
    owned[owner] = (owned[owner] ?? 0) + 1;
    topStars[owner] = Math.max(topStars[owner] ?? 0, card.repo.stars);
  }
  catalog.sort((a, b) => {
    const ownerA = a.repo.full_name.split("/")[0].toLowerCase();
    const ownerB = b.repo.full_name.split("/")[0].toLowerCase();
    if (owned[ownerA] !== owned[ownerB]) {
      return owned[ownerB] - owned[ownerA];
    }
    if (topStars[ownerA] !== topStars[ownerB]) {
      return topStars[ownerB] - topStars[ownerA];
    }
    if (ownerA !== ownerB) {
      return ownerA < ownerB ? -1 : 1;
    }
    return b.repo.stars - a.repo.stars;
  });
  const columns = [
    { title: "Contributed", contributed: true, removed: false, cards: contributed },
    { title: "Planned", contributed: false, removed: false, cards: planned },
    { title: "Catalog", contributed: false, removed: false, cards: catalog },
    { title: "Removed", contributed: false, removed: true, cards: removed },
  ];

  async function plan(name: string, value: boolean) {
    try {
      await api("/api/repos/plan", { method: "POST", body: { names: [name], planned: value } });
    } catch (err) {
      toast.error(`Could not change ${name}: ${err instanceof Error ? err.message : err}`);
    }
  }

  async function deleteRepo(name: string) {
    setDeleted((old) => [...old, name]);
    try {
      await api("/api/repos/delete", { method: "POST", body: { name: name } });
    } catch (err) {
      setDeleted((old) => old.filter((each) => each !== name));
      toast.error(`Could not delete ${name}: ${err instanceof Error ? err.message : err}`);
    }
  }

  async function setPriority(name: string, value: Priority) {
    setPicked((old) => ({ ...old, [name]: value }));
    try {
      await api("/api/repos/priority", { method: "POST", body: { name: name, priority: value } });
    } catch (err) {
      setPicked((old) => {
        const kept = { ...old };
        delete kept[name];
        return kept;
      });
      toast.error(`Could not change ${name}: ${err instanceof Error ? err.message : err}`);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex min-h-9 shrink-0 items-center border-b px-3 py-1 text-muted-foreground tabular-nums">
        {shown.length} {shown.length === 1 ? "repository" : "repositories"}
      </div>

      {loaded && shown.length === 0 && <div className="p-3 text-muted-foreground">No repositories yet.</div>}
      {shown.length > 0 && (
        <div className="flex min-h-0 flex-1 gap-3 overflow-x-auto p-3">
          {columns.map((column) => {
            // An owner's repos together, where its first one comes; one with more than one gets its own card above them.
            const owners: string[] = [];
            const byOwner: Record<string, typeof shown> = {};
            for (const card of column.cards) {
              const owner = card.repo.full_name.split("/")[0].toLowerCase();
              if (byOwner[owner] === undefined) {
                owners.push(owner);
                byOwner[owner] = [];
              }
              byOwner[owner].push(card);
            }
            const entries: { owner: string; card: (typeof shown)[number] | null; grouped: boolean }[] = [];
            for (const owner of owners) {
              const grouped = byOwner[owner].length > 1;
              if (grouped) {
                entries.push({ owner: owner, card: null, grouped: true });
              }
              if (grouped && folded.includes(`${column.title}:${owner}`)) {
                continue;
              }
              for (const card of byOwner[owner]) {
                entries.push({ owner: owner, card: card, grouped: grouped });
              }
            }

            return (
              <section key={column.title} className="flex min-h-0 min-w-64 flex-1 flex-col">
                <h2 className="mb-2 flex h-6 shrink-0 items-center gap-2 text-xs font-medium text-muted-foreground">
                  {column.title}
                  <span className="tabular-nums">{column.cards.length}</span>
                  {column.contributed && (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button
                          type="button"
                          className="ml-auto flex h-6 items-center gap-1 rounded-sm px-1.5 font-normal hover:bg-accent hover:text-foreground data-[state=open]:bg-accent"
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
                        </DropdownMenuRadioGroup>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  )}
                </h2>
                <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto">
                  {entries.map((entry) => {
                    // The owner's own card: how many of its repos are here, and a click folds or unfolds them.
                    if (entry.card === null) {
                      const key = `${column.title}:${entry.owner}`;
                      const isFolded = folded.includes(key);
                      const name = byOwner[entry.owner][0].repo.full_name.split("/")[0];
                      return (
                        <button
                          key={`owner:${entry.owner}`}
                          type="button"
                          className="flex min-w-0 shrink-0 items-center gap-2 rounded-md border bg-card px-2 py-1.5 text-left hover:bg-accent/50"
                          aria-expanded={!isFolded}
                          onClick={() => setFolded(isFolded ? folded.filter((each) => each !== key) : [...folded, key])}
                        >
                          <img src={`https://github.com/${name}.png?size=64`} alt="" className="size-8 shrink-0 rounded" />
                          <div className="min-w-0 flex-1">
                            <div className="truncate font-medium text-foreground">{name}</div>
                            <div className="text-xs text-muted-foreground tabular-nums">{byOwner[entry.owner].length} repositories</div>
                          </div>
                          <ChevronRight className={cn("size-4 shrink-0 text-muted-foreground transition-transform", !isFolded && "rotate-90")} />
                        </button>
                      );
                    }

                    const card = entry.card;
                    const priority = picked[card.repo.full_name] ?? repos.priority[card.repo.full_name] ?? "normal";
                    return (
                      <div
                        key={card.repo.full_name}
                        title={card.repo.full_name}
                        className={cn("flex min-w-0 shrink-0 items-center gap-2 rounded-md border bg-card px-2 py-1.5", entry.grouped && "ml-4")}
                      >
                        <img src={`https://github.com/${card.repo.full_name.split("/")[0]}.png?size=64`} alt="" className="size-8 shrink-0 rounded" />
                        <div className="min-w-0 flex-1">
                          <div className="truncate font-medium text-foreground">{card.repo.full_name}</div>
                          <div className="flex items-center gap-2.5 text-xs text-muted-foreground tabular-nums">
                            <span className={cn("flex items-center gap-0.5", column.contributed && "text-yellow-600 dark:text-yellow-400")} title="Stars">
                              <Star className="size-3" />
                              {card.repo.stars.toLocaleString("en", { notation: "compact" })}
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
                          </div>
                        </div>
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
                            <DropdownMenuItem onSelect={() => window.open(card.repo.html_url, "_blank", "noreferrer")}>Open on GitHub</DropdownMenuItem>
                            {!column.contributed && !column.removed && repos.planned.includes(card.repo.full_name) && (
                              <DropdownMenuItem onSelect={() => plan(card.repo.full_name, false)}>Remove from Planned</DropdownMenuItem>
                            )}
                            {!column.contributed && !column.removed && !repos.planned.includes(card.repo.full_name) && (
                              <DropdownMenuItem onSelect={() => plan(card.repo.full_name, true)}>Add to Planned</DropdownMenuItem>
                            )}
                            {!column.removed && (
                              <DropdownMenuItem variant="destructive" onSelect={() => deleteRepo(card.repo.full_name)}>
                                Delete
                              </DropdownMenuItem>
                            )}
                          </DropdownMenuContent>
                        </DropdownMenu>
                        <button
                          type="button"
                          className={cn(
                            "flex size-6 shrink-0 items-center justify-center rounded-sm text-white",
                            priority === "normal" && "border text-muted-foreground hover:bg-accent hover:text-foreground",
                            priority === "high" && "bg-green-600 hover:bg-green-700",
                            (priority === "low" || priority === "stopped") && "bg-red-600 hover:bg-red-700",
                          )}
                          title=""
                          aria-label={`${PRIORITY_TITLE[priority]}: ${card.repo.full_name}`}
                          onClick={() => setPriority(card.repo.full_name, NEXT[priority])}
                        >
                          {(priority === "normal" || priority === "high") && <Star className="size-4" />}
                          {priority === "low" && <ArrowDown className="size-4" />}
                          {priority === "stopped" && <Ban className="size-4" />}
                        </button>
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
