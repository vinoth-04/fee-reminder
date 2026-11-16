from fastapi import APIRouter, UploadFile, File
from pydantic import BaseModel

from app import config
from app.errors import AppError
from app.services import excel_upload_service as svc

router = APIRouter(prefix="/api/import", tags=["import"])


class ConfirmIn(BaseModel):
    upload_id: str | None = None
    token: str | None = None
    mapping: dict[str, str] = {}
    due_date_confirmed: bool = False


@router.post("/preview")
async def import_preview(file: UploadFile = File(...)):
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise AppError(413, f"File is larger than {config.MAX_UPLOAD_MB} MB.")
    return svc.preview(file.filename or "", content)


@router.post("/confirm")
def import_confirm(body: ConfirmIn):
    return svc.confirm_import(body.upload_id or body.token or "", body.mapping, body.due_date_confirmed)
