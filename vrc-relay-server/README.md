# vrc-relay-server

VRC配信中継システムの公開サーバー。FastAPI + MySQL + MediaMTX + nginx。

## セットアップ(ローカル開発)

```bash
uv sync
cp .env.example .env
# .envのDATABASE_URL等をローカル環境に合わせて編集する
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

初回起動時、`.env`の`ADMIN_USERNAME`/`ADMIN_PASSWORD`で管理者アカウントが自動作成される。

## Docker Composeでの起動(本番相当)

```bash
cp .env.example .env
# .envを編集(特にJWT_SECRET_KEY, ADMIN_PASSWORD, DISCORD_BOT_TOKEN, PUBLIC_*_HOST)

mkdir -p certs
# certsディレクトリに server.crt / server.key を配置する(本番はCA発行証明書を推奨)

docker compose up -d --build
```

- 管理パネル・Web申請フォーム: `https://<host>/`
- MediaMTX RTMP(配信主中継からのpush受信): `<host>:1935`
- MediaMTX RTSPS(VRChat再生用): `<host>:8322`

## マイグレーション

```bash
uv run alembic revision -m "説明" --autogenerate
uv run alembic upgrade head
```

## 既知の環境問題(Windows開発機でのローカル実行時)

一部のWindows環境(社内プロキシ/セキュリティソフトによるTLS介入がある場合など)では、
httpxが実際のソケット通信を行うタイミングで`OPENSSL_Uplink(...): no OPENSSL_Applink`という
ネイティブクラッシュが発生することがある(Pythonの例外として捕捉できない)。
これはOpenSSLのDLL競合によるOS依存の問題であり、Dockerコンテナ(Linux)上では発生しない。
MediaMTX HTTP API連携(`/api/me/status`, `/api/admin/streams`等)やDiscord通知を伴う挙動を
Windows上で`uv run uvicorn`により素で動作確認する場合は影響を受ける可能性があるため、
その場合はDocker Composeでの起動を推奨する。

## ディレクトリ構成

仕様書(vrc-relay-system-spec.md) 3.6節を参照。
