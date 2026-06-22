# AI Media Assistant 架构设计方案（V2.0）

## 一、项目定位

### 项目名称

AI Media Assistant

### 项目目标

打造一个基于 OpenClaw 的 AI Agent 实战项目，通过真实业务场景学习和实践：

* AI Agent 开发
* MCP Tool 开发
* Tool Calling
* Agent Memory
* Agent Workflow
* Multi-Agent
* OpenClaw 集成

同时实现：

* PT资源搜索
* PT资源下载
* 自动追剧
* RSS监控
* qBittorrent集成
* Web管理后台

---

# 二、最终用户体验

## 场景一：电影下载

用户：

```text
下载《沙丘2》
```

Agent：

```text
1. 搜索PT站
2. 找到最佳资源
3. 自动添加到qBittorrent
4. 返回下载结果
```

---

## 场景二：追剧

用户：

```text
追《最后生还者》第二季
```

Agent：

```text
1. 搜索现有剧集
2. 下载所有已发布剧集
3. 建立订阅记录
4. 开启自动追踪
```

---

## 场景三：自动补集

RSS发现：

```text
The Last of Us S02E05
```

系统：

```text
自动识别
自动下载
自动通知
```

---

## 场景四：AI推荐

用户：

```text
最近有什么值得下载的科幻电影？
```

Agent：

```text
分析用户偏好
分析RSS资源
生成推荐列表
```

---

# 三、总体架构

```text
┌───────────────────────────┐
│       OpenClaw Agent      │
└─────────────┬─────────────┘
              │
              ▼
┌───────────────────────────┐
│        MCP Tool Layer     │
└─────────────┬─────────────┘
              │
 ┌────────────┼────────────┐
 │            │            │
 ▼            ▼            ▼

Search     Follow      Download
Service    Service     Service

 │            │            │
 ▼            ▼            ▼

PT Site     RSS       qBittorrent

              │
              ▼

            MySQL
```

---

# 四、技术栈

## Backend

```text
Node.js
TypeScript
Express
```

---

## Database

```text
MySQL
```

已存在服务器数据库。

---

## AI

```text
OpenClaw
Ollama
Qwen3 8B
```

后续可升级：

```text
DeepSeek-R1
Qwen3 14B
```

---

## Download

qBittorrent

---

## Frontend

Flutter Web

---

## Automation

RSS Worker

---

# 五、项目目录

```text
ai-media-assistant

apps
├── api
├── rss-worker
├── openclaw-tools
├── scheduler
└── web

packages
├── database
├── pt-client
├── qb-client
├── rss-client
├── agent-core
└── shared

docs

docker
```

---

# 六、数据库设计

## media_subscription

追剧订阅

```sql
CREATE TABLE media_subscription (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,

    title VARCHAR(255) NOT NULL,

    original_title VARCHAR(255),

    media_type VARCHAR(20),

    season_no INT,

    quality VARCHAR(50),

    follow_enabled TINYINT DEFAULT 1,

    status VARCHAR(20),

    created_time DATETIME,

    updated_time DATETIME
);
```

---

## media_episode

剧集管理

```sql
CREATE TABLE media_episode (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,

    subscription_id BIGINT NOT NULL,

    season_no INT NOT NULL,

    episode_no INT NOT NULL,

    downloaded TINYINT DEFAULT 0,

    torrent_resource_id BIGINT,

    created_time DATETIME
);
```

---

## torrent_resource

资源缓存

```sql
CREATE TABLE torrent_resource (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,

    site_name VARCHAR(100),

    title VARCHAR(500),

    category VARCHAR(50),

    resolution VARCHAR(20),

    quality VARCHAR(50),

    size_bytes BIGINT,

    seeders INT,

    leechers INT,

    detail_url TEXT,

    download_url TEXT,

    publish_time DATETIME,

    created_time DATETIME
);
```

---

## download_task

下载任务

```sql
CREATE TABLE download_task (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,

    resource_id BIGINT,

    qb_hash VARCHAR(100),

    task_status VARCHAR(50),

    progress DECIMAL(5,2),

    save_path VARCHAR(500),

    created_time DATETIME,

    updated_time DATETIME
);
```

---

## rss_feed

RSS配置

```sql
CREATE TABLE rss_feed (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,

    feed_name VARCHAR(100),

    feed_url TEXT,

    enabled TINYINT DEFAULT 1,

    created_time DATETIME
);
```

---

## rss_item

RSS缓存

```sql
CREATE TABLE rss_item (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,

    feed_id BIGINT,

    guid VARCHAR(500),

    title VARCHAR(500),

    link TEXT,

    processed TINYINT DEFAULT 0,

    publish_time DATETIME,

    created_time DATETIME
);
```

---

# 七、Agent相关数据库

## agent_memory

长期记忆

```sql
CREATE TABLE agent_memory (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,

    memory_type VARCHAR(50),

    memory_key VARCHAR(100),

    memory_value TEXT,

    importance INT DEFAULT 1,

    created_time DATETIME
);
```

示例：

```text
preferred_quality = 2160P
preferred_release = REMUX
favorite_category = Sci-Fi
```

---

## agent_task

Agent任务

```sql
CREATE TABLE agent_task (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,

    task_type VARCHAR(50),

    task_status VARCHAR(50),

    task_content TEXT,

    created_time DATETIME
);
```

---

## agent_execution_log

执行轨迹

```sql
CREATE TABLE agent_execution_log (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,

    task_id BIGINT,

    step_name VARCHAR(100),

    tool_name VARCHAR(100),

    request_data LONGTEXT,

    response_data LONGTEXT,

    created_time DATETIME
);
```

用于：

```text
观察Agent思考过程
分析Tool调用
学习Workflow
```

---

# 八、MCP Tool设计

## search_media

搜索资源

输入：

```json
{
  "keyword":"Dune Part Two"
}
```

---

## download_media

下载资源

输入：

```json
{
  "resourceId":1
}
```

---

## follow_show

追剧

输入：

```json
{
  "title":"The Last of Us",
  "season":2,
  "quality":"2160P"
}
```

---

## list_subscriptions

查看追剧列表

---

## get_download_status

查看下载状态

---

## get_recommendations

获取推荐资源

---

# 九、Agent发展路线

## Phase 1

目标：

下载电影

实现：

```text
Search Service
Download Service
qBittorrent
```

Agent能力：

```text
下载沙丘2
```

---

## Phase 2

目标：

追剧

实现：

```text
Subscription
Episode
```

Agent能力：

```text
追最后生还者第二季
```

---

## Phase 3

目标：

自动补集

实现：

```text
RSS Worker
```

Agent能力：

```text
发现新剧集自动下载
```

---

## Phase 4

目标：

OpenClaw MCP

实现：

```text
Tool Calling
Workflow
```

Agent能力：

```text
自然语言控制系统
```

---

## Phase 5

目标：

Agent Memory

实现：

```text
agent_memory
```

Agent能力：

```text
记住用户偏好
```

例如：

```text
优先2160P
优先REMUX
```

---

## Phase 6

目标：

Multi-Agent

实现：

### Planner Agent

负责：

```text
任务规划
```

### Search Agent

负责：

```text
资源搜索
```

### Download Agent

负责：

```text
下载执行
```

### Follow Agent

负责：

```text
自动追剧
```

---

# 十、学习目标

项目完成后掌握：

## OpenClaw

* Agent配置
* Agent运行机制
* Memory
* Workflow

---

## MCP

* MCP Server
* MCP Tool
* Tool Schema
* Tool Result

---

## Agent

* Tool Calling
* Planning
* Reflection
* Long-Term Memory
* Multi-Agent

---

## AI工程化

* Prompt Design
* Agent Debug
* Execution Trace
* Memory Design
* Workflow Design

---

# 十一、最终目标

打造一个长期运行的私人AI媒体助手。

既能解决：

```text
下载电影
自动追剧
资源管理
```

又能作为：

```text
OpenClaw
MCP
Agent
Workflow
Multi-Agent
```

完整学习平台。

项目最终成果不仅是一个媒体系统，更是一套真实可落地的 AI Agent 实战项目。
