FROM python:3.13-slim

RUN pip install --no-cache-dir uv

# cloudflared: Web管理パネル/APIをポート開放せずCloudflare Tunnelで公開するために同梱する。
# CLOUDFLARE_TUNNEL_TOKEN未設定時はdocker-entrypoint.shが起動をスキップする。
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && arch="$(dpkg --print-architecture)" \
    && curl -fsSL -o /usr/local/bin/cloudflared \
       "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${arch}" \
    && chmod +x /usr/local/bin/cloudflared \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# MediaMTX: appと同一コンテナで起動し、HTTP API(認証Webhook・配信監視)を127.0.0.1経由で
# 使う(別コンテナに分けるとAPI疎通の設定ミスが起きやすいため統合する)。公式イメージから
# バイナリだけ拝借する。
COPY --from=bluenviron/mediamtx:latest /mediamtx /usr/local/bin/mediamtx

WORKDIR /app

COPY pyproject.toml ./
RUN uv sync --no-dev

COPY . .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000

CMD ["./docker-entrypoint.sh"]
