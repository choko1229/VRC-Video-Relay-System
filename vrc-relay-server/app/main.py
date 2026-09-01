import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import admin, auth, me, mediamtx_hook
from app.config import get_settings
from app.db.session import async_session_maker
from app.logging_config import configure_logging
from app.services import admin_bootstrap
from app.services.discord_service import DiscordNotifier
from app.web.routes import router as web_router

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    async with async_session_maker() as db:
        await admin_bootstrap.ensure_admin_user(db, settings)

    notifier = DiscordNotifier(settings.discord_bot_token)
    await notifier.start()
    app.state.discord_notifier = notifier

    logger.info("vrc-relay-server 起動完了")
    yield

    await notifier.stop()


app = FastAPI(title="VRC配信中継システム 公開サーバー", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(me.router)
app.include_router(admin.router)
app.include_router(mediamtx_hook.router)
app.include_router(web_router)

app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
