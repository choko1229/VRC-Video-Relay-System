import threading
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class RelayStats:
    bitrate_kbps: float = 0.0
    fps: float = 0.0
    speed: float = 0.0
    dropped_frames: int = 0
    updated_at: float = field(default_factory=time.time)


class NetworkMonitor:
    """relay_client(ffmpeg)の`-progress pipe:1`出力をパースし、帯域・品質を保持する。

    ffmpegの-progressは `key=value` 形式の行を1フレーム分ごとに出力し、
    `progress=continue` または `progress=end` で1区切りとなる。
    """

    def __init__(self, history_size: int = 60) -> None:
        self._lock = threading.Lock()
        self._current = RelayStats()
        self._pending: dict[str, str] = {}
        self._history: deque[RelayStats] = deque(maxlen=history_size)

    def feed_line(self, line: str) -> None:
        line = line.strip()
        if not line or "=" not in line:
            return
        key, _, value = line.partition("=")
        self._pending[key] = value

        if key == "progress":
            self._commit()

    def _commit(self) -> None:
        stats = RelayStats(
            bitrate_kbps=_parse_bitrate_kbps(self._pending.get("bitrate", "0kbits/s")),
            fps=_parse_float(self._pending.get("fps", "0")),
            speed=_parse_speed(self._pending.get("speed", "0x")),
            dropped_frames=_parse_int(self._pending.get("drop_frames", "0")),
            updated_at=time.time(),
        )
        with self._lock:
            self._current = stats
            self._history.append(stats)
        self._pending = {}

    def reset(self) -> None:
        with self._lock:
            self._current = RelayStats()
            self._history.clear()

    def snapshot(self) -> dict:
        with self._lock:
            current = self._current
            history = list(self._history)
        return {
            "bitrate_kbps": current.bitrate_kbps,
            "fps": current.fps,
            "speed": current.speed,
            "dropped_frames": current.dropped_frames,
            "updated_at": current.updated_at,
            "history": [h.bitrate_kbps for h in history],
        }


def _parse_float(raw: str) -> float:
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _parse_int(raw: str) -> int:
    try:
        return int(raw)
    except ValueError:
        return 0


def _parse_bitrate_kbps(raw: str) -> float:
    # 例: "1234.5kbits/s" / "N/A"
    raw = raw.strip().lower().replace("kbits/s", "")
    return _parse_float(raw)


def _parse_speed(raw: str) -> float:
    # 例: "1.02x"
    return _parse_float(raw.strip().lower().replace("x", ""))
