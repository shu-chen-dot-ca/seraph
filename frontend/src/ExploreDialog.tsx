/*
The Explore dialog, from the Explore card on the Dashboard: what decides which new repositories come in, laid out like
a settings page. It starts from the live "automation" topic and keeps your edits until Save (PUT /api/automation with
every field: Settings → Automation's as they are), which is enabled only when something changed and closes the dialog
once saved. Your edits stay shown until the live topic has them, so nothing flips back while it comes. Cancel, or
closing it any other way, drops the edits.
- The switch beside the title: Add repositories (add_repos). Off, nothing new is added and no Explore run starts.
- Include and Exclude: the kinds of repositories you want, and the kinds you don't, in your own words (include,
  exclude). They are kept in the data (Explore's profile), never in the code, and Explore, the issue checks and the
  agents follow them (github_searcher/explore.py, issue_tags.py). How big a repo should be goes in Include; under it
  Explore keeps its own minimum of over 1k stars.
- AI policy: a switch per policy a repository can have (repo_signals.py ai_policy): on means its repositories may be
  worked on (ai_policies). Bans AI stays off and can't be turned on.
*/

import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api, useLive, useLoaded, type AutomationData } from "@/live";

const AI_POLICIES = [
  { key: "welcome", title: "Welcomes AI" },
  { key: "disclose", title: "Allows AI with disclosure" },
  { key: "none", title: "No policy" },
  { key: "unclear", title: "Unclear" },
];

// The dialog's copy of the settings.
type Form = {
  addRepos: boolean;
  policies: string[];
  include: string;
  exclude: string;
};

export default function ExploreDialog(props: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const automation = useLive("automation");
  const loaded = useLoaded("automation");
  const [edited, setEdited] = useState<Form | null>(null);
  const [saving, setSaving] = useState(false);

  // The settings as the backend has them, in the dialog's shape.
  const saved: Form = {
    addRepos: automation.add_repos,
    policies: automation.ai_policies,
    include: automation.include,
    exclude: automation.exclude,
  };
  const form = edited ?? saved;

  // What Save sends, and the same from the backend, to tell whether anything changed. Settings → Automation's fields go
  // back as they are. Policies in the dialog's order.
  const body = {
    on: automation.on,
    add_repos: form.addRepos,
    take_new: automation.take_new,
    send_prs: automation.send_prs,
    send_comments: automation.send_comments,
    max_prs_per_day: automation.max_prs_per_day,
    max_open_prs: automation.max_open_prs,
    max_open_per_repo: automation.max_open_per_repo,
    max_agents: automation.max_agents,
    ai_policies: AI_POLICIES.filter((policy) => form.policies.includes(policy.key)).map((policy) => policy.key),
    include: form.include,
    exclude: form.exclude,
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
    ai_policies: AI_POLICIES.filter((policy) => automation.ai_policies.includes(policy.key)).map((policy) => policy.key),
    include: automation.include,
    exclude: automation.exclude,
  };
  const changed = JSON.stringify(body) !== JSON.stringify(current);

  // The edits are in the backend's topic now (saved, or put back by hand): follow the topic again. (Setting state while
  // rendering is React's pattern for state derived from props.)
  if (edited !== null && !changed && !saving) {
    setEdited(null);
  }

  async function save() {
    setSaving(true);
    try {
      await api<AutomationData>("/api/automation", { method: "PUT", body: body });
      toast.success("Saved");
      changeOpen(false);
    } catch (err) {
      toast.error(`Could not save: ${err instanceof Error ? err.message : err}`);
    }
    setSaving(false);
  }

  // Closed: the edits go.
  function changeOpen(open: boolean) {
    if (!open) {
      setEdited(null);
    }
    props.onOpenChange(open);
  }

  const section = "space-y-2";
  const heading = "text-base font-semibold";
  const list = "divide-y rounded-lg border bg-card";
  const row = "flex min-h-11 items-center gap-4 px-4 py-2";

  return (
    <Dialog open={props.open} onOpenChange={changeOpen}>
      <DialogContent className="gap-0 p-0 sm:max-w-2xl" aria-describedby={undefined}>
        <div className="flex items-center gap-3 px-4 pt-4 pb-3">
          <DialogTitle>Explore</DialogTitle>
          <Switch checked={form.addRepos} onCheckedChange={(on) => setEdited({ ...form, addRepos: on })} aria-label="Add repositories" />
        </div>
        <div className="max-h-[70vh] overflow-y-auto border-y">
          <div className="space-y-8 p-4">
            <div className={section}>
              <div className={heading}>Include</div>
              <Textarea rows={6} value={form.include} onChange={(event) => setEdited({ ...form, include: event.target.value })} aria-label="Include" />
            </div>

            <div className={section}>
              <div className={heading}>Exclude</div>
              <Textarea rows={6} value={form.exclude} onChange={(event) => setEdited({ ...form, exclude: event.target.value })} aria-label="Exclude" />
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
          </div>
        </div>
        <DialogFooter className="px-4 py-3">
          <Button variant="outline" onClick={() => changeOpen(false)}>
            Cancel
          </Button>
          <Button onClick={save} disabled={!loaded || !changed || saving}>
            {saving && <Loader2 className="animate-spin" />}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
