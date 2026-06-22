# 诊断指南：为什么找不到资源

## 问题描述

在 OpenClaw 中执行 `search_media` 或 `get_recommendations` 查询时返回 0 结果，即使是常见的片子名字（如"大侦探"、"拯救计划"）也无法搜到。

## 诊断流程

### 1. 确认后端类型

```bash
cd AIMediaAssistant
.venv/bin/python -c "
from ai_media_assistant.shared.config import get_settings
cfg = get_settings()
print(f'PT_BACKEND={cfg.effective_pt_backend}')
print(f'PT_RSS_URL={cfg.pt_rss_url}')
print(f'PT_MOCK={cfg.pt_mock}')
"
```

**预期输出:**
- 如果 `PT_BACKEND=mock`：系统只会返回虚拟数据。如需真实资源，改 `.env` 的 `PT_BACKEND=rss`。
- 如果 `PT_BACKEND=rss`：继续诊断 RSS 连接。

### 2. 测试 RSS 连接

```bash
.venv/bin/python - <<'PY'
from ai_media_assistant.shared.config import get_settings
import httpx

cfg = get_settings()
url = cfg.pt_rss_url
print(f"Fetching: {url}")

try:
    r = httpx.get(url, timeout=15)
    print(f"HTTP Status: {r.status_code}")
    print(f"Content-Type: {r.headers.get('content-type', 'N/A')}")
    print(f"\nFirst 500 chars of response:")
    print(r.text[:500])
except Exception as e:
    print(f"Error: {e}")
PY
```

**常见响应:**

**Case A：限流保护**
```
HTTP Status: 200
Content-Type: text/html

响应内容:
请调整RSS请求间隔时间至少为2分钟！  Please adjust the RSS request time to...
最后请求时间：2026-06-18 13:24:29
```
**解决方案:**
- 这是正常的 PT 站 API 限流。等待 2+ 分钟，或换一个新的 rsskey。
- 限流发生原因：最近频繁调用 RSS 接口。建议在生产环境中增加缓存 TTL 或使用更低频的轮询。

**Case B：无效的 rsskey**
```
HTTP Status: 401 或 403
Content-Type: text/html

响应内容:
Unauthorized / Forbidden
```
**解决方案:**
- 重新登录 PT 站，复制最新的 rsskey（通常在个人中心或设置页）。
- 更新 `.env` 的 `PT_RSS_URL`。

**Case C：正常 RSS 文档**
```
HTTP Status: 200
Content-Type: application/rss+xml 或 text/xml

响应内容:
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>PT站</title>
    ...
```
**继续:** 检查 RSS 内容是否含有你要搜的片子。

### 3. 检查 RSS 内容

如果 RSS 连接正常，用 feedparser 解析看实际有没有你要的片子：

```bash
.venv/bin/python - <<'PY'
from ai_media_assistant.shared.config import get_settings
import feedparser

cfg = get_settings()
feed = feedparser.parse(cfg.pt_rss_url)

if feed.bozo:
    print(f"⚠️  XML 解析警告: {feed.bozo_exception}")

print(f"RSS Title: {feed.feed.get('title', 'N/A')}")
print(f"Total entries: {len(feed.entries)}")

# 搜索你要的片子关键词
keyword = "大侦探"
matching = [e for e in feed.entries if keyword in e.get('title', '')]
print(f"\n含 '{keyword}' 的条目数: {len(matching)}")

if matching:
    print(f"\n示例条目:")
    for e in matching[:3]:
        print(f"  - {e.get('title', 'N/A')[:60]}")
        print(f"    Seeders: {e.get('seeders', 'N/A')}")
else:
    print(f"\n未找到含 '{keyword}' 的条目。试试搜索部分关键词:")
    # 列出前 5 条
    for e in feed.entries[:5]:
        print(f"  - {e.get('title', 'N/A')[:60]}")
PY
```

**结果判断:**

| 结果 | 含义 | 处理方法 |
|---|---|---|
| 0 条目 | RSS 为空或只有限流文案 | 等待 2 分钟或更新 rsskey |
| 有条目但无"大侦探" | RSS 正常但该片子不在你的 PT 站 | 试试其他关键词；或题目不对（如中/英文差异）|
| 有条目有"大侦探"但 Seeders=0 | 该资源无人做种 | 正常现象；系统会过滤这类死资源 |
| 有条目有"大侦探" 且 Seeders>0 | 应该能搜到！ | 见下一步：测试搜索 API |

### 4. 测试搜索 API

如果 RSS 内容正确且有符合条件的资源，测试搜索函数：

```bash
.venv/bin/python - <<'PY'
from ai_media_assistant.services.search_service import SearchService

service = SearchService()
results = service.search("大侦探")

print(f"搜索结果数: {len(results)}")
for r in results[:5]:
    print(f"  - {r.title} ({r.resolution or 'N/A'}) - {r.seeders} seeders")
PY
```

**预期:**
- 若 `search()` 返回 > 0 结果，系统工作正常。可能是 OpenClaw 的工具选择问题（见下步）。
- 若 `search()` 仍返回 0，说明 RSS 解析或过滤有问题；继续 debug。

### 5. 测试 MCP 工具

在 Python 中直接调用 MCP 工具：

```bash
.venv/bin/python - <<'PY'
from ai_media_assistant.mcp.server import search_media_impl, get_recommendations_impl

# 直接调用工具实现
results = search_media_impl("大侦探", seeders_min=1)
print(f"search_media 结果数: {len(results.get('results', []))}")
print(f"结果: {results}")

# 或试试推荐
rec = get_recommendations_impl("大侦探有哪些资源可下载")
print(f"\nget_recommendations 结果: {rec}")
PY
```

**预期:**
- 若 MCP 工具返回正确结果，问题在 OpenClaw 端（见常见问题 §10）。
- 若 MCP 工具仍返回 0，系统层有问题；继续 debug。

### 6. OpenClaw 端诊断

在 OpenClaw 中运行诊断命令：

```openclaw
@ai-media /no_think 请先调用 get_system_status 看系统状态，然后搜索"大侦探有哪些资源可下载"
```

**预期输出:**
- `get_system_status` 应显示 `pt_backend=rss`（或 mock）和 `db_backend=mysql`
- `search_media` 应返回符合条件的资源列表，包括种子数

**常见错误:**
- `incomplete_result`：加 `/no_think` 或换模型
- `web fetch security restriction`：可能误用了 web 工具；明确指令"只用 ai-media 工具"
- `tool not found`：运行 `openclaw mcp reload` 重新加载工具

## 核查清单

- [ ] `.env` 中 `PT_BACKEND` 设置为 `rss`（不是 `mock`）
- [ ] `PT_RSS_URL` 含有有效的 rsskey（最近从 PT 站复制）
- [ ] RSS 连接返回 HTTP 200 且内容是有效 XML（不是限流页面）
- [ ] RSS 内容含有你要搜的片子且 seeders > 0
- [ ] 本地搜索 API 能返回结果
- [ ] MCP 工具能正确调用
- [ ] OpenClaw 已运行 `mcp reload`
- [ ] 最近 2+ 分钟没有频繁查询（避免限流）

## 其他资源

- 系统日志：`.log` 或 stderr 输出
- 数据库状态：`doctor` 命令
- 本地验证：`test_follow_and_rag.py` 包含完整的集成测试
