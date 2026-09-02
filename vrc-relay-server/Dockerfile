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

WORKDIR /app

COPY pyproject.toml ./
RUN uv sync --no-dev

COPY . .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000

CMD ["./docker-entrypoint.sh"]
