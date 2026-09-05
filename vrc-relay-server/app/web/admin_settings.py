import asyncio
import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import session as db_session
from app.db.session import get_db
from app.services import admin_bootstrap, setup_service
from app.services.discord_service import DiscordNotifier
from app.web.routes import _get_admin, _require_admin_or_redirect

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


def _current_form_values(settings: Settings) -> dict:
    db = setup_service.parse_database_url(settings.database_url) if settings.database_url else {}
    return {
        "db_host": db.get("host", ""),
        "db_port": db.get("port", 3306),
        "db_username": db.get("username", ""),
        "db_password": db.get("password", ""),
        "db_database": db.get("database", ""),
        "admin_username": settings.admin_username or "",
        "admin_password": settings.admin_password or "",
        "rtmp_host": settings.public_rtmp_host or "",
        "rtmp_port": settings.public_rtmp_port,
        "rtsps_host": settings.public_rtsps_host or "",
        "rtsps_port": settings.public_rtsps_port,
        "public_web_base_url": settings.public_web_base_url or "",
        "discord_oauth_client_id": settings.discord_oauth_client_id or "",
        "discord_oauth_client_secret": settings.discord_oauth_client_secret or "",
        "discord_bot_token": settings.discord_bot_token or "",
        "cloudflare_tunnel_token": settings.cloudflare_tunnel_token or "",
    }


@router.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings_form(
    request: Request, db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> HTMLResponse:
    admin = await _get_admin(request, db, settings)
    if (redirect := _require_admin_or_redirect(admin)) is not None:
        return redirect

    return templates.TemplateResponse(
        request, "admin/settings.html", {"admin": admin, "form": _current_form_values(settings)}
    )


@router.post("/admin/settings", response_class=HTMLResponse)
async def admin_settings_submit(
    request: Request,
    db_host: str = Form(...),
    db_port: int = Form(...),
    db_username: str = Form(...),
    db_password: str = Form(...),
    db_database: str = Form(...),
    admin_username: str = Form(...),
    admin_password: str = Form(...),
    rtmp_host: str = Form(...),
    rtmp_port: int = Form(...),
    rtsps_host: str = Form(...),
    rtsps_port: int = Form(...),
    public_web_base_url: str = Form(...),
    discord_oauth_client_id: str = Form(...),
    discord_oauth_client_secret: str = Form(...),
    discord_bot_token: str = Form(""),
    cloudflare_tunnel_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    admin = await _get_admin(request, db, settings)
    if (redirect := _require_admin_or_redirect(admin)) is not None:
        return redirect

    # 更新前のbreak-glassユーザー名を控えておく(admin_usernameが変更された場合、
    # 「新規作成」ではなく既存行の更新にするため)
    old_admin_username = settings.admin_username

    form_values = {
        "db_host": db_host,
        "db_port": db_port,
        "db_username": db_username,
        "db_password": db_password,
        "db_database": db_database,
        "admin_username": admin_username,
        "admin_password": admin_password,
        "rtmp_host": rtmp_host,
        "rtmp_port": rtmp_port,
        "rtsps_host": rtsps_host,
        "rtsps_port": rtsps_port,
        "public_web_base_url": public_web_base_url,
        "discord_oauth_client_id": discord_oauth_client_id,
        "discord_oauth_client_secret": discord_oauth_client_secret,
        "discord_bot_token": discord_bot_token,
        "cloudflare_tunnel_token": cloudflare_tunnel_token,
    }

    database_url = setup_service.build_database_url(
        db_host, db_port, db_username, db_password, db_database
    )

    try:
        await setup_service.test_database_connection(database_url)
    except setup_service.DatabaseConnectionError as exc:
        logger.warning("管理画面: DB接続確認に失敗しました: %s", exc)
        return templates.TemplateResponse(
            request,
            "admin/settings.html",
            {
                "admin": admin,
                "form": form_values,
                "error": f"データベースに接続できませんでした。ホスト・ポート・ユーザー名・パスワード・DB名を確認してください。({exc})",
            },
            status_code=400,
        )

    setup_service.write_env(
        {
            "DATABASE_URL": database_url,
            "ADMIN_USERNAME": admin_username,
            "ADMIN_PASSWORD": admin_password,
            # MediaMTXはappと同一コンテナ/プロセスグループで常に起動する運用のため固定値でよい
            # (/setup移行前の古い値が.envに残っている場合の是正も兼ねる)
            "MEDIAMTX_API_BASE_URL": "http://127.0.0.1:9997",
            "PUBLIC_RTMP_HOST": rtmp_host,
            "PUBLIC_RTMP_PORT": str(rtmp_port),
            "PUBLIC_RTSPS_HOST": rtsps_host,
            "PUBLIC_RTSPS_PORT": str(rtsps_port),
            "PUBLIC_WEB_BASE_URL": public_web_base_url.rstrip("/"),
            "DISCORD_OAUTH_CLIENT_ID": discord_oauth_client_id,
            "DISCORD_OAUTH_CLIENT_SECRET": discord_oauth_client_secret,
            "DISCORD_BOT_TOKEN": discord_bot_token,
            "CLOUDFLARE_TUNNEL_TOKEN": cloudflare_tunnel_token,
        }
    )

    get_settings.cache_clear()
    db_session.reset()
    new_settings = get_settings()

    try:
        await asyncio.to_thread(setup_service.run_migrations)
    except Exception as exc:
        logger.exception("管理画面: マイグレーション実行に失敗しました")
        return templates.TemplateResponse(
            request,
            "admin/settings.html",
            {
                "admin": admin,
                "form": form_values,
                "error": f"データベースのテーブル作成(マイグレーション)に失敗しました。({exc})",
            },
            status_code=500,
        )

    session_maker = db_session.get_session_maker()
    async with session_maker() as new_db:
        try:
            await admin_bootstrap.update_admin_credentials(
                new_db, old_admin_username, admin_username, admin_password
            )
        except admin_bootstrap.AdminUsernameTakenError as exc:
            return templates.TemplateResponse(
                request,
                "admin/settings.html",
                {"admin": admin, "form": form_values, "error": str(exc)},
                status_code=409,
            )

    if discord_bot_token:
        old_notifier: DiscordNotifier | None = getattr(request.app.state, "discord_notifier", None)
        if old_notifier is not None:
            await old_notifier.stop()
        new_notifier = DiscordNotifier(discord_bot_token)
        await new_notifier.start()
        request.app.state.discord_notifier = new_notifier

    logger.info("管理画面から接続設定を更新しました")
    return templates.TemplateResponse(
        request,
        "admin/settings.html",
        {"admin": admin, "form": _current_form_values(new_settings), "saved": True},
    )
