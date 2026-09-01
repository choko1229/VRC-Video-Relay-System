# PoC: 疎通確認手順書

目的: `OBS → ローカルMediaMTX → ffmpeg中継(-c copy) → 公開サーバーMediaMTX → VRChat(RTSPS再生)`
の二段中継が実機で動作するか、遅延・安定性を含めて手動検証する。仕様書のロードマップ①に対応。

このPoCでは**認証・BAN等のセキュリティ機構は組み込みません**。疎通と体感品質の確認のみが目的です。

## 0. 事前準備

### 0.1 必要なソフトウェア
- OBS Studio (配信主PC)
- [MediaMTX](https://github.com/bluenviron/mediamtx/releases) バイナリ (配信主PC・公開サーバー役の両方に配置)
- ffmpeg (配信主PC。`winget install ffmpeg` や公式ビルドを利用)
- VRChat + RTSP/RTSPT再生に対応したワールド(ProTV等の映像プレイヤーPrefabを設置したワールド、または既存の対応ワールド)

### 0.2 公開サーバー役の用意
以下のいずれかで良い。
- **VPS/クラウドで検証する場合(推奨)**: グローバルIPを持つLinux/Windowsマシンを1台用意し、そこに`mediamtx`と`poc/public-mediamtx.yml`を配置する。ポート`1935`(RTMP)・`8322`(RTSPS)をファイアウォールで開放する。
- **同一PCで簡易確認する場合**: ポートを衝突させないよう、ローカルMediaMTXとは別ポートで2つ目のmediamtxインスタンスを起動する。ただしVRChat側からの実際のネットワーク経路(NAT越え等)は検証できないため、あくまで簡易確認用。

### 0.3 自己署名証明書の作成(公開サーバー役のマシンで実施)
RTSPS(TLS)には証明書が必要。PoCでは自己署名で良い。

```bash
openssl req -x509 -newkey rsa:2048 -nodes -keyout server.key -out server.crt -days 30 -subj "/CN=poc"
```

`server.crt` / `server.key` を `public-mediamtx.yml` と同じディレクトリに置く。

## 1. ローカルMediaMTXの起動(配信主PC)

```bash
mediamtx.exe local-mediamtx.yml
```

OBSの配信設定:
- サービス: カスタム
- サーバー: `rtmp://127.0.0.1:1935/obs_local`
- ストリームキー: 空欄で可(パスで区別しているため)

OBSで「配信開始」し、MediaMTXのログに`obs_local`へのpublishが記録されることを確認する。

## 2. 公開サーバーMediaMTXの起動(公開サーバー役マシン)

```bash
mediamtx.exe public-mediamtx.yml
```

## 3. 中継の実行(配信主PC)

```powershell
.\relay.ps1 -PublicHost "<公開サーバーのグローバルIPまたはホスト名>"
```

内部的には `ffmpeg -re -i rtmp://127.0.0.1:1935/obs_local -c copy -f flv rtmp://<public-server>:1935/live_poc` を実行している。
公開サーバー側MediaMTXのログに`live_poc`へのpublishが記録されることを確認する。

## 4. VRChat側での再生確認

ProTV等の映像プレイヤーに以下のURLを設定する。

```
rtsps://<公開サーバーのグローバルIPまたはホスト名>:8322/live_poc
```

(RTSPTでの再生指定が必要なプレイヤーの場合は、その旨の設定も併せて行う)

## 5. 検証項目

以下を記録すること。

| 項目 | 結果 |
|---|---|
| 映像が最終的にVRChat上で再生できたか | |
| OBS配信開始からVRChat再生までのエンドツーエンド遅延(概算) | |
| 数分間の連続再生で映像・音声のズレ/途切れが発生しないか | |
| relay.ps1を強制終了→再実行した場合の復帰挙動(自動再接続機能実装の参考にする) | |
| 配信主PC側・公開サーバー側それぞれのCPU/帯域使用量(概算) | |
| OBS側のビットレート設定を変えた場合の追従性(-c copyのため設定変更にはOBS再起動が必要な点の確認) | |
| VRChat側での自己署名証明書によるRTSPS接続エラーの有無(本番はCA発行証明書に切替想定) | |

## 6. 既知の注意点

- `-c copy`はストリームコピーのため、ローカル中継段階でのビットレート調整はできない。動的ビットレート調整(Tier2)は、ffmpegを一旦停止し、別のエンコード設定(`-c:v libx264`等)で再起動する方式になる想定。この挙動もあわせてPoCで手動確認しておくと後工程の設計検証になる。
- 本番の公開サーバーMediaMTXは`vrc-relay-server/mediamtx/mediamtx.yml`のとおり、パスワイルドカード(`~^live_.*$`)＋外部HTTP認証を用いる。PoCの`live_poc`固定パス・認証なし構成とは異なる点に注意。
