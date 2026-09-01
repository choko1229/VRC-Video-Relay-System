"""アプリ全体で共有するシングルトン(ローカルMediaMTX管理・中継クライアント・帯域監視)。

main.py起動時に一度だけ生成され、各api/*ルーターから参照される。
"""

from core.mediamtx_manager import MediaMTXManager
from core.network_monitor import NetworkMonitor
from core.relay_client import RelayClient

network_monitor = NetworkMonitor()
mediamtx_manager = MediaMTXManager()
relay_client = RelayClient(network_monitor)

CONFIG_KEY_PUBLIC_SERVER_URL = "public_server_url"
CONFIG_KEY_PUSH_URL = "cached_push_url"
CONFIG_KEY_PLAYBACK_URL = "cached_playback_url"
CONFIG_KEY_THEME = "theme_preference"

RELAY_SETTING_DYNAMIC_BITRATE = "dynamic_bitrate_enabled"
RELAY_SETTING_AUTO_RECONNECT = "auto_reconnect_enabled"
RELAY_SETTING_DEGRADE_THRESHOLD = "degrade_streak_threshold"
RELAY_SETTING_RECOVER_THRESHOLD = "recover_streak_threshold"
