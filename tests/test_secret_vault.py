"""Secrets (github_searcher/secret_vault.py): what status() shows, and how move() and put() keep the secrets in AWS
Secrets Manager.

AWS is a fake Secrets Manager kept in memory, and the system keyring is a fake secret-tool: nothing here reaches AWS
or the real keyring. .env and the data folder are in pytest's temporary folder, never the real ones. The module's
SETTINGS, CLIENT and VALUES start as on a computer that keeps its secrets itself, and go back after every test."""

import json
import subprocess
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

from github_searcher import secret_vault

ENV = """# ===== GitHub =====
GITHUB_TOKEN=ghp_first
GITHUB_TOKEN_2=ghp_second
GITHUB_TOKEN_3=

GITHUB_API_URL=https://api.github.com

# ===== Claude =====
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat-claude
CLAUDE_MODEL=claude-opus-5-5[1m]

DATA_DIR=data
"""
# What move() leaves of ENV: one note where the first secret was, every other line as it was.
ENV_AFTER = f"""# ===== GitHub =====
{secret_vault.ENV_NOTE}

GITHUB_API_URL=https://api.github.com

# ===== Claude =====
CLAUDE_MODEL=claude-opus-5-5[1m]

DATA_DIR=data
"""
ACCOUNT = {"login": "octocat", "token": "gho_signin"}
APP = {"client_id": "Iv1.abc", "client_secret": "app_secret"}
# Everything on this computer in ENV, ACCOUNT and APP, by the name it has in AWS.
ON_DISK = {
    "GITHUB_TOKEN": "ghp_first",
    "GITHUB_TOKEN_2": "ghp_second",
    "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat-claude",
    "GITHUB_SIGN_IN_TOKEN": "gho_signin",
    "GITHUB_APP_CLIENT_SECRET": "app_secret",
}
ACCESS_KEY_ID = "AKIAEXAMPLEKEY"
SECRET_ACCESS_KEY = "example/secret/access/key"
DENIED = {"Error": {"Code": "AccessDeniedException", "Message": "not allowed"}}


class ResourceNotFound(ClientError):
    """What boto3 raises for a secret that isn't there (a ClientError, as in boto3)."""


class FakeSecretsManager:
    """AWS Secrets Manager in memory. refuse: the one call that answers AccessDenied. stored_instead: what it keeps
    instead of what it was sent, so reading back doesn't match. made: how each boto3.client() was made."""

    class exceptions:
        ResourceNotFoundException = ResourceNotFound

    def __init__(self):
        self.secrets = {}
        self.refuse = ""
        self.stored_instead = None
        self.created = False
        self.made = []

    def get_secret_value(self, SecretId):
        if self.refuse == "get_secret_value":
            raise ClientError(DENIED, "GetSecretValue")
        if SecretId not in self.secrets:
            raise ResourceNotFound({"Error": {"Code": "ResourceNotFoundException", "Message": "no such secret"}}, "GetSecretValue")
        return {"SecretString": self.secrets[SecretId]}

    def put_secret_value(self, SecretId, SecretString):
        if self.refuse == "put_secret_value":
            raise ClientError(DENIED, "PutSecretValue")
        self.secrets[SecretId] = self.stored_instead or SecretString

    def create_secret(self, Name, Description, SecretString):
        if self.refuse == "create_secret":
            raise ClientError(DENIED, "CreateSecret")
        self.secrets[Name] = self.stored_instead or SecretString
        self.created = True


class FakeSecretTool:
    """secret-tool, faked: keeps what it was asked. works False answers like a locked keyring."""

    def __init__(self):
        self.calls = []
        self.works = True

    def run(self, args, input=None, capture_output=False, text=False):
        self.calls.append({"args": args, "input": input})
        if not self.works:
            return subprocess.CompletedProcess(args, 1, "", "Cannot create an item in a locked collection")
        return subprocess.CompletedProcess(args, 0, "", "")


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """.env and the data folder in a temporary folder, with every secret still on this computer."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(secret_vault, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(secret_vault, "DATA_DIR", data)
    monkeypatch.setattr(secret_vault, "SETTINGS_PATH", data / "secret_vault.json")
    monkeypatch.setattr(secret_vault, "SETTINGS", None)
    monkeypatch.setattr(secret_vault, "CLIENT", None)
    monkeypatch.setattr(secret_vault, "VALUES", {})
    (tmp_path / ".env").write_text(ENV)
    (data / "github_account.json").write_text(json.dumps(ACCOUNT))
    (data / "github_app.json").write_text(json.dumps(APP))
    return tmp_path


@pytest.fixture(autouse=True)
def aws(monkeypatch):
    """The fake Secrets Manager, which every boto3.client() gives."""
    fake = FakeSecretsManager()

    def client(service, **kwargs):
        fake.made.append({"service": service, **kwargs})
        return fake

    monkeypatch.setattr(secret_vault.boto3, "client", client)
    return fake


@pytest.fixture(autouse=True)
def keyring(monkeypatch):
    """The fake secret-tool, the only subprocess secret_vault can run here."""
    tool = FakeSecretTool()
    monkeypatch.setattr(secret_vault, "subprocess", SimpleNamespace(run=tool.run))
    return tool


@pytest.fixture
def in_aws(aws, monkeypatch):
    """Secrets already moved to AWS (ca-central-1) by an earlier move()."""
    aws.secrets[secret_vault.SECRET_NAME] = json.dumps({"GITHUB_TOKEN": "ghp_first"})
    settings = {"kind": "aws", "region": "ca-central-1", "secret_name": secret_vault.SECRET_NAME, "moved_at": "2026-11-15T12:00:00+00:00"}
    monkeypatch.setattr(secret_vault, "SETTINGS", settings)
    monkeypatch.setattr(secret_vault, "CLIENT", aws)
    monkeypatch.setattr(secret_vault, "VALUES", {"GITHUB_TOKEN": "ghp_first"})
    return aws


def test_status_on_this_computer_names_what_is_on_disk():
    # GITHUB_TOKEN_3 is empty, so it isn't a secret on disk.
    assert secret_vault.status() == {
        "kind": "computer",
        "on_disk": ["GITHUB_TOKEN", "GITHUB_TOKEN_2", "CLAUDE_CODE_OAUTH_TOKEN", "GITHUB_SIGN_IN_TOKEN", "GITHUB_APP_CLIENT_SECRET"],
    }


def test_status_with_aws_names_the_secret_and_its_console_page(in_aws, monkeypatch):
    monkeypatch.setattr(secret_vault, "VALUES", {"GITHUB_TOKEN": "ghp_first", "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat-claude"})

    status = secret_vault.status()

    assert status["kind"] == "aws"
    assert status["region"] == "ca-central-1"
    assert status["secret_name"] == "seraph/secrets"
    assert status["moved_at"] == "2026-11-15T12:00:00+00:00"
    assert status["names"] == ["CLAUDE_CODE_OAUTH_TOKEN", "GITHUB_TOKEN"]
    assert status["console_url"] == "https://ca-central-1.console.aws.amazon.com/secretsmanager/secret?name=seraph%2Fsecrets&region=ca-central-1"


def test_status_never_gives_a_value(in_aws, monkeypatch):
    monkeypatch.setattr(secret_vault, "VALUES", dict(ON_DISK))

    shown = json.dumps(secret_vault.status())

    for value in ON_DISK.values():
        assert value not in shown


def test_move_puts_every_secret_in_aws(aws):
    secret_vault.move(ACCESS_KEY_ID, SECRET_ACCESS_KEY, "ca-central-1")

    assert aws.created is True
    assert json.loads(aws.secrets["seraph/secrets"]) == ON_DISK
    assert aws.made == [
        {"service": "secretsmanager", "region_name": "ca-central-1", "aws_access_key_id": ACCESS_KEY_ID, "aws_secret_access_key": SECRET_ACCESS_KEY}
    ]
    assert secret_vault.VALUES == ON_DISK


def test_move_leaves_one_note_in_env_where_the_secrets_were(home):
    secret_vault.move(ACCESS_KEY_ID, SECRET_ACCESS_KEY, "ca-central-1")

    assert (home / ".env").read_text() == ENV_AFTER


def test_move_takes_the_secrets_out_of_the_two_files_and_keeps_the_rest(home):
    secret_vault.move(ACCESS_KEY_ID, SECRET_ACCESS_KEY, "ca-central-1")

    assert json.loads((home / "data" / "github_account.json").read_text()) == {"login": "octocat"}
    assert json.loads((home / "data" / "github_app.json").read_text()) == {"client_id": "Iv1.abc"}


def test_move_says_where_they_are_now(home):
    status = secret_vault.move(ACCESS_KEY_ID, SECRET_ACCESS_KEY, "ca-central-1")

    assert status["kind"] == "aws"
    assert status["on_disk"] == []
    assert status["names"] == sorted(ON_DISK)
    settings = json.loads((home / "data" / "secret_vault.json").read_text())
    assert settings["kind"] == "aws"
    assert settings["region"] == "ca-central-1"
    assert settings["secret_name"] == "seraph/secrets"


def test_access_key_goes_in_the_keyring_and_never_in_a_file(home, keyring):
    secret_vault.move(ACCESS_KEY_ID, SECRET_ACCESS_KEY, "ca-central-1")

    assert len(keyring.calls) == 1
    assert keyring.calls[0]["args"] == ["secret-tool", "store", "--label", "Seraph AWS access key", "app", "seraph", "key", "aws"]
    assert json.loads(keyring.calls[0]["input"]) == {"access_key_id": ACCESS_KEY_ID, "secret_access_key": SECRET_ACCESS_KEY}
    for path in home.rglob("*"):
        if path.is_file():
            assert SECRET_ACCESS_KEY not in path.read_text()


def test_pasted_fields_are_trimmed(aws, keyring):
    secret_vault.move(f"  {ACCESS_KEY_ID}\n", f" {SECRET_ACCESS_KEY} ", " ca-central-1 ")

    assert aws.made[0]["aws_access_key_id"] == ACCESS_KEY_ID
    assert aws.made[0]["aws_secret_access_key"] == SECRET_ACCESS_KEY
    assert aws.made[0]["region_name"] == "ca-central-1"
    assert json.loads(keyring.calls[0]["input"])["access_key_id"] == ACCESS_KEY_ID


def test_move_adds_to_what_the_secret_already_has(aws):
    aws.secrets["seraph/secrets"] = json.dumps({"SOMETHING_ELSE": "kept", "GITHUB_TOKEN": "ghp_old"})

    secret_vault.move(ACCESS_KEY_ID, SECRET_ACCESS_KEY, "ca-central-1")

    kept = json.loads(aws.secrets["seraph/secrets"])
    assert aws.created is False
    assert kept["SOMETHING_ELSE"] == "kept"
    assert kept["GITHUB_TOKEN"] == "ghp_first"


@pytest.mark.parametrize(
    "access_key_id, secret_access_key, region",
    [
        ("", SECRET_ACCESS_KEY, "ca-central-1"),
        (ACCESS_KEY_ID, "", "ca-central-1"),
        (ACCESS_KEY_ID, SECRET_ACCESS_KEY, ""),
        ("  ", "  ", "  "),
    ],
)
def test_first_move_needs_all_three_fields(aws, home, access_key_id, secret_access_key, region):
    with pytest.raises(ValueError, match="Fill in"):
        secret_vault.move(access_key_id, secret_access_key, region)

    assert aws.made == []
    assert (home / ".env").read_text() == ENV


@pytest.mark.parametrize(
    "refuse, secret_exists, problem",
    [
        ("get_secret_value", True, "Couldn't read AWS Secrets Manager"),
        ("put_secret_value", True, "AWS didn't take them"),
        ("create_secret", False, "AWS didn't take them"),
    ],
)
def test_nothing_leaves_this_computer_when_aws_refuses(aws, home, keyring, refuse, secret_exists, problem):
    aws.refuse = refuse
    if secret_exists:
        aws.secrets["seraph/secrets"] = "{}"

    with pytest.raises(ValueError, match=problem):
        secret_vault.move(ACCESS_KEY_ID, SECRET_ACCESS_KEY, "ca-central-1")

    assert (home / ".env").read_text() == ENV
    assert json.loads((home / "data" / "github_account.json").read_text()) == ACCOUNT
    assert json.loads((home / "data" / "github_app.json").read_text()) == APP
    assert not (home / "data" / "secret_vault.json").exists()
    assert secret_vault.SETTINGS is None
    assert keyring.calls == []


def test_nothing_leaves_this_computer_when_aws_keeps_something_else(aws, home):
    # Read back, the secret isn't what was sent: the copy in AWS can't be trusted, so the one on disk stays.
    aws.stored_instead = json.dumps({"GITHUB_TOKEN": "ghp_first"})

    with pytest.raises(ValueError, match="didn't keep them as they were sent"):
        secret_vault.move(ACCESS_KEY_ID, SECRET_ACCESS_KEY, "ca-central-1")

    assert (home / ".env").read_text() == ENV
    assert json.loads((home / "data" / "github_account.json").read_text()) == ACCOUNT
    assert json.loads((home / "data" / "github_app.json").read_text()) == APP
    assert secret_vault.SETTINGS is None


def test_nothing_leaves_this_computer_when_the_keyring_is_locked(home, keyring):
    # Without the access key in the keyring the next start couldn't read AWS, so the secrets must stay on disk.
    keyring.works = False

    with pytest.raises(ValueError, match="system keyring"):
        secret_vault.move(ACCESS_KEY_ID, SECRET_ACCESS_KEY, "ca-central-1")

    assert (home / ".env").read_text() == ENV
    assert json.loads((home / "data" / "github_account.json").read_text()) == ACCOUNT
    assert json.loads((home / "data" / "github_app.json").read_text()) == APP
    assert not (home / "data" / "secret_vault.json").exists()
    assert secret_vault.SETTINGS is None


def test_second_copys_env_moves_with_the_same_key(in_aws, home, keyring):
    # ./live.sh's and ./run.sh's .env are not the same file, but data/ is: once the live copy moved its secrets, the
    # other copy's .env still has them, and moving those needs no key (the one in the keyring is used).
    in_aws.secrets["seraph/secrets"] = json.dumps({"GITHUB_SIGN_IN_TOKEN": "gho_signin", "GITHUB_APP_CLIENT_SECRET": "app_secret"})
    (home / "data" / "github_account.json").write_text(json.dumps({"login": "octocat"}))
    (home / "data" / "github_app.json").write_text(json.dumps({"client_id": "Iv1.abc"}))

    status = secret_vault.move("", "", "")

    assert in_aws.made == []
    assert keyring.calls == []
    assert json.loads(in_aws.secrets["seraph/secrets"]) == ON_DISK
    assert (home / ".env").read_text() == ENV_AFTER
    assert status["region"] == "ca-central-1"
    assert status["on_disk"] == []


def test_put_adds_one_value(in_aws):
    secret_vault.put("GITHUB_SIGN_IN_TOKEN", "gho_new")

    assert json.loads(in_aws.secrets["seraph/secrets"]) == {"GITHUB_TOKEN": "ghp_first", "GITHUB_SIGN_IN_TOKEN": "gho_new"}
    assert secret_vault.VALUES == {"GITHUB_TOKEN": "ghp_first", "GITHUB_SIGN_IN_TOKEN": "gho_new"}


def test_put_none_removes_one_value(in_aws):
    in_aws.secrets["seraph/secrets"] = json.dumps({"GITHUB_TOKEN": "ghp_first", "GITHUB_SIGN_IN_TOKEN": "gho_old"})

    secret_vault.put("GITHUB_SIGN_IN_TOKEN", None)

    assert json.loads(in_aws.secrets["seraph/secrets"]) == {"GITHUB_TOKEN": "ghp_first"}
    assert secret_vault.VALUES == {"GITHUB_TOKEN": "ghp_first"}


def test_signing_out_twice_is_fine(in_aws):
    secret_vault.put("GITHUB_SIGN_IN_TOKEN", None)

    assert json.loads(in_aws.secrets["seraph/secrets"]) == {"GITHUB_TOKEN": "ghp_first"}


def test_put_refused_keeps_what_was_there(in_aws):
    in_aws.refuse = "put_secret_value"

    with pytest.raises(ValueError, match="didn't take it"):
        secret_vault.put("GITHUB_SIGN_IN_TOKEN", "gho_new")

    assert json.loads(in_aws.secrets["seraph/secrets"]) == {"GITHUB_TOKEN": "ghp_first"}
    assert secret_vault.VALUES == {"GITHUB_TOKEN": "ghp_first"}


def test_an_export_line_leaves_env_too(home):
    # dotenv reads "export NAME=value" too, so move() sends it to AWS; its line must go from .env as well.
    (home / ".env").write_text("export GITHUB_TOKEN=ghp_first\nCLAUDE_MODEL=claude-opus-5-5[1m]\n")

    status = secret_vault.move(ACCESS_KEY_ID, SECRET_ACCESS_KEY, "ca-central-1")

    assert (home / ".env").read_text() == f"{secret_vault.ENV_NOTE}\nCLAUDE_MODEL=claude-opus-5-5[1m]\n"
    assert "GITHUB_TOKEN" not in status["on_disk"]


def test_a_key_for_another_region_takes_the_secrets_moved_before_along(in_aws, home):
    # Secrets moved earlier are only in AWS (VALUES), not on disk anymore: a new key that starts an empty secret
    # elsewhere must get them too, or the next start has no GITHUB_TOKEN.
    in_aws.secrets = {}
    (home / ".env").write_text("CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat-claude\n")

    secret_vault.move(ACCESS_KEY_ID, SECRET_ACCESS_KEY, "us-east-1")

    assert json.loads(in_aws.secrets["seraph/secrets"])["GITHUB_TOKEN"] == "ghp_first"
    assert secret_vault.SETTINGS["region"] == "us-east-1"
