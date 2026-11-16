/*
Settings → Secrets: where the app's secrets are kept (the GitHub search tokens, the agents' Claude login, your GitHub
sign-in and the sign-in app's client secret), and Move secrets to AWS Secrets Manager (github_searcher/secret_vault.py
has how it works). Only names show here, never a value.

On this computer: the names still in .env and data/, and a form for an AWS access key (ID, secret, region). Move
secrets puts them in AWS, checks AWS kept them, and only then removes them from this computer; the access key goes in
the system keyring. In AWS: the secret's name and region, Open in AWS (its page in the AWS console), the names it
holds, and, when some are still on this computer (another copy's .env), Move secrets with the same key.

GET /api/secrets each time Settings opens, and after a move.
*/

import { ExternalLink, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/live";
import { timeAgo } from "@/lib/utils";

type Status = {
  kind: "computer" | "aws";
  on_disk: string[];
  // Only with aws.
  region?: string;
  secret_name?: string;
  moved_at?: string;
  names?: string[];
  console_url?: string;
};

export default function Secrets(props: { open: boolean }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState("");
  const [accessKeyId, setAccessKeyId] = useState("");
  const [secretAccessKey, setSecretAccessKey] = useState("");
  const [region, setRegion] = useState("us-east-1");
  const [moving, setMoving] = useState(false);

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

  return (
    <section>
      <div className="mb-2 font-medium">Secrets</div>
      {error !== "" && <p className="mb-2 border border-destructive/40 bg-destructive/10 px-3 py-1.5 text-destructive">{error}</p>}
      {status === null && error === "" && (
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" /> Loading…
        </div>
      )}

      {status !== null && status.kind === "computer" && (
        <div className="space-y-2">
          <p>
            Kept on this computer, in <span className="font-mono text-xs">.env</span> and <span className="font-mono text-xs">data/</span>
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
              keyring. The secrets leave .env and data/ only once AWS has them.
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
