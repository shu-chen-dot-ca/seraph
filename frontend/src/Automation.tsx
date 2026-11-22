/*
Automation, a section of the Settings dialog (SettingsDialog.tsx): lists of rows with the name on the left and its
controls on the right. It starts from the live "automation" topic and keeps your edits until Save (PUT /api/automation
with every field: the Explore dialog's as they are), which is enabled only when something changed. Your edits stay shown
until the live topic has them, so nothing flips back while it comes. Discard changes drops them, and so does closing
Settings.
- Activities: one switch each. Manage repositories (on: archives the repositories that don't merge ours and later closes
  our PRs there; adding new ones is the Explore dialog's switch), Take new issues (take_new), Create pull requests
  (send_prs), Reply to reviews and comments (send_comments).
- Limits: Pull requests per day, Open pull requests and Open pull requests per repository, each a number and a switch;
  off means no limit (null) and its number can't be changed. Concurrent agents is a number only, at least 1.
A number must be a whole number (0 or more, Concurrent agents 1 or more) for Save to be enabled.
scrollTo: Settings was opened on Automation (the Dashboard's Limits title), so the dialog scrolls to it.
What decides which new repositories come in is the Explore dialog (ExploreDialog.tsx).
*/

import { Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { api, useLive, useLoaded, type AutomationData } from "@/live";

const ACTIVITIES = [
  { key: "on", title: "Manage repositories" },
  { key: "take_new", title: "Take new issues" },
  { key: "send_prs", title: "Create pull requests" },
  { key: "send_comments", title: "Reply to reviews and comments" },
];
const LIMITS = [
  { key: "max_prs_per_day", title: "Pull requests per day" },
  { key: "max_open_prs", title: "Open pull requests" },
  { key: "max_open_per_repo", title: "Open pull requests per repository" },
];

// The section's copy of the settings. numbers: each number box as typed (a limit that is off keeps its number, greyed
// out); limitOn: each limit's switch.
type Form = {
  activities: Record<string, boolean>;
  numbers: Record<string, string>;
  limitOn: Record<string, boolean>;
};

export default function Automation(props: { open: boolean; scrollTo: boolean }) {
  const automation = useLive("automation");
  const loaded = useLoaded("automation");
  const [edited, setEdited] = useState<Form | null>(null);
  const [saving, setSaving] = useState(false);
  const sectionRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (props.open && props.scrollTo && sectionRef.current !== null) {
      sectionRef.current.scrollIntoView({ block: "start" });
    }
  }, [props.open, props.scrollTo]);

  // The settings as the backend has them, in the section's shape. A limit that is off shows a usual number.
  const saved: Form = {
    activities: { on: automation.on, take_new: automation.take_new, send_prs: automation.send_prs, send_comments: automation.send_comments },
    numbers: {
      max_prs_per_day: String(automation.max_prs_per_day ?? 10),
      max_open_prs: String(automation.max_open_prs ?? 30),
      max_open_per_repo: String(automation.max_open_per_repo ?? 2),
      max_agents: String(automation.max_agents),
    },
    limitOn: {
      max_prs_per_day: automation.max_prs_per_day !== null,
      max_open_prs: automation.max_open_prs !== null,
      max_open_per_repo: automation.max_open_per_repo !== null,
    },
  };
  const form = edited ?? saved;

  // What Save sends, and the same from the backend, to tell whether anything changed. The Explore dialog's fields go
  // back as they are (its Include and Exclude are left out, so they stay).
  const body = {
    on: form.activities.on,
    add_repos: automation.add_repos,
    take_new: form.activities.take_new,
    send_prs: form.activities.send_prs,
    send_comments: form.activities.send_comments,
    max_prs_per_day: form.limitOn.max_prs_per_day ? Number(form.numbers.max_prs_per_day) : null,
    max_open_prs: form.limitOn.max_open_prs ? Number(form.numbers.max_open_prs) : null,
    max_open_per_repo: form.limitOn.max_open_per_repo ? Number(form.numbers.max_open_per_repo) : null,
    max_agents: Number(form.numbers.max_agents),
    ai_policies: automation.ai_policies,
  };
  const current = {
    on: automation.on,
    add_repos: automation.add_repos,
    take_new: automation.take_new,
    send_prs: automation.send_prs,
    send_comments: automation.send_comments,
    max_prs_per_day: automation.max_prs_per_day,
    max_open_prs: automation.max_open_prs,
    max_open_per_repo: automation.max_open_per_repo,
    max_agents: automation.max_agents,
    ai_policies: automation.ai_policies,
  };
  const changed = JSON.stringify(body) !== JSON.stringify(current);

  // Every number that counts must be a whole number; Concurrent agents at least 1.
  let valid = /^\d+$/.test(form.numbers.max_agents.trim()) && body.max_agents >= 1;
  for (const key of ["max_prs_per_day", "max_open_prs", "max_open_per_repo"]) {
    if (form.limitOn[key] && !/^\d+$/.test(form.numbers[key].trim())) {
      valid = false;
    }
  }

  // The edits are in the backend's topic now (saved, or put back by hand): follow the topic again. Not while a number
  // box is being retyped. (Setting state while rendering is React's pattern for state derived from props.)
  if (edited !== null && !changed && valid && !saving) {
    setEdited(null);
  }

  async function save() {
    setSaving(true);
    try {
      await api<AutomationData>("/api/automation", { method: "PUT", body: body });
      toast.success("Saved");
    } catch (err) {
      toast.error(`Could not save: ${err instanceof Error ? err.message : err}`);
    }
    setSaving(false);
  }

  const list = "divide-y rounded-lg border bg-card";
  const row = "flex min-h-11 items-center gap-4 px-4 py-2";

  return (
    <section ref={sectionRef} className="scroll-mt-4 space-y-2">
      <div className="font-medium">Automation</div>
      <div className="text-muted-foreground">Activities</div>
      <div className={list}>
        {ACTIVITIES.map((activity) => (
          <label key={activity.key} className={row}>
            <span className="flex-1">{activity.title}</span>
            <Switch
              checked={form.activities[activity.key]}
              onCheckedChange={(on) => setEdited({ ...form, activities: { ...form.activities, [activity.key]: on } })}
            />
          </label>
        ))}
      </div>
      <div className="pt-2 text-muted-foreground">Limits</div>
      <div className={list}>
        {LIMITS.map((limit) => (
          <div key={limit.key} className={row}>
            <span className="flex-1">{limit.title}</span>
            <Input
              type="number"
              min={0}
              className="w-24 text-right tabular-nums"
              value={form.numbers[limit.key]}
              disabled={!form.limitOn[limit.key]}
              onChange={(event) => setEdited({ ...form, numbers: { ...form.numbers, [limit.key]: event.target.value } })}
            />
            <Switch
              checked={form.limitOn[limit.key]}
              onCheckedChange={(on) => setEdited({ ...form, limitOn: { ...form.limitOn, [limit.key]: on } })}
              aria-label={`${limit.title} limit`}
            />
          </div>
        ))}
        <div className={row}>
          <span className="flex-1">Concurrent agents</span>
          <Input
            type="number"
            min={1}
            className="w-24 text-right tabular-nums"
            value={form.numbers.max_agents}
            onChange={(event) => setEdited({ ...form, numbers: { ...form.numbers, max_agents: event.target.value } })}
          />
          {/* Where the others' switch is, so the numbers line up. */}
          <span className="w-8 shrink-0" />
        </div>
      </div>
      <div className="flex items-center gap-2 pt-1">
        <Button size="sm" onClick={save} disabled={!loaded || !changed || !valid || saving}>
          {saving && <Loader2 className="animate-spin" />}
          Save
        </Button>
        {edited !== null && (
          <Button variant="ghost" size="sm" onClick={() => setEdited(null)}>
            Discard changes
          </Button>
        )}
      </div>
    </section>
  );
}
