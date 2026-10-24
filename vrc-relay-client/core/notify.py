"""Windowsトースト通知。

OBS設定の復元失敗など、アプリを閉じた後でもユーザーに気づいてもらう必要がある
エラーを通知するために使う。通知自体の失敗が呼び出し元の処理を止めないよう、
例外は内部で握りつぶしログにのみ残す。
"""

import logging

logger = logging.getLogger(__name__)


def show_toast(title: str, message: str) -> None:
    try:
        from winotify import Notification

        toast = Notification(app_id="VRChat Live Relay", title=title, msg=message)
        toast.show()
    except Exception:
        logger.exception("トースト通知の表示に失敗しました")
