# vrc-relay-server

VRC配信中継システムの公開サーバー。FastAPI + MySQL + MediaMTX。
Web管理パネル/APIはポート開放せずCloudflare Tunnelで公開する構成。

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
# .envを編集(特にJWT_SECRET_KEY, ADMIN_PASSWORD, DISCORD_BOT_TOKEN,
#            PUBLIC_*_HOST, CLOUDFLARE_TUNNEL_TOKEN)

mkdir -p certs
# certsディレクトリに server.crt / server.key を配置する(RTSPS用。本番はCA発行証明書を推奨)

docker compose up -d --build
```

### 公開の仕組み(2ドメイン構成)

Web管理パネル/APIとストリーム(RTMP/RTSPS)は別ドメインで公開する想定。

| 用途 | 公開方法 | ポート | 例 |
|---|---|---|---|
| Web管理パネル・API・申請フォーム | Cloudflare Tunnel(ポート開放不要) | なし | `https://vrc-lr.choko1229.net` |
| MediaMTX RTMP(配信主中継からのpush受信) | 直接ポート公開 | 1935 | `vrc-lr.chok.ooo:1935` |
| MediaMTX RTSPS(VRChat再生用) | 直接ポート公開 | 8322 | `vrc-lr.chok.ooo:8322` |

Cloudflare Tunnelは[Zero Trustダッシュボード](https://one.dash.cloudflare.com/)でトンネルを作成し、
発行されたトークンを`.env`の`CLOUDFLARE_TUNNEL_TOKEN`に設定する。トンネルのpublic hostname
(`vrc-lr.choko1229.net`)のServiceは`http://app:${APP_PORT}`(`APP_PORT`のデフォルトは8000)を
指すようダッシュボード側で設定すること。RTMP/RTSPSはHTTPではないためTunnelを経由できず、
`vrc-lr.chok.ooo`は通常のDNS(Aレコード)でサーバーのIPに向ける。

## Pterodactylでの運用

「DBホスト機能」「既存のリバースプロキシ」のどちらも前提にしないため、エッグ構成は以下。

| エッグ | 用途 | ポート割り当て |
|---|---|---|
| app | FastAPI(+ cloudflaredを同梱起動) | `APP_PORT`(割り当てに合わせて`.env`で変更) |
| mediamtx | RTMP/RTSPS受信・配信 | 1935, 8322(9997は内部専用) |
| mysql | DB | 内部専用(外部公開不要) |

cloudflaredはappコンテナのエントリポイント(`docker-entrypoint.sh`)から同時起動する
(`CLOUDFLARE_TUNNEL_TOKEN`が未設定なら起動をスキップするだけなので、別エッグ・別ホストで
公開する場合もこのイメージをそのまま使い回せる)。

### appエッグをカスタムDockerイメージではなく汎用Pythonエッグで動かす場合

`Dockerfile`を使わず、Pterodactylの汎用Pythonエッグ(`{{PY_FILE}}` / `{{REQUIREMENTS_FILE}}`を
`pip install`してから`python {{PY_FILE}}`するタイプ)で動かすこともできる。この場合:

- `{{REQUIREMENTS_FILE}}` → `requirements.txt`(`uv export --format requirements-txt --no-dev --no-hashes -o requirements.txt`で生成済み。依存関係を変更したら再生成すること)
- `{{PY_FILE}}` → `run.py`(マイグレーション実行→cloudflared起動→uvicorn起動を`uv`無しでも行えるようにしたスクリプト)
- ポートはPterodactylが渡す`SERVER_PORT`環境変数を`run.py`が自動で読む
- `DATABASE_URL`・`JWT_SECRET_KEY`等は`.env`ファイルではなく、エッグの環境変数として設定する
  (pydantic-settingsは実環境変数を優先して読むため、これで動作する)

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
