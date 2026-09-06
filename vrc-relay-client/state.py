"""アプリ全体で共有するシングルトン(ローカルMediaMTX管理・中継クライアント・帯域監視)。

main.py起動時に一度だけ生成され、各api/*ルーターから参照される。
"""

from core.mediamtx_manager import MediaMTXManager
from core.network_monitor import NetworkMonitor
from core.obs_manager import ObsManager
from core.relay_client import RelayClient

network_monitor = NetworkMonitor()
mediamtx_manager = MediaMTXManager()
relay_client = RelayClient(network_monitor)
obs_manager = ObsManager()

# ローカルFastAPIは127.0.0.1限定でリッスンする(外部からのアクセス不可)。
# Discord OAuthのredirect_uriリレー先(/oauth/callback)としても使う。
LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 47821

CONFIG_KEY_PUBLIC_SERVER_URL = "public_server_url"
# 公開サーバーは固定運用のため、ログイン画面ではURL入力を求めずこの値を使う。
PUBLIC_SERVER_URL = "https://vrc-lr.choko1229.net"
CONFIG_KEY_PUSH_URL = "cached_push_url"
CONFIG_KEY_PLAYBACK_URL = "cached_playback_url"
# RTSPSが映らない場合の非暗号フォールバック(rtspt、ポート省略のことが多い)。
# ダッシュボードでは「映らないときは？」の中にのみ表示し、デフォルトのURLとしては使わない。
CONFIG_KEY_PLAYBACK_URL_FALLBACK = "cached_playback_url_fallback"
CONFIG_KEY_THEME = "theme_preference"

RELAY_SETTING_DYNAMIC_BITRATE = "dynamic_bitrate_enabled"
RELAY_SETTING_AUTO_RECONNECT = "auto_reconnect_enabled"
RELAY_SETTING_DEGRADE_THRESHOLD = "degrade_streak_threshold"
RELAY_SETTING_RECOVER_THRESHOLD = "recover_streak_threshold"

CONFIG_KEY_OBS_SELECTED_PROFILE = "obs_selected_profile"
