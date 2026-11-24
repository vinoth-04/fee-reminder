from fastapi import APIRouter
from fastapi.responses import Response

from app.errors import AppError
from app.services import whatsapp_session as wa

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


@router.get("/status")
def status():
    return wa.status()


@router.post("/connect")
def connect():
    return wa.connect()


@router.get("/qr")
def qr():
    png = wa.qr_png()
    if png is None:
        raise AppError(404, "No QR code available right now.")
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/disconnect")
def disconnect(forget: bool = False):
    return wa.disconnect(forget)
