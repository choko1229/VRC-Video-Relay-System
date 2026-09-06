import logging
import threading
import webbrowser

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from core import auth_client, notify
from core.obs_manager import ObsNotFoundError
from core.relay_client import RelayConfig
from db.models import add_log, get_config, get_relay_setting, set_config, set_relay_setting
from state import (
    CONFIG_KEY_OBS_SELECTED_PROFILE,
    CONFIG_KEY_PLAYBACK_URL,
    CONFIG_KEY_PLAYBACK_URL_FALLBACK,
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
    obs_manager,
    relay_client,
)
from templating import templates

logger = logging.getLogger(__name__)
router = APIRouter()


def _is_authenticated() -> bool:
    return auth_client.load_token() is not None


def _start_obs_then_relay(profile_name: str, relay_config: RelayConfig | None) -> None:
    """バックグラウンドスレッドで実行する。OBSの起動・配信自動開始を待ってから
    (成功した場合のみ)ffmpeg中継を開始する。OBSがまだ配信していない状態で
    ffmpegを起動すると入力ストリームが無く即座に失敗するため、この順序が必要。
    """
    try:
        obs_manager.prepare_and_launch(profile_name)
        add_log("info", f"OBSを自動起動し配信を開始しました(プロファイル: {profile_name})")
    except ObsNotFoundError:
        add_log("error", "OBSの実行ファイルが見つからないため自動起動できませんでした")
        return
    except Exception:
        logger.exception("OBSの起動準備に失敗しました")
        add_log("error", "OBSの自動起動・配信開始に失敗しました。手動でOBSの配信設定を確認してください。")
        return

    if relay_config:
        relay_client.start(relay_config)
        add_log("info", "中継サーバーを起動しました")


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
    """アプリ内蔵の小さいウィンドウでDiscordの認可ページを直接開くと、Discordが
    「デスクトップアプリと連携するか」の確認ダイアログを表示してしまい狭い画面で
    崩れるため、認可はOSの既定ブラウザで行わせ、このウィンドウ側は完了を待つだけにする。
    """
    set_config(CONFIG_KEY_PUBLIC_SERVER_URL, PUBLIC_SERVER_URL)
    local_redirect = f"http://{LOCAL_HOST}:{LOCAL_PORT}/oauth/callback"
    auth_url = f"{PUBLIC_SERVER_URL}/oauth/discord/login/start?redirect_uri={local_redirect}"
    webbrowser.open(auth_url)
    return templates.TemplateResponse(request, "login_waiting.html", {})


@router.get("/login/status")
async def login_status() -> JSONResponse:
    return JSONResponse({"authenticated": _is_authenticated()})


@router.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(request: Request, token: str | None = None) -> HTMLResponse:
    """公開サーバーのDiscord OAuthコールバックが、ここへさらにリダイレクトしてくる
    (redirect_uriを事前登録できないデスクトップアプリのための中継方式)。
    ブラウザ側のタブに直接表示される応答なので、アプリのダッシュボードではなく
    「アプリに戻ってください」という簡潔な完了画面を返す(遷移はアプリ側が待機画面で検知する)。
    """
    if not token:
        add_log("error", "Discordログインに失敗しました(トークンを受信できませんでした)")
        return templates.TemplateResponse(
            request,
            "oauth_browser_result.html",
            {"message": "Discordログインに失敗しました。アプリの画面からもう一度お試しください。"},
            status_code=400,
        )

    username = auth_client.save_token_from_jwt(token)

    server_url = get_config(CONFIG_KEY_PUBLIC_SERVER_URL)
    if server_url:
        try:
            status = await auth_client.get_my_status(server_url, token)
            set_config(CONFIG_KEY_PUSH_URL, status["push_url"])
            set_config(CONFIG_KEY_PLAYBACK_URL, status["playback_url"])
            set_config(CONFIG_KEY_PLAYBACK_URL_FALLBACK, status["playback_url_fallback"])
        except Exception:
            logger.warning("最新の配信URL取得に失敗しました(ログイン自体は成功)")

    add_log("info", f"ログインしました: {username}")
    return templates.TemplateResponse(
        request, "oauth_browser_result.html", {"message": "ログインが完了しました。アプリの画面に戻ってください。"}
    )


@router.get("/logout")
async def logout() -> RedirectResponse:
    if relay_client.is_running():
        relay_client.stop()
    if mediamtx_manager.is_running():
        mediamtx_manager.stop()
    if obs_manager.has_backup() and not obs_manager.stop_and_restore():
        notify.show_toast(
            "VRChat Live Relay",
            "OBSの設定を元に戻せませんでした。OBSの配信設定を確認してください。",
        )
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

        if obs_manager.has_backup():
            add_log("info", "OBSを終了し、元の設定に復元します")
            if obs_manager.stop_and_restore():
                add_log("info", "OBSの設定を復元しました")
            else:
                add_log("error", "OBSの設定復元に失敗しました。OBSで配信設定を確認してください。")
                notify.show_toast(
                    "VRChat Live Relay",
                    "OBSの設定を元に戻せませんでした。OBSの配信設定を確認してください。",
                )
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
                set_config(CONFIG_KEY_PLAYBACK_URL_FALLBACK, status["playback_url_fallback"])
            except Exception:
                logger.warning("最新の配信URL取得に失敗したため、キャッシュされたURLを使用します")

        # ローカルMediaMTX(OBS受信)は配信URLの有無にかかわらず必ず起動する。
        # 公開サーバーへのpushだけが配信URL依存であり、それが取得できない場合でも
        # OBSの受信確認やローカル動作確認自体はできるようにする。
        mediamtx_manager.start()

        relay_config = None
        if not push_url:
            add_log(
                "warning",
                "配信URLが取得できないため公開サーバーへの中継は開始しません(OBS受信のみ有効です)。再ログインするか設定を確認してください。",
            )
        else:
            relay_config = RelayConfig(
                push_url=push_url,
                dynamic_bitrate_enabled=get_relay_setting(RELAY_SETTING_DYNAMIC_BITRATE, "true") == "true",
                auto_reconnect_enabled=get_relay_setting(RELAY_SETTING_AUTO_RECONNECT, "true") == "true",
                degrade_streak_threshold=int(get_relay_setting(RELAY_SETTING_DEGRADE_THRESHOLD, "5")),
                recover_streak_threshold=int(get_relay_setting(RELAY_SETTING_RECOVER_THRESHOLD, "30")),
            )

        obs_profile_name = None
        if obs_manager.is_installed():
            obs_profile_name = get_config(CONFIG_KEY_OBS_SELECTED_PROFILE) or obs_manager.get_active_profile()

        if obs_profile_name:
            # OBSの起動待ち・配信自動開始(WebSocket接続)は数秒〜数十秒かかりうるため、
            # このリクエストをブロックしないようバックグラウンドスレッドで行う。
            # ffmpeg中継はOBSの配信開始を待つ必要があるため、ここでまとめて開始する。
            add_log("info", f"OBSを準備しています(プロファイル: {obs_profile_name})")
            threading.Thread(
                target=_start_obs_then_relay, args=(obs_profile_name, relay_config), daemon=True
            ).start()
        elif relay_config:
            relay_client.start(relay_config)
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


@router.post("/dashboard/obs/profile", response_class=HTMLResponse)
async def obs_profile_select(request: Request, obs_profile: str = Form(...)) -> HTMLResponse:
    if obs_profile in obs_manager.list_profiles():
        set_config(CONFIG_KEY_OBS_SELECTED_PROFILE, obs_profile)
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
        "playback_url_fallback": get_config(CONFIG_KEY_PLAYBACK_URL_FALLBACK, ""),
        "dynamic_bitrate_enabled": get_relay_setting(RELAY_SETTING_DYNAMIC_BITRATE, "true") == "true",
        "auto_reconnect_enabled": get_relay_setting(RELAY_SETTING_AUTO_RECONNECT, "true") == "true",
        **_obs_context(),
    }


def _obs_context() -> dict:
    if not obs_manager.is_installed():
        return {"obs_installed": False}

    profiles = obs_manager.list_profiles()
    selected_profile = get_config(CONFIG_KEY_OBS_SELECTED_PROFILE)
    if selected_profile not in profiles:
        selected_profile = obs_manager.get_active_profile()

    return {
        "obs_installed": True,
        "obs_profiles": profiles,
        "obs_selected_profile": selected_profile,
        "obs_profile_info": obs_manager.get_profile_info(selected_profile) if selected_profile else None,
        "obs_tool_active": obs_manager.has_backup(),
    }
