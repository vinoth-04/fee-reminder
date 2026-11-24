import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config, db as _db
from app.errors import AppError
from app.routes import (dashboard_routes, member_routes, payment_routes, reminder_routes,
                        upload_routes, whatsapp_routes, inbox_routes)
from app.scheduler import jobs
from app.services import excel_service

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    excel_service.ensure_workbook()
    _db.ensure_db()
    jobs.start()
    yield
    jobs.stop()
    from app.services import whatsapp_session
    whatsapp_session.shutdown()


app = FastAPI(title="Gym Fee Reminder Automation", lifespan=lifespan)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status, content={"detail": exc.message})


for r in (member_routes.router, payment_routes.router, reminder_routes.router,
          upload_routes.router, dashboard_routes.router, whatsapp_routes.router,
          inbox_routes.router):
    app.include_router(r)

app.mount("/static", StaticFiles(directory=config.BASE_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(config.BASE_DIR / "templates" / "index.html")


@app.get("/import", include_in_schema=False)
def import_page():
    return FileResponse(config.BASE_DIR / "templates" / "import.html")
