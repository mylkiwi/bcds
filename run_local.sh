#!/bin/sh
set -eu

if [ -f ./.env ]; then
  set -a
  . ./.env
  set +a
fi

: "${SSQ_ADMIN_TOKEN:?请在 .env 配置 SSQ_ADMIN_TOKEN}"
: "${DEEPSEEK_API_KEY:?请在 .env 配置新的 DEEPSEEK_API_KEY}"

: "${SSQ_API_HOST:=127.0.0.1}"
: "${SSQ_API_PORT:=8000}"
export SSQ_API_HOST SSQ_API_PORT

exec python3 purchase_api.py
