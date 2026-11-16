from fastapi import APIRouter
from pydantic import BaseModel

from app.services import member_service as members
from app.services import payment_service as payments

router = APIRouter(prefix="/api/members", tags=["members"])


class MemberIn(BaseModel):
    name: str | None = None
    phone: str | None = None
    monthly_fee: float | str | None = None
    joining_date: str | None = None
    due_date: str | None = None
    status: str | None = None


@router.get("")
def list_members(q: str = "", status: str = ""):
    return members.list_members(q, status)


@router.post("", status_code=201)
def add_member(body: MemberIn):
    return members.add_member(body.model_dump())


@router.get("/{member_id}")
def get_member(member_id: str):
    return members.get_member(member_id)


@router.put("/{member_id}")
def update_member(member_id: str, body: MemberIn):
    return members.update_member(member_id, body.model_dump(exclude_unset=True))


@router.get("/{member_id}/payments")
def member_payments(member_id: str):
    members.get_member(member_id)
    return payments.list_payments(member_id=member_id)
