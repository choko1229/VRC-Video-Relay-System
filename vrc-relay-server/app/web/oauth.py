import logging
from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.user import User, UserRole, UserStatus
from app.services import auth_service, discord_oauth_service, stream_key_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/oauth/discord")
templates = Jinja2Templates(directory="app/web/templates")

STATE_PURPOSE = "oauth_state"
APPLY_CONFIRM_PURPOSE = "apply_confirm"


def _is_allowed_client_redirect(url: str) -> bool:
    """デスクトップクライアントのローカルコールバック(127.0.0.1限定)のみ許可する。
    任意のURLへリダイレクトできてしまうOpen Redirectを防ぐため。"""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")


@router.get("/apply/start")
async def apply_start(request: Request, settings: Settings = Depends(get_settings)) -> RedirectResponse:
    state = auth_service.create_short_lived_token(STATE_PURPOSE, {"flow": "apply"}, settings)
    return RedirectResponse(discord_oauth_service.build_authorize_url(state, settings))


@router.get("/login/start")
async def login_start(
    request: Request, redirect_uri: str, settings: Settings = Depends(get_settings)
) -> RedirectResponse:
    if not _is_allowed_client_redirect(redirect_uri):
        return HTMLResponse("不正なredirect_uriです", status_code=400)
    state = auth_service.create_short_lived_token(
        STATE_PURPOSE, {"flow": "login", "client_redirect": redirect_uri}, settings
    )
    return RedirectResponse(discord_oauth_service.build_authorize_url(state, settings))


@router.get("/admin-login/start")
async def admin_login_start(
    request: Request, settings: Settings = Depends(get_settings)
) -> RedirectResponse:
    """Web管理パネル(/login)からのDiscordログイン開始。管理者アカウントのみ利用できる。"""
    state = auth_service.create_short_lived_token(STATE_PURPOSE, {"flow": "admin_web"}, settings)
    return RedirectResponse(discord_oauth_service.build_authorize_url(state, settings))


@router.get("/callback", response_class=HTMLResponse)
async def callback(
    request: Request,
    code: str,
    state: str,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    try:
        state_payload = auth_service.verify_short_lived_token(state, STATE_PURPOSE, settings)
    except auth_service.InvalidTokenError:
        return HTMLResponse("認証セッションの有効期限が切れました。最初からやり直してください。", status_code=400)

    try:
        access_token = await discord_oauth_service.exchange_code(code, settings)
        discord_user = await discord_oauth_service.fetch_discord_user(access_token)
    except discord_oauth_service.DiscordOAuthError:
        logger.exception("Discord OAuth処理に失敗しました")
        return HTMLResponse("Discord認証に失敗しました。もう一度お試しください。", status_code=502)

    discord_id = str(discord_user["id"])
    discord_username = discord_user.get("global_name") or discord_user["username"]

    result = await db.execute(select(User).where(User.discord_id == discord_id))
    existing = result.scalar_one_or_none()

    if state_payload["flow"] == "apply":
        if existing is not None:
            return templates.TemplateResponse(
                request,
                "oauth_result.html",
                {"message": f"既に「{existing.username}」として申請済みです。状態: {existing.status.value}"},
            )
        confirm_token = auth_service.create_short_lived_token(
            APPLY_CONFIRM_PURPOSE,
            {"discord_id": discord_id, "discord_username": discord_username},
            settings,
            expire_minutes=15,
        )
        return templates.TemplateResponse(
            request,
            "apply_username.html",
            {"discord_username": discord_username, "confirm_token": confirm_token},
        )

    if state_payload["flow"] == "admin_web":
        if existing is None or existing.role != UserRole.admin:
            return templates.TemplateResponse(
                request,
                "oauth_result.html",
                {"message": "このDiscordアカウントは管理者として登録されていません。"},
                status_code=403,
            )
        token = auth_service.create_access_token(existing, settings)
        response = RedirectResponse("/admin/users/pending", status_code=303)
        response.set_cookie(
            auth_service.ADMIN_COOKIE, token, httponly=True, samesite="lax", max_age=60 * 60 * 24
        )
        return response

    # flow == "login"(Windowsクライアントからのログイン)
    client_redirect = state_payload.get("client_redirect")
    if existing is None:
        return templates.TemplateResponse(
            request,
            "oauth_result.html",
            {"message": "このDiscordアカウントでの申請が見つかりません。先に利用申請を行ってください。"},
        )
    # 管理者はstatus(pending/banned)にかかわらず無条件で利用できる
    if existing.role != UserRole.admin:
        if existing.status == UserStatus.pending:
            return templates.TemplateResponse(
                request, "oauth_result.html", {"message": "まだ管理者の承認待ちです。"}
            )
        if existing.status == UserStatus.banned:
            return templates.TemplateResponse(
                request, "oauth_result.html", {"message": "このアカウントは利用できません。"}
            )

    token = auth_service.create_access_token(existing, settings)
    if client_redirect:
        return RedirectResponse(f"{client_redirect}?token={token}")
    return templates.TemplateResponse(
        request, "oauth_result.html", {"message": "ログインに成功しました。"}
    )


@router.post("/apply/confirm", response_class=HTMLResponse)
async def apply_confirm(
    request: Request,
    confirm_token: str = Form(...),
    username: str = Form(...),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    try:
        payload = auth_service.verify_short_lived_token(confirm_token, APPLY_CONFIRM_PURPOSE, settings)
    except auth_service.InvalidTokenError:
        return HTMLResponse("セッションの有効期限が切れました。最初からやり直してください。", status_code=400)

    result = await db.execute(select(User).where(User.username == username))
    if result.scalar_one_or_none() is not None:
        return templates.TemplateResponse(
            request,
            "apply_username.html",
            {
                "discord_username": payload["discord_username"],
                "confirm_token": confirm_token,
                "error": "このユーザー名は既に使用されています",
            },
            status_code=409,
        )

    # サーバー初回セットアップ後、最初にDiscordで申請したユーザーを
    # 自動的に管理者として即承認する(以降の申請は通常どおり承認待ちになる)
    discord_user_count = await db.execute(
        select(func.count()).select_from(User).where(User.discord_id.is_not(None))
    )
    is_first_discord_user = discord_user_count.scalar_one() == 0

    now = datetime.now(UTC)
    user = User(
        username=username,
        discord_id=payload["discord_id"],
        applied_at=now,
    )
    if is_first_discord_user:
        user.role = UserRole.admin
        user.status = UserStatus.approved
        user.approved_at = now
    else:
        user.status = UserStatus.pending

    db.add(user)
    if is_first_discord_user:
        await db.flush()
        await stream_key_service.create_for_user(db, user)
    await db.commit()

    if is_first_discord_user:
        logger.info("Discord OAuth経由の初回申請につき管理者として即承認しました: username=%s", username)
    else:
        logger.info("Discord OAuth経由で新規申請を受け付けました: username=%s", username)
    return templates.TemplateResponse(request, "applied.html", {"is_admin": is_first_discord_user})
