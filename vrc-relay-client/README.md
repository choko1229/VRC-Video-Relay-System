# vrc-relay-client

VRC配信中継システムのWindowsクライアントアプリ。Python(FastAPI) + pywebview。

## セットアップ(開発)

```bash
uv sync
```

### 事前準備

- `mediamtx/`ディレクトリに`mediamtx.exe`([MediaMTX](https://github.com/bluenviron/mediamtx/releases)のWindowsビルド)を配置する
- `ffmpeg`をインストールし、PATHが通っていること(`relay_client.py`が`ffmpeg`コマンドを直接呼び出す)

### 起動

```bash
uv run python main.py
```

初回起動時はログイン画面が表示される。公開サーバーURLを入力し「Discordでログイン」を押すと、
ブラウザ側でDiscord認証が行われアプリに戻ってくる(事前に公開サーバーのWeb申請フォームで
Discordアカウントでの利用申請・管理者による承認が完了している必要がある)。

## 画面構成

- ダッシュボード(`/`): 中継サーバーON/OFF、OBS接続状態、帯域・品質、配信URLコピー、Tier2トグル
- 設定(`/settings`): 公開サーバー接続情報、Tier2詳細設定(帯域判定のしきい値)
- ログ(`/logs`): 接続ログ・エラーログ

## ローカルDB

`vrc_relay_client.db`(SQLite、リポジトリ直下に生成)。認証トークンはWindows DPAPIで暗号化して保存する
(`core/auth_client.py`)。Windows以外の環境で開発する場合はDPAPIが利用できないためBase64エンコードに
フォールバックする(本番のWindows環境では発生しない)。

## 配布(PyInstaller)

```bash
uv sync
uv run pyinstaller --noconfirm vrc-relay-client.spec
```

`dist/vrc-relay-client/`に実行ファイル一式が生成される(`vrc-relay-client.exe`起動で
ローカルFastAPI+pywebviewウィンドウが立ち上がることを確認済み)。配布前に
`dist/vrc-relay-client/_internal/mediamtx/`へ`mediamtx.exe`を配置すること
(ライセンスの都合上ビルド成果物には含めていない)。
