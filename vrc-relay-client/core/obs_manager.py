"""OBS Studioとの連携。

配信開始時にOBSの配信設定を「ツール用(ローカルMediaMTX向け)」へ一時的に書き換えて
OBSを自動起動し、停止時には元の設定に復元してOBSを終了する。

OBSは設定ファイル(%APPDATA%\\obs-studio\\)を起動時にしか読み込まないため、起動中に
書き換えても反映されない。そのため書き換えの前後で必ずOBSプロセスの終了・起動を行う。

basic.iniにはYouTube等の連携トークンが平文で含まれることがあるため、バックアップは
ファイル内容を丸ごとDBへ退避するだけに留め、表示用に読み出す値は解像度・ビットレート
など配信設定に関わる項目だけに限定する(トークン等をログや画面に出さない)。
"""

import configparser
import json
import logging
import os
import subprocess
import time
import winreg
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import win32con
import win32gui
import win32process

from core.mediamtx_manager import LOCAL_RTMP_URL
from db.models import get_config, set_config

logger = logging.getLogger(__name__)

OBS_CONFIG_DIR = Path(os.environ["APPDATA"]) / "obs-studio"
OBS_PROCESS_NAME = "obs64.exe"
OBS_WEBSOCKET_CONFIG = OBS_CONFIG_DIR / "plugin_config" / "obs-websocket" / "config.json"

# ローカルMediaMTXへOBSから配信させるための接続先。mediamtx_manager.LOCAL_RTMP_URLと
# 常に一致させる(パス名=ストリームキーが食い違うとMediaMTXが接続を拒否するため)。
_parsed_local_rtmp = urlsplit(LOCAL_RTMP_URL)
TOOL_RTMP_SERVER = f"{_parsed_local_rtmp.scheme}://{_parsed_local_rtmp.netloc}"
TOOL_STREAM_KEY = _parsed_local_rtmp.path.lstrip("/")

_CONFIG_KEY_BACKUP_PROFILE = "obs_backup_profile"
_CONFIG_KEY_BACKUP_BASIC_INI = "obs_backup_basic_ini"
_CONFIG_KEY_BACKUP_SERVICE_JSON = "obs_backup_service_json"
_CONFIG_KEY_BACKUP_WS_CONFIG = "obs_backup_ws_config"

_PROCESS_POLL_INTERVAL_SEC = 0.5
_WEBSOCKET_CONNECT_TIMEOUT_SEC = 30.0
_WEBSOCKET_RETRY_INTERVAL_SEC = 1.5

# ダッシュボード表示用。未知のIDはそのまま生の値を表示する。
_ENCODER_DISPLAY_NAMES = {
    "obs_x264": "x264 (CPU)",
    "obs_qsv11": "Intel QuickSync",
    "obs_qsv11_v2": "Intel QuickSync",
    "obs_nvenc_h264_tex": "NVENC (H.264)",
    "obs_nvenc_hevc_tex": "NVENC (HEVC)",
    "jim_nvenc": "NVENC (H.264)",
    "jim_hevc_nvenc": "NVENC (HEVC)",
    "h264_texture_amf": "AMD AMF (H.264)",
    "amd_amf_h264": "AMD AMF (H.264)",
}


@dataclass
class ObsProfileInfo:
    mode: str
    encoder: str
    video_bitrate_kbps: str
    base_resolution: str
    output_resolution: str
    fps: str


class ObsNotFoundError(Exception):
    pass


class ObsManager:
    def find_exe(self) -> Path | None:
        for hive, subkey in (
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\OBS Studio"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\OBS Studio"),
        ):
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    install_dir, _ = winreg.QueryValueEx(key, "")
                    exe = Path(install_dir) / "bin" / "64bit" / "obs64.exe"
                    if exe.exists():
                        return exe
            except OSError:
                continue

        default = Path(r"C:\Program Files\obs-studio\bin\64bit\obs64.exe")
        return default if default.exists() else None

    def is_installed(self) -> bool:
        return self.find_exe() is not None

    def list_profiles(self) -> list[str]:
        profiles_dir = OBS_CONFIG_DIR / "basic" / "profiles"
        if not profiles_dir.exists():
            return []
        return sorted(
            p.name for p in profiles_dir.iterdir() if p.is_dir() and (p / "basic.ini").exists()
        )

    def _read_ini(self, path: Path) -> configparser.ConfigParser:
        # OBSのINIキーは大文字小文字を区別するため、書き込み側(_apply_tool_settings)と
        # 読み込み側とで扱いが食い違わないよう常にoptionxform=strを使う。
        # strict=Falseにして、想定外の重複キーがあっても表示処理自体は落とさない。
        parser = configparser.ConfigParser(strict=False)
        parser.optionxform = str
        parser.read(path, encoding="utf-8-sig")
        return parser

    def get_active_profile(self) -> str | None:
        # OBS 28以降はuser.ini、それ以前はglobal.iniに現在選択中のプロファイル名が入る。
        for filename in ("user.ini", "global.ini"):
            ini_path = OBS_CONFIG_DIR / filename
            if not ini_path.exists():
                continue
            parser = self._read_ini(ini_path)
            profile = parser.get("Basic", "Profile", fallback=None)
            if profile:
                return profile
        return None

    def get_profile_info(self, profile_name: str) -> ObsProfileInfo | None:
        basic_ini = OBS_CONFIG_DIR / "basic" / "profiles" / profile_name / "basic.ini"
        if not basic_ini.exists():
            return None

        parser = self._read_ini(basic_ini)

        mode = parser.get("Output", "Mode", fallback="Simple")
        if mode == "Advanced":
            encoder = parser.get("AdvOut", "Encoder", fallback="-")
            # 詳細出力モードの配信ビットレートはエンコーダーごとの個別設定として
            # 保存されbasic.iniには含まれないため、ここでは表示しない。
            bitrate = "-"
        else:
            encoder = parser.get("SimpleOutput", "StreamEncoder", fallback="-")
            bitrate = parser.get("SimpleOutput", "VBitrate", fallback="-")

        return ObsProfileInfo(
            mode=mode,
            encoder=_ENCODER_DISPLAY_NAMES.get(encoder, encoder),
            video_bitrate_kbps=bitrate,
            base_resolution=(
                f"{parser.get('Video', 'BaseCX', fallback='?')}"
                f"x{parser.get('Video', 'BaseCY', fallback='?')}"
            ),
            output_resolution=(
                f"{parser.get('Video', 'OutputCX', fallback='?')}"
                f"x{parser.get('Video', 'OutputCY', fallback='?')}"
            ),
            fps=parser.get("Video", "FPSCommon", fallback=parser.get("Video", "FPSInt", fallback="?")),
        )

    def is_running(self) -> bool:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {OBS_PROCESS_NAME}", "/NH"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return OBS_PROCESS_NAME.lower() in result.stdout.lower()

    def has_backup(self) -> bool:
        return bool(get_config(_CONFIG_KEY_BACKUP_PROFILE))

    def _get_obs_pids(self) -> set[int]:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {OBS_PROCESS_NAME}", "/NH", "/FO", "CSV"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        pids: set[int] = set()
        for line in result.stdout.splitlines():
            parts = [p.strip('"') for p in line.split(",")]
            if len(parts) >= 2 and parts[0].lower() == OBS_PROCESS_NAME.lower():
                try:
                    pids.add(int(parts[1]))
                except ValueError:
                    pass
        return pids

    def _post_close_to_main_windows(self) -> bool:
        target_pids = self._get_obs_pids()
        if not target_pids:
            return False

        found = False

        def _enum_handler(hwnd: int, _: object) -> bool:
            nonlocal found
            if not win32gui.IsWindowVisible(hwnd) or not win32gui.GetWindowText(hwnd):
                return True
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid in target_pids:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                found = True
            return True

        win32gui.EnumWindows(_enum_handler, None)
        return found

    def _terminate(self, timeout: float = 20.0) -> None:
        if not self.is_running():
            return

        # taskkillでの強制終了はOBSに「前回は異常終了した」と誤認識させ、次回起動時に
        # ユーザー操作を要求するクラッシュ確認ダイアログを表示させてしまい、自動化が
        # 完全に止まる。まずメインウィンドウにWM_CLOSEを送って正常な終了処理(Qtの
        # クローズイベント)を通し、それでも終わらない場合にのみtaskkillへ後退する。
        if self._post_close_to_main_windows():
            deadline = time.time() + timeout
            while self.is_running() and time.time() < deadline:
                time.sleep(_PROCESS_POLL_INTERVAL_SEC)

        if not self.is_running():
            return

        subprocess.run(
            ["taskkill", "/IM", OBS_PROCESS_NAME],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        deadline = time.time() + timeout
        while self.is_running() and time.time() < deadline:
            time.sleep(_PROCESS_POLL_INTERVAL_SEC)
        if self.is_running():
            subprocess.run(
                ["taskkill", "/IM", OBS_PROCESS_NAME, "/F"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            deadline = time.time() + timeout
            while self.is_running() and time.time() < deadline:
                time.sleep(_PROCESS_POLL_INTERVAL_SEC)

    def _clear_shutdown_sentinel(self) -> None:
        """OBS 32以降、正常終了しなかった場合に次回起動時ユーザー操作を要求する
        「セーフモードで起動しますか」ダイアログが表示され自動化が完全に止まって
        しまう。これはこのアプリの終了方法(taskkill/WM_CLOSE)の問題ではなく、
        OBS自身が%APPDATA%\\obs-studio\\.sentinel内に起動ごとのマーカーファイルを
        作り正常終了時にのみ消す仕組みのため、起動前に消せばダイアログを回避できる
        (--disable-shutdown-checkはOBS 32で廃止され使えなくなった)。
        """
        sentinel_dir = OBS_CONFIG_DIR / ".sentinel"
        if not sentinel_dir.exists():
            return
        for marker in sentinel_dir.iterdir():
            try:
                marker.unlink()
            except OSError:
                pass

    def _launch(self, obs_exe: Path) -> None:
        self._clear_shutdown_sentinel()
        # --startstreaming: 起動と同時に配信を開始させる。これがあれば理屈上はWebSocket
        # 経由のstart_stream()は不要だが、環境差で効かない場合に備え両方行う。
        subprocess.Popen(
            [str(obs_exe), "--startstreaming"],
            cwd=str(obs_exe.parent),
        )

    def _backup_profile(self, profile_name: str) -> None:
        profile_dir = OBS_CONFIG_DIR / "basic" / "profiles" / profile_name
        basic_ini = profile_dir / "basic.ini"
        service_json = profile_dir / "service.json"

        set_config(_CONFIG_KEY_BACKUP_PROFILE, profile_name)
        set_config(
            _CONFIG_KEY_BACKUP_BASIC_INI,
            basic_ini.read_text(encoding="utf-8-sig") if basic_ini.exists() else "",
        )
        set_config(
            _CONFIG_KEY_BACKUP_SERVICE_JSON,
            service_json.read_text(encoding="utf-8") if service_json.exists() else "",
        )
        set_config(
            _CONFIG_KEY_BACKUP_WS_CONFIG,
            OBS_WEBSOCKET_CONFIG.read_text(encoding="utf-8") if OBS_WEBSOCKET_CONFIG.exists() else "",
        )

    def _apply_tool_settings(self, profile_name: str) -> tuple[int, str]:
        """ツール用に設定を書き換える。戻り値はOBS WebSocketの(ポート, パスワード)。

        配信の自動開始にはWebSocket経由の操作が必要なため、無効化されていれば
        一時的に有効化する(既存のパスワード・認証要否はそのまま尊重する)。
        """
        profile_dir = OBS_CONFIG_DIR / "basic" / "profiles" / profile_name
        service_json = profile_dir / "service.json"
        basic_ini = profile_dir / "basic.ini"

        service_json.write_text(
            json.dumps(
                {
                    "type": "rtmp_custom",
                    "settings": {
                        "server": TOOL_RTMP_SERVER,
                        "key": TOOL_STREAM_KEY,
                        "use_auth": False,
                        "bwtest": False,
                    },
                }
            ),
            encoding="utf-8",
        )

        parser = self._read_ini(basic_ini) if basic_ini.exists() else configparser.ConfigParser(strict=False)
        parser.optionxform = str  # OBSのINIキーは大文字小文字を区別するため保持する

        if not parser.has_section("Output"):
            parser.add_section("Output")
        parser.set("Output", "Mode", "Simple")

        # 解像度・FPSはユーザー環境依存(VRChatでの見え方に影響)のため変更しない。
        # エンコーダーはGPU種別に依存しないx264に固定し、環境差でのクラッシュを避ける。
        if not parser.has_section("SimpleOutput"):
            parser.add_section("SimpleOutput")
        parser.set("SimpleOutput", "VBitrate", "6000")
        parser.set("SimpleOutput", "ABitrate", "160")
        parser.set("SimpleOutput", "Preset", "veryfast")
        parser.set("SimpleOutput", "StreamEncoder", "x264")
        parser.set("SimpleOutput", "StreamAudioEncoder", "aac")
        parser.set("SimpleOutput", "UseAdvanced", "false")

        with basic_ini.open("w", encoding="utf-8-sig") as f:
            parser.write(f)

        if OBS_WEBSOCKET_CONFIG.exists():
            ws_config = json.loads(OBS_WEBSOCKET_CONFIG.read_text(encoding="utf-8"))
        else:
            ws_config = {"auth_required": False, "server_password": "", "server_port": 4455}
        ws_config["server_enabled"] = True
        OBS_WEBSOCKET_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        OBS_WEBSOCKET_CONFIG.write_text(json.dumps(ws_config), encoding="utf-8")

        port = ws_config.get("server_port", 4455)
        password = ws_config.get("server_password", "") if ws_config.get("auth_required", True) else ""
        return port, password

    def _start_stream_via_websocket(self, port: int, password: str) -> None:
        """OBS起動直後はWebSocketサーバーへ接続できても、出力パイプラインの初期化が
        追いついておらずstart_stream()が例外を出さないまま実際には配信を開始しない
        ことがある。そのためget_stream_status()のoutput_activeで実際の開始を
        確認できるまでstart_stream()を呼び直す。
        """
        import obsws_python as obs

        deadline = time.time() + _WEBSOCKET_CONNECT_TIMEOUT_SEC
        last_exc: Exception | None = None
        while time.time() < deadline:
            try:
                with obs.ReqClient(host="127.0.0.1", port=port, password=password, timeout=3) as client:
                    if client.get_stream_status().output_active:
                        return
                    client.start_stream()
            except Exception as exc:
                last_exc = exc
            time.sleep(_WEBSOCKET_RETRY_INTERVAL_SEC)
        raise RuntimeError(f"OBS WebSocketへの接続に失敗し、配信を自動開始できませんでした: {last_exc}")

    def prepare_and_launch(self, profile_name: str) -> None:
        """配信開始時に呼ぶ。設定をバックアップしてツール用に書き換え、OBSを起動して
        配信も自動開始する(OBS WebSocket経由)。呼び出し元でのブロッキングを避けるため
        バックグラウンドスレッドから呼ぶことを想定している。
        """
        obs_exe = self.find_exe()
        if obs_exe is None:
            raise ObsNotFoundError("OBSの実行ファイルが見つかりません")

        self._terminate()
        # 既にツール用設定を適用中(=中継停止を経ずに再度開始された)場合、ここで
        # バックアップを取り直すと、ツール用設定そのものを「元の設定」として
        # 上書き保存してしまい元に戻せなくなる。既存のバックアップを優先する。
        if not self.has_backup():
            self._backup_profile(profile_name)
        ws_port, ws_password = self._apply_tool_settings(profile_name)
        self._launch(obs_exe)
        self._start_stream_via_websocket(ws_port, ws_password)

    def stop_and_restore(self) -> bool:
        """配信停止時に呼ぶ。OBSを終了し元の設定に復元する。成功したらTrue。

        バックアップが存在しない(そもそも本ツールがOBSへ触れていない)場合は
        何もせずTrueを返す。
        """
        profile_name = get_config(_CONFIG_KEY_BACKUP_PROFILE)
        if not profile_name:
            return True

        self._terminate()

        try:
            profile_dir = OBS_CONFIG_DIR / "basic" / "profiles" / profile_name
            basic_ini_content = get_config(_CONFIG_KEY_BACKUP_BASIC_INI)
            service_json_content = get_config(_CONFIG_KEY_BACKUP_SERVICE_JSON)
            ws_config_content = get_config(_CONFIG_KEY_BACKUP_WS_CONFIG)

            if basic_ini_content:
                (profile_dir / "basic.ini").write_text(basic_ini_content, encoding="utf-8-sig")
            if service_json_content:
                (profile_dir / "service.json").write_text(service_json_content, encoding="utf-8")
            if ws_config_content:
                OBS_WEBSOCKET_CONFIG.write_text(ws_config_content, encoding="utf-8")

            set_config(_CONFIG_KEY_BACKUP_PROFILE, "")
            set_config(_CONFIG_KEY_BACKUP_BASIC_INI, "")
            set_config(_CONFIG_KEY_BACKUP_SERVICE_JSON, "")
            set_config(_CONFIG_KEY_BACKUP_WS_CONFIG, "")
            return True
        except Exception:
            logger.exception("OBS設定の復元に失敗しました")
            return False
