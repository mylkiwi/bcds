# 双色球策略选号工具

本工具是纯前端页面加一个手动更新数据的 Python 脚本。前端负责走势图、策略选号、复式/胆拖展开概率；Python 负责抓取历史开奖并生成 `data/ssq-history.js`。

生产环境地址：https://ssq.iphonex.plus

## 使用

```bash
python3 fetch_history.py --start 2026001 --end 2026064
```

然后直接打开 `index.html`。

也可以用本地服务器访问：

```bash
python3 -m http.server 8080
```

再打开 `http://localhost:8080`。

## Docker 部署

镜像是一体化的：内置 nginx 提供静态页面、cron 定时抓取、容器启动时先后台抓取一次。容器跑起来后访问 `http://<服务器IP>:8081`（映射到容器 80 端口）。

提供三种运行方式。

### 方式 1：本地构建镜像，再运行镜像

不依赖 compose，纯 `docker` 命令：

```bash
# 构建本地镜像
docker build -t ssq:local .

# 运行
docker run -d --name ssq -p 8081:80 -e TZ=Asia/Shanghai --restart unless-stopped ssq:local
```

### 方式 2：Docker Compose 构建并运行本地镜像

`docker-compose.yml` 已配置 `build: .`，会用当前目录的 Dockerfile 构建本地镜像（标签 `ssq:local`）：

```bash
docker compose up -d --build
```

改了代码或 `Dockerfile` 后重新执行同一条命令即可重建。

### 方式 3：生产环境用 docker-compose.prod.yml

`docker-compose.prod.yml` 直接拉取已发布的镜像，无需本地构建：

```bash
docker compose -f docker-compose.prod.yml up -d
```

### 定时抓取

容器内置 cron，**每周二、四、日 22:00（北京时间）**自动运行：

```bash
python3 fetch_history.py --months 6
```

抓取最近 6 个月的滚动窗口数据并刷新 `data/ssq-history.js`。开奖时间约 21:15，官网公布有延迟，定到 22:00 以稳定抓到当天最新一期。容器启动时也会先在后台抓取一次（不阻塞页面启动）。

修改抓取时间编辑 `crontab` 后重建容器（方式 1 重新 `build`+`run`，方式 2/3 重新 `up`）。

### 常用命令

```bash
# 查看抓取日志（compose）
docker compose logs -f app
# 或纯 docker
docker logs -f ssq

# 手动立即抓取一次
docker compose exec app python3 fetch_history.py --months 6
docker exec ssq python3 fetch_history.py --months 6

# 确认时区
docker compose exec app date

# 停止
docker compose down                              # 方式 2
docker compose -f docker-compose.prod.yml down   # 方式 3
docker rm -f ssq                                 # 方式 1
```

## 口径

双色球是随机开奖。工具能提升的是复式、胆拖、多蓝球带来的覆盖概率，并不能预测下一期开奖号码。

## 推荐机制

前端会先按策略给每个号码打分，再多轮生成候选组合，最后按覆盖分散、形态质量、分奖风险、蓝球覆盖、历史走势的综合权重选出方案。

当前权重：

- 覆盖分散度：40%
- 组合形态质量：25%
- 分奖风险控制：15%
- 蓝球覆盖策略：10%
- 历史热/冷/遗漏：10%

- 均衡覆盖：综合历史频次、近 20 期频次、遗漏和随机扰动。
- 热号偏向：提高历史高频和近期高频权重。
- 遗漏回补：提高长时间未出号码权重。
- 冷号逆向：提高低频和长遗漏号码权重。
- 冷热混合：热号、遗漏和随机扰动混合。
- 纯随机：不使用走势权重，只保留基础形态过滤。

组合形态过滤会检查奇偶、大小区、三区分布、和值、连号。避开大众号码会降低生日号集中、长连号、同尾号过多、上期重号过多、全奇/全偶、全大/全小组合的权重。

低重叠组合池会按同一策略生成多组备选，并限制组间红球重复数量，适合多组投注时减少重复覆盖。
