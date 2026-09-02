# vrc-relay-server

VRC配信中継システムの公開サーバー。FastAPI + MySQL + MediaMTX。
Web管理パネル/APIはポート開放せずCloudflare Tunnelで公開する構成。

## セットアップ

`.env`に必要なのは`APP_PORT`のみ。DB接続・秘密鍵・管理者アカウント・公開URL等は
初回起動後にブラウザで`/setup`を開いて設定する(保存すると自動で`.env`に書き込まれ、
プロセス再起動なしでその場から使えるようになる。Cloudflare Tunnelの反映のみ再起動が必要)。

```bash
uv sync
cp .env.example .env
uv run uvicorn app.main:app --reload
```

起動したら `http://127.0.0.1:8000/setup` を開き、DB接続情報(ホスト/ポート/ユーザー名/
パスワード/DB名を個別入力。記号を含むパスワードもそのまま入力してよい、URLの組み立ては
サーバー側で行う)・管理者アカウント・MediaMTX API・公開URL等を入力する。保存時に実際に
DBへ接続確認してから`.env`に書き込むため、接続情報の書式ミスはその場でエラー表示される。

## Docker Composeでの起動(本番相当)

```bash
cp .env.example .env
# .envはAPP_PORTだけ確認すればよい(他は起動後に/setupで設定する)

mkdir -p certs
# certsディレクトリに server.crt / server.key を配置する(RTSPS用。本番はCA発行証明書を推奨)

docker compose up -d --build
```

起動後、`https://<Cloudflare Tunnelのドメイン>/setup`(またはポートを直接開けている場合は
`http://<host>:<APP_PORT>/setup`)を開いて初期設定を行う。

### 公開の仕組み(2ドメイン構成)

Web管理パネル/APIとストリーム(RTMP/RTSPS)は別ドメインで公開する想定。

| 用途 | 公開方法 | ポート | 例 |
|---|---|---|---|
| Web管理パネル・API・申請フォーム | Cloudflare Tunnel(ポート開放不要) | なし | `https://vrc-lr.choko1229.net` |
| MediaMTX RTMP(配信主中継からのpush受信) | 直接ポート公開 | 1935 | `vrc-lr.chok.ooo:1935` |
| MediaMTX RTSPS(VRChat再生用) | 直接ポート公開 | 8322 | `vrc-lr.chok.ooo:8322` |

Cloudflare Tunnelは[Zero Trustダッシュボード](https://one.dash.cloudflare.com/)でトンネルを作成し、
発行されたトークンを`/setup`画面の「Cloudflare Tunnelトークン」に入力する(反映にはプロセスの
再起動が必要)。トンネルのpublic hostname(`vrc-lr.choko1229.net`)のServiceは
`http://app:${APP_PORT}`(`APP_PORT`のデフォルトは8000)を指すようダッシュボード側で設定すること。
RTMP/RTSPSはHTTPではないためTunnelを経由できず、`vrc-lr.chok.ooo`は通常のDNS(AまたはCNAME、
Cloudflare管理下なら「DNSのみ」でプロキシしない設定)でサーバーに直接向ける。

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

DB接続情報を含め、`APP_PORT`以外は`/setup`画面から設定する(エッグの環境変数として
直接渡す必要はない)。ただしモノレポ全体をクローンするエッグでは、書き込み先の
`.env`が`vrc-relay-server/.env`になる点に注意(リポジトリ直下にも動作確認用の橋渡しは
用意していないので、`/setup`はそのまま使える。パスの問題が起きるのは`{{PY_FILE}}`側のみ)。

### appエッグをカスタムDockerイメージではなく汎用Pythonエッグで動かす場合

`Dockerfile`を使わず、Pterodactylの汎用Pythonエッグ(`{{PY_FILE}}` / `{{REQUIREMENTS_FILE}}`を
`pip install`してから`python {{PY_FILE}}`するタイプ)で動かすこともできる。この場合:

- `{{REQUIREMENTS_FILE}}` → `requirements.txt`(`uv export --format requirements-txt --no-dev --no-hashes -o requirements.txt`で生成済み。依存関係を変更したら再生成すること)
- `{{PY_FILE}}` → `run.py`(マイグレーション実行→cloudflared起動→uvicorn起動を`uv`無しでも行えるようにしたスクリプト。`DATABASE_URL`未設定時はマイグレーションをスキップし、`/setup`のみを提供する)
- ポートはPterodactylが渡す`SERVER_PORT`環境変数を`run.py`が自動で読む
- モノレポ全体をクローンする場合、`{{PY_FILE}}`は`vrc-relay-server/run.py`、
  `{{REQUIREMENTS_FILE}}`は`vrc-relay-server/requirements.txt`を指定する
  (エッグ変数がサブディレクトリのパスを受け付けない場合は、リポジトリ直下の
  `run.py`/`requirements.txt`がそちらへ橋渡しするのでデフォルト値のままでよい)

## マイグレーション

```bash
uv run alembic revision -m "説明" --autogenerate
uv run alembic upgrade head
```

`/setup`完了時にもマイグレーションは自動実行される。手動での`alembic upgrade head`は
スキーマ変更を追加した際の開発時のみ必要。

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
