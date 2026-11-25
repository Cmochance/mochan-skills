---
name: linear-index
description: 全工作区多 Team 本地 Linear issue 索引与 linear-idx CLI。需要定位、查找、盘点 Linear issue（按编号、关键词、Team、Project、状态、标签、里程碑或归档状态）或做收尾筛查时，先用 linear-idx 查本地索引，命中后再按需调 MCP 拉实时详情；同时负责全工作区增量/全量索引刷新与归档状态同步。
---

# linear-index — 全工作区多 Team 本地索引

> **实例配置**（`workspace` / `default_team` / `index_dir` / `stale_hours` / `api_key_path`）自动读取本目录 `config.local.json`（模板见 `config.example.json`，已 gitignore）。
>
> **可选实例级 PM 约定**：若本目录存在 `config.local.pm-conventions.md`（如特定项目的 milestone 归桶、状态流转或 followup 建档规则），新建/更新 issue 或合并收尾前先按需读取。

索引目录默认为 `config.index_dir`（如 `~/.claude/linear-index/<workspace slug>/`），包含全工作区统一的 `issues.jsonl` 与 `meta.json`。

## 1. 默认调用方式（`linear-idx` CLI 优先）

将 `linear-index/scripts/linear-idx` 软链至 `~/.local/bin/linear-idx` 后，**一律以单条独立命令直接调用**（禁止拼接 `$(...)`、环境变量前缀、管道或多行 python heredoc，以保护 Antigravity CLI 二进制前缀自动审批；若沙盒限制写入 `~/.claude/linear-index/`，仅对单条写索引命令 `linear-idx upsert` / `linear-idx mark-archived` 设置 `BypassSandbox: true`）：

```bash
# 查看索引新鲜度（FRESH / STALE / UNINITIALIZED）、各 Team 与状态统计
linear-idx status

# 按编号精确直查（可逗号分隔多编号；--id 默认自动包含已归档 issue）
linear-idx search --id CHX-21,MOC-55 --desc

# 全工作区多关键词检索（默认多词 AND，加 --any 切换 OR；默认过滤已归档，加 --include-archived 放开）
linear-idx search ssh proxy

# 限定单个或多个 Team / 默认主 Team / Project / 未完成项（--open 含 triage|backlog|unstarted|started）
linear-idx search --team CHX --project comfyui --open
linear-idx search --default-team --open
linear-idx search --milestone followup --label Bug --json

# 用落盘的 MCP 返回文件增量合并（全量重建加 --rebuild；支持一次传多页文件）
linear-idx upsert /path/to/page1.txt /path/to/page2.txt
linear-idx upsert --rebuild /path/to/page1.txt /path/to/page2.txt

# 归档或取消归档后同步本地索引
linear-idx mark-archived CHX-21 MOC-55
linear-idx mark-archived CHX-21 --unarchive
```

## 2. 智能保鲜与全工作区刷新

### 何时刷新
- **按编号直查（`--id`）**：本地命中即直接返回定位信息（后续任何写操作前反正必须调 `get_issue` 实时核验，无需先刷索引拖慢响应）；仅当本地未命中时，再走增量刷新或直接调 `get_issue`。
- **列表 / 关键词 / `--open` 扫描或本地 miss**：先看 `linear-idx search` 首行状态摘要或 `linear-idx status`：
  - `UNINITIALIZED` → 执行一次全量拉取并 `linear-idx upsert --rebuild ...`；
  - `STALE`（距 `last_sync` 超过 `config.stale_hours`，默认 `24h`）或怀疑漏了刚建的新 issue → 先执行一次增量拉取并 `linear-idx upsert ...`，再重新检索。

### 全工作区拉取参数（不传 `team`）
调用 Linear `list_issues` 时**不要传 `team` 参数**，一次拉齐工作区内 `CHX`、`MOC` 等全部 Team，并显式传入固定 `fields` 白名单以节省上下文体积、避免额外探路：

```json
{
  "includeArchived": true,
  "limit": 250,
  "orderBy": "updatedAt",
  "updatedAt": "<meta.json 中的 last_sync；全量重建时不传此字段>",
  "fields": [
    "id", "title", "description", "projectMilestone", "priority", "url",
    "createdAt", "updatedAt", "archivedAt", "completedAt", "canceledAt",
    "status", "statusType", "labels", "project", "team"
  ]
}
```

若返回 `"hasNextPage": true`，带上返回的 `cursor` 继续翻页拉完所有页（若最后一页仍为 `hasNextPage=true`，`linear-idx upsert` 会在 `stderr` 告警防漏页）。

### 双宿主落盘衔接
- **Claude Code**（`mcp__linear__list_issues`）：大返回自动落盘至 `tool-results/mcp-linear-list_issues-*.txt`，直接传该文件路径给 `linear-idx upsert`。
- **Antigravity CLI**（`call_mcp_tool`，`ServerName: "linear"`，`ToolName: "list_issues"`）：
  - 大返回自动落盘至 `<appDataDir>/brain/<cid>/.system_generated/steps/<N>/output.txt`，直接传该路径给 `linear-idx upsert`；
  - 小增量直接内联返回时，用 `write_file` 写入 `/tmp/linear_sync.json`，再执行 `linear-idx upsert /tmp/linear_sync.json`。
- 多页分页文件可在一条命令中合并：`linear-idx upsert <page1> <page2>`（全量重建加 `--rebuild`）。

## 3. 归档同步

- **Linear MCP 无归档工具**（`save_issue` 不含归档参数，归档也不是 workflow state）。
- **API 归档前置检查**：仅当 `config.api_key_path` 指向的本地文件存在时，才可调用 Linear GraphQL 执行 `issueArchive(id: "CHX-N"){success}`（`Authorization` 头直接放 API key 原值，不加 `Bearer`；多条可用 GraphQL alias `a0: issueArchive(...) a1: issueArchive(...)` 合并批次）。**若 `api_key_path` 文件不存在，直接提示用户在 Linear UI 手动归档，切勿盲发必然失败的请求**。
- **归档不更新 `updatedAt`**：Linear 写入 `archivedAt` 时不会改动 `updatedAt`，增量同步抓不到归档变化；完成归档后必须立即执行 `linear-idx mark-archived <ID...>` 同步本地索引（若怀疑外部发生过未记录的批量归档，执行一次 `--rebuild` 全量同步）。

## 4. 配套写入规范（跨项目通用）

- **`description` 严格 `< 450` 字符**：写成**单段自包含检索摘要**（症状关键词 + 模块/协议名 + 关联编号 + 中英同义词），不写长篇正文。原因：Linear MCP `list_issues` 在 ~450 字符处会截断 `description`；控制在 `< 450` 字符即可保证单次同步完整入库且关键词高密度可搜。
- **详情按轮次追加评论**：背景调研、根因分析、实现方案与变更决策一律写入评论（`save_comment`），每一轮新写一条评论追加在后，不回头覆盖或改写历史评论。
- **实例级补充约定**：若存在 `config.local.pm-conventions.md`，按其中记录的项目专属规则执行。

## 5. 硬性规则

1. **只定位不盲写**：本地索引仅用于定位与筛选；任何写操作（改状态、发评论、改 label / milestone / priority 等）前，**必须先调 `get_issue` 拉取实时状态核验**，严禁凭本地索引缓存直接做写入决策。
2. **禁止入库**：索引目录生成物（`issues.jsonl`、`meta.json`）及本目录所有 `config.local.*` 均不入 git，严禁提交。
