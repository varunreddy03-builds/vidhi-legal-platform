"""The legal directory: where courts, tribunals, official portals, Acts, law reports, court rules and legal aid bodies are found. Read-only; see lib/legal_directory.py for the rules."""

from fastapi import APIRouter, Depends, HTTPException, Query

from lib import legal_directory as directory
from lib.auth import current_user

router = APIRouter(prefix="/legal-directory", tags=["legal-directory"])


@router.get("")
async def directory_search(q: str = Query("", max_length=100), section: str = Query("", max_length=40), state: str = Query("", max_length=60), user: dict = Depends(current_user)):
    try:
        return directory.search(q, section or None, state or None)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e) + ". Use one of: " + ", ".join(s for s, _ in directory.SECTIONS) + ".") from e


@router.get("/legal-aid")
async def directory_legal_aid(state: str = Query("", max_length=60), user: dict = Depends(current_user)):
    try:
        return directory.legal_aid(state or None)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
