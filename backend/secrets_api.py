"""Settings → Secrets (frontend/src/Secrets.tsx): the tokens (GitHub search tokens, the agents' Claude Code token and
Fix all's), where the app's secrets are kept, and Move secrets to AWS Secrets Manager (github_searcher/secret_vault.py
has how it works). A value only ever comes from the browser: what goes back is names and each token's last 4
characters.

GET    /api/secrets: {"kind": "computer" | "aws", "tokens": [{"name", "end"}], "on_disk": names still on this computer},
       and with aws "region", "secret_name", "moved_at", "names" (the ones in AWS) and "console_url" (the secret's page
       in the AWS console).
POST   /api/secrets/github_tokens {"value"}: adds a GitHub token, as the first free GITHUB_TOKEN, GITHUB_TOKEN_2, ...
PUT    /api/secrets/{name} {"value"}: sets CLAUDE_CODE_OAUTH_TOKEN or CLAUDE_CODE_OAUTH_TOKEN_VM.
DELETE /api/secrets/{name}: removes one token.
POST   /api/secrets/move {"access_key_id", "secret_access_key", "region"}: moves them, and answers like GET. Once AWS is set
       up, empty fields keep the access key it has. 400 says why not; then nothing left this computer.
Each answers like GET. A GitHub token change goes to the balancer at once (token_balancer.py load()); the agents'
Claude Code takes a new Claude token at its next start.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from github_searcher import secret_vault
from github_searcher.token_balancer import BALANCER

router = APIRouter(prefix="/api")


class MoveRequest(BaseModel):
    access_key_id: str = ""
    secret_access_key: str = ""
    region: str = ""


class TokenRequest(BaseModel):
    value: str


@router.get("/secrets")
def secrets_status() -> dict:
    return secret_vault.status()


@router.post("/secrets/github_tokens")
def add_github_token(body: TokenRequest) -> dict:
    value = body.value.strip()
    if value == "":
        raise HTTPException(status_code=400, detail="Paste the token first.")
    name = "GITHUB_TOKEN"
    number = 2
    while secret_vault.VALUES.get(name, "") != "":
        name = f"GITHUB_TOKEN_{number}"
        number += 1
    try:
        secret_vault.save(name, value)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    BALANCER.load()
    return secret_vault.status()


@router.put("/secrets/{name}")
def set_token(name: str, body: TokenRequest) -> dict:
    value = body.value.strip()
    if name not in ["CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN_VM"]:
        raise HTTPException(status_code=404, detail=f"No token {name} to set.")
    if value == "":
        raise HTTPException(status_code=400, detail="Paste the token first.")
    try:
        secret_vault.save(name, value)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return secret_vault.status()


@router.delete("/secrets/{name}")
def remove_token(name: str) -> dict:
    if not secret_vault.is_token(name):
        raise HTTPException(status_code=404, detail=f"No token {name}.")
    try:
        secret_vault.save(name, None)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    BALANCER.load()
    return secret_vault.status()


@router.post("/secrets/move")
def move_secrets(body: MoveRequest) -> dict:
    try:
        return secret_vault.move(body.access_key_id, body.secret_access_key, body.region)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
