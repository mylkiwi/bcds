# 双色球策略选号工具

本工具由静态前端和 Python 本地服务组成。前端负责走势图、策略选号、复式/胆拖覆盖与购买记录；Python 负责更新开奖、核奖、保存私有数据，并在服务端调用 DeepSeek。

生产环境地址：https://ssq.iphonex.plus

## 使用

```bash
python3 fetch_history.py --months 6
```

本地需要使用 DeepSeek AI 时，填写 `.env` 后运行一体化服务：

```bash
./run_local.sh
```

再打开 `http://127.0.0.1:8000`。页面、历史数据和 `/api/ai/*` 使用同一来源，AI 请求由 Python 服务端携带密钥调用真实 DeepSeek API。只查看静态页面时仍可直接打开 `index.html`，但 AI 和购买记录接口不可用。

## Docker 部署

镜像是一体化的：内置 nginx 提供静态页面、cron 定时抓取、容器启动时先后台抓取一次。容器跑起来后访问 `http://<服务器IP>:8081`（映射到容器 80 端口）。

提供三种运行方式。

首次运行先创建本地环境配置：

```bash
cp .env.example .env
```

填写 `SSQ_ADMIN_TOKEN`、Bark 配置和新生成的 `DEEPSEEK_API_KEY`。`.env` 已被 Git 忽略；不要把真实密钥写入 HTML、JavaScript、Compose 文件或提交记录。

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

双色球每个合法单式组合的开奖概率相同。历史频次、遗漏、冷热、连号和票面形态只能用于描述、筛选或分散组合，不能证明下一期更容易开出。复式、胆拖和多蓝球通过增加不同投注注数提高覆盖概率，同时也会增加成本。

## 策略与生成

- 官方机选模拟：红球从 1-33 不重复抽取，蓝球从 1-16 抽取，不使用历史信号。开启形态过滤后，本工具会额外剔除三区缺失、奇偶或大小极端票面；这属于本地过滤，不是官方公开算法。
- 概率机选（可过滤）与纯随机：主方案从均匀底池抽取。开启形态或大众号码过滤后采用拒绝采样，输出不再是所有合法组合严格均匀；备选方案还会经过通用质量排序。
- 本地综合研究：把历史走势、遗漏周期、冷热转换、概率模型、弱特征和随机模拟合成为解释性评分，不调用外部模型。
- 本地热号、遗漏、冷号和冷热混合：在综合评分基础上小幅提高对应分量，不代表这些方向具有稳定预测优势。

本地综合评分权重：

- 历史走势：20%
- 遗漏周期：20%
- 冷热转换：15%
- 概率模型：15%
- 机器学习弱特征：20%
- 随机模拟：10%

这里的“机器学习”是小样本手工弱特征集成，不是经过独立样本验证的中奖预测模型。

候选组合质量权重：

- 形态质量：36%
- 大众票面风险：22%
- 历史规则：18%
- 蓝球覆盖：10%
- 组间分散：14%

组合形态过滤会检查奇偶、大小区、三区分布、和值和连号。大众票面风险基于全在 1-31、长连号、同尾过多等规则估计，没有真实投注分布作为依据，只用于尝试降低潜在分奖风险，不改变中奖概率。低重叠组合池把“组间最大重号”作为硬约束；条件无法满足时会少生成几组，而不会静默突破上限。

页面每次点击“本地生成”都会从浏览器安全随机源取得新熵，因此相同设置也会生成新方案。本地综合评分和随机模拟不会调用外部大模型。

## 回测与走势

大样本策略研究按 30、50、100 期窗口滚动执行，每一期只使用此前数据，比较红球热号、遗漏、冷号、弱信号、上期重号以及蓝球 Top4 的后续命中表现。表格展示样本数、平均命中、中位数和 90 分位；它验证的是历史标签是否偏离随机期望，不是完整投注收益回测。现有结果不支持历史信号具有稳定预测优势。

热度与遗漏面板跟随所选统计范围；最近开奖走势图最多展示 80 期，包括红球点位、蓝球连线和逐期号码表。

## DeepSeek AI 历史研究

点击顶部“AI 分析生成”后，DeepSeek 使用当前统计范围、策略方向和投注方式执行以下链路：

1. Python 服务端读取真实开奖数据，计算所选范围的号码频次、近 5/10/20/30/50 期统计、遗漏、最近走势，以及奇偶、大小、三区、和值和连号的历史分布。
2. 服务端按 30、50 期窗口滚动回测热号、遗漏、冷号、上期重号和蓝球 Top4，并给出随机期望基线。
3. 第一次 DeepSeek 调用会先核对页面选择的策略方向是否得到回测支持，再从奇偶、大小、三区、和值、连号这组可校验规则类型中自行选择本期实际启用的规则；没有被选中的类型不会成为隐藏约束。每条规则都必须引用服务端提供的证据标识，并以每组实际 6 红单注为口径，不能把单期开奖形态直接套到更大的红球池。
4. 第二次 DeepSeek 调用只能依据已冻结的规则生成号码和逐号定性理由。单式固定返回 6+1，复式按 `C(红球池, 6)` 检查全部展开组合，胆拖只检查“胆码全选、拖码补足 6 红”的合法组合；服务端逐组校验数量、范围、不重复、胆拖互斥和本期实际启用的规则。
5. AI 号码直接成为页面上方的主推荐，复用注数、成本、复制和“填入当前推荐”流程，不再维护另一套独立推荐。
6. 页面先创建后台 AI 任务，再用短请求查询进度和结果；成功报告写入 SQLite，任务内存被清理或页面刷新后仍可从历史记录恢复。

服务端固定的只有玩法合法性和可校验规则语法，不固定本期必须使用哪类形态规则。两阶段调用能固定“先分析、后选号”的接口顺序，但历史统计和回测仍只能解释过去，不能证明下一期更容易开出。

AI 接口复用 `SSQ_ADMIN_TOKEN` 鉴权，并设置单请求互斥、最短调用间隔、每日额度、64KB 请求上限和上游超时。默认使用 `deepseek-v4-flash`，可通过环境变量调整：

```text
DEEPSEEK_API_KEY=服务端密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_DAILY_LIMIT=50
DEEPSEEK_MIN_INTERVAL=2
```

AI 的职责是综合阅读历史报告并给出结构合理、可解释的研究组合。它不能改变随机开奖概率，也不能把回测中的历史偏差当成下一期预测优势。核奖结果仍完全由本地代码和实际开奖号码决定。

## 后台核奖和 Bark 推送

服务器部署后，已购彩票记录保存在容器私有目录：

```text
/app/private/purchases.json
/app/private/check-results.json
/app/private/ssq.sqlite3              # AI 分析历史
```

Compose 使用命名卷 `ssq-private` 挂载 `/app/private`，更新镜像或重建容器不会删除购买记录和 AI 分析历史。

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
GET    /api/ai/status
GET    /api/ai/recommendations
GET    /api/ai/recommendations/latest
GET    /api/ai/recommendations/:id
POST   /api/ai/tasks
GET    /api/ai/tasks/:task_id
POST   /api/purchases
POST   /api/ai/recommendation       # 保留的同步兼容接口
DELETE /api/purchases/:id
DELETE /api/ai/recommendations/:id
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
