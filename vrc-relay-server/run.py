"""Pterodactyl汎用Pythonエッグ用の起動スクリプト。

`uv run uvicorn app.main:app`相当の処理(マイグレーション→MediaMTX起動→cloudflared起動→
uvicorn起動)を`python run.py`単体で行う。エッグの{{PY_FILE}}にこのファイルを指定して使う。

DATABASE_URL未設定(初回起動、まだ/setupを完了していない)の場合はマイグレーションを
スキップし、uvicornだけを起動する(アプリ側がセットアップ画面のみを提供する)。
"""

import os
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)
sys.path.insert(0, str(BASE_DIR))

# .envに書かれた値(セットアップ画面が書き込んだDATABASE_URL/CLOUDFLARE_TUNNEL_TOKEN等)を
# 環境変数へ読み込む。既に環境変数側に値がある場合はそちらを優先する。
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env", override=False)
except ImportError:
    pass


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(BASE_DIR / "alembic.ini"))
    command.upgrade(config, "head")


MEDIAMTX_DIR = BASE_DIR / "mediamtx"


def start_mediamtx(app_port: int) -> None:
    """MediaMTXをappと同一プロセスグループで起動する(HTTP APIをlocalhost経由で使うため)。

    ライセンス上の理由でリポジトリにはバイナリを同梱していないため、
    事前に`mediamtx/mediamtx`(Linux用実行ファイル)を手動配置しておく必要がある
    (README参照)。見つからない場合はスキップし、uvicornは通常どおり起動を続ける。
    """
    binary = MEDIAMTX_DIR / "mediamtx"
    if not binary.exists():
        print(
            "mediamtx/mediamtx が見つからないため、MediaMTXの起動をスキップしました"
            "(READMEの手順に従って配置してください)。",
            flush=True,
        )
        return

    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)

    env = os.environ.copy()
    env["MTX_AUTHHTTPADDRESS"] = f"http://127.0.0.1:{app_port}/internal/mediamtx/auth"
    subprocess.Popen([str(binary), "mediamtx.yml"], cwd=str(MEDIAMTX_DIR), env=env)


def start_cloudflared() -> None:
    token = os.environ.get("CLOUDFLARE_TUNNEL_TOKEN")
    if not token:
        return

    binary = BASE_DIR / "cloudflared"
    if not binary.exists():
        machine = os.uname().machine
        arch = "arm64" if machine in ("aarch64", "arm64") else "amd64"
        url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
        urllib.request.urlretrieve(url, binary)
        binary.chmod(binary.stat().st_mode | stat.S_IEXEC)

    subprocess.Popen([str(binary), "tunnel", "run", "--token", token])


def main() -> None:
    # PterodactylはSERVER_PORTで割り当てポートを渡す
    port = int(os.environ.get("SERVER_PORT") or os.environ.get("APP_PORT") or 8000)

    if os.environ.get("DATABASE_URL"):
        run_migrations()
        start_mediamtx(port)
        start_cloudflared()
    else:
        print("DATABASE_URL未設定のため、/setup 画面のみを起動します。", flush=True)

    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
