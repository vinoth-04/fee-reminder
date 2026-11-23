from fastapi import APIRouter
from pydantic import BaseModel

from app.services import reminder_service as svc

router = APIRouter(prefix="/api/reminders", tags=["reminders"])


class StatusIn(BaseModel):
    status: str


@router.get("")
def reminders():
    return svc.list_reminders()


@router.post("/prepare")
def prepare():
    return svc.prepare_reminders()


@router.post("/prepare/{payment_id}")
def prepare_one(payment_id: str):
    return svc.prepare_for_payment(payment_id)


@router.post("/send/{payment_id}")
def send_one(payment_id: str):
    return svc.send_reminder(payment_id)


@router.get("/logs")
def logs(limit: int = 100, status: str = ""):
    return svc.get_logs(limit, status)


@router.put("/{reminder_id}/status")
def set_status(reminder_id: str, body: StatusIn):
    return svc.set_status(reminder_id, body.status)
