import logging
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum

from core.mediamtx_manager import LOCAL_RTMP_URL
from core.network_monitor import NetworkMonitor
from db.models import add_log

logger = logging.getLogger(__name__)


class RelayState(str, Enum):
    stopped = "stopped"
    connecting = "connecting"
    relaying = "relaying"
    reconnecting = "reconnecting"
    error = "error"


@dataclass
class EncodeProfile:
    name: str
    video_args: list[str]
    audio_args: list[str]


# -c copy(ストリームコピー)が基本。帯域悪化時はTier2の動的ビットレート調整で
# 低ビットレートの再エンコードプロファイルに切り替える(ffmpeg再起動が必要)。
PROFILE_COPY = EncodeProfile("copy", ["-c:v", "copy"], ["-c:a", "copy"])
PROFILE_MEDIUM = EncodeProfile(
    "medium", ["-c:v", "libx264", "-preset", "veryfast", "-b:v", "2500k"], ["-c:a", "aac", "-b:a", "128k"]
)
PROFILE_LOW = EncodeProfile(
    "low", ["-c:v", "libx264", "-preset", "veryfast", "-b:v", "1200k"], ["-c:a", "aac", "-b:a", "96k"]
)
DEGRADE_ORDER = [PROFILE_COPY, PROFILE_MEDIUM, PROFILE_LOW]

_MAX_BACKOFF_SEC = 30


@dataclass
class RelayConfig:
    push_url: str
    dynamic_bitrate_enabled: bool = True
    auto_reconnect_enabled: bool = True
    # 何回連続でspeed<1(実時間に追いつけていない)を観測したら格下げ/回復するか
    degrade_streak_threshold: int = 5
    recover_streak_threshold: int = 30


@dataclass
class _RuntimeInfo:
    state: RelayState = RelayState.stopped
    profile_name: str = PROFILE_COPY.name
    reconnect_attempts: int = 0
    last_error: str | None = None


class RelayClient:
    """公開サーバーへの中継(push)。ffmpeg -c copyを基本とし、
    Tier2の動的ビットレート調整・自動再接続を行う。
    """

    def __init__(self, network_monitor: NetworkMonitor) -> None:
        self._monitor = network_monitor
        self._config: RelayConfig | None = None
        self._process: subprocess.Popen | None = None
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._profile_index = 0
        self._good_streak = 0
        self._bad_streak = 0
        self._info = _RuntimeInfo()
        self._lock = threading.Lock()

    def start(self, config: RelayConfig) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._config = config
        self._profile_index = 0
        self._stop_event.clear()
        self._monitor.reset()
        self._set_info(state=RelayState.connecting, profile_name=PROFILE_COPY.name, reconnect_attempts=0)
        self._worker = threading.Thread(target=self._supervisor_loop, daemon=True)
        self._worker.start()

    def update_config(
        self,
        dynamic_bitrate_enabled: bool | None = None,
        auto_reconnect_enabled: bool | None = None,
        degrade_streak_threshold: int | None = None,
        recover_streak_threshold: int | None = None,
    ) -> None:
        if self._config is None:
            return
        if dynamic_bitrate_enabled is not None:
            self._config.dynamic_bitrate_enabled = dynamic_bitrate_enabled
        if auto_reconnect_enabled is not None:
            self._config.auto_reconnect_enabled = auto_reconnect_enabled
        if degrade_streak_threshold is not None:
            self._config.degrade_streak_threshold = degrade_streak_threshold
        if recover_streak_threshold is not None:
            self._config.recover_streak_threshold = recover_streak_threshold

    def is_running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def stop(self) -> None:
        self._stop_event.set()
        self._terminate_process()
        if self._worker is not None:
            self._worker.join(timeout=5)
        self._worker = None
        self._set_info(state=RelayState.stopped)
        add_log("info", "公開サーバーへの中継を停止しました")

    def status(self) -> dict:
        with self._lock:
            info = self._info
        return {
            "state": info.state.value,
            "profile": info.profile_name,
            "reconnect_attempts": info.reconnect_attempts,
            "last_error": info.last_error,
        }

    def _set_info(self, **kwargs) -> None:
        with self._lock:
            for k, v in kwargs.items():
                setattr(self._info, k, v)

    def _current_profile(self) -> EncodeProfile:
        return DEGRADE_ORDER[self._profile_index]

    def _supervisor_loop(self) -> None:
        assert self._config is not None
        backoff = 1

        while not self._stop_event.is_set():
            profile = self._current_profile()
            self._set_info(state=RelayState.connecting, profile_name=profile.name)
            try:
                self._run_ffmpeg_once(profile)
                backoff = 1
            except Exception as exc:
                logger.exception("ffmpeg中継プロセスでエラーが発生しました")
                self._set_info(last_error=str(exc))
                add_log("error", f"中継エラー: {exc}")

            if self._stop_event.is_set():
                break

            if not self._config.auto_reconnect_enabled:
                self._set_info(state=RelayState.error, last_error="接続が切断されました(自動再接続は無効)")
                add_log("error", "中継が切断されました。自動再接続が無効のため停止します。")
                break

            self._set_info(state=RelayState.reconnecting)
            with self._lock:
                self._info.reconnect_attempts += 1
            add_log("info", f"{backoff}秒後に再接続します(試行 {self._info.reconnect_attempts}回目)")
            if self._stop_event.wait(backoff):
                break
            backoff = min(backoff * 2, _MAX_BACKOFF_SEC)

        self._set_info(state=RelayState.stopped)

    def _run_ffmpeg_once(self, profile: EncodeProfile) -> None:
        assert self._config is not None
        cmd = [
            "ffmpeg",
            "-loglevel", "warning",
            "-re",
            "-i", LOCAL_RTMP_URL,
            *profile.video_args,
            *profile.audio_args,
            "-f", "flv",
            self._config.push_url,
            "-progress", "pipe:1",
            "-nostats",
        ]
        add_log("info", f"ffmpeg中継を開始します(profile={profile.name})")

        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._set_info(state=RelayState.relaying)
        self._good_streak = 0
        self._bad_streak = 0

        assert self._process.stdout is not None
        for line in self._process.stdout:
            if self._stop_event.is_set():
                break
            self._monitor.feed_line(line)
            if line.strip() == "progress=continue":
                self._evaluate_bitrate_adjustment()

        returncode = self._process.wait()
        self._process = None
        if not self._stop_event.is_set() and returncode != 0:
            raise RuntimeError(f"ffmpegが異常終了しました(code={returncode})")

    def _evaluate_bitrate_adjustment(self) -> None:
        if self._config is None or not self._config.dynamic_bitrate_enabled:
            return

        speed = self._monitor.snapshot().get("speed", 1.0)
        if speed < 0.98:
            self._bad_streak += 1
            self._good_streak = 0
        else:
            self._good_streak += 1
            self._bad_streak = 0

        if (
            self._bad_streak >= self._config.degrade_streak_threshold
            and self._profile_index < len(DEGRADE_ORDER) - 1
        ):
            self._profile_index += 1
            add_log(
                "warning",
                f"帯域悪化を検知したためエンコード設定を切り替えます: {DEGRADE_ORDER[self._profile_index].name}",
            )
            self._terminate_process()  # 再起動は_supervisor_loopが検知して行う
        elif self._good_streak >= self._config.recover_streak_threshold and self._profile_index > 0:
            self._profile_index -= 1
            add_log(
                "info",
                f"帯域が回復したためエンコード設定を戻します: {DEGRADE_ORDER[self._profile_index].name}",
            )
            self._terminate_process()

    def _terminate_process(self) -> None:
        if self._process is None:
            return
        try:
            self._process.terminate()
            self._process.wait(timeout=5)
        except Exception:
            try:
                self._process.kill()
            except Exception:
                pass
