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
- Catalog: the rest. The ones with an open PR of yours first, then the others, each by stars.
- Removed: the ones you deleted that have pull requests of yours (the Repos list's removed), and every other one with a
  PR of yours closed that isn't in another column (none merged or open, no issue in progress, never in Target). By
  stars. Its ⋯ takes one out with another chance (POST /api/repos/restore, the Repos list's restored, with when): Add to
  Catalog or Add to Target, or Add to Contributed for one with a merged PR. The same rules put it back, but only its PRs
  closed without a merge after that count.
Every repo with a pull request of yours has a card, also one that isn't in the Repos list (a PR you opened by hand, a
repo taken out of the list): made from its pull requests, so it goes to its column like any other (only closed ones:
Removed). Its stars (and contributors) are asked of POST /api/repos/counts once; until they come it shows – and comes
last in its column. Its ⋯ has only the moves (none in Catalog: no ⋯ there).
A card: the owner's picture as its logo, owner/name, and under it in color: its stars (yellow), outside Prioritized and
Contributed how many contributors it has (blue, a people icon: the number on its GitHub page, from the live repos topic,
or for a card made from PRs asked of POST /api/repos/counts; none while not known), then of your pull
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
list. A card with none of these has no ⋯. In Catalog a card also has a red trash button left of its ⋯ (with a border) that
does that Delete (or Add to Removed) at once.
A card also moves by dragging it with the mouse between Prioritized and Contributed; the column it can go to lights up
while it's dragged.
A move, Add to or Remove from Target (POST /api/repos/move) or out of Removed shows at once, before the live feed has it
(the repos topic comes every few seconds).
Over the cards on the right, left of the dialog's close button, two boxes, Owner / Repository, add a repo to Target, each
with a cross that empties it. Typing in Owner shows under it the GitHub accounts whose login has the text in it (GET
/api/repos/owners: logo, login, User or Organization; "NVIDIA": NVIDIA, NVIDIA-NeMo, ...); a click on one, or Enter for
the first, puts it in Owner and goes on to Repository. In Repository (a moment after the last key) they find on GitHub
(GET /api/repos/find): the repo a link or owner/name points to; with an Owner, its repos (the most stars first), only
those whose name has the Repository text in it; with no Owner, the best matches of the Repository text. They show as
cards under the boxes (logo, owner/name, stars, contributors as on the cards). In both, a click on the name (the text itself) opens it on GitHub in a
new tab instead. A click on one, or Enter for the first, adds it to the Repos list if it isn't there
and to Target (POST /api/repos/add_target; one in Removed leaves it with another chance), shown at once; the boxes and
what they found stay, for the next one. What they found shows from a click in a box until a click elsewhere on the page:
it stays while the window is away (another tab, a name opened on GitHub).
Every column but Removed has a ⚙ right after its count, which opens its settings in a pop-up (a dialog over the page,
titled "<column> settings"; Save sends them, PUT /api/automation/column, the live "automation" topic's columns;
backend/automation_api.py): Open PRs per repository (the most PRs of ours open at once in each of its repos; empty: the
usual limits; else a whole number from 1), Model (Default, Fable, Opus or Sonnet: the agents fixing issues and
following up on PRs in its repos, for new jobs) and Issues to scan (how many of each of its repos' newest open issues,
opened in the last 14 days, Add issues looks at; a whole number from 1, 300 at first).
Every column but Removed has a switch in its header: on, agents take new issues of its repos; off, they don't, and what
is going there goes on (PUT /api/automation/take_from, the live "automation" topic's take_from). Agents take new issues
column by column: Target, Prioritized, Contributed, then Catalog (backend/issues_api.py take_from_catalog); Removed
never.
Your pull requests are the ones the app follows (github_searcher/pr_tracking.py), from the live "prs" topic, so the
numbers update themselves.
*/

import {
  ChevronDown,
  GitMerge,
  GitPullRequest,
  GitPullRequestClosed,
  GitPullRequestDraft,
  MoreHorizontal,
  Search,
  Settings,
  Star,
  Trash2,
  Users,
  X,
} from "lucide-react";
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
type ColumnSetting = { max_open_per_repo: number | null; model: string; max_scan?: number };
// Issues to scan when a column's settings don't say (saved before it): backend/repo_automation_api.py MAX_SCAN.
const MAX_SCAN = 300;
const MODEL_CHOICES = [
  { value: "default", title: "Default" },
  { value: "fable", title: "Fable" },
  { value: "opus", title: "Opus" },
  { value: "sonnet", title: "Sonnet" },
];
// A repo the boxes over the cards found on GitHub, and an account the Owner box found.
type Found = { full_name: string; description: string; stars: number };
type Owner = { login: string; type: string };

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
  // The repos added to Target with the boxes over the cards, until the live feed has them.
  const [added, setAdded] = useState<Found[]>([]);
  // The boxes' text (Owner, Repository), the repos they found and for which text ("owner/repository"), the accounts the
  // Owner box found and for which text, and which box's list shows ("owner", "repository" or ""): the accounts are
  // Owner's, the repos Repository's. It is set when a box gets the focus and cleared by a click elsewhere on the page
  // only, not when the window loses the focus. searchArea: the boxes and their lists.
  const [owner, setOwner] = useState("");
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<Found[]>([]);
  const [foundFor, setFoundFor] = useState("");
  const [owners, setOwners] = useState<Owner[]>([]);
  const [ownersFor, setOwnersFor] = useState("");
  const [list, setList] = useState("");
  const repositoryBox = useRef<HTMLInputElement>(null);
  const searchArea = useRef<HTMLDivElement>(null);
  // The stars and contributors of repos with no signals (found by the boxes, cards made from PRs alone), by name in
  // lower case (null: not known), and the ones asked already (each once).
  const [repoCounts, setRepoCounts] = useState<Record<string, { stars: number | null; contributors: number | null }>>({});
  const asked = useRef<string[]>([]);
  // The column switches flipped here, until the live feed has them.
  const [switched, setSwitched] = useState<Record<string, boolean>>({});
  // The column settings saved here, until the live feed has them; the column whose settings pop-up is open ("": none),
  // and what its Open PRs per repository box, Model and Issues to scan box say.
  const [columnEdits, setColumnEdits] = useState<Record<string, ColumnSetting>>({});
  const [settingsFor, setSettingsFor] = useState("");
  const [limitText, setLimitText] = useState("");
  const [modelPick, setModelPick] = useState("default");
  const [scanText, setScanText] = useState(String(MAX_SCAN));
  // The card being dragged, and the column it comes from.
  const [dragging, setDragging] = useState<{ name: string; from: string } | null>(null);

  // Once the live feed comes again, it has them.
  useEffect(() => {
    setMoved({});
    setRestored([]);
    setAdded([]);
  }, [repos]);

  // The Owner box finds accounts a moment after the last key; an answer to older text is dropped.
  useEffect(() => {
    const text = owner.trim();
    if (list !== "owner" || text.length < 2) {
      setOwners([]);
      return;
    }
    let old = false;
    const timer = window.setTimeout(async () => {
      try {
        const answer = await api<{ items: Owner[] }>(`/api/repos/owners?q=${encodeURIComponent(text)}`);
        if (!old) {
          setOwners(answer.items);
          setOwnersFor(text);
        }
      } catch (err) {
        toast.error(`Could not search GitHub: ${err instanceof Error ? err.message : err}`);
      }
    }, 300);
    return () => {
      old = true;
      window.clearTimeout(timer);
    };
  }, [owner, list]);

  // The Repository box finds repos the same way, while its list shows. An Owner alone is enough.
  useEffect(() => {
    const text = query.trim();
    const by = owner.trim();
    if (list !== "repository") {
      return;
    }
    if (by === "" && text.length < 2) {
      setFound([]);
      return;
    }
    let old = false;
    const timer = window.setTimeout(async () => {
      try {
        const answer = await api<{ items: Found[] }>(`/api/repos/find?owner=${encodeURIComponent(by)}&q=${encodeURIComponent(text)}`);
        if (!old) {
          setFound(answer.items);
          setFoundFor(`${by}/${text}`);
        }
      } catch (err) {
        toast.error(`Could not search GitHub: ${err instanceof Error ? err.message : err}`);
      }
    }, 300);
    return () => {
      old = true;
      window.clearTimeout(timer);
    };
  }, [owner, query, list]);

  // A click elsewhere on the page closes the boxes' list.
  useEffect(() => {
    function onPointerDown(event: PointerEvent) {
      if (searchArea.current !== null && !searchArea.current.contains(event.target as Node)) {
        setList("");
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, []);
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
  // A repo added to Target here: its card at once, until the live feed has it.
  for (const each of added) {
    const key = each.full_name.toLowerCase();
    if (listedNames.includes(key)) {
      continue;
    }
    listedNames.push(key);
    const repo = {
      full_name: each.full_name,
      description: each.description,
      stars: each.stars,
      default_branch: "",
      html_url: `https://github.com/${each.full_name}`,
      note: "",
      added_by: "user",
      added_at: "",
    };
    cards.push({ repo: repo, listed: true, merged: merged[key] ?? 0, closed: closed[key] ?? 0, open: open[key] ?? 0, working: working[key] ?? 0 });
  }
  for (const pr of prs.items) {
    const key = pr.repo.toLowerCase();
    if (pr.relation !== "author" || listedNames.includes(key)) {
      continue;
    }
    listedNames.push(key);
    // Its stars once asked (0 until then: last in its column).
    const repo = {
      full_name: pr.repo,
      description: "",
      stars: repoCounts[key]?.stars ?? 0,
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
  // Catalog: the rest. Those with an open PR of yours first, each group by stars (cards are by stars already).
  const catalog = shown.filter((card) => !removed.includes(card) && !prioritized.includes(card) && !contributed.includes(card) && !target.includes(card));
  catalog.sort((a, b) => (b.open > 0 ? 1 : 0) - (a.open > 0 ? 1 : 0));
  // moveTo: the column a card here can move to (its ⋯ or a drag), and back. key: its switch in take_from ("" for none).
  const columns = [
    { title: "Prioritized", key: "prioritized", removed: false, moveTo: "Contributed", cards: prioritized },
    { title: "Contributed", key: "contributed", removed: false, moveTo: "Prioritized", cards: contributed },
    { title: "Target", key: "target", removed: false, moveTo: "", cards: target },
    { title: "Catalog", key: "catalog", removed: false, moveTo: "", cards: catalog },
    { title: "Removed", key: "", removed: true, moveTo: "", cards: removed },
  ];

  // The stars and contributors of repos the live feed has no numbers for: what the boxes found and cards made from PRs
  // alone, asked ten at a time, each answer shown as it comes. A failed ask is asked again next time.
  useEffect(() => {
    const names = [...found.map((each) => each.full_name), ...shown.filter((card) => !card.listed).map((card) => card.repo.full_name)];
    const keys = names.map((name) => name.toLowerCase()).filter((key) => repos.contributors[key] === undefined && !asked.current.includes(key));
    asked.current = [...asked.current, ...keys];
    for (let start = 0; start < keys.length; start += 10) {
      const group = keys.slice(start, start + 10);
      api<Record<string, { stars: number | null; contributors: number | null }>>("/api/repos/counts", { method: "POST", body: { names: group } })
        .then((answer) => setRepoCounts((old) => ({ ...old, ...answer })))
        .catch(() => {
          asked.current = asked.current.filter((key) => !group.includes(key));
        });
    }
  }, [found, prs, repos]);

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

  // An account the Owner box found: it goes in Owner, and Repository takes the focus (and shows its repos).
  function pickOwner(login: string) {
    setOwner(login);
    setOwners([]);
    repositoryBox.current?.focus();
  }

  // A repo the boxes found, to Target (and the Repos list): shown there at once, as a move is. The boxes and their list
  // stay, for the next one.
  async function addTarget(each: Found) {
    setAdded((old) => [...old, each]);
    setRestored((old) => [...old, each.full_name]);
    setMoved((old) => ({ ...old, [each.full_name]: "Target" }));
    try {
      await api("/api/repos/add_target", { method: "POST", body: { name: each.full_name } });
    } catch (err) {
      setAdded((old) => old.filter((other) => other.full_name !== each.full_name));
      setRestored((old) => old.filter((other) => other !== each.full_name));
      setMoved((old) => {
        const next = { ...old };
        delete next[each.full_name];
        return next;
      });
      toast.error(`Could not add ${each.full_name}: ${err instanceof Error ? err.message : err}`);
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
  // And its Issues to scan: a whole number from 1.
  const scanTyped = Number(scanText.trim());
  const scanValid = scanText.trim() !== "" && Number.isInteger(scanTyped) && scanTyped >= 1;

  function saveSettings() {
    if (!limitValid || !scanValid) {
      return;
    }
    saveColumn(settingsFor, { max_open_per_repo: limitTyped, model: modelPick, max_scan: scanTyped });
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
      <div className="flex h-9 shrink-0 items-center border-b px-1">
        {tabs}
        {/* pr-10: room for the dialog's close button. The crosses: onMouseDown keeps the focus in the box. Enter takes
        only what was found for the text now, not for the text before the last keys. */}
        <div ref={searchArea} className="relative ml-auto flex items-center gap-1.5 pr-10">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={owner}
              placeholder="Owner"
              aria-label="Owner"
              className="w-48 pr-7 pl-7"
              onChange={(event) => setOwner(event.target.value)}
              onFocus={() => setList("owner")}
              onKeyDown={(event) => {
                if (event.key !== "Enter") {
                  return;
                }
                if (owners.length > 0 && ownersFor === owner.trim()) {
                  pickOwner(owners[0].login);
                } else {
                  repositoryBox.current?.focus();
                }
              }}
            />
            {owner !== "" && (
              <button
                type="button"
                aria-label="Clear owner"
                className="absolute top-1/2 right-1.5 -translate-y-1/2 text-muted-foreground"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => setOwner("")}
              >
                <X className="size-3.5" />
              </button>
            )}
            {/* The accounts it found, as cards like the repos'. onMouseDown: a click keeps the focus in the box. A div, not a
            button: the name in it is a link (to GitHub, not a pick). */}
            {list === "owner" && owners.length > 0 && (
              <div
                className="absolute top-full left-0 z-50 mt-1 flex max-h-[60vh] w-64 flex-col gap-1 overflow-y-auto rounded-md border bg-popover p-1 shadow-md"
                onMouseDown={(event) => event.preventDefault()}
              >
                {owners.map((each) => (
                  <div
                    key={each.login}
                    className="flex min-w-0 shrink-0 cursor-pointer items-center gap-2 rounded-md border bg-card px-2 py-1.5 hover-line"
                    onClick={() => pickOwner(each.login)}
                  >
                    <img src={`https://github.com/${each.login}.png?size=64`} alt="" className="size-8 shrink-0 rounded" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium text-foreground">
                        <a
                          href={`https://github.com/${each.login}`}
                          target="_blank"
                          rel="noreferrer"
                          className="hover:underline"
                          onClick={(event) => event.stopPropagation()}
                        >
                          {each.login}
                        </a>
                      </div>
                      <div className="text-xs text-muted-foreground">{each.type}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          <span className="text-muted-foreground">/</span>
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              ref={repositoryBox}
              value={query}
              placeholder="Repository"
              aria-label="Repository"
              className="w-64 pr-7 pl-7"
              onChange={(event) => setQuery(event.target.value)}
              onFocus={() => setList("repository")}
              onKeyDown={(event) => {
                if (event.key === "Enter" && found.length > 0 && foundFor === `${owner.trim()}/${query.trim()}`) {
                  addTarget(found[0]);
                }
              }}
            />
            {query !== "" && (
              <button
                type="button"
                aria-label="Clear repository"
                className="absolute top-1/2 right-1.5 -translate-y-1/2 text-muted-foreground"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => setQuery("")}
              >
                <X className="size-3.5" />
              </button>
            )}
          </div>
          {/* Cards like the ones below. onMouseDown: a click keeps the focus in the box. A div, not a button: the name in it is
          a link (to GitHub, not an add). */}
          {list === "repository" && found.length > 0 && (
            <div
              className="absolute top-full right-10 z-50 mt-1 flex max-h-[60vh] w-80 flex-col gap-1 overflow-y-auto rounded-md border bg-popover p-1 shadow-md"
              onMouseDown={(event) => event.preventDefault()}
            >
              {found.map((each) => {
                // Its contributors: null when not known.
                const people = repos.contributors[each.full_name.toLowerCase()] ?? repoCounts[each.full_name.toLowerCase()]?.contributors ?? null;
                return (
                  <div
                    key={each.full_name}
                    className="flex min-w-0 shrink-0 cursor-pointer items-center gap-2 rounded-md border bg-card px-2 py-1.5 hover-line"
                    onClick={() => addTarget(each)}
                  >
                    <img src={`https://github.com/${each.full_name.split("/")[0]}.png?size=64`} alt="" className="size-8 shrink-0 rounded" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium text-foreground">
                        <a
                          href={`https://github.com/${each.full_name}`}
                          target="_blank"
                          rel="noreferrer"
                          className="hover:underline"
                          onClick={(event) => event.stopPropagation()}
                        >
                          {each.full_name}
                        </a>
                      </div>
                      <div className="flex items-center gap-2.5 text-xs text-muted-foreground tabular-nums">
                        <span className="flex items-center gap-0.5 text-yellow-600 dark:text-yellow-400">
                          <Star className="size-3" />
                          {each.stars.toLocaleString("en", { notation: "compact" })}
                        </span>
                        {people !== null && (
                          <span className="flex items-center gap-0.5 text-blue-500">
                            <Users className="size-3" />
                            {people.toLocaleString("en", { notation: "compact" })}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

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
                        setScanText(String(setting.max_scan ?? MAX_SCAN));
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
                    // Its contributors, outside Prioritized and Contributed: null when not known.
                    let people: number | null = null;
                    if (column.title !== "Prioritized" && column.title !== "Contributed") {
                      people = repos.contributors[card.repo.full_name.toLowerCase()] ?? repoCounts[card.repo.full_name.toLowerCase()]?.contributors ?? null;
                    }
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
                              {card.listed || (repoCounts[card.repo.full_name.toLowerCase()]?.stars ?? null) !== null
                                ? card.repo.stars.toLocaleString("en", { notation: "compact" })
                                : "–"}
                            </span>
                            {people !== null && (
                              <span className="flex items-center gap-0.5 text-blue-500">
                                <Users className="size-3" />
                                {people.toLocaleString("en", { notation: "compact" })}
                              </span>
                            )}
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
                        {/* Catalog's trash: its ⋯'s Delete (or Add to Removed), at once. title="": no tooltip (the card's name). */}
                        {column.title === "Catalog" && card.listed && (
                          <button
                            type="button"
                            title=""
                            className="flex size-6 shrink-0 items-center justify-center rounded-sm border text-destructive hover:bg-destructive/10"
                            aria-label={`${card.merged + card.closed + card.open > 0 ? "Add to Removed" : "Delete"} ${card.repo.full_name}`}
                            onClick={() => deleteRepo(card.repo.full_name)}
                          >
                            <Trash2 className="size-3.5" />
                          </button>
                        )}
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
            <label htmlFor="column-max-scan" className="text-muted-foreground">
              Issues to scan
            </label>
            <Input
              id="column-max-scan"
              type="number"
              min={1}
              step={1}
              value={scanText}
              aria-invalid={!scanValid}
              onChange={(event) => setScanText(event.target.value)}
            />
            {!scanValid && <p className="col-start-2 text-xs text-destructive">A whole number from 1.</p>}
            <button type="submit" className="hidden" />
          </form>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSettingsFor("")}>
              Cancel
            </Button>
            <Button onClick={saveSettings} disabled={!limitValid || !scanValid}>
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
