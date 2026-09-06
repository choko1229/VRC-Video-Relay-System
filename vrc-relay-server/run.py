"""Pterodactyl汎用Pythonエッグ用の起動スクリプト。

`uv run uvicorn app.main:app`相当の処理(マイグレーション→MediaMTX起動→cloudflared起動→
uvicorn起動)を`python run.py`単体で行う。エッグの{{PY_FILE}}にこのファイルを指定して使う。

DATABASE_URL未設定(初回起動、まだ/setupを完了していない)の場合はマイグレーションを
スキップし、uvicornだけを起動する(アプリ側がセットアップ画面のみを提供する)。

MediaMTXはcloudflared同様、起動のたびにGitHubの最新リリースを確認して自動取得・
自動更新する(mediamtx/mediamtxが無い、またはバージョンが古ければ取得し直す)。
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
MEDIAMTX_BINARY = MEDIAMTX_DIR / "mediamtx"
MEDIAMTX_VERSION_FILE = MEDIAMTX_DIR / ".version"


def _mediamtx_asset_suffix() -> str:
    machine = os.uname().machine
    arch = "arm64" if machine in ("aarch64", "arm64") else "amd64"
    return f"linux_{arch}.tar.gz"


def _fetch_latest_mediamtx_release() -> dict | None:
    import json

    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/bluenviron/mediamtx/releases/latest",
            headers={"User-Agent": "vrc-relay-server"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        print(f"MediaMTXの最新版情報取得に失敗しました({exc})。", flush=True)
        return None


def _download_mediamtx(asset_url: str) -> None:
    import tarfile
    import tempfile

    MEDIAMTX_DIR.mkdir(parents=True, exist_ok=True)
    # NamedTemporaryFileはWindowsだと開いたままの状態で別途urlretrieve/tarfileから
    # 再度開けない(共有違反になる)ため、mkstempでパスだけ確保してすぐ閉じる。
    fd, tmp_path = tempfile.mkstemp(suffix=".tar.gz")
    os.close(fd)
    try:
        urllib.request.urlretrieve(asset_url, tmp_path)
        with tarfile.open(tmp_path) as tar:
            tar.extract("mediamtx", path=MEDIAMTX_DIR)
    finally:
        os.remove(tmp_path)


def ensure_mediamtx_binary() -> None:
    """MediaMTXバイナリを自動取得・自動更新する。

    起動のたびにGitHubの最新リリースを確認し、導入済みのバージョン(mediamtx/.version に
    記録)と異なれば取得し直す。GitHub APIに到達できない場合や取得に失敗した場合は、
    既にバイナリがあればそれをそのまま使い続け、無ければ何もしない
    (呼び出し側のstart_mediamtxがMediaMTXの起動自体をスキップする)。
    """
    current_version = MEDIAMTX_VERSION_FILE.read_text().strip() if MEDIAMTX_VERSION_FILE.exists() else None

    release = _fetch_latest_mediamtx_release()
    if release is None:
        return

    latest_version = release.get("tag_name")
    if latest_version is None or (latest_version == current_version and MEDIAMTX_BINARY.exists()):
        return

    suffix = _mediamtx_asset_suffix()
    asset = next((a for a in release.get("assets", []) if a["name"].endswith(suffix)), None)
    if asset is None:
        print(f"MediaMTXのリリースに{suffix}が見つかりませんでした。", flush=True)
        return

    print(f"MediaMTXを更新します: {current_version or '(未導入)'} -> {latest_version}", flush=True)
    try:
        _download_mediamtx(asset["browser_download_url"])
        MEDIAMTX_VERSION_FILE.write_text(latest_version)
    except Exception:
        print("MediaMTXのダウンロードに失敗しました。既存のバイナリがあればそれを使います。", flush=True)


def start_mediamtx(app_port: int) -> None:
    """MediaMTXをappと同一プロセスグループで起動する(HTTP APIをlocalhost経由で使うため)。"""
    ensure_mediamtx_binary()

    if not MEDIAMTX_BINARY.exists():
        print(
            "mediamtxバイナリを用意できなかったため、MediaMTXの起動をスキップしました。",
            flush=True,
        )
        return

    MEDIAMTX_BINARY.chmod(MEDIAMTX_BINARY.stat().st_mode | stat.S_IEXEC)

    env = os.environ.copy()
    env["MTX_AUTHHTTPADDRESS"] = f"http://127.0.0.1:{app_port}/internal/mediamtx/auth"
    # 非暗号フォールバック(rtspAddress)のポートは環境ごとに変わりうるため、
    # PUBLIC_RTSP_PLAIN_PORT(.env、デフォルト554)に合わせて上書きする。
    plain_rtsp_port = os.environ.get("PUBLIC_RTSP_PLAIN_PORT") or "554"
    env["MTX_RTSPADDRESS"] = f":{plain_rtsp_port}"
    subprocess.Popen([str(MEDIAMTX_BINARY), "mediamtx.yml"], cwd=str(MEDIAMTX_DIR), env=env)


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
