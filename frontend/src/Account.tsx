/*
Settings → Account: your GitHub account, the one the app sends pull requests and comments as
(github_searcher/github_account.py). GET /api/github_account each time Settings opens, and on the "github-account"
window event. The token itself never comes back.
- Signed in: your picture, "Signed in as @login" (a link to the profile), its scopes, Sign in again while it lacks
  delete_repo (needed to delete forks nothing uses), and Sign out (DELETE /api/github_account).
- Not signed in, with sign in set up: Sign in with GitHub (POST /api/github_account/sign_in gives GitHub's address, and
  this tab goes there; GitHub sends it back to #/?signed_in=<login> or #/?error=<text>, which App.tsx says in a toast).
  Under it Use a token instead and Change app settings.
- Not signed in, sign in not set up (or Change app settings): how to register the app on GitHub once, with the addresses
  to paste there, then Client ID, Client secret and Save (PUT /api/github_account/app).
- Use a token instead: a classic token pasted by hand and Sign in (PUT /api/github_account), for an organization that
  blocks apps it hasn't approved.
Signing in or out, and saving the app, sends the "github-account" event, so the header shows who is signed in.
scrollTo: Settings was opened on Account (from the header), so the dialog scrolls to it.
*/

import { Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, type GithubAccountStatus } from "@/live";

export default function Account(props: { open: boolean; scrollTo: boolean }) {
  const sectionRef = useRef<HTMLElement>(null);
  const [account, setAccount] = useState<GithubAccountStatus | null>(null);
  const [error, setError] = useState("");
  const [token, setToken] = useState("");
  const [useToken, setUseToken] = useState(false);
  const [settingUp, setSettingUp] = useState(false);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  // The button whose request is on its way: "token", "sign_in", "app" or "sign_out".
  const [busy, setBusy] = useState("");

  useEffect(() => {
    if (!props.open) {
      return;
    }
    let stopped = false;
    function load() {
      api<GithubAccountStatus>("/api/github_account")
        .then((data) => {
          if (!stopped) {
            setAccount(data);
          }
        })
        .catch((err) => {
          if (!stopped) {
            setError(`Could not load the GitHub account: ${err instanceof Error ? err.message : err}`);
          }
        });
    }
    load();
    window.addEventListener("github-account", load);
    return () => {
      stopped = true;
      window.removeEventListener("github-account", load);
    };
  }, [props.open]);

  useEffect(() => {
    if (props.open && props.scrollTo && sectionRef.current !== null) {
      sectionRef.current.scrollIntoView({ block: "start" });
    }
  }, [props.open, props.scrollTo]);

  async function connectToken() {
    setBusy("token");
    setError("");
    try {
      const data = await api<GithubAccountStatus>("/api/github_account", { method: "PUT", body: { token: token } });
      setAccount(data);
      setToken("");
      setUseToken(false);
      window.dispatchEvent(new Event("github-account"));
      toast.success(`Signed in as @${data.login}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
    setBusy("");
  }

  async function signIn() {
    setBusy("sign_in");
    setError("");
    try {
      const data = await api<{ url: string }>("/api/github_account/sign_in", { method: "POST" });
      // GitHub's page, in this tab. It comes back to the app when you are done there.
      window.location.href = data.url;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy("");
    }
  }

  async function saveApp() {
    setBusy("app");
    setError("");
    try {
      const body = { client_id: clientId, client_secret: clientSecret };
      setAccount(await api<GithubAccountStatus>("/api/github_account/app", { method: "PUT", body: body }));
      setClientId("");
      setClientSecret("");
      setSettingUp(false);
      // The header's Sign in goes straight to GitHub now.
      window.dispatchEvent(new Event("github-account"));
      toast.success("Saved. Now sign in with GitHub.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
    setBusy("");
  }

  async function signOut() {
    setBusy("sign_out");
    setError("");
    try {
      setAccount(await api<GithubAccountStatus>("/api/github_account", { method: "DELETE" }));
      window.dispatchEvent(new Event("github-account"));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
    setBusy("");
  }

  const signedOut = account !== null && !account.connected;
  const showSignIn = signedOut && account.can_sign_in === true && !settingUp && !useToken;
  const showSetUp = signedOut && (account.can_sign_in !== true || settingUp) && !useToken;
  const link = "text-xs text-primary hover:underline";

  return (
    <section ref={sectionRef} className="scroll-mt-4">
      <div className="mb-2 font-medium">Account</div>
      {error !== "" && <p className="mb-2 border border-destructive/40 bg-destructive/10 px-3 py-1.5 text-destructive">{error}</p>}
      {account === null && error === "" && (
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" /> Loading…
        </div>
      )}

      {account !== null && account.connected && (
        <div className="flex items-center gap-2">
          <img src={`https://github.com/${account.login}.png?size=40`} alt="" className="size-5 rounded-full" />
          <span>
            Signed in as{" "}
            <a href={`https://github.com/${account.login}`} target="_blank" rel="noreferrer" className="font-medium hover:underline">
              @{account.login}
            </a>
          </span>
          <span className="min-w-0 truncate text-xs text-muted-foreground">{(account.scopes ?? []).join(", ")}</span>
          <div className="ml-auto flex gap-1.5">
            {/* Signed in before the app asked for delete_repo: signing in again lets it delete forks nothing uses. */}
            {account.can_sign_in === true && !(account.scopes ?? []).includes("delete_repo") && (
              <Button size="sm" onClick={signIn} disabled={busy !== ""} title="Lets the app delete forks nothing uses">
                {busy === "sign_in" && <Loader2 className="animate-spin" />}
                Sign in again
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={signOut} disabled={busy !== ""}>
              {busy === "sign_out" && <Loader2 className="animate-spin" />}
              Sign out
            </Button>
          </div>
        </div>
      )}

      {showSignIn && (
        <div className="space-y-2">
          <Button size="sm" onClick={signIn} disabled={busy !== ""}>
            {busy === "sign_in" && <Loader2 className="animate-spin" />}
            Sign in with GitHub
          </Button>
          <div className="flex items-center gap-3">
            <button type="button" className={link} onClick={() => setUseToken(true)}>
              Use a token instead
            </button>
            <button type="button" className={link} onClick={() => setSettingUp(true)}>
              Change app settings
            </button>
          </div>
        </div>
      )}

      {showSetUp && (
        <div className="space-y-2">
          <ol className="list-decimal space-y-2 pl-5">
            <li>
              Open{" "}
              <a href="https://github.com/settings/applications/new" target="_blank" rel="noreferrer" className="text-primary hover:underline">
                GitHub's form for a new OAuth app
              </a>
              , fill it in with these and click Register application:
              <div className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
                <span className="text-muted-foreground">Application name</span>
                <span className="font-mono select-all">Seraph</span>
                <span className="text-muted-foreground">Homepage URL</span>
                <span className="font-mono break-all select-all">{window.location.origin}</span>
                <span className="text-muted-foreground">Authorization callback URL</span>
                <span className="font-mono break-all select-all">{`${window.location.origin}/api/github_account/callback`}</span>
              </div>
            </li>
            <li>On the app's page, copy the Client ID. Then click Generate a new client secret and copy that too.</li>
            <li>Paste both here and Save.</li>
          </ol>
          <div className="flex items-center gap-1.5">
            <Input
              className="min-w-0 flex-1 font-mono text-xs"
              placeholder="Client ID"
              autoComplete="off"
              spellCheck={false}
              value={clientId}
              onChange={(event) => setClientId(event.target.value)}
            />
            <Input
              className="min-w-0 flex-1 font-mono text-xs"
              placeholder="Client secret"
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={clientSecret}
              onChange={(event) => setClientSecret(event.target.value)}
            />
            <Button size="sm" onClick={saveApp} disabled={clientId.trim() === "" || clientSecret.trim() === "" || busy !== ""}>
              {busy === "app" && <Loader2 className="animate-spin" />}
              Save
            </Button>
            {settingUp && (
              <Button variant="ghost" size="sm" onClick={() => setSettingUp(false)}>
                Cancel
              </Button>
            )}
          </div>
          <button type="button" className={link} onClick={() => setUseToken(true)}>
            Use a token instead
          </button>
        </div>
      )}

      {signedOut && useToken && (
        <div className="space-y-2">
          <div className="flex items-center gap-1.5">
            <Input
              className="min-w-0 flex-1 font-mono text-xs"
              placeholder="Token"
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={token}
              onChange={(event) => setToken(event.target.value)}
            />
            <Button size="sm" onClick={connectToken} disabled={token.trim() === "" || busy !== ""}>
              {busy === "token" && <Loader2 className="animate-spin" />}
              Sign in
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setUseToken(false)}>
              Cancel
            </Button>
          </div>
          <a
            href="https://github.com/settings/tokens/new?scopes=repo,workflow,read:org,gist,notifications,user,delete_repo&description=Seraph"
            target="_blank"
            rel="noreferrer"
            className={link}
          >
            New classic token
          </a>
        </div>
      )}
    </section>
  );
}
