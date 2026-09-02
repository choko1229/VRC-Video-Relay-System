#!/bin/sh
set -e

# APP_PORT未設定時は8000(Pterodactyl等、環境ごとに異なるポート割り当てに追従できるようにする)
APP_PORT="${APP_PORT:-8000}"

uv run alembic upgrade head

# CLOUDFLARE_TUNNEL_TOKENが設定されていれば、Web管理パネル/APIを公開するためcloudflaredを
# バックグラウンドで同時起動する(Pterodactylは1エッグ1プロセス想定のため、別コンテナに
# 分けず同梱する)。未設定ならスキップし、ポート開放前提の別経路で公開する。
if [ -n "$CLOUDFLARE_TUNNEL_TOKEN" ]; then
    cloudflared tunnel run --token "$CLOUDFLARE_TUNNEL_TOKEN" &
fi

exec uv run uvicorn app.main:app --host 0.0.0.0 --port "$APP_PORT"
