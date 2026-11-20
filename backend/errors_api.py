"""The pages' own errors: POST /api/errors with {"message", "stack", "page"} (frontend/src/main.tsx sends every error a
page didn't catch). Each one is one of the app's errors (github_searcher/crashes.py), like a backend exception.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from backend.shared import crashes

router = APIRouter(prefix="/api")


class ErrorReport(BaseModel):
    message: str
    stack: str = ""
    page: str = ""


@router.post("/errors")
def report_error(body: ErrorReport) -> dict:
    crashes.add("browser", body.message, f"{body.page}\n{body.stack}")
    return {"ok": True}
