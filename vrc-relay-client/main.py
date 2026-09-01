import logging
import threading

import uvicorn
import webview

from app import app
from db.models import init_db, purge_old_logs
from state import mediamtx_manager, relay_client

logger = logging.getLogger(__name__)

# ローカルFastAPIは127.0.0.1限定でリッスンする(外部からのアクセス不可)
LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 47821


def _run_server() -> uvicorn.Server:
    config = uvicorn.Config(app, host=LOCAL_HOST, port=LOCAL_PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server


def _shutdown(server: uvicorn.Server) -> None:
    logger.info("アプリを終了します。中継・ローカルMediaMTXを停止します。")
    if relay_client.is_running():
        relay_client.stop()
    if mediamtx_manager.is_running():
        mediamtx_manager.stop()
    server.should_exit = True


def main() -> None:
    init_db()
    purge_old_logs()

    server = _run_server()

    window = webview.create_window(
        "VRC配信中継クライアント",
        f"http://{LOCAL_HOST}:{LOCAL_PORT}/",
        width=480,
        height=780,
        min_size=(400, 600),
    )
    window.events.closed += lambda: _shutdown(server)

    webview.start()


if __name__ == "__main__":
    main()
