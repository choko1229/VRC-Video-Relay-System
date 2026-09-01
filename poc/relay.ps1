# PoC用: ローカルMediaMTXが受けたOBS映像を、公開サーバーMediaMTXへ-c copyで中継するスクリプト
# core/relay_client.py が将来的にPythonから同等の処理をffmpegサブプロセスとして制御する想定。
#
# 使い方:
#   .\relay.ps1 -PublicHost "1.2.3.4"
#
# 停止: Ctrl+C

param(
    [Parameter(Mandatory = $true)]
    [string]$PublicHost,

    [int]$PublicRtmpPort = 1935,

    [string]$LocalUrl = "rtmp://127.0.0.1:1935/obs_local",

    [string]$PublicPath = "live_poc"
)

$publicUrl = "rtmp://${PublicHost}:${PublicRtmpPort}/${PublicPath}"

Write-Host "中継開始: $LocalUrl -> $publicUrl"
Write-Host "(-c copy でストリームコピー。CPU負荷は低いが、映像は元のOBS出力設定に依存します)"

ffmpeg -re -i $LocalUrl `
    -c copy `
    -f flv $publicUrl
