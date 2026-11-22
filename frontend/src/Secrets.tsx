/*
Settings → Secrets: the tokens the app needs (GitHub tokens for search, the agents' Claude Code token and Fix all's), and
where the app's secrets are kept (those tokens, your GitHub sign-in and the sign-in app's client secret), with Move
secrets to AWS Secrets Manager (github_searcher/secret_vault.py has how it works). A token is pasted here and never
shown again: only its last 4 characters.

GitHub tokens: one row per token, Remove, and Add for a new one. Claude Code tokens (the agents', one per Claude
account): one row per token with its name (yours, so you know which account it belongs to; changed in place, saved when
you leave the field), In use on the one the agents use and Use on the others, Limit reached under one whose usage limit
Claude reported (with when it resets), Remove, and a name and a token to Add one. Nothing switches by itself: Use does,
from each agent's next run on. Claude Code token (Fix all): one field, Save puts the pasted token in (or replaces the one
there), Remove takes it out. A new GitHub token is used at once.

On this computer: the names in data/, and a form for an AWS access key (ID, secret, region). Move secrets puts them in
AWS, checks AWS kept them, and only then removes them from this computer; the access key goes in the system keyring. In
AWS: the secret's name and region, Open in AWS (its page in the AWS console), the names it holds, and, when some are
still on this computer, Move secrets with the same key.

GET /api/secrets each time Settings opens; every change answers with it again.
*/

import { ExternalLink, Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
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
  // The agents' Claude Code tokens: the one in use, your names for them, and the usage limit Claude last reported on each.
  claude: { in_use: string | null; names: Record<string, string>; limits: Record<string, string> };
};

// Fix all's Claude Code token, with its own field.
const FIX_ALL_TOKEN = { name: "CLAUDE_CODE_OAUTH_TOKEN_VM", label: "Claude Code token (Fix all)" };

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
  // A Claude Code token's name as you type it, by token, until you leave the field.
  const [naming, setNaming] = useState<Record<string, string>>({});

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
      setNaming({});
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
      } else if (key === "claude") {
        const named = { value: pasted.claude ?? "", name: pasted.claude_name ?? "" };
        setStatus(await api<Status>("/api/secrets/claude_tokens", { method: "POST", body: named }));
      } else {
        setStatus(await api<Status>(`/api/secrets/${key}`, { method: "PUT", body: body }));
      }
      if (key === "claude") {
        setPasted({ ...pasted, claude: "", claude_name: "" });
      } else {
        setPasted({ ...pasted, [key]: "" });
      }
      toast.success("Token saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
    setBusy("");
  }

  // The agents use this Claude Code token from their next run on.
  async function useToken(name: string) {
    setBusy(name);
    setError("");
    try {
      setStatus(await api<Status>(`/api/secrets/claude_tokens/${name}/use`, { method: "PUT" }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
    setBusy("");
  }

  // Saves a Claude Code token's name once you leave its field, if it changed.
  async function saveName(name: string) {
    const text = naming[name];
    if (text === undefined || status === null || text.trim() === (status.claude.names[name] ?? "")) {
      return;
    }
    setError("");
    try {
      setStatus(await api<Status>(`/api/secrets/claude_tokens/${name}/name`, { method: "PUT", body: { name: text } }));
      const rest = { ...naming };
      delete rest[name];
      setNaming(rest);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
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
  // The agents' Claude Code tokens the same way: CLAUDE_CODE_OAUTH_TOKEN, then _2, _3, ... by number.
  const claudeTokens = (status?.tokens ?? [])
    .filter((token) => /^CLAUDE_CODE_OAUTH_TOKEN(_\d+)?$/.test(token.name))
    .sort(
      (a, b) =>
        Number(a.name.replace("CLAUDE_CODE_OAUTH_TOKEN_", "").replace("CLAUDE_CODE_OAUTH_TOKEN", "1")) -
        Number(b.name.replace("CLAUDE_CODE_OAUTH_TOKEN_", "").replace("CLAUDE_CODE_OAUTH_TOKEN", "1")),
    );
  const fixAll = status?.tokens.find((token) => token.name === FIX_ALL_TOKEN.name);

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
                  variant="icon"
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

          <div className="space-y-1">
            <div>Claude Code tokens</div>
            {claudeTokens.length === 0 && <p className="text-muted-foreground">No Claude Code tokens.</p>}
            {claudeTokens.map((token) => {
              const inUse = status.claude.in_use === token.name;
              const limit = status.claude.limits[token.name];
              return (
                <div key={token.name}>
                  <div className="flex items-center gap-1.5">
                    <Input
                      className="min-w-0 flex-1"
                      placeholder="Name"
                      spellCheck={false}
                      value={naming[token.name] ?? status.claude.names[token.name] ?? ""}
                      onChange={(event) => setNaming({ ...naming, [token.name]: event.target.value })}
                      onBlur={() => saveName(token.name)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.currentTarget.blur();
                        }
                      }}
                    />
                    <span className="shrink-0 font-mono text-xs">••••{token.end}</span>
                    {inUse && (
                      <Badge variant="ok" className="w-14">
                        In use
                      </Badge>
                    )}
                    {!inUse && (
                      <Button variant="outline" size="sm" className="w-14" onClick={() => useToken(token.name)} disabled={busy !== ""}>
                        {busy === token.name ? <Loader2 className="animate-spin" /> : "Use"}
                      </Button>
                    )}
                    <Button
                      variant="icon"
                      size="icon"
                      aria-label={`Remove the token ending in ${token.end}`}
                      title="Remove"
                      disabled={busy !== ""}
                      onClick={() => removeToken(token.name)}
                    >
                      <X />
                    </Button>
                  </div>
                  {limit !== undefined && (
                    <div className="text-xs text-warn" title={limit}>
                      Limit reached{limit.includes("resets") ? `, ${limit.slice(limit.indexOf("resets"))}` : ""}
                    </div>
                  )}
                </div>
              );
            })}
            <div className="flex items-center gap-1.5">
              <Input
                className="w-32 shrink-0"
                placeholder="Name"
                spellCheck={false}
                value={pasted.claude_name ?? ""}
                onChange={(event) => setPasted({ ...pasted, claude_name: event.target.value })}
              />
              <Input
                className="min-w-0 flex-1 font-mono text-xs"
                placeholder="New token"
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={pasted.claude ?? ""}
                onChange={(event) => setPasted({ ...pasted, claude: event.target.value })}
              />
              <Button size="sm" onClick={() => saveToken("claude")} disabled={busy !== "" || (pasted.claude ?? "").trim() === ""}>
                {busy === "claude" && <Loader2 className="animate-spin" />}
                Add
              </Button>
            </div>
          </div>

          <div className="space-y-1">
            <div>{FIX_ALL_TOKEN.label}</div>
            <div className="flex items-center gap-1.5">
              <Input
                className="min-w-0 flex-1 font-mono text-xs"
                placeholder={fixAll === undefined ? "Not set" : `••••${fixAll.end}`}
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={pasted[FIX_ALL_TOKEN.name] ?? ""}
                onChange={(event) => setPasted({ ...pasted, [FIX_ALL_TOKEN.name]: event.target.value })}
              />
              <Button size="sm" onClick={() => saveToken(FIX_ALL_TOKEN.name)} disabled={busy !== "" || (pasted[FIX_ALL_TOKEN.name] ?? "").trim() === ""}>
                {busy === FIX_ALL_TOKEN.name && <Loader2 className="animate-spin" />}
                Save
              </Button>
              {fixAll !== undefined && (
                <Button variant="outline" size="sm" onClick={() => removeToken(FIX_ALL_TOKEN.name)} disabled={busy !== ""}>
                  Remove
                </Button>
              )}
            </div>
          </div>
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
