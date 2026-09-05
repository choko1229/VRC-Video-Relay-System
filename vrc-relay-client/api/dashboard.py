import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from core import auth_client
from core.relay_client import RelayConfig
from db.models import add_log, get_config, get_relay_setting, set_config, set_relay_setting
from state import (
    CONFIG_KEY_PLAYBACK_URL,
    CONFIG_KEY_PUBLIC_SERVER_URL,
    CONFIG_KEY_PUSH_URL,
    LOCAL_HOST,
    LOCAL_PORT,
    PUBLIC_SERVER_URL,
    RELAY_SETTING_AUTO_RECONNECT,
    RELAY_SETTING_DEGRADE_THRESHOLD,
    RELAY_SETTING_DYNAMIC_BITRATE,
    RELAY_SETTING_RECOVER_THRESHOLD,
    mediamtx_manager,
    network_monitor,
    relay_client,
)
from templating import templates

logger = logging.getLogger(__name__)
router = APIRouter()


def _is_authenticated() -> bool:
    return auth_client.load_token() is not None


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    if not _is_authenticated():
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "dashboard.html", _dashboard_context())


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {})


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request) -> HTMLResponse:
    set_config(CONFIG_KEY_PUBLIC_SERVER_URL, PUBLIC_SERVER_URL)
    local_redirect = f"http://{LOCAL_HOST}:{LOCAL_PORT}/oauth/callback"
    return RedirectResponse(
        f"{PUBLIC_SERVER_URL}/oauth/discord/login/start?redirect_uri={local_redirect}"
    )


@router.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(request: Request, token: str) -> HTMLResponse:
    """公開サーバーのDiscord OAuthコールバックが、ここへさらにリダイレクトしてくる
    (redirect_uriを事前登録できないデスクトップアプリのための中継方式)。"""
    username = auth_client.save_token_from_jwt(token)

    server_url = get_config(CONFIG_KEY_PUBLIC_SERVER_URL)
    if server_url:
        try:
            status = await auth_client.get_my_status(server_url, token)
            set_config(CONFIG_KEY_PUSH_URL, status["push_url"])
            set_config(CONFIG_KEY_PLAYBACK_URL, status["playback_url"])
        except Exception:
            logger.warning("最新の配信URL取得に失敗しました(ログイン自体は成功)")

    add_log("info", f"ログインしました: {username}")
    return RedirectResponse("/", status_code=303)


@router.get("/logout")
async def logout() -> RedirectResponse:
    if relay_client.is_running():
        relay_client.stop()
    if mediamtx_manager.is_running():
        mediamtx_manager.stop()
    auth_client.clear_token()
    return RedirectResponse("/login", status_code=303)


@router.get("/dashboard/status", response_class=HTMLResponse)
async def dashboard_status(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "_dashboard_status.html", _dashboard_context())


@router.post("/dashboard/relay/toggle", response_class=HTMLResponse)
async def relay_toggle(request: Request) -> HTMLResponse:
    if relay_client.is_running() or mediamtx_manager.is_running():
        relay_client.stop()
        mediamtx_manager.stop()
        add_log("info", "中継サーバーを停止しました")
    else:
        token_info = auth_client.load_token()
        server_url = get_config(CONFIG_KEY_PUBLIC_SERVER_URL)
        push_url = get_config(CONFIG_KEY_PUSH_URL)

        if token_info and server_url:
            try:
                _username, token = token_info
                status = await auth_client.get_my_status(server_url, token)
                push_url = status["push_url"]
                set_config(CONFIG_KEY_PUSH_URL, push_url)
                set_config(CONFIG_KEY_PLAYBACK_URL, status["playback_url"])
            except Exception:
                logger.warning("最新の配信URL取得に失敗したため、キャッシュされたURLを使用します")

        # ローカルMediaMTX(OBS受信)は配信URLの有無にかかわらず必ず起動する。
        # 公開サーバーへのpushだけが配信URL依存であり、それが取得できない場合でも
        # OBSの受信確認やローカル動作確認自体はできるようにする。
        mediamtx_manager.start()

        if not push_url:
            add_log(
                "warning",
                "配信URLが取得できないため公開サーバーへの中継は開始しません(OBS受信のみ有効です)。再ログインするか設定を確認してください。",
            )
        else:
            relay_client.start(
                RelayConfig(
                    push_url=push_url,
                    dynamic_bitrate_enabled=get_relay_setting(RELAY_SETTING_DYNAMIC_BITRATE, "true") == "true",
                    auto_reconnect_enabled=get_relay_setting(RELAY_SETTING_AUTO_RECONNECT, "true") == "true",
                    degrade_streak_threshold=int(get_relay_setting(RELAY_SETTING_DEGRADE_THRESHOLD, "5")),
                    recover_streak_threshold=int(get_relay_setting(RELAY_SETTING_RECOVER_THRESHOLD, "30")),
                )
            )
            add_log("info", "中継サーバーを起動しました")

    return templates.TemplateResponse(request, "_dashboard_status.html", _dashboard_context())


@router.post("/dashboard/tier2/{key}/toggle", response_class=HTMLResponse)
async def tier2_toggle(request: Request, key: str) -> HTMLResponse:
    if key not in (RELAY_SETTING_DYNAMIC_BITRATE, RELAY_SETTING_AUTO_RECONNECT):
        return HTMLResponse("unknown setting", status_code=404)

    current = get_relay_setting(key, "true") == "true"
    new_value = not current
    set_relay_setting(key, "true" if new_value else "false")

    if key == RELAY_SETTING_DYNAMIC_BITRATE:
        relay_client.update_config(dynamic_bitrate_enabled=new_value)
    else:
        relay_client.update_config(auto_reconnect_enabled=new_value)

    return templates.TemplateResponse(request, "_dashboard_status.html", _dashboard_context())


@router.post("/dashboard/stream-key/rotate", response_class=HTMLResponse)
async def stream_key_rotate(request: Request) -> HTMLResponse:
    token_info = auth_client.load_token()
    server_url = get_config(CONFIG_KEY_PUBLIC_SERVER_URL)
    if token_info and server_url:
        _username, token = token_info
        try:
            result = await auth_client.rotate_stream_key(server_url, token)
            set_config(CONFIG_KEY_PUSH_URL, result["push_url"])
            add_log("info", "ストリームキーを再発行しました。中継中の場合は再起動してください。")
        except Exception:
            add_log("error", "ストリームキーの再発行に失敗しました")

    return templates.TemplateResponse(request, "_dashboard_status.html", _dashboard_context())


def _dashboard_context() -> dict:
    return {
        "obs_connected": mediamtx_manager.is_obs_connected(),
        "mediamtx_running": mediamtx_manager.is_running(),
        "relay": relay_client.status(),
        "network": network_monitor.snapshot(),
        "playback_url": get_config(CONFIG_KEY_PLAYBACK_URL, ""),
        "dynamic_bitrate_enabled": get_relay_setting(RELAY_SETTING_DYNAMIC_BITRATE, "true") == "true",
        "auto_reconnect_enabled": get_relay_setting(RELAY_SETTING_AUTO_RECONNECT, "true") == "true",
    }
