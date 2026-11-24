from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel

from app.services import invoice_service, payment_service as svc

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



@router.get("/{payment_id}/invoice")
def invoice(payment_id: str, download: bool = False):
    pdf, filename = invoice_service.build_invoice_pdf(payment_id)
    disposition = "attachment" if download else "inline"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'{disposition}; filename="{filename}"'})
