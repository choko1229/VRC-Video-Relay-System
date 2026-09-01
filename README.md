# VRC配信中継システム

配信主のPC上のOBSから、ローカル中継(Windowsアプリ)→公開サーバー→VRChatまで映像を配信する、
数十人規模のコミュニティ向けシステム。詳細仕様は元の要件定義書を参照。

```
OBS → ローカルMediaMTX(Windowsアプリ内) → core/relay_client.py(ffmpeg -c copy)
   → 公開サーバー MediaMTX(認証・パス管理) → VRC(ProTV等でRTSPT再生)
```

## 構成

| ディレクトリ | 内容 |
|---|---|
| [`poc/`](poc/README.md) | 二段中継の疎通確認PoC(手動検証手順書・設定ファイル) |
| [`vrc-relay-server/`](vrc-relay-server/README.md) | 公開サーバー(FastAPI + MySQL + MediaMTX + nginx) |
| [`vrc-relay-client/`](vrc-relay-client/README.md) | Windowsクライアントアプリ(FastAPI + pywebview) |

## 開発の進め方

1. まず `poc/README.md` の手順でOBS→ローカル中継→公開サーバー→VRChat再生の疎通・遅延・安定性を実機確認する。
2. 並行して `vrc-relay-server/` と `vrc-relay-client/` の基盤コードを構築している(現状: 両方ともv1スケルトン実装済み)。
3. 各サブプロジェクトの詳細セットアップ手順は、それぞれのREADMEを参照。

## 現状の実装状況(v1スケルトン)

- **vrc-relay-server**: ユーザー申請/承認/BAN、JWT認証、ストリームキー発行・ローテーション、
  MediaMTX外部HTTP認証Webhook、MediaMTX HTTP API連携(配信状況監視・強制切断)、Discord DM通知(REST API直叩き)、
  管理パネル(Jinja2+HTMX)、Docker Compose一式。ASGI経由の一連の申請→承認→ログイン→管理パネル表示を動作確認済み。
- **vrc-relay-client**: ログイン、ダッシュボード(中継ON/OFF・OBS接続状態・帯域監視・配信URLコピー・Tier2トグル)、
  設定画面、ログ画面、ローカルMediaMTX管理、ffmpeg中継(動的ビットレート調整・自動再接続)、
  DPAPIによる認証トークン暗号化保存。ASGI経由の画面遷移・DPAPI暗号化ラウンドトリップを動作確認済み。
- 両者とも実際のMediaMTXバイナリ・ffmpeg・OBS・VRChatを使った実機E2E確認はまだ行っていない
  (このマシンにはOBS/VRChat実機検証環境が別途あるとのことなので、`poc/`の手順を参照しつつ確認を進めてほしい)。

## 未決事項(要フォローアップ)

- 公開サーバーのホスティング先(帯域・負荷見積もり後に決定)
- VRC側再生互換性の詳細検証(Quest対応の要否含む)
- Windowsクライアントアプリの配布(PyInstaller化)は未着手
