# AI Media Assistant — 完整使用说明文档

本文档面向真实使用场景：从你**已注册会员的 PT 站（通过 RSS 订阅）**搜索资源，
通过**部署在 NAS 上的 qBittorrent** 远程下载，数据存入**你的 MySQL 服务器**，
并通过本机的 **OpenClaw + 本地 Ollama 模型**用自然语言指挥整个流程（零 API 费用）。

> 想先快速了解架构，请看 [architecture.md](architecture.md)；安全设计见
> [ai-safety.md](ai-safety.md)；OpenClaw 细节见 [openclaw-integration.md](openclaw-integration.md)。

---

## 0. 三个核心问题的直接回答

| 你的疑问 | 答案 |
|---|---|
| **集成的 PT search 是什么？怎么用我的 RSS 会员站？** | 现支持 4 种后端：`mock` / **`rss`（你的会员站 RSS 订阅）** / `torznab`（Jackett/Prowlarr）/ `json`。你的情况选 `rss`，把会员站的个人 RSS 地址填进 `PT_RSS_URL` 即可。详见 §2。 |
| **我要下载到 NAS 上的 qBittorrent（有 API）** | 完全支持。qBittorrent 客户端就是走 Web UI API 的，把 `QB_HOST` 指向 NAS 的地址即可，种子上传后直接下到 NAS。详见 §3。 |
| **数据库实际用什么？是本地 SQLite 吗？** | 默认仅在你**没配置** MySQL 时才回退到本地 SQLite。配置 `DB_HOST` 等即可使用你的 MySQL 服务器。详见 §4。 |

运行 `python -m ai_media_assistant.doctor` 可一键体检上述三项是否真正打通。

---

## 1. 安装

```bash
cd /Users/jiahuichu/Workspaces/AIMediaAssistant
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env          # 然后按下面各节编辑 .env
```

---

## 2. 配置 PT 搜索（你的 RSS 会员站）

### 2.1 “PT search” 是什么

它是一个**可插拔的搜索后端**，把“按关键词找资源”这件事抽象出来。`search_media`
工具调用当前后端，返回候选种子（标题、分辨率、质量、大小、做种数、下载链接），
再按你的偏好排序。后端由 `PT_BACKEND` 决定：

- `mock`：内置离线样例库（学习/演示用）。
- **`rss`：读取你会员 PT 站的“个人 RSS 订阅”地址**（最适合你）。
- `torznab`：对接 Jackett/Prowlarr 聚合器。
- `json`：对接自定义 JSON 搜索 API。

### 2.2 获取你 PT 站的 RSS 地址

登录你的 PT 站 → 找到 **“RSS / 订阅 / Subscriptions”** 页面 → 复制你的**个人 RSS 链接**。
该链接里通常带有你的 `passkey`（个人密钥），形如：

```
https://你的PT站/torrentrss.php?passkey=你的密钥&cat=电影分类
```

> ⚠️ 这个地址等同于你的下载凭证，请妥善保密。它只保存在本地 `.env`（已被 git 忽略）。

### 2.3 在 `.env` 中配置

PT 站的 RSS 有两种情况：

**情况 A：RSS 支持带关键词搜索**（地址里能放搜索词）——用 `{keyword}` 占位：

```dotenv
PT_BACKEND=rss
PT_MOCK=false
PT_SITE_NAME=我的PT站
PT_RSS_URL=https://你的PT站/torrentrss.php?passkey=你的密钥&search={keyword}
PT_MIN_SEEDERS=1
```

**情况 B：RSS 只输出“最新种子”列表**（不支持搜索）——不放占位符，程序会拉取
最新列表并在本地按关键词过滤：

```dotenv
PT_BACKEND=rss
PT_MOCK=false
PT_SITE_NAME=我的PT站
PT_RSS_URL=https://你的PT站/torrentrss.php?passkey=你的密钥&cat=401
PT_MIN_SEEDERS=1
```

> 不确定属于哪种？先按 B 填，运行 `doctor` 看是否有结果；若你的站支持搜索参数，
> 再改成 A 体验更准的检索。

### 2.4 RSS 还能驱动“自动追剧”

你的 PT 站 RSS 同样可以喂给**自动追剧 Worker**：当订阅的剧集出现新一集时自动下载。
把同一个 RSS 地址加入 `rss_feed` 表即可（见 §6 自动化）。

下载链接（enclosure）已经带 passkey，所以 NAS 上的 qBittorrent 能直接拉取，无需再登录。

---

## 3. 配置 NAS 上的 qBittorrent（远程下载）

本项目的 qBittorrent 客户端通过其 **Web UI API** 工作，所以**本机或 NAS 都一样**——
只要把地址指向 NAS 即可，种子会上传到 NAS 并直接下载到 NAS 磁盘。

### 3.1 在 NAS 的 qBittorrent 上启用 Web UI

qBittorrent → 设置 → **Web UI** → 勾选启用，设置用户名/密码和端口（默认 8080），
确保本机能访问 `http://<NAS_IP>:8080`。

### 3.2 在 `.env` 中配置

```dotenv
QB_MOCK=false
QB_HOST=http://192.168.50.10:8080        # ← 改成你 NAS 的 IP 和端口
QB_USERNAME=admin
QB_PASSWORD=你的密码
QB_CATEGORY=ai-media                       # 下载会归到这个分类，方便管理
DOWNLOAD_SAVE_PATH=/volume1/media/downloads   # ← NAS 上的保存路径（NAS 文件系统视角）
```

要点：
- `DOWNLOAD_SAVE_PATH` 是 **NAS 上的路径**（例如群晖常见 `/volume1/...`），不是你 Mac 的路径。
- 程序会自动创建 `ai-media` 分类；`get_download_status` 返回的是 NAS 上的**真实进度**。
- magnet 链接会先解析出 info-hash；`.torrent` 直链也支持。

---

## 4. 配置 MySQL 数据库（替代本地 SQLite）

### 4.1 真相

数据库由 `DB_HOST` 决定：**只有当 `DB_HOST` 为空时，才会回退到本地 SQLite
（`data/app.db`）**，那只是为了零依赖跑起来。配置了 MySQL 就用 MySQL。

连接串由代码自动拼装：
`mysql+pymysql://用户:密码@主机:端口/库名?charset=utf8mb4`（`PyMySQL` 已随依赖安装）。

### 4.2 在 `.env` 中配置

```dotenv
DB_HOST=192.168.50.10          # ← 你的 MySQL 服务器地址
DB_PORT=3306
DB_NAME=ai_media_assistant
DB_USER=media
DB_PASSWORD=你的密码
```

### 4.3 建库并初始化表

在 MySQL 上先建一个空库（一次性）：

```sql
CREATE DATABASE ai_media_assistant CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

然后让程序自动建表（幂等，可重复执行）：

```bash
source .venv/bin/activate
python -c "from ai_media_assistant.database import init_db; init_db()"
```

设计里的 9 张表（订阅、剧集、资源、下载任务、RSS、Agent 记忆/任务/执行轨迹）
会全部在你的 MySQL 中创建。

---

## 5. 一键体检（确认三项都真打通）

改完 `.env` 后运行：

```bash
python -m ai_media_assistant.doctor
```

它会依次检查并给出 ✓/✗：

```text
[1/4] Database — MySQL @ 192.168.50.10      ✓ Connected and tables ensured (MySQL).
[2/4] qBittorrent — http://192.168.50.10:8080  ✓ Connected; 0 torrent(s) tracked.
[3/4] PT source — backend 'rss'             ✓ Search returned N result(s)…
[4/4] LLM — provider 'ollama', model 'qwen3:8b'  ✓ Ollama reachable; model installed.
```

任意一项 ✗，按提示修正 `.env` 即可。

---

## 6. 运行方式

四种入口，按需选择：

### 6.1 命令行（最快验证）

```bash
python -m ai_media_assistant.cli "下载《沙丘2》"
python -m ai_media_assistant.cli "追《最后生还者》第二季"
python -m ai_media_assistant.cli "推荐最近值得下载的科幻电影"
```

### 6.2 Web 后台 + REST API

```bash
uvicorn ai_media_assistant.api.app:app --host 0.0.0.0 --port 8000
# 浏览器打开 http://localhost:8000
```
常用接口：`POST /api/agent/chat`、`GET /api/search?keyword=`、`POST /api/download`、
`POST /api/follow`、`GET /api/downloads`、`GET /api/recommendations`、
`GET /api/tasks/{id}/trace`（查看 Agent 执行轨迹）。

如果启动时报 `address already in use`，说明 8000 端口已经被另一个进程占用。先停止旧的
`uvicorn` / `python` 进程，或者改成别的端口，例如：

```bash
uvicorn ai_media_assistant.api.app:app --host 0.0.0.0 --port 8001
```

### 6.3 OpenClaw + 本地 Ollama（自然语言，零 API 费用）★推荐

```bash
./scripts/register_openclaw.sh ai-media     # 注册并探测，应显示 "7 tools"
openclaw chat
#   下载《沙丘2》
#   追《最后生还者》第二季
#   查看下载进度
```

OpenClaw 用本机 `ollama/qwen3:8b` 规划并调用我们的工具。小模型偶尔会把输出预算
耗在思考上，可在指令前加 `/no_think`，或对复杂任务用 `--model ollama/deepseek-r1:8b`。
详见 [openclaw-integration.md](openclaw-integration.md)。

#### 6.3.1 问“推荐最近值得下载的科幻电影”时，实际执行了什么

在理想路径下，OpenClaw 会走这条链路（不需要 web fetch）：

```text
你：推荐最近值得下载的科幻电影
OpenClaw（规划）
  -> ai-media.get_recommendations(query="推荐最近值得下载的科幻电影")
      -> RecommendationService.recommend()
         1) 从两类数据构建语料：
            - 内置知识库（空库也可推荐）
            - 数据库 recent resources（你 PT 搜索缓存）
         2) 叠加你的偏好记忆（如 favorite_genre / preferred_resolution）
         3) 向量召回 top-k
         4) 本地 LLM 仅基于召回上下文生成推荐；若 LLM 不可用则直接回退召回结果
  <- 返回推荐列表（title/reason/score）
```

如果你在 OpenClaw 里看到这类报错：

```text
The web fetch operation failed due to a security restriction...
```

这通常表示本轮被模型误路由到了“外部网页抓取”工具，而不是 `ai-media` 的
`get_recommendations`。这不是本项目 MCP 后端崩溃。

#### 6.3.2 推荐场景的稳定提问模板（可直接复制）

先刷新 MCP：

```bash
openclaw mcp reload
```

再用强约束提问（交互模式中也可直接贴这句）：

```text
/no_think 只使用 ai-media MCP 工具，不要调用 web fetch 或浏览器工具。
先调用 get_system_status；然后调用 get_recommendations，
query="推荐最近值得下载的科幻电影"；最后用中文返回 5 个推荐和理由。
```

命令行 one-shot 示例：

```bash
openclaw agent --agent main --session-key media-reco \
  --message "/no_think 只使用 ai-media MCP 工具，不要调用 web fetch 或浏览器工具。先调用 get_system_status；然后调用 get_recommendations，query='推荐最近值得下载的科幻电影'；最后用中文返回 5 个推荐和理由。"
```

若仍偶发误路由，优先按顺序处理：

1. 新开一个 session-key（避免历史上下文干扰）。
2. 明确写“只使用 ai-media MCP 工具”。
3. 先让它调用 `get_system_status` 再做推荐。
4. 缩短问题长度，避免混入“联网查询/最新新闻”等词。

### 6.4 自动追剧 / 自动补集（后台）

```bash
# 跑一次：扫描已启用的 RSS feed，发现订阅中的新剧集就自动下载
python -m ai_media_assistant.workers.rss_worker

# 常驻调度：每 10 分钟扫一次 RSS，每 30 秒刷新下载进度
python -m ai_media_assistant.workers.scheduler
```

调度任务管理（API 方式）：

```bash
# 查看任务状态（rss_sync / download_refresh）
curl http://127.0.0.1:8000/api/scheduler/status

# 立即执行一次 rss_sync（不必等 10 分钟）
curl -X POST http://127.0.0.1:8000/api/scheduler/jobs/rss_sync/run

# 暂停 / 恢复 / 重启任务
curl -X POST http://127.0.0.1:8000/api/scheduler/jobs/rss_sync/pause
curl -X POST http://127.0.0.1:8000/api/scheduler/jobs/rss_sync/resume
curl -X POST http://127.0.0.1:8000/api/scheduler/jobs/rss_sync/restart
```

> 注意：如果你启动 API 时没有 `--reload`，修改代码后需要重启 API 进程，新的调度接口才会生效。

把你 PT 站的 RSS 加入监控（写入 `rss_feed` 表）：

```bash
python -c "
from ai_media_assistant.database import init_db, session_scope
from ai_media_assistant.database.models import RssFeed
init_db()
with session_scope() as s:
    s.add(RssFeed(feed_name='我的PT站', feed_url='https://你的PT站/torrentrss.php?passkey=你的密钥', enabled=True))
"
```

### 6.5 下载种子到 NAS 的 qBittorrent，实际怎么跑

这条链路的关键点是：**你不需要手工上传 `.torrent` 文件**。系统拿到的是资源的 `download_url`，然后调用 qBittorrent Web API 把磁力链接或种子直链交给 qBittorrent，由它自己去拉种。

实际流程如下：

```text
你说“下载《沙丘2》”
  -> Agent / CLI / OpenClaw 调用 search_media("沙丘2")
  -> SearchService 从本地缓冲优先查；没有命中再查 RSS / PT 源
  -> 返回一组资源，每条都有 id、title、download_url、seeders
  -> 调用 download_media(resource_id=某条结果的 id)
  -> DownloadService 读取数据库里的该资源
  -> 若是 HTTP 下载链接：先从 PT 站下载 .torrent 文件（带 PT_COOKIE 登录态）
  -> qBittorrent 客户端调用 Web UI API 上传 .torrent 文件（并指定 save_path/category）
  -> 若是 magnet：直接调用 qB Web UI API 添加 magnet
  -> qBittorrent 开始下载到 NAS
  -> 系统把 task_id / qb_hash 写回数据库，后续通过 get_download_status 查询进度
```

对应实现位置：

- 搜索结果落库：`search_service.py`
- 下载入口：`download_service.py`
- qB 远程 API：`clients/qb/real.py`

要点说明：

- 只要你配置了 `QB_HOST`、`QB_USERNAME`、`QB_PASSWORD`，系统就能登录 NAS 上的 qBittorrent Web UI。
- 如果搜索结果是 magnet 链接，客户端会先从 magnet 里提取 info-hash；如果是 `.torrent` 直链，就直接交给 qB 去添加。
- `DOWNLOAD_SAVE_PATH` 是 NAS 文件系统上的保存路径，不是 Mac 本地路径。
- `QB_CATEGORY` 会自动创建并用于分类管理，方便你在 qB 里筛选。
- 下载是否允许自动开始，由 `AGENT_REQUIRE_DOWNLOAD_CONFIRM` 控制；开了之后必须显式 `confirm=true`。

如果你想单独验证 qB 是否可用，可以先跑：

```bash
python -m ai_media_assistant.doctor
```

其中第 2 项会尝试连接 qBittorrent 并列出当前任务数；这能直接确认“登录、上传、开始下载、状态查询”这条链路是否通了。

---

## 7. 典型完整链路（真实）

```text
你（OpenClaw 里说）：下载《沙丘2》
Agent 依次：
  1. search_media("沙丘2")     → 读取你 PT 站 RSS → 返回带 passkey 的真实种子，按偏好排序
  2. download_media(最佳id)    → 调 NAS 上 qBittorrent API 上传种子（分类 ai-media）
  3. get_download_status()     → 返回 NAS 上的真实下载进度
数据全程写入你的 MySQL；执行轨迹存入 agent_execution_log。
```

### 7.1 下载链路的更细实现

如果你想看代码层的真实路径，下载动作的核心是：

```text
download_media(resource_id)
  -> DownloadService.download(resource_id)
  -> repo.get_resource(resource_id)
  -> qb_client.add(resource.download_url, save_path=..., name=resource.title)
  -> 如果是 HTTP 下载链接：先 GET 下载 .torrent（带 PT_COOKIE）
  -> qBittorrent Web UI API 收到 torrents_add(torrent_files=..., save_path=..., category=...)
  -> 如果是 magnet：qBittorrent Web UI API 收到 torrents_add(urls=magnet...)
  -> 返回 qb_hash
  -> create_download_task(...) 写入数据库
```

所以这套系统不需要你手工下载再上传。程序会自动完成“从 PT 下载种子文件 -> 上传到 qB -> 创建下载任务”。

如果资源来自 RSS：

- RSS item 里通常已经带有下载直链或 enclosure。
- 我们在同步 RSS 时会把这些资源写入本地 `torrent_resource`。
- 之后不管是搜索还是推荐，都可以直接拿这个缓存里的 `download_url`；下载时会自动拉取 .torrent 并上传到 qB。

如果资源来自 Torznab / 自定义 JSON：

- 逻辑完全一样，差别只是上游后端来源不同。
- 只要返回了 `download_url`，下载逻辑不需要改。

---

## 8. 偏好记忆（让推荐越用越准）

直接用自然语言告诉它偏好，会被存入 `agent_memory` 并影响后续搜索排序与推荐：

```bash
python -m ai_media_assistant.cli "我喜欢 2160P REMUX 的科幻电影"
```
之后 `search_media` 会优先把 2160P / REMUX 资源排在前面。

---

## 9. 安全与“无害性”

下载是唯一会改动外部状态的动作。无人值守时建议开启人工确认：

```dotenv
AGENT_REQUIRE_DOWNLOAD_CONFIRM=true
AGENT_MAX_ITERATIONS=12
```

输入/输出守卫、提示注入清洗、执行轨迹等机制见 [ai-safety.md](ai-safety.md)。
请遵守你 PT 站的规则与当地法律。

---

## 10. 常见问题

| 现象 | 处理 |
|---|---|
| `doctor` 显示 PT 0 结果，或问"拯救计划/大侦探有哪些资源可下载"返回空 | 最常见原因是 PT 站 RSS API 限流返回了错误页（如 "请调整RSS请求间隔至少2分钟"）。解决方法：<br>1. 检查是否最近频繁调用；如是，稍等 2+ 分钟后重试。<br>2. 确认 `PT_RSS_URL` 的 rsskey 未过期（过期会返回 401）。<br>3. 换一个关键词试（若只有部分片子有资源）。<br>4. 暂时切到 mock 后端（`PT_BACKEND=mock`）验证其他环节。 |
| RSS/本地缓存没命中时仍返回空 | 已支持网页模拟查询兜底，但需要配置 `PT_BASE_URL` + `PT_COOKIE`（有效登录态）。未配置时会跳过网页兜底。 |
| qB 里没有自动开始下载 | 先确认 `QB_HOST` 能访问、`QB_USERNAME` / `QB_PASSWORD` 正确，再跑 `python -m ai_media_assistant.doctor`。若 `download_url` 是空，说明上游搜索结果没有返回可下载链接，需要换 RSS/Torznab 源。 |
| 下载已创建但进度不动 | 检查 NAS 上的 qBittorrent 是否能访问外网、保存路径是否存在、PT 的下载链接是否过期或需要重新登录。用 `GET /api/downloads/{task_id}` 或 `get_download_status` 看 `qb_hash` 和进度。 |
| 想暂停 / 恢复 / 重启后台定时任务 | 用 `GET /api/scheduler/status` 查看状态，`POST /api/scheduler/jobs/rss_sync/pause` 暂停，`.../resume` 恢复，`.../restart` 重启。 |
| qBittorrent 连接失败 | 确认 NAS 的 Web UI 已开、`QB_HOST` 含 `http://` 和端口、Mac 能 `curl` 通该地址、账号密码正确。 |
| 仍在用 SQLite | `.env` 里 `DB_HOST` 必须非空；改完重启进程；用 `get_system_status` 或 `doctor` 确认 `db_backend=mysql`。 |
| OpenClaw 调用报 `incomplete_result` | 指令前加 `/no_think`，或换 `--model ollama/deepseek-r1:8b`。 |
| OpenClaw 提示 `web fetch ... security restriction` | 本轮多半误选了 web fetch，不是 ai-media 挂掉。先 `openclaw mcp reload`，然后在指令里写"只使用 ai-media MCP 工具，不要调用 web fetch"，并先调 `get_system_status` 再调 `get_recommendations`。 |
| 改了 `.env` 但 OpenClaw 没生效 | 运行 `openclaw mcp reload`。 |
| MCP 输出乱码 | 本项目日志只走 stderr，stdout 仅走 MCP 协议；勿在工具里 print 到 stdout。 |
| 推荐总是那几部科幻片子 | v2 已改：推荐使用通用类型模板 + 实时缓存资源混合。如果推荐结果仍然太少或重复，可能因为：<br>1. 你的 RSS 连接刚跑过，资源缓存还很少。搜索几个关键词后就会积累。<br>2. 没有配置个人偏好记忆（见 §8）。说"我喜欢 2160P REMUX 的科幻电影"让系统学习。 |

---

## 11. 配置项速查

| 变量 | 作用 |
|---|---|
| `PT_BACKEND` | `mock` / `rss` / `torznab` / `json` |
| `PT_RSS_URL` | 你 PT 站的个人 RSS 地址（可含 `{keyword}`），含 passkey |
| `PT_MIN_SEEDERS` | 过滤掉做种数过低的资源 |
| `QB_MOCK` | `false` 走真实 qBittorrent |
| `QB_HOST` | NAS 上 qBittorrent Web UI 地址 |
| `DOWNLOAD_SAVE_PATH` | NAS 上的保存路径 |
| `QB_CATEGORY` | 下载分类（默认 `ai-media`） |
| `DB_HOST`…`DB_PASSWORD` | MySQL 连接；为空则回退 SQLite |
| `LLM_PROVIDER` / `LLM_MODEL` | `ollama` + `qwen3:8b`（本地、零费用） |
| `EMBED_PROVIDER` | `fallback`（离线）/ `ollama` / `openai` |
| `AGENT_REQUIRE_DOWNLOAD_CONFIRM` | 下载前是否需人工确认 |
