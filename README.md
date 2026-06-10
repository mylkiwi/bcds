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
python3 check_winnings.py
```

抓取最近 6 个月的滚动窗口数据并刷新公开历史数据，随后核验私有购买记录，中奖时通过 Bark 推送。开奖时间约 21:15，官网公布有延迟，定到 22:00 以稳定抓到当天最新一期。容器启动时也会先在后台抓取并核验一次（不阻塞页面启动）。

容器同时启动一个本地购买记录 API，nginx 通过 `/api/` 反向代理给它。前端页面里的「购买记录」面板会调用这些接口。

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

前端会先按策略给每个号码打分，再多轮生成候选组合，最后按逐期反推规则、覆盖分散、形态质量、分奖风险和蓝球覆盖综合选出方案。

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

低重叠组合池会按同一策略生成多组备选，并限制组间红球重复数量，适合多组投注时减少重复覆盖。蓝球策略会降低上期刚开蓝球的权重，并在多组方案之间尽量分散蓝球覆盖。

逐期反推规则来自滚动历史对比：红球优先靠近 1-2 个前 30 期高频号、1-2 个久未出号、1-2 个上期附近号；蓝球优先一热一漏/一热一普通，并降低上期刚开蓝球。

## 后台核奖和 Bark 推送

服务器部署后，已购彩票记录保存在容器私有目录：

```text
/app/private/purchases.json
/app/private/check-results.json
```

公开给前端读取的只有历史开奖：

```text
/usr/share/nginx/html/data/ssq-history.js
/usr/share/nginx/html/data/ssq-history.json
```

前端交互接口：

```text
GET    /api/state
GET    /api/purchases
GET    /api/check-results
POST   /api/purchases
DELETE /api/purchases/:id
POST   /api/check-now
```

所有购买记录接口都需要管理密钥。部署环境变量：

```text
SSQ_ADMIN_TOKEN=你的管理密钥
```

页面会把你输入的管理密钥保存在浏览器 `localStorage`，请求时通过 `Authorization: Bearer <token>` 发给服务器。

普通复式记录格式：

```json
[
  {
    "id": "2026066-main",
    "issue": "2026066",
    "red": [1, 2, 10, 15, 28, 30, 33],
    "blue": [10, 16],
    "note": "6月11日主推 7+2"
  }
]
```

胆拖示例：

```json
[
  {
    "id": "2026066-dt",
    "issue": "2026066",
    "dan": [2, 30],
    "tuo": [1, 10, 15, 22, 28, 31, 33, 12],
    "blue": [10, 16],
    "note": "胆拖示例"
  }
]
```

GitHub Actions 每天更新开奖后会运行 `check_winnings.py`。Docker 容器也会在启动和每期开奖日 22:00 抓取后自动核验。如果中奖，会通过 Bark 推送。

当前部署分支的 `docker-compose.yml`、`docker-compose.prod.yml` 和 GitHub Actions 已配置 Bark 推送参数。要替换设备时，改 `BARK_KEY` 和 `BARK_SOUND` 后重新部署。

例如 Bark URL 是 `https://api.day.app/xxx/标题`，`BARK_KEY` 只填写中间的 `xxx`。
