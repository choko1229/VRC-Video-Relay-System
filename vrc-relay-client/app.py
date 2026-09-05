import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from api import dashboard, logs, settings
from templating import templates

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="VRChat Live Relay Windowsクライアント")

app.include_router(dashboard.router)
app.include_router(settings.router)
app.include_router(logs.router)

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


# エラー発生時にFastAPIの素のJSONエラー(例: {"detail":"Method Not Allowed"})を
# そのまま表示すると、ウィンドウ内で操作不能になりアプリの再起動が必要になってしまう。
# ここで捕捉し、続きの操作に戻れるエラー画面を代わりに表示する。
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "error.html", {"message": str(exc.detail)}, status_code=exc.status_code
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "error.html",
        {"message": "リクエストの内容が正しくありません。"},
        status_code=422,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> HTMLResponse:
    logger.exception("未処理のエラーが発生しました")
    return templates.TemplateResponse(
        request,
        "error.html",
        {"message": "予期しないエラーが発生しました。"},
        status_code=500,
    )
