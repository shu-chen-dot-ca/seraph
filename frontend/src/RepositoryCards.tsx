/*
The Dashboard's Repository page (#/dashboard/repos): the repos on the Repos page as cards, four to a row (fewer on a
narrow window, one on a phone). Four sections:
- Contributed: repos that merged a pull request of yours. By stars, most first.
- Planned: repos you want to contribute to, none of yours merged yet: the ones you picked (Add to Planned, kept in the
  Repos list's planned, repo_list.py), and the ones where a PR of yours is open (unless the repo was given up). By stars.
- Catalog: the rest, grouped by owner: the owners with the most repos here first, an owner's repos always together, by
  stars, and owners with as many by their most starred repo.
- Rejected: none of yours merged, and either we tried and every PR of ours there was closed, or the repo was given up
  (archived, Repos' Archived). By stars.
A card: the owner's picture as its logo, owner/name, and under it in GitHub's colors: its stars (yellow), then of your
pull requests there how many it merged (purple), closed without a merge (red) and are still open (green). Gray instead:
a closed count of 0, and outside Contributed the stars and every count of 0.
A click opens it on GitHub. Outside Contributed, the ⋯ on a card (shown on hover) has Add to Planned, or Remove from
Planned for one you picked (POST /api/repos/plan).
Your pull requests are the ones the app follows (github_searcher/pr_tracking.py), from the live "prs" topic, so the
numbers update themselves.
*/

import { GitMerge, GitPullRequest, GitPullRequestClosed, MoreHorizontal, Star } from "lucide-react";
import { toast } from "sonner";

import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { api, useLive, useLoaded } from "@/live";
import { cn } from "@/lib/utils";

export default function RepositoryCards() {
  const repos = useLive("repos");
  const prs = useLive("prs");
  const loaded = useLoaded("repos");

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
  // Planned: none merged, and you picked it, or a PR of yours is open there (unless the repo was given up).
  const planned = cards.filter(
    (card) => card.merged === 0 && (repos.planned.includes(card.repo.full_name) || (card.open > 0 && !repos.archived.includes(card.repo.full_name))),
  );
  // Rejected: the others with none merged, where every PR of ours was closed, or the repo given up (archived).
  const rejected = cards.filter(
    (card) => card.merged === 0 && !planned.includes(card) && ((card.closed > 0 && card.open === 0) || repos.archived.includes(card.repo.full_name)),
  );
  // Catalog by owner: how many repos each owner has here, and its most stars.
  const catalog = cards.filter((card) => card.merged === 0 && !planned.includes(card) && !rejected.includes(card));
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
  const sections = [
    { title: "Contributed", contributed: true, cards: cards.filter((card) => card.merged > 0) },
    { title: "Planned", contributed: false, cards: planned },
    { title: "Catalog", contributed: false, cards: catalog },
    { title: "Rejected", contributed: false, cards: rejected },
  ];

  async function plan(name: string, value: boolean) {
    try {
      await api("/api/repos/plan", { method: "POST", body: { names: [name], planned: value } });
    } catch (err) {
      toast.error(`Could not change ${name}: ${err instanceof Error ? err.message : err}`);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex min-h-9 shrink-0 items-center border-b px-3 py-1 text-muted-foreground tabular-nums">
        {cards.length} {cards.length === 1 ? "repository" : "repositories"}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {loaded && cards.length === 0 && <div className="text-muted-foreground">No repositories yet.</div>}
        {sections.map(
          (section) =>
            section.cards.length > 0 && (
              <section key={section.title} className="mb-4">
                <h2 className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
                  {section.title}
                  <span className="tabular-nums">{section.cards.length}</span>
                </h2>
                <div className="grid grid-cols-4 gap-2 max-xl:grid-cols-3 max-lg:grid-cols-2 max-md:grid-cols-1">
                  {section.cards.map((card) => (
                    <div
                      key={card.repo.full_name}
                      title={card.repo.full_name}
                      className="group flex min-w-0 cursor-pointer items-center gap-2 rounded-md border bg-card px-2 py-1.5 hover:bg-accent/50"
                      onClick={() => window.open(card.repo.html_url, "_blank", "noreferrer")}
                    >
                      <img src={`https://github.com/${card.repo.full_name.split("/")[0]}.png?size=64`} alt="" className="size-8 shrink-0 rounded" />
                      <div className="min-w-0 flex-1">
                        <a
                          href={card.repo.html_url}
                          target="_blank"
                          rel="noreferrer"
                          className="block truncate font-medium text-foreground"
                          onClick={(event) => event.stopPropagation()}
                        >
                          {card.repo.full_name}
                        </a>
                        <div className="flex items-center gap-2.5 text-xs text-muted-foreground tabular-nums">
                          <span className={cn("flex items-center gap-0.5", section.contributed && "text-yellow-600 dark:text-yellow-400")} title="Stars">
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
                          <span className={cn("flex items-center gap-0.5", (section.contributed || card.open > 0) && "text-ok")} title="Your open PRs">
                            <GitPullRequest className="size-3" />
                            {card.open}
                          </span>
                        </div>
                      </div>
                      {!section.contributed && (
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <button
                              type="button"
                              className="flex size-6 shrink-0 items-center justify-center rounded-sm text-muted-foreground opacity-0 group-hover:opacity-100 hover:bg-accent hover:text-foreground data-[state=open]:bg-accent data-[state=open]:opacity-100 max-md:opacity-100"
                              aria-label={`Settings for ${card.repo.full_name}`}
                              onClick={(event) => event.stopPropagation()}
                            >
                              <MoreHorizontal className="size-4" />
                            </button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" onClick={(event) => event.stopPropagation()}>
                            {repos.planned.includes(card.repo.full_name) ? (
                              <DropdownMenuItem onSelect={() => plan(card.repo.full_name, false)}>Remove from Planned</DropdownMenuItem>
                            ) : (
                              <DropdownMenuItem onSelect={() => plan(card.repo.full_name, true)}>Add to Planned</DropdownMenuItem>
                            )}
                          </DropdownMenuContent>
                        </DropdownMenu>
                      )}
                    </div>
                  ))}
                </div>
              </section>
            ),
        )}
      </div>
    </div>
  );
}
