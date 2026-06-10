#!/bin/sh
set -e

# 设置容器时区（默认北京时间），保证 cron 的 22:00 是本地时间
: "${TZ:=Asia/Shanghai}"
if [ -f "/usr/share/zoneinfo/$TZ" ]; then
    ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime
    echo "$TZ" > /etc/timezone
fi
echo "时区: $(date)"

# 容器启动时在后台抓取并核验一次，保证数据和中奖结果尽量最新
echo "后台抓取最近 6 个月数据并核验已购彩票..."
(
    cd /app
    /usr/local/bin/python3 fetch_history.py --months 6 >> /var/log/fetch.log 2>&1 || \
        echo "启动抓取失败，继续尝试核验已有数据" >> /var/log/fetch.log
    /usr/local/bin/python3 check_winnings.py >> /var/log/fetch.log 2>&1 || \
        echo "启动核验失败，等待下次定时任务" >> /var/log/fetch.log
) &

# 启动 cron（后台），定时任务：每周二/四/日 22:00 抓取并核验
echo "启动 cron，定时任务：每周二/四/日 22:00 抓取并核验"
cron

# 把抓取日志透传到容器日志（docker logs / docker compose logs）
tail -F /var/log/fetch.log &

# 启动 nginx 前台，保持容器存活
echo "启动 nginx..."
exec nginx -g 'daemon off;'
