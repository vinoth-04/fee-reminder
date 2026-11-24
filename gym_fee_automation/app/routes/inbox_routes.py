from fastapi import APIRouter

from app.services import inbox_service as svc

router = APIRouter(prefix="/api/inbox", tags=["inbox"])


@router.get("")
def inbox():
    return svc.list_inbox()


@router.post("/sync")
def sync():
    return svc.start_sync()


@router.get("/sync/status")
def sync_status():
    return svc.sync_status()


@router.put("/{member_id}/seen")
def seen(member_id: str):
    return svc.mark_seen(member_id)
