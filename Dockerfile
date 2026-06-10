FROM python:3.12-slim

# 安装 cron、时区数据、nginx
RUN apt-get update \
    && apt-get install -y --no-install-recommends cron tzdata nginx \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Shanghai \
    SSQ_PUBLIC_DATA_DIR=/usr/share/nginx/html/data \
    SSQ_PRIVATE_DATA_DIR=/app/private \
    SSQ_API_HOST=127.0.0.1 \
    SSQ_API_PORT=8000

WORKDIR /app

# 静态页面烤进镜像
COPY index.html styles.css app.js /usr/share/nginx/html/
COPY data/ssq-history.js data/ssq-history.json /usr/share/nginx/html/data/
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 抓取、中奖核验、购买记录 API 与定时任务
COPY fetch_history.py /app/fetch_history.py
COPY check_winnings.py /app/check_winnings.py
COPY purchase_api.py /app/purchase_api.py
COPY data/purchases.json data/check-results.json /app/private/
COPY crontab /etc/cron.d/ssq-fetch
COPY entrypoint.sh /app/entrypoint.sh

# data 目录软链到 nginx 站点目录：fetcher 写入即被 nginx 直接服务；购买记录保留在 /app/private
RUN rm -f /etc/nginx/sites-enabled/default \
    && mkdir -p /usr/share/nginx/html/data /app/private \
    && ln -s /usr/share/nginx/html/data /app/data \
    && chmod 0644 /etc/cron.d/ssq-fetch \
    && chmod +x /app/entrypoint.sh \
    && touch /var/log/fetch.log /var/log/api.log

EXPOSE 80

ENTRYPOINT ["/app/entrypoint.sh"]
