"""Where the app's secrets are kept: on this computer (the default) or in AWS Secrets Manager, never in .env. Settings →
Secrets (frontend/src/Secrets.tsx, backend/secrets_api.py) adds, replaces and removes the tokens, and moves them all to
AWS.

The secrets, and where each is on this computer:
- GITHUB_TOKEN, GITHUB_TOKEN_2, ...: the search tokens (token_balancer.py), in DATA_DIR/secrets.json.
- CLAUDE_CODE_OAUTH_TOKEN: the agents' Claude login, in DATA_DIR/secrets.json.
- CLAUDE_CODE_OAUTH_TOKEN_VM: the Claude login of Fix all's Claude Code in Seraph's own VM (problem_fixes.py), in
  DATA_DIR/secrets.json.
- GITHUB_SIGN_IN_TOKEN: your GitHub sign-in (github_account.py), the "token" of DATA_DIR/github_account.json.
- GITHUB_APP_CLIENT_SECRET: the sign-in app's client secret, the "client_secret" of DATA_DIR/github_app.json.
DATA_DIR/secrets.json is {name: value}, and only this computer's user may read it. is_token() tells the first three,
the ones Settings sets (save()).

In AWS they are one secret, SECRET_NAME, a JSON object of name → value, and none of them is on this computer's disk.
DATA_DIR/secret_vault.json says they are there: {"kind": "aws", "region", "secret_name", "moved_at"}. Without that file
they are on this computer. The one key left here is the AWS access key that reads the secret, kept in the system
keyring (GNOME Keyring: encrypted, unlocked when you log in) with secret-tool under KEYRING_ITEM, never in a file. It
should be an IAM user's that may only use secrets named seraph/* (docs/security.md has the policy).

At import the tokens are read once, from AWS or from DATA_DIR/secrets.json, and go into os.environ, in memory only:
token_balancer.py reads them there (it imports this first), and the agents' Claude Code gets them from it. VALUES keeps
all of them, for github_account.py. When AWS or the keyring can't be reached (no internet yet after a reboot or a power
cut, the keyring still locked until you log in), the app waits: it says why and asks again every RETRY_SECONDS until
both answer, then starts. Nothing falls back to disk.

save() sets or removes one token, where they are kept, and in os.environ. move() moves what is on this computer to AWS:
it adds it to the secret, reads the secret back to check it, keeps the access key in the keyring, and only then removes
it from DATA_DIR/secrets.json and the two files. put() changes one value in AWS (signing in and out,
github_account.py). One change at a time is enough: they come from your own clicks.

    python -m github_searcher.secret_vault     # where they are kept, and which are still on this computer
"""

import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# override: the backend reloads itself on code changes, and .env changes should apply then too.
load_dotenv(PROJECT_ROOT / ".env", override=True)

DATA_DIR = PROJECT_ROOT / os.environ["DATA_DIR"]
SETTINGS_PATH = DATA_DIR / "secret_vault.json"
SECRETS_PATH = DATA_DIR / "secrets.json"
SECRET_NAME = "seraph/secrets"
# The access key's item in the system keyring: secret-tool's attributes for it. Its value is
# {"access_key_id", "secret_access_key"}.
KEYRING_ITEM = ["app", "seraph", "key", "aws"]
# How long the app waits before asking the keyring or AWS again, when either can't be reached at start.
RETRY_SECONDS = 15


def is_token(name: str) -> bool:
    """The secrets Settings sets: GITHUB_TOKEN, GITHUB_TOKEN_<n>, CLAUDE_CODE_OAUTH_TOKEN and CLAUDE_CODE_OAUTH_TOKEN_VM."""
    if name in ["GITHUB_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN_VM"]:
        return True
    return name.startswith("GITHUB_TOKEN_") and name.removeprefix("GITHUB_TOKEN_").isdigit()


# None: on this computer.
SETTINGS = None
CLIENT = None
VALUES = {}
# The tests never read the vault or the tokens (tests/conftest.py sets SERAPH_TESTS=1): they run as on a new computer.
if os.environ.get("SERAPH_TESTS") != "1":
    if SETTINGS_PATH.is_file():
        SETTINGS = json.loads(SETTINGS_PATH.read_text())
    elif SECRETS_PATH.is_file():
        VALUES = json.loads(SECRETS_PATH.read_text())
# Until both answer: the app can do nothing without its secrets, so it waits (module docstring).
while SETTINGS is not None:
    lookup = subprocess.run(["secret-tool", "lookup", *KEYRING_ITEM], capture_output=True, text=True)
    if lookup.returncode != 0 or lookup.stdout.strip() == "":
        print(
            "Can't reach the vault: the AWS access key isn't in the system keyring, or the keyring is locked (logging in to "
            f"the desktop unlocks it). Trying again in {RETRY_SECONDS} s.",
            flush=True,
        )
        time.sleep(RETRY_SECONDS)
        continue
    key = json.loads(lookup.stdout)
    CLIENT = boto3.client(
        "secretsmanager",
        region_name=SETTINGS["region"],
        aws_access_key_id=key["access_key_id"],
        aws_secret_access_key=key["secret_access_key"],
    )
    try:
        VALUES = json.loads(CLIENT.get_secret_value(SecretId=SETTINGS["secret_name"])["SecretString"])
        break
    except (BotoCoreError, ClientError) as error:
        print(f"Can't reach the vault (AWS Secrets Manager, {SETTINGS['region']}): {error}. Trying again in {RETRY_SECONDS} s.", flush=True)
        time.sleep(RETRY_SECONDS)
# The search tokens and the Claude logins, for token_balancer.py, the agents' Claude Code and Fix all's.
for name, value in VALUES.items():
    if is_token(name):
        os.environ[name] = value


def status() -> dict:
    """What Settings → Secrets shows: where they are, the tokens set (each with its last 4 characters only), and which
    secrets are still on this computer. Never a whole value."""
    tokens = []
    for name, value in VALUES.items():
        if is_token(name) and value != "":
            tokens.append({"name": name, "end": value[-4:]})
    on_disk = []
    if SECRETS_PATH.is_file():
        for name, value in json.loads(SECRETS_PATH.read_text()).items():
            if value != "":
                on_disk.append(name)
    account_path = DATA_DIR / "github_account.json"
    if account_path.is_file() and "token" in json.loads(account_path.read_text()):
        on_disk.append("GITHUB_SIGN_IN_TOKEN")
    app_path = DATA_DIR / "github_app.json"
    if app_path.is_file() and "client_secret" in json.loads(app_path.read_text()):
        on_disk.append("GITHUB_APP_CLIENT_SECRET")
    if SETTINGS is None:
        return {"kind": "computer", "tokens": tokens, "on_disk": on_disk}
    region = SETTINGS["region"]
    return {
        "kind": "aws",
        "tokens": tokens,
        "on_disk": on_disk,
        "region": region,
        "secret_name": SETTINGS["secret_name"],
        "moved_at": SETTINGS["moved_at"],
        "names": sorted(VALUES),
        # The secret's page in the AWS console.
        "console_url": f"https://{region}.console.aws.amazon.com/secretsmanager/secret?name={quote(SETTINGS['secret_name'], safe='')}&region={region}",
    }


def save(name: str, value: str | None) -> None:
    """Sets one token (is_token), in AWS or in DATA_DIR/secrets.json, then in os.environ; None removes it. ValueError
    says why not."""
    if not is_token(name):
        raise ValueError(f"{name} isn't one of the tokens Settings keeps.")
    if SETTINGS is not None:
        put(name, value)
    else:
        values = dict(VALUES)
        if value is None:
            values.pop(name, None)
        else:
            values[name] = value
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        # Only this computer's user may read it, from the first byte on.
        temporary = SECRETS_PATH.with_name("secrets.json.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.chmod(temporary, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write(json.dumps(values, indent=2))
        temporary.replace(SECRETS_PATH)
        VALUES.clear()
        VALUES.update(values)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


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
    found = dict(VALUES)
    if SECRETS_PATH.is_file():
        for name, value in json.loads(SECRETS_PATH.read_text()).items():
            if value != "":
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

    # Off this computer's disk: secrets.json goes, and the two files keep the rest.
    SECRETS_PATH.unlink(missing_ok=True)
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
