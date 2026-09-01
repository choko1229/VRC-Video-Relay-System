import logging
import subprocess
import threading
from pathlib import Path

from db.models import add_log

logger = logging.getLogger(__name__)

MEDIAMTX_DIR = Path(__file__).resolve().parent.parent / "mediamtx"
MEDIAMTX_EXE = MEDIAMTX_DIR / "mediamtx.exe"
MEDIAMTX_CONFIG = MEDIAMTX_DIR / "mediamtx.yml"

# OBSの配信先(このアプリのローカルMediaMTXが受け付けるパス)
LOCAL_RTMP_URL = "rtmp://127.0.0.1:1935/obs_local"


class MediaMTXManager:
    """ローカルMediaMTX(OBSからのRTMP受信用)のプロセス起動・停止・監視。"""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._log_thread: threading.Thread | None = None
        self._obs_connected = False

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def is_obs_connected(self) -> bool:
        return self._obs_connected

    def start(self) -> None:
        if self.is_running():
            return
        if not MEDIAMTX_EXE.exists():
            raise FileNotFoundError(
                f"mediamtx.exeが見つかりません: {MEDIAMTX_EXE}。"
                "配布物に同梱するか、mediamtxディレクトリに配置してください。"
            )

        logger.info("ローカルMediaMTXを起動します")
        self._process = subprocess.Popen(
            [str(MEDIAMTX_EXE), str(MEDIAMTX_CONFIG)],
            cwd=str(MEDIAMTX_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._obs_connected = False
        self._log_thread = threading.Thread(target=self._pump_logs, daemon=True)
        self._log_thread.start()
        add_log("info", "ローカルMediaMTXを起動しました")

    def stop(self) -> None:
        if not self.is_running():
            return
        logger.info("ローカルMediaMTXを停止します")
        self._process.terminate()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
        self._process = None
        self._obs_connected = False
        add_log("info", "ローカルMediaMTXを停止しました")

    def _pump_logs(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        for line in self._process.stdout:
            line = line.strip()
            if not line:
                continue
            # OBS(publisher)がobs_localパスに接続/切断したかをログから検出する
            if "obs_local" in line and "is publishing" in line:
                self._obs_connected = True
                add_log("info", "OBSからの映像受信を開始しました")
            elif "obs_local" in line and ("destroyed" in line or "closed" in line):
                self._obs_connected = False
                add_log("info", "OBSからの映像受信が終了しました")
            logger.debug("[mediamtx] %s", line)
