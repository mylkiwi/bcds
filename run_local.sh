#!/bin/sh
set -eu

cd "$(dirname "$0")"

if [ -f ./.env ]; then
  set -a
  . ./.env
  set +a
fi

: "${SSQ_API_HOST:=127.0.0.1}"
: "${SSQ_API_PORT:=8000}"
export SSQ_API_HOST SSQ_API_PORT

exec python3 run_local.py
