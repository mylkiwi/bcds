#!/bin/sh
set -e

# 设置容器时区（默认北京时间），保证 cron 的 22:00 是本地时间
: "${TZ:=Asia/Shanghai}"
if [ -f "/usr/share/zoneinfo/$TZ" ]; then
    ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime
    echo "$TZ" > /etc/timezone
fi
echo "时区: $(date)"

write_env_var() {
    name="$1"
    value="$(printenv "$name" | sed "s/'/'\\\\''/g")"
    printf "export %s='%s'\n" "$name" "$value"
}

: "${SSQ_PUBLIC_DATA_DIR:=/usr/share/nginx/html/data}"
: "${SSQ_PRIVATE_DATA_DIR:=/app/private}"
: "${SSQ_API_HOST:=127.0.0.1}"
: "${SSQ_API_PORT:=8000}"
export SSQ_PUBLIC_DATA_DIR SSQ_PRIVATE_DATA_DIR SSQ_API_HOST SSQ_API_PORT

mkdir -p "$SSQ_PUBLIC_DATA_DIR" "$SSQ_PRIVATE_DATA_DIR"
[ -f "$SSQ_PRIVATE_DATA_DIR/purchases.json" ] || echo "[]" > "$SSQ_PRIVATE_DATA_DIR/purchases.json"
[ -f "$SSQ_PRIVATE_DATA_DIR/check-results.json" ] || echo "[]" > "$SSQ_PRIVATE_DATA_DIR/check-results.json"

{
    write_env_var TZ
    write_env_var BARK_KEY
    write_env_var BARK_SOUND
    write_env_var SSQ_PUBLIC_DATA_DIR
    write_env_var SSQ_PRIVATE_DATA_DIR
    write_env_var SSQ_API_HOST
    write_env_var SSQ_API_PORT
    write_env_var SSQ_ADMIN_TOKEN
} > /app/runtime.env
chmod 600 /app/runtime.env

echo "启动购买记录 API..."
/usr/local/bin/python3 /app/purchase_api.py >> /var/log/api.log 2>&1 &

# 容器启动时在后台抓取并核验一次，保证数据和中奖结果尽量最新
echo "后台抓取最近 6 个月数据并核验已购彩票..."
(
    cd /app
    . /app/runtime.env
    /usr/local/bin/python3 fetch_history.py --months 6 >> /var/log/fetch.log 2>&1 || \
        echo "启动抓取失败，继续尝试核验已有数据" >> /var/log/fetch.log
    /usr/local/bin/python3 check_winnings.py >> /var/log/fetch.log 2>&1 || \
        echo "启动核验失败，等待下次定时任务" >> /var/log/fetch.log
) &

# 启动 cron（后台），定时任务：每周二/四/日 22:00 抓取并核验
echo "启动 cron，定时任务：每周二/四/日 22:00 抓取并核验"
cron

# 把抓取/API 日志透传到容器日志（docker logs / docker compose logs）
tail -F /var/log/fetch.log /var/log/api.log &

# 启动 nginx 前台，保持容器存活
echo "启动 nginx..."
exec nginx -g 'daemon off;'
