/*
Automation (#/automation), laid out like a settings page: sections, each a list of rows with the name on the left and
its controls on the right. The page starts from the live "automation" topic and keeps your edits until Save
(PUT /api/automation with every field), which is enabled only when something changed. Your edits stay shown until the
live topic has them, so nothing flips back while it comes.
- Activities: one switch each. Manage repositories (on: finds and adds repositories, archives the ones that don't
  merge ours), Take new issues (take_new), Create pull requests (send_prs), Reply to reviews and comments
  (send_comments).
- Limits: Pull requests per day, Open pull requests and Open pull requests per repository, each a number and a switch;
  off means no limit (null) and its number can't be changed. Concurrent agents is a number only, at least 1.
- Repositories: Minimum stars, a number and a switch (off: null).
- AI policy: a switch per policy a repository can have (repo_signals.py ai_policy): on means its repositories may be
  worked on (ai_policies). Bans AI stays off and can't be turned on.
- Excluded repositories: the kinds that are never worked on, always on: Politically sensitive, Games and
  Chinese-language documentation.
A number must be a whole number (0 or more, Concurrent agents 1 or more) for Save to be enabled.
*/

import { Loader2 } from "lucide-react";
import { useState } from "react";
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
const AI_POLICIES = [
  { key: "welcome", title: "Welcomes AI" },
  { key: "disclose", title: "Allows AI with disclosure" },
  { key: "none", title: "No policy" },
  { key: "unclear", title: "Unclear" },
];
const EXCLUDED = ["Politically sensitive", "Games", "Chinese-language documentation"];

// The page's copy of the settings. numbers: each number box as typed (a limit that is off keeps its number, greyed
// out); limitOn: each limit's switch and Minimum stars'.
type Form = {
  activities: Record<string, boolean>;
  numbers: Record<string, string>;
  limitOn: Record<string, boolean>;
  policies: string[];
};

export default function Automation() {
  const automation = useLive("automation");
  const loaded = useLoaded("automation");
  const [edited, setEdited] = useState<Form | null>(null);
  const [saving, setSaving] = useState(false);

  // The settings as the backend has them, in the page's shape. A limit that is off shows a usual number.
  const saved: Form = {
    activities: { on: automation.on, take_new: automation.take_new, send_prs: automation.send_prs, send_comments: automation.send_comments },
    numbers: {
      max_prs_per_day: String(automation.max_prs_per_day ?? 10),
      max_open_prs: String(automation.max_open_prs ?? 30),
      max_open_per_repo: String(automation.max_open_per_repo ?? 2),
      max_agents: String(automation.max_agents),
      min_stars: String(automation.min_stars ?? 3000),
    },
    limitOn: {
      max_prs_per_day: automation.max_prs_per_day !== null,
      max_open_prs: automation.max_open_prs !== null,
      max_open_per_repo: automation.max_open_per_repo !== null,
      min_stars: automation.min_stars !== null,
    },
    policies: automation.ai_policies,
  };
  const form = edited ?? saved;

  // What Save sends, and the same from the backend, to tell whether anything changed. Policies in the page's order.
  const body = {
    on: form.activities.on,
    take_new: form.activities.take_new,
    send_prs: form.activities.send_prs,
    send_comments: form.activities.send_comments,
    max_prs_per_day: form.limitOn.max_prs_per_day ? Number(form.numbers.max_prs_per_day) : null,
    max_open_prs: form.limitOn.max_open_prs ? Number(form.numbers.max_open_prs) : null,
    max_open_per_repo: form.limitOn.max_open_per_repo ? Number(form.numbers.max_open_per_repo) : null,
    max_agents: Number(form.numbers.max_agents),
    min_stars: form.limitOn.min_stars ? Number(form.numbers.min_stars) : null,
    ai_policies: AI_POLICIES.filter((policy) => form.policies.includes(policy.key)).map((policy) => policy.key),
  };
  const current = {
    on: automation.on,
    take_new: automation.take_new,
    send_prs: automation.send_prs,
    send_comments: automation.send_comments,
    max_prs_per_day: automation.max_prs_per_day,
    max_open_prs: automation.max_open_prs,
    max_open_per_repo: automation.max_open_per_repo,
    max_agents: automation.max_agents,
    min_stars: automation.min_stars,
    ai_policies: AI_POLICIES.filter((policy) => automation.ai_policies.includes(policy.key)).map((policy) => policy.key),
  };
  const changed = JSON.stringify(body) !== JSON.stringify(current);

  // Every number that counts must be a whole number; Concurrent agents at least 1.
  let valid = /^\d+$/.test(form.numbers.max_agents.trim()) && body.max_agents >= 1;
  for (const key of ["max_prs_per_day", "max_open_prs", "max_open_per_repo", "min_stars"]) {
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

  const section = "space-y-2";
  const heading = "text-base font-semibold";
  const list = "divide-y rounded-lg border bg-card";
  const row = "flex min-h-11 items-center gap-4 px-4 py-2";

  return (
    <div className="flex h-full flex-col">
      <div className="flex min-h-9 shrink-0 items-center gap-3 border-b px-3 py-1">
        <span className="font-medium">Automation</span>
        <Button size="xs" className="ml-auto" onClick={save} disabled={!loaded || !changed || !valid || saving}>
          {saving && <Loader2 className="animate-spin" />}
          Save
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="max-w-3xl space-y-8 p-6 max-md:p-3">
          <div className={section}>
            <div className={heading}>Activities</div>
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
          </div>

          <div className={section}>
            <div className={heading}>Limits</div>
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
          </div>

          <div className={section}>
            <div className={heading}>Repositories</div>
            <div className={list}>
              <div className={row}>
                <span className="flex-1">Minimum stars</span>
                <Input
                  type="number"
                  min={0}
                  step={500}
                  className="w-24 text-right tabular-nums"
                  value={form.numbers.min_stars}
                  disabled={!form.limitOn.min_stars}
                  onChange={(event) => setEdited({ ...form, numbers: { ...form.numbers, min_stars: event.target.value } })}
                />
                <Switch
                  checked={form.limitOn.min_stars}
                  onCheckedChange={(on) => setEdited({ ...form, limitOn: { ...form.limitOn, min_stars: on } })}
                  aria-label="Minimum stars"
                />
              </div>
            </div>
          </div>

          <div className={section}>
            <div className={heading}>AI policy</div>
            <div className={list}>
              {AI_POLICIES.map((policy) => (
                <label key={policy.key} className={row}>
                  <span className="flex-1">{policy.title}</span>
                  <Switch
                    checked={form.policies.includes(policy.key)}
                    onCheckedChange={(on) =>
                      setEdited({ ...form, policies: on ? [...form.policies, policy.key] : form.policies.filter((key) => key !== policy.key) })
                    }
                  />
                </label>
              ))}
              <div className={row}>
                <span className="flex-1 text-muted-foreground">Bans AI</span>
                <Switch checked={false} disabled aria-label="Bans AI" />
              </div>
            </div>
          </div>

          <div className={section}>
            <div className={heading}>Excluded repositories</div>
            <div className={list}>
              {EXCLUDED.map((title) => (
                <div key={title} className={row}>
                  <span className="flex-1">{title}</span>
                  <Switch checked disabled aria-label={title} />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
