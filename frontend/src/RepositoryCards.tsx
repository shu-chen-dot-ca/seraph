/*
The Repositories page (#/repos): the repos in the repo list (repo_list.py) as cards, in four columns side by side,
each a list from top to bottom that scrolls on its own (on a narrow window the columns keep their width and the page
scrolls sideways):
- Contributed: repos that merged a pull request of yours. By stars, most first, or by the pick in the column's sort
  menu (Sort by stars, merged PRs, open PRs, closed PRs or in-progress PRs, always the most first; then by stars).
- Planned: repos you want to contribute to, none of yours merged yet: the ones you picked (Add to Planned, kept in the
  Repos list's planned, repo_list.py), the ones where a PR of yours is open, and the ones with an issue in progress. By
  stars.
- Catalog: the rest (no PR of yours open, no issue in progress), grouped by owner: the owner with the most starred repo
  first, an owner's repos always together, by stars.
- Removed: the ones you deleted that have pull requests of yours (the Repos list's removed), and the ones where every PR
  of ours was closed, none merged or open, and no issue is in progress (unless you picked them for Planned). By stars.
In every column an owner's repos are together, where its first one comes.
A card: the owner's picture as its logo, owner/name, and under it in GitHub's colors: its stars (yellow), then of your
pull requests there how many it merged (purple), closed without a merge (red) and are still open (green). Gray instead:
a closed count of 0, and outside Contributed the stars and every count of 0. Last, only when there are any, the issues
in progress there (yellow, a draft PR icon): fix_issue jobs still open with no pull request on GitHub yet, as the Pull
requests page's In progress has them (from the live "jobs" topic).
A click on a card does nothing yet. Every card has a ⋯, whose menu opens when the mouse is on it (a tap or click on a
phone): Open on GitHub; in Planned and Catalog Add to Planned, or Remove from Planned for one you picked (POST
/api/repos/plan); and outside Removed Delete, at once, with no "are you sure?" (POST /api/repos/delete): every agent
working on the repo stops, and one with pull requests of yours (merged, closed or open) goes to Removed, any other leaves
the page and the list.
Your pull requests are the ones the app follows (github_searcher/pr_tracking.py), from the live "prs" topic, so the
numbers update themselves.
*/

import { ChevronDown, GitMerge, GitPullRequest, GitPullRequestClosed, GitPullRequestDraft, MoreHorizontal, Star } from "lucide-react";
import { useRef, useState } from "react";
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

type Sort = "stars" | "merged" | "open" | "closed" | "working";

const OPEN_JOB = ["queued", "working", "waiting_on_user", "waiting_on_maintainers"];

// The Contributed column's sort menu.
const SORT_TITLE: Record<Sort, string> = {
  stars: "Sort by stars",
  merged: "Sort by merged PRs",
  open: "Sort by open PRs",
  closed: "Sort by closed PRs",
  working: "Sort by in-progress PRs",
};

export default function RepositoryCards() {
  const repos = useLive("repos");
  const prs = useLive("prs");
  const jobs = useLive("jobs");
  const loaded = useLoaded("repos");
  // The card whose ⋯ menu is open: the mouse on the ⋯ opens it at once, and it closes once the mouse left both the ⋯
  // and the menu (closeTimer: a tenth of a second, to go from one to the other). A tap or a key opens and closes it as
  // a click does.
  const [menuOpen, setMenuOpen] = useState<string | null>(null);
  const closeTimer = useRef<number | undefined>(undefined);
  // The repos deleted here, until the live feed has it (it comes every few seconds).
  const [deleted, setDeleted] = useState<string[]>([]);
  const [sort, setSort] = useState<Sort>("stars");

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

  // The issues in progress in each repo: fix_issue jobs still open with no pull request yet.
  const prJobs = prs.items.filter((pr) => pr.relation === "author").map((pr) => pr.job);
  const working: Record<string, number> = {};
  for (const job of jobs) {
    if (job.kind !== "fix_issue" || !OPEN_JOB.includes(job.status) || prJobs.includes(job.id)) {
      continue;
    }
    if (job.repo === null) {
      continue;
    }
    const key = job.repo.toLowerCase();
    working[key] = (working[key] ?? 0) + 1;
  }

  const cards = repos.items.map((repo) => {
    const key = repo.full_name.toLowerCase();
    return { repo: repo, merged: merged[key] ?? 0, closed: closed[key] ?? 0, open: open[key] ?? 0, working: working[key] ?? 0 };
  });
  cards.sort((a, b) => b.repo.stars - a.repo.stars);
  // A repo deleted here with no pull requests of yours is gone; one with some goes to Removed.
  const shown = cards.filter((card) => !deleted.includes(card.repo.full_name) || card.merged + card.closed + card.open > 0);
  const removedNames = [...repos.removed, ...deleted];
  // Removed: the ones you deleted, and the ones where every PR of ours was closed, none merged or open and no issue in
  // progress, unless you picked them for Planned.
  const removed = shown.filter(
    (card) =>
      removedNames.includes(card.repo.full_name) ||
      (card.merged === 0 && card.open === 0 && card.working === 0 && card.closed > 0 && !repos.planned.includes(card.repo.full_name)),
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
    if (sort === "working") {
      return b.working - a.working;
    }
    return 0;
  });
  // Planned: none merged, and you picked it, a PR of yours is open there, or an issue is in progress.
  const planned = shown.filter(
    (card) =>
      card.merged === 0 && !removed.includes(card) && (repos.planned.includes(card.repo.full_name) || card.open > 0 || card.working > 0),
  );
  // Catalog by owner: each owner's most stars.
  const catalog = shown.filter((card) => !removed.includes(card) && !contributed.includes(card) && !planned.includes(card));
  const topStars: Record<string, number> = {};
  for (const card of catalog) {
    const owner = card.repo.full_name.split("/")[0].toLowerCase();
    topStars[owner] = Math.max(topStars[owner] ?? 0, card.repo.stars);
  }
  catalog.sort((a, b) => {
    const ownerA = a.repo.full_name.split("/")[0].toLowerCase();
    const ownerB = b.repo.full_name.split("/")[0].toLowerCase();
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

  return (
    <div className="flex h-full flex-col">
      <div className="flex min-h-9 shrink-0 items-center border-b px-3 py-1 text-muted-foreground tabular-nums">
        {shown.length} {shown.length === 1 ? "repository" : "repositories"}
      </div>

      {loaded && shown.length === 0 && <div className="p-3 text-muted-foreground">No repositories yet.</div>}
      {shown.length > 0 && (
        <div className="flex min-h-0 flex-1 gap-3 overflow-x-auto p-3">
          {columns.map((column) => {
            // An owner's repos together, where its first one comes.
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
            const ordered: typeof shown = [];
            for (const owner of owners) {
              ordered.push(...byOwner[owner]);
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
                          <DropdownMenuRadioItem value="working">{SORT_TITLE.working}</DropdownMenuRadioItem>
                        </DropdownMenuRadioGroup>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  )}
                </h2>
                <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto">
                  {ordered.map((card) => {
                    return (
                      <div
                        key={card.repo.full_name}
                        title={card.repo.full_name}
                        className="flex min-w-0 shrink-0 items-center gap-2 rounded-md border bg-card px-2 py-1.5"
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
                            {card.working > 0 && (
                              <span className="flex items-center gap-0.5 text-yellow-600 dark:text-yellow-400" title="In progress">
                                <GitPullRequestDraft className="size-3" />
                                {card.working}
                              </span>
                            )}
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
