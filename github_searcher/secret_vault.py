"""Where the app's secrets are kept: on this computer (the default) or in AWS Secrets Manager. Settings → Secrets shows
it and moves them (frontend/src/Secrets.tsx, backend/secrets_api.py).

The secrets, and where each is on this computer:
- GITHUB_TOKEN, GITHUB_TOKEN_2, ...: the search tokens (token_balancer.py), in .env.
- CLAUDE_CODE_OAUTH_TOKEN: the agents' Claude login, in .env.
- GITHUB_SIGN_IN_TOKEN: your GitHub sign-in (github_account.py), the "token" of DATA_DIR/github_account.json.
- GITHUB_APP_CLIENT_SECRET: the sign-in app's client secret, the "client_secret" of DATA_DIR/github_app.json.

In AWS they are one secret, SECRET_NAME, a JSON object of name → value, and none of them is on this computer's disk.
DATA_DIR/secret_vault.json says they are there: {"kind": "aws", "region", "secret_name", "moved_at"}. Without that file
they are on this computer. The one key left here is the AWS access key that reads the secret, kept in the system
keyring (GNOME Keyring: encrypted, unlocked when you log in) with secret-tool under KEYRING_ITEM, never in a file. It
should be an IAM user's that may only use secrets named seraph/* (docs/security.md has the policy).

At import, with AWS, the secret is read once. The search tokens and the Claude login go into os.environ, in memory only:
token_balancer.py reads them there (it imports this first), and the agents' Claude Code gets them from it. VALUES keeps
all of them, for github_account.py. When AWS or the keyring can't be reached, the app doesn't start, with why: nothing
falls back to disk.

move() moves what is on this computer to AWS: it adds it to the secret, reads the secret back to check it, keeps the
access key in the keyring, and only then removes it from .env and the two files (.env keeps a comment where they were).
Once AWS is set up, move() without a key moves what is left with the same key: another copy's .env (./live.sh's and
./run.sh's are not the same file; data/ is the same). put() changes one value in AWS (signing in and out,
github_account.py). One change at a time is enough: they come from your own clicks.

    python -m github_searcher.secret_vault     # where they are kept, and which are still on this computer
"""

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import dotenv_values, load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# override: the backend reloads itself on code changes, and .env changes should apply then too.
load_dotenv(PROJECT_ROOT / ".env", override=True)

DATA_DIR = PROJECT_ROOT / os.environ["DATA_DIR"]
SETTINGS_PATH = DATA_DIR / "secret_vault.json"
SECRET_NAME = "seraph/secrets"
# The access key's item in the system keyring: secret-tool's attributes for it. Its value is
# {"access_key_id", "secret_access_key"}.
KEYRING_ITEM = ["app", "seraph", "key", "aws"]
# Written in .env where the secrets were.
ENV_NOTE = "# GITHUB_TOKEN, GITHUB_TOKEN_2, ... and CLAUDE_CODE_OAUTH_TOKEN are in AWS Secrets Manager (Settings → Secrets)."

# None: on this computer.
SETTINGS = None
CLIENT = None
VALUES = {}
# The tests never read the vault (tests/conftest.py sets SERAPH_TESTS=1): they run as on a computer without one.
if SETTINGS_PATH.is_file() and os.environ.get("SERAPH_TESTS") != "1":
    SETTINGS = json.loads(SETTINGS_PATH.read_text())
    lookup = subprocess.run(["secret-tool", "lookup", *KEYRING_ITEM], capture_output=True, text=True)
    if lookup.returncode != 0 or lookup.stdout.strip() == "":
        raise RuntimeError(
            "Can't reach the vault: the AWS access key isn't in the system keyring, or the keyring is locked. "
            "Log in to the desktop (it unlocks the keyring), then start Seraph again."
        )
    key = json.loads(lookup.stdout)
    CLIENT = boto3.client(
        "secretsmanager",
        region_name=SETTINGS["region"],
        aws_access_key_id=key["access_key_id"],
        aws_secret_access_key=key["secret_access_key"],
    )
    try:
        VALUES = json.loads(CLIENT.get_secret_value(SecretId=SETTINGS["secret_name"])["SecretString"])
    except (BotoCoreError, ClientError) as error:
        raise RuntimeError(f"Can't reach the vault (AWS Secrets Manager, {SETTINGS['region']}): {error}") from None
# The search tokens and the Claude login, for token_balancer.py and the agents' Claude Code.
for name, value in VALUES.items():
    if name.startswith("GITHUB_TOKEN") or name == "CLAUDE_CODE_OAUTH_TOKEN":
        os.environ[name] = value


def status() -> dict:
    """What Settings → Secrets shows: where they are, their names, and which are still on this computer. Never a value."""
    on_disk = []
    for name, value in dotenv_values(PROJECT_ROOT / ".env").items():
        if (name.startswith("GITHUB_TOKEN") or name == "CLAUDE_CODE_OAUTH_TOKEN") and value:
            on_disk.append(name)
    account_path = DATA_DIR / "github_account.json"
    if account_path.is_file() and "token" in json.loads(account_path.read_text()):
        on_disk.append("GITHUB_SIGN_IN_TOKEN")
    app_path = DATA_DIR / "github_app.json"
    if app_path.is_file() and "client_secret" in json.loads(app_path.read_text()):
        on_disk.append("GITHUB_APP_CLIENT_SECRET")
    if SETTINGS is None:
        return {"kind": "computer", "on_disk": on_disk}
    region = SETTINGS["region"]
    return {
        "kind": "aws",
        "on_disk": on_disk,
        "region": region,
        "secret_name": SETTINGS["secret_name"],
        "moved_at": SETTINGS["moved_at"],
        "names": sorted(VALUES),
        # The secret's page in the AWS console.
        "console_url": f"https://{region}.console.aws.amazon.com/secretsmanager/secret?name={quote(SETTINGS['secret_name'], safe='')}&region={region}",
    }


def move(access_key_id: str, secret_access_key: str, region: str) -> dict:
    """Moves the secrets on this computer to AWS (module docstring), then gives status(). ValueError says why not; then
    nothing was removed from this computer."""
    global SETTINGS, CLIENT, VALUES
    access_key_id = access_key_id.strip()
    secret_access_key = secret_access_key.strip()
    region = region.strip()
    client = CLIENT
    if access_key_id != "" or SETTINGS is None:
        if access_key_id == "" or secret_access_key == "" or region == "":
            raise ValueError("Fill in the access key ID, the secret access key and the region.")
        client = boto3.client("secretsmanager", region_name=region, aws_access_key_id=access_key_id, aws_secret_access_key=secret_access_key)
    else:
        region = SETTINGS["region"]

    # What is on this computer, and what an earlier move put in AWS (it goes along when the key is for another region
    # or account).
    env_path = (PROJECT_ROOT / ".env").resolve()
    found = dict(VALUES)
    for name, value in dotenv_values(env_path).items():
        if (name.startswith("GITHUB_TOKEN") or name == "CLAUDE_CODE_OAUTH_TOKEN") and value:
            found[name] = value
    account_path = DATA_DIR / "github_account.json"
    account = None
    if account_path.is_file():
        account = json.loads(account_path.read_text())
    if account is not None and "token" in account:
        found["GITHUB_SIGN_IN_TOKEN"] = account["token"]
    app_path = DATA_DIR / "github_app.json"
    app = None
    if app_path.is_file():
        app = json.loads(app_path.read_text())
    if app is not None and "client_secret" in app:
        found["GITHUB_APP_CLIENT_SECRET"] = app["client_secret"]

    # Into AWS, added to what the secret has (made the first time), then read back.
    exists = True
    values = {}
    try:
        values = json.loads(client.get_secret_value(SecretId=SECRET_NAME)["SecretString"])
    except client.exceptions.ResourceNotFoundException:
        exists = False
    except (BotoCoreError, ClientError) as error:
        raise ValueError(f"Couldn't read AWS Secrets Manager: {error}") from None
    values.update(found)
    try:
        if exists:
            client.put_secret_value(SecretId=SECRET_NAME, SecretString=json.dumps(values))
        else:
            client.create_secret(Name=SECRET_NAME, Description="Seraph's secrets (github_searcher/secret_vault.py)", SecretString=json.dumps(values))
        kept = json.loads(client.get_secret_value(SecretId=SECRET_NAME)["SecretString"])
    except (BotoCoreError, ClientError) as error:
        raise ValueError(f"AWS didn't take them: {error}") from None
    if kept != values:
        raise ValueError("AWS didn't keep them as they were sent.")

    # A new access key goes in the keyring.
    if access_key_id != "":
        key = json.dumps({"access_key_id": access_key_id, "secret_access_key": secret_access_key})
        stored = subprocess.run(["secret-tool", "store", "--label", "Seraph AWS access key", *KEYRING_ITEM], input=key, capture_output=True, text=True)
        if stored.returncode != 0:
            raise ValueError(f"Couldn't keep the access key in the system keyring: {stored.stderr.strip() or 'secret-tool failed'}")

    SETTINGS = {"kind": "aws", "region": region, "secret_name": SECRET_NAME, "moved_at": datetime.now(UTC).isoformat()}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(SETTINGS, indent=2))
    CLIENT = client
    VALUES = values

    # Off this computer's disk: .env's lines go (the note takes the first one's place), and the files keep the rest.
    lines = []
    noted = False
    for line in env_path.read_text().splitlines():
        # dotenv also reads "export NAME=value".
        name = line.partition("=")[0].strip().removeprefix("export ").strip()
        secret = "=" in line and (name.startswith("GITHUB_TOKEN") or name == "CLAUDE_CODE_OAUTH_TOKEN")
        if secret and not noted:
            lines.append(ENV_NOTE)
            noted = True
        if not secret:
            lines.append(line)
    env_path.write_text("\n".join(lines) + "\n")
    if account is not None and "token" in account:
        del account["token"]
        account_path.write_text(json.dumps(account, indent=2))
    if app is not None and "client_secret" in app:
        del app["client_secret"]
        app_path.write_text(json.dumps(app, indent=2))
    return status()


def put(name: str, value: str | None) -> None:
    """Keeps one secret in AWS; None removes it. ValueError says why AWS didn't take it."""
    try:
        values = json.loads(CLIENT.get_secret_value(SecretId=SETTINGS["secret_name"])["SecretString"])
        if value is None:
            values.pop(name, None)
        else:
            values[name] = value
        CLIENT.put_secret_value(SecretId=SETTINGS["secret_name"], SecretString=json.dumps(values))
    except (BotoCoreError, ClientError) as error:
        raise ValueError(f"AWS Secrets Manager didn't take it: {error}") from None
    VALUES.clear()
    VALUES.update(values)


if __name__ == "__main__":
    print(json.dumps(status(), indent=2))
