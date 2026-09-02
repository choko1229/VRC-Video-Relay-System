"""Pterodactyl汎用Pythonエッグ用の起動スクリプト。

`uv run uvicorn app.main:app`相当の処理(マイグレーション→cloudflared起動→uvicorn起動)を
`python run.py`単体で行う。エッグの{{PY_FILE}}にこのファイルを指定して使う。
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


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(BASE_DIR / "alembic.ini"))
    command.upgrade(config, "head")


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
    run_migrations()
    start_cloudflared()

    import uvicorn

    # PterodactylはSERVER_PORTで割り当てポートを渡す
    port = int(os.environ.get("SERVER_PORT") or os.environ.get("APP_PORT") or 8000)
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
