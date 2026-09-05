import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_discord_notifier, get_mediamtx_client
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.user import User, UserRole, UserStatus
from app.services import admin_actions, auth_service, stream_key_service
from app.services.discord_service import DiscordNotifier
from app.services.mediamtx_client import MediaMTXClient

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")

ADMIN_COOKIE = auth_service.ADMIN_COOKIE


async def _get_admin(request: Request, db: AsyncSession, settings: Settings) -> User | None:
    token = request.cookies.get(ADMIN_COOKIE)
    if not token:
        return None
    try:
        payload = auth_service.decode_token(token, settings)
    except auth_service.InvalidTokenError:
        return None
    if payload.get("purpose") != auth_service.TOKEN_PURPOSE_ACCESS or payload.get("role") != "admin":
        return None
    result = await db.execute(select(User).where(User.id == int(payload["sub"])))
    user = result.scalar_one_or_none()
    # 管理者はstatus(pending/banned)にかかわらず無条件で利用できる
    if user is None or user.role != UserRole.admin:
        return None
    return user


def _require_admin_or_redirect(admin: User | None) -> RedirectResponse | None:
    if admin is None:
        return RedirectResponse("/login", status_code=303)
    return None


# --- 利用申請(Discord OAuthのstart/callback/confirmはapp/web/oauth.pyを参照) ---


@router.get("/apply", response_class=HTMLResponse)
async def apply_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "apply.html", {})


# --- 申請状況確認 ---


@router.get("/status", response_class=HTMLResponse)
async def status_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "status.html", {})


@router.post("/status", response_class=HTMLResponse)
async def status_submit(
    request: Request,
    username: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        return templates.TemplateResponse(
            request, "status.html", {"searched": True, "username": username}
        )

    return templates.TemplateResponse(
        request,
        "status.html",
        {"username": username, "result": {"status": user.status.value}, "searched": True},
    )


# --- 管理者ログイン(Discord OAuthのstart/callbackはapp/web/oauth.pyを参照) ---


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {})


@router.get("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(ADMIN_COOKIE)
    return response


# --- 管理パネル ---


@router.get("/admin")
async def admin_root() -> RedirectResponse:
    return RedirectResponse("/admin/users/pending", status_code=303)


@router.get("/admin/users/pending", response_class=HTMLResponse)
async def admin_pending_users(
    request: Request, db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> HTMLResponse:
    admin = await _get_admin(request, db, settings)
    if (redirect := _require_admin_or_redirect(admin)) is not None:
        return redirect

    result = await db.execute(
        select(User).where(User.status == UserStatus.pending).order_by(User.applied_at)
    )
    users = list(result.scalars())
    return templates.TemplateResponse(
        request, "admin/pending_users.html", {"admin": admin, "users": users}
    )


@router.post("/admin/users/{user_id}/approve", response_class=HTMLResponse)
async def admin_approve(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    discord: DiscordNotifier = Depends(get_discord_notifier),
) -> HTMLResponse:
    admin = await _get_admin(request, db, settings)
    if (redirect := _require_admin_or_redirect(admin)) is not None:
        return redirect

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is not None and user.status == UserStatus.pending:
        await admin_actions.approve_user(db, user, discord)

    return await _render_pending_list(request, db, admin)


@router.post("/admin/users/{user_id}/reject", response_class=HTMLResponse)
async def admin_reject(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    mediamtx: MediaMTXClient = Depends(get_mediamtx_client),
) -> HTMLResponse:
    admin = await _get_admin(request, db, settings)
    if (redirect := _require_admin_or_redirect(admin)) is not None:
        return redirect

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is not None and user.status == UserStatus.pending:
        await admin_actions.ban_user(db, user, mediamtx)

    return await _render_pending_list(request, db, admin)


async def _render_pending_list(request: Request, db: AsyncSession, admin: User) -> HTMLResponse:
    result = await db.execute(
        select(User).where(User.status == UserStatus.pending).order_by(User.applied_at)
    )
    users = list(result.scalars())
    return templates.TemplateResponse(
        request, "admin/_pending_list.html", {"admin": admin, "users": users}
    )


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users(
    request: Request, db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> HTMLResponse:
    admin = await _get_admin(request, db, settings)
    if (redirect := _require_admin_or_redirect(admin)) is not None:
        return redirect

    result = await db.execute(select(User).order_by(User.applied_at.desc()))
    users = list(result.scalars())
    return templates.TemplateResponse(request, "admin/users.html", {"admin": admin, "users": users})


@router.post("/admin/users/{user_id}/ban", response_class=HTMLResponse)
async def admin_ban(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    mediamtx: MediaMTXClient = Depends(get_mediamtx_client),
) -> HTMLResponse:
    admin = await _get_admin(request, db, settings)
    if (redirect := _require_admin_or_redirect(admin)) is not None:
        return redirect

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is not None and user.id != admin.id:
        await admin_actions.ban_user(db, user, mediamtx)

    result = await db.execute(select(User).order_by(User.applied_at.desc()))
    users = list(result.scalars())
    return templates.TemplateResponse(request, "admin/_users_list.html", {"admin": admin, "users": users})


@router.get("/admin/streams", response_class=HTMLResponse)
async def admin_streams(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    mediamtx: MediaMTXClient = Depends(get_mediamtx_client),
) -> HTMLResponse:
    admin = await _get_admin(request, db, settings)
    if (redirect := _require_admin_or_redirect(admin)) is not None:
        return redirect

    result = await db.execute(
        select(User).where(User.role == UserRole.user).where(User.status == UserStatus.approved)
    )
    users = list(result.scalars())
    paths = {p["name"]: p for p in await mediamtx.list_paths()}

    streams = []
    for user in users:
        key = await stream_key_service.get_by_user_id(db, user.id)
        if key is None:
            continue
        path_info = paths.get(key.path_name)
        streams.append(
            {
                "username": user.username,
                "path_name": key.path_name,
                "is_publishing": bool(path_info and path_info.get("ready")),
                "bytes_received": path_info.get("bytesReceived") if path_info else None,
            }
        )

    template_name = "admin/_streams_table.html" if request.headers.get("hx-request") else "admin/streams.html"
    return templates.TemplateResponse(
        request, template_name, {"admin": admin, "streams": streams}
    )
