"""Settings → Secrets (frontend/src/Secrets.tsx): where the app's secrets are kept, and Move secrets to AWS Secrets
Manager (github_searcher/secret_vault.py has how it works). Only names go to the browser, never a value.

GET  /api/secrets: {"kind": "computer" | "aws", "on_disk": names still on this computer}, and with aws "region",
     "secret_name", "moved_at", "names" (the ones in AWS) and "console_url" (the secret's page in the AWS console).
POST /api/secrets/move {"access_key_id", "secret_access_key", "region"}: moves them, and answers like GET. Once AWS is set
     up, empty fields keep the access key it has. 400 says why not; then nothing left this computer.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from github_searcher import secret_vault

router = APIRouter(prefix="/api")


class MoveRequest(BaseModel):
    access_key_id: str = ""
    secret_access_key: str = ""
    region: str = ""


@router.get("/secrets")
def secrets_status() -> dict:
    return secret_vault.status()


@router.post("/secrets/move")
def move_secrets(body: MoveRequest) -> dict:
    try:
        return secret_vault.move(body.access_key_id, body.secret_access_key, body.region)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
