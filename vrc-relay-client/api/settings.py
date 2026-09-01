from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from db.models import get_config, get_relay_setting, set_config, set_relay_setting
from state import (
    CONFIG_KEY_PUBLIC_SERVER_URL,
    RELAY_SETTING_DEGRADE_THRESHOLD,
    RELAY_SETTING_RECOVER_THRESHOLD,
    relay_client,
)
from templating import templates

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
async def settings_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "settings.html", _settings_context())


@router.post("/settings", response_class=HTMLResponse)
async def settings_submit(
    request: Request,
    server_url: str = Form(...),
    degrade_streak_threshold: int = Form(...),
    recover_streak_threshold: int = Form(...),
) -> HTMLResponse:
    set_config(CONFIG_KEY_PUBLIC_SERVER_URL, server_url.rstrip("/"))
    set_relay_setting(RELAY_SETTING_DEGRADE_THRESHOLD, str(degrade_streak_threshold))
    set_relay_setting(RELAY_SETTING_RECOVER_THRESHOLD, str(recover_streak_threshold))
    relay_client.update_config(
        degrade_streak_threshold=degrade_streak_threshold,
        recover_streak_threshold=recover_streak_threshold,
    )

    context = _settings_context()
    context["saved"] = True
    return templates.TemplateResponse(request, "settings.html", context)


def _settings_context() -> dict:
    return {
        "server_url": get_config(CONFIG_KEY_PUBLIC_SERVER_URL, ""),
        "degrade_streak_threshold": int(get_relay_setting(RELAY_SETTING_DEGRADE_THRESHOLD, "5")),
        "recover_streak_threshold": int(get_relay_setting(RELAY_SETTING_RECOVER_THRESHOLD, "30")),
    }
