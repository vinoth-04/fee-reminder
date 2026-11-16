from fastapi import APIRouter
from pydantic import BaseModel

from app.services import payment_service as svc

router = APIRouter(prefix="/api/payments", tags=["payments"])


class PaidIn(BaseModel):
    payment_date: str | None = None
    payment_mode: str = "Cash"
    amount: float | str | None = None


class GenerateIn(BaseModel):
    month: str
    dry_run: bool = False


@router.get("")
def list_payments(status: str = "", month: str = "", member_id: str = ""):
    return svc.list_payments(status, month, member_id)


@router.get("/pending")
def pending(month: str = ""):
    return svc.list_payments("Pending", month)


@router.get("/paid")
def paid(month: str = ""):
    return svc.list_payments("Paid", month)


@router.get("/summary")
def summary():
    return svc.summary()


@router.post("/generate")
def generate(body: GenerateIn):
    return svc.generate_billing(body.month, body.dry_run)


@router.put("/{payment_id}/paid")
def mark_paid(payment_id: str, body: PaidIn):
    return svc.mark_paid(payment_id, body.payment_date, body.payment_mode, body.amount)
