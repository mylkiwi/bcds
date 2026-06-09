FROM python:3.12-slim

# 安装 cron、时区数据、nginx
RUN apt-get update \
    && apt-get install -y --no-install-recommends cron tzdata nginx \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Shanghai

WORKDIR /app

# 静态页面烤进镜像
COPY index.html styles.css app.js /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 抓取脚本与定时任务
COPY fetch_history.py /app/fetch_history.py
COPY crontab /etc/cron.d/ssq-fetch
COPY entrypoint.sh /app/entrypoint.sh

# data 目录软链到 nginx 站点目录：fetcher 写入即被 nginx 直接服务
RUN rm -f /etc/nginx/sites-enabled/default \
    && mkdir -p /usr/share/nginx/html/data \
    && ln -s /usr/share/nginx/html/data /app/data \
    && chmod 0644 /etc/cron.d/ssq-fetch \
    && chmod +x /app/entrypoint.sh \
    && touch /var/log/fetch.log

EXPOSE 80

ENTRYPOINT ["/app/entrypoint.sh"]
