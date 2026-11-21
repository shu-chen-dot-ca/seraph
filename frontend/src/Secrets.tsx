/*
Settings → Secrets: the tokens the app needs (GitHub tokens for search, the agents' Claude Code token and Fix all's), and
where the app's secrets are kept (those tokens, your GitHub sign-in and the sign-in app's client secret), with Move
secrets to AWS Secrets Manager (github_searcher/secret_vault.py has how it works). A token is pasted here and never
shown again: only its last 4 characters.

GitHub tokens: one row per token, Remove, and Add for a new one. Claude Code token and Claude Code token (Fix all): one
field each, Save puts the pasted token in (or replaces the one there), Remove takes it out. A new GitHub token is used at
once; a new Claude Code token from each agent's next start.

On this computer: the names in data/, and a form for an AWS access key (ID, secret, region). Move secrets puts them in
AWS, checks AWS kept them, and only then removes them from this computer; the access key goes in the system keyring. In
AWS: the secret's name and region, Open in AWS (its page in the AWS console), the names it holds, and, when some are
still on this computer, Move secrets with the same key.

GET /api/secrets each time Settings opens; every change answers with it again.
*/

import { ExternalLink, Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/live";
import { timeAgo } from "@/lib/utils";

type Status = {
  kind: "computer" | "aws";
  // The tokens set, each with its last 4 characters.
  tokens: { name: string; end: string }[];
  on_disk: string[];
  // Only with aws.
  region?: string;
  secret_name?: string;
  moved_at?: string;
  names?: string[];
  console_url?: string;
};

// The two Claude Code tokens, each with its own field.
const CLAUDE_TOKENS = [
  { name: "CLAUDE_CODE_OAUTH_TOKEN", label: "Claude Code token" },
  { name: "CLAUDE_CODE_OAUTH_TOKEN_VM", label: "Claude Code token (Fix all)" },
];

export default function Secrets(props: { open: boolean }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState("");
  const [accessKeyId, setAccessKeyId] = useState("");
  const [secretAccessKey, setSecretAccessKey] = useState("");
  const [region, setRegion] = useState("us-east-1");
  const [moving, setMoving] = useState(false);
  // What is pasted in each token field, by name ("github" for a new GitHub token), until it is saved.
  const [pasted, setPasted] = useState<Record<string, string>>({});
  // The field or row being saved or removed right now.
  const [busy, setBusy] = useState("");

  useEffect(() => {
    if (!props.open) {
      return;
    }
    let stopped = false;
    api<Status>("/api/secrets")
      .then((data) => {
        if (!stopped) {
          setStatus(data);
        }
      })
      .catch((err) => {
        if (!stopped) {
          setError(`Could not load the secrets: ${err instanceof Error ? err.message : err}`);
        }
      });
    return () => {
      stopped = true;
      setPasted({});
    };
  }, [props.open]);

  async function move() {
    setMoving(true);
    setError("");
    try {
      const body = { access_key_id: accessKeyId, secret_access_key: secretAccessKey, region: region };
      setStatus(await api<Status>("/api/secrets/move", { method: "POST", body: body }));
      setAccessKeyId("");
      setSecretAccessKey("");
      toast.success("Secrets moved to AWS Secrets Manager. They are no longer on this computer.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
    setMoving(false);
  }

  // Adds a GitHub token (key "github") or sets a Claude Code token (key: its name) from what is pasted in its field.
  async function saveToken(key: string) {
    setBusy(key);
    setError("");
    try {
      const body = { value: pasted[key] ?? "" };
      if (key === "github") {
        setStatus(await api<Status>("/api/secrets/github_tokens", { method: "POST", body: body }));
      } else {
        setStatus(await api<Status>(`/api/secrets/${key}`, { method: "PUT", body: body }));
      }
      setPasted({ ...pasted, [key]: "" });
      toast.success("Token saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
    setBusy("");
  }

  async function removeToken(name: string) {
    setBusy(name);
    setError("");
    try {
      setStatus(await api<Status>(`/api/secrets/${name}`, { method: "DELETE" }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
    setBusy("");
  }

  // GitHub tokens in the balancer's order: GITHUB_TOKEN, then GITHUB_TOKEN_2, _3, ... by number.
  const githubTokens = (status?.tokens ?? [])
    .filter((token) => token.name.startsWith("GITHUB_TOKEN"))
    .sort((a, b) => Number(a.name.replace("GITHUB_TOKEN_", "").replace("GITHUB_TOKEN", "1")) - Number(b.name.replace("GITHUB_TOKEN_", "").replace("GITHUB_TOKEN", "1")));

  return (
    <section>
      <div className="mb-2 font-medium">Secrets</div>
      {error !== "" && <p className="mb-2 border border-destructive/40 bg-destructive/10 px-3 py-1.5 text-destructive">{error}</p>}
      {status === null && error === "" && (
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" /> Loading…
        </div>
      )}

      {status !== null && (
        <div className="mb-4 space-y-3">
          <div className="space-y-1">
            <div>GitHub tokens</div>
            {githubTokens.length === 0 && <p className="text-muted-foreground">No GitHub tokens.</p>}
            {githubTokens.map((token) => (
              <div key={token.name} className="flex items-center gap-1.5">
                <span className="min-w-0 flex-1 font-mono text-xs">••••{token.end}</span>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Remove the token ending in ${token.end}`}
                  title="Remove"
                  disabled={busy !== ""}
                  onClick={() => removeToken(token.name)}
                >
                  {busy === token.name ? <Loader2 className="animate-spin" /> : <X />}
                </Button>
              </div>
            ))}
            <div className="flex items-center gap-1.5">
              <Input
                className="min-w-0 flex-1 font-mono text-xs"
                placeholder="New token"
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={pasted.github ?? ""}
                onChange={(event) => setPasted({ ...pasted, github: event.target.value })}
              />
              <Button size="sm" onClick={() => saveToken("github")} disabled={busy !== "" || (pasted.github ?? "").trim() === ""}>
                {busy === "github" && <Loader2 className="animate-spin" />}
                Add
              </Button>
            </div>
          </div>

          {CLAUDE_TOKENS.map((slot) => {
            const set = status.tokens.find((token) => token.name === slot.name);
            return (
              <div key={slot.name} className="space-y-1">
                <div>{slot.label}</div>
                <div className="flex items-center gap-1.5">
                  <Input
                    className="min-w-0 flex-1 font-mono text-xs"
                    placeholder={set === undefined ? "Not set" : `••••${set.end}`}
                    type="password"
                    autoComplete="off"
                    spellCheck={false}
                    value={pasted[slot.name] ?? ""}
                    onChange={(event) => setPasted({ ...pasted, [slot.name]: event.target.value })}
                  />
                  <Button size="sm" onClick={() => saveToken(slot.name)} disabled={busy !== "" || (pasted[slot.name] ?? "").trim() === ""}>
                    {busy === slot.name && <Loader2 className="animate-spin" />}
                    Save
                  </Button>
                  {set !== undefined && (
                    <Button variant="outline" size="sm" onClick={() => removeToken(slot.name)} disabled={busy !== ""}>
                      Remove
                    </Button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {status !== null && status.kind === "computer" && (
        <div className="space-y-2">
          <p>
            Kept on this computer, in <span className="font-mono text-xs">data/</span>
            {status.on_disk.length > 0 && <span className="text-muted-foreground">: {status.on_disk.join(", ")}</span>}
          </p>
          <div className="space-y-1.5 rounded-lg border p-3">
            <div>Move them to AWS Secrets Manager</div>
            <Input
              className="font-mono text-xs"
              placeholder="Access key ID"
              autoComplete="off"
              spellCheck={false}
              value={accessKeyId}
              onChange={(event) => setAccessKeyId(event.target.value)}
            />
            <Input
              className="font-mono text-xs"
              placeholder="Secret access key"
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={secretAccessKey}
              onChange={(event) => setSecretAccessKey(event.target.value)}
            />
            <Input
              className="font-mono text-xs"
              placeholder="Region, e.g. us-east-1"
              spellCheck={false}
              value={region}
              onChange={(event) => setRegion(event.target.value)}
            />
            <Button size="sm" onClick={move} disabled={moving || accessKeyId === "" || secretAccessKey === "" || region === ""}>
              {moving && <Loader2 className="animate-spin" />}
              Move secrets
            </Button>
            <p className="text-xs text-muted-foreground">
              Use an IAM user that may only use secrets named seraph/* (docs/security.md has the policy). Its key is kept in the system
              keyring. The secrets leave data/ only once AWS has them.
            </p>
          </div>
        </div>
      )}

      {status !== null && status.kind === "aws" && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span>AWS Secrets Manager</span>
            <span className="font-mono text-xs text-muted-foreground">
              {status.secret_name} · {status.region}
            </span>
            <Button variant="outline" size="sm" className="ml-auto" asChild>
              <a href={status.console_url} target="_blank" rel="noreferrer">
                <ExternalLink /> Open in AWS
              </a>
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            {(status.names ?? []).join(", ")}. Moved {timeAgo(status.moved_at ?? "")}. The access key is in the system keyring.
          </p>
          {status.on_disk.length > 0 && (
            <div className="flex items-center gap-2">
              <span className="min-w-0 flex-1 text-warn">Still on this computer: {status.on_disk.join(", ")}</span>
              <Button variant="outline" size="sm" onClick={move} disabled={moving}>
                {moving && <Loader2 className="animate-spin" />}
                Move secrets
              </Button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
