from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from db.models import LocalLog, SessionLocal
from templating import templates

router = APIRouter()


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "logs.html", {"logs": _recent_logs()})


@router.get("/logs/data", response_class=HTMLResponse)
async def logs_data(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "_logs_table.html", {"logs": _recent_logs()})


def _recent_logs(limit: int = 200) -> list[LocalLog]:
    with SessionLocal() as session:
        result = session.execute(
            select(LocalLog).order_by(LocalLog.created_at.desc()).limit(limit)
        )
        return list(result.scalars())
