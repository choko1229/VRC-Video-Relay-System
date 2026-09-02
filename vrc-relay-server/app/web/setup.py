import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import generate_secret, get_settings
from app.db import session as db_session
from app.services import admin_bootstrap, setup_service
from app.services.discord_service import DiscordNotifier

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/setup", response_class=HTMLResponse)
async def setup_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "setup.html", {"form": {}})


@router.post("/setup", response_class=HTMLResponse)
async def setup_submit(
    request: Request,
    db_host: str = Form(...),
    db_port: int = Form(...),
    db_username: str = Form(...),
    db_password: str = Form(...),
    db_database: str = Form(...),
    admin_username: str = Form(...),
    admin_password: str = Form(...),
    mediamtx_host: str = Form(...),
    mediamtx_port: int = Form(...),
    rtmp_host: str = Form(...),
    rtmp_port: int = Form(...),
    rtsps_host: str = Form(...),
    rtsps_port: int = Form(...),
    public_web_base_url: str = Form(...),
    discord_bot_token: str = Form(""),
    cloudflare_tunnel_token: str = Form(""),
) -> HTMLResponse:
    form_values = {
        "db_host": db_host,
        "db_port": db_port,
        "db_username": db_username,
        "db_password": db_password,
        "db_database": db_database,
        "admin_username": admin_username,
        "admin_password": admin_password,
        "mediamtx_host": mediamtx_host,
        "mediamtx_port": mediamtx_port,
        "rtmp_host": rtmp_host,
        "rtmp_port": rtmp_port,
        "rtsps_host": rtsps_host,
        "rtsps_port": rtsps_port,
        "public_web_base_url": public_web_base_url,
        "discord_bot_token": discord_bot_token,
        "cloudflare_tunnel_token": cloudflare_tunnel_token,
    }

    database_url = setup_service.build_database_url(
        db_host, db_port, db_username, db_password, db_database
    )

    try:
        await setup_service.test_database_connection(database_url)
    except setup_service.DatabaseConnectionError as exc:
        logger.warning("セットアップ画面: DB接続確認に失敗しました: %s", exc)
        return templates.TemplateResponse(
            request,
            "setup.html",
            {
                "form": form_values,
                "error": f"データベースに接続できませんでした。ホスト・ポート・ユーザー名・パスワード・DB名を確認してください。({exc})",
            },
            status_code=400,
        )

    setup_service.write_env(
        {
            "DATABASE_URL": database_url,
            "JWT_SECRET_KEY": generate_secret(),
            "ADMIN_USERNAME": admin_username,
            "ADMIN_PASSWORD": admin_password,
            "MEDIAMTX_API_BASE_URL": f"http://{mediamtx_host}:{mediamtx_port}",
            "PUBLIC_RTMP_HOST": rtmp_host,
            "PUBLIC_RTMP_PORT": str(rtmp_port),
            "PUBLIC_RTSPS_HOST": rtsps_host,
            "PUBLIC_RTSPS_PORT": str(rtsps_port),
            "PUBLIC_WEB_BASE_URL": public_web_base_url.rstrip("/"),
            "DISCORD_BOT_TOKEN": discord_bot_token,
            "CLOUDFLARE_TUNNEL_TOKEN": cloudflare_tunnel_token,
        }
    )

    # 設定キャッシュとDBエンジンを作り直し、プロセス再起動なしで新しい接続情報を反映する
    get_settings.cache_clear()
    db_session.reset()
    settings = get_settings()

    session_maker = db_session.get_session_maker()
    async with session_maker() as db:
        await admin_bootstrap.ensure_admin_user(db, settings)

    if discord_bot_token:
        old_notifier: DiscordNotifier | None = getattr(request.app.state, "discord_notifier", None)
        if old_notifier is not None:
            await old_notifier.stop()
        new_notifier = DiscordNotifier(discord_bot_token)
        await new_notifier.start()
        request.app.state.discord_notifier = new_notifier

    logger.info("初期セットアップが完了しました")
    return RedirectResponse("/login", status_code=303)
