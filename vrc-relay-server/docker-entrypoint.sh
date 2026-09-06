#!/bin/sh
set -e

# APP_PORT未設定時は8000(Pterodactyl等、環境ごとに異なるポート割り当てに追従できるようにする)
APP_PORT="${APP_PORT:-8000}"
# 非暗号フォールバック(RTSP平文)のポート。標準ポート(554)ならプレイヤー側でポートを省略できる。
PUBLIC_RTSP_PLAIN_PORT="${PUBLIC_RTSP_PLAIN_PORT:-554}"

# DATABASE_URL未設定(初回起動、まだ/setupを完了していない)ならマイグレーション・MediaMTX・
# cloudflaredをスキップし、uvicornだけを起動する(アプリ側がセットアップ画面のみを提供し、
# セットアップ完了時にマイグレーションを自前で実行する)。
if [ -n "$DATABASE_URL" ]; then
    uv run alembic upgrade head

    # MediaMTXをappと同一コンテナで起動する(HTTP API連携をlocalhost経由にするため)。
    # 認証Webhookのアドレスは実際のAPP_PORTに合わせてMTX_AUTHHTTPADDRESSで上書きする。
    # 作業ディレクトリをmediamtx/にしてから起動し、mediamtx.yml内の証明書相対パスを解決する。
    (cd mediamtx && MTX_AUTHHTTPADDRESS="http://127.0.0.1:${APP_PORT}/internal/mediamtx/auth" MTX_RTSPADDRESS=":${PUBLIC_RTSP_PLAIN_PORT}" mediamtx mediamtx.yml) &

    # CLOUDFLARE_TUNNEL_TOKENが設定されていれば、Web管理パネル/APIを公開するためcloudflared
    # をバックグラウンドで同時起動する(Pterodactylは1エッグ1プロセス想定のため、別コンテナ
    # に分けず同梱する)。未設定ならスキップし、ポート開放前提の別経路で公開する。
    if [ -n "$CLOUDFLARE_TUNNEL_TOKEN" ]; then
        cloudflared tunnel run --token "$CLOUDFLARE_TUNNEL_TOKEN" &
    fi
else
    echo "DATABASE_URL未設定のため、/setup 画面のみを起動します。"
fi

exec uv run uvicorn app.main:app --host 0.0.0.0 --port "$APP_PORT"
