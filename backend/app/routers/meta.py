from fastapi import APIRouter

from app.release_notes import APP_VERSION, RELEASE_NOTES

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("")
def get_meta():
    return {"version": APP_VERSION}


@router.get("/release-notes")
def list_release_notes():
    return RELEASE_NOTES
