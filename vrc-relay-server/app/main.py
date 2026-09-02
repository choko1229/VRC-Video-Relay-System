import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin, auth, me, mediamtx_hook
from app.config import get_settings
from app.db import session as db_session
from app.logging_config import configure_logging
from app.services import admin_bootstrap
from app.services.discord_service import DiscordNotifier
from app.web.oauth import router as oauth_router
from app.web.routes import router as web_router
from app.web.setup import router as setup_router

configure_logging()
logger = logging.getLogger(__name__)

# 未セットアップ時でもアクセスできるパス(/setupへのリダイレクト対象から除外する)
_SETUP_EXEMPT_PREFIXES = ("/setup", "/static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    notifier = DiscordNotifier(settings.discord_bot_token)
    app.state.discord_notifier = notifier

    if settings.is_configured:
        session_maker = db_session.get_session_maker()
        async with session_maker() as db:
            await admin_bootstrap.ensure_admin_user(db, settings)
        await notifier.start()
        logger.info("vrc-relay-server 起動完了")
    else:
        logger.warning("未セットアップのため /setup のみ提供します")

    yield

    await notifier.stop()


app = FastAPI(title="VRC配信中継システム 公開サーバー", lifespan=lifespan)


@app.middleware("http")
async def require_setup(request: Request, call_next):
    settings = get_settings()
    if not settings.is_configured and not request.url.path.startswith(_SETUP_EXEMPT_PREFIXES):
        return RedirectResponse("/setup", status_code=303)
    return await call_next(request)


app.include_router(setup_router)
app.include_router(oauth_router)
app.include_router(auth.router)
app.include_router(me.router)
app.include_router(admin.router)
app.include_router(mediamtx_hook.router)
app.include_router(web_router)

app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
