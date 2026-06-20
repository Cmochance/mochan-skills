---
name: linear-index
description: 本地 Linear issue 索引。需要定位、查找、回忆 Linear issue 时(按编号/关键词/状态/标签/里程碑/归档状态),先查本地索引再按需 MCP 拉详情;也负责索引的增量/全量刷新。merge 收尾扫描相关 issue 时同样先走本索引筛候选。
---

# Linear 本地索引

> **实例配置**(workspace / team / 索引目录 / 归桶 milestone 映射 / api key 路径)读本目录 `config.local.json`(模板见 `config.example.json`)。下文凡出现 `config.<字段>` 均指读该文件对应字段;示例命令里的 `<index dir>` 替换为 `config.index_dir`。

索引位置:`config.index_dir`(如 `~/.claude/linear-index/<workspace slug>/`)

- `issues.jsonl` — 一行一个 issue(字段见下)
- `meta.json` — `last_sync`(ISO 时间)、`team`、统计 `counts`(total / archived / 按 statusType 分布)

issues.jsonl 每行字段:
`id`(如 `ABC-N`)、`title`、`status`、`statusType`(triage|backlog|unstarted|started|completed|canceled)、`priority`、`labels`、`project`、`milestone`、`archivedAt`(null=未归档)、`createdAt`、`updatedAt`、`completedAt`、`canceledAt`、`url`、`desc`(description 截断 ≤400 字符、已去换行)

## 查询(默认路径)

1. **先查本地索引**,不要上来就 `list_issues` 翻页(下例 `<index dir>` = `config.index_dir`):
   - 按编号:`jq -c 'select(.id=="ABC-79")' <index dir>/issues.jsonl`
   - 按关键词(搜 title+desc):`rg -i '关键词' <index dir>/issues.jsonl | jq -r '[.id,.status,.title] | @tsv'`
   - 按状态:`jq -r 'select(.statusType=="started") | [.id,.title] | @tsv' issues.jsonl`
   - 未归档的未完成项:`jq -r 'select(.archivedAt==null and (.statusType=="backlog" or .statusType=="unstarted" or .statusType=="started")) | [.id,.status,.title] | @tsv' issues.jsonl`
   - 按里程碑/标签:`jq -r 'select(.milestone | test("协议")) | ...'` / `jq -r 'select(.labels | index("Bug")) | ...'`
2. 命中后需要完整 description / 评论 / relations / attachments → `mcp__linear__get_issue`(按需 `includeRelations: true`)
3. 本地查不到(可能是索引后新建的)→ 先做一次增量刷新再查;仍无 → 用 MCP `list_issues` 的 `query` 参数直查

## 刷新

读 `meta.json` 拿 `last_sync`,然后(team 取 `config.team` 对应的 workspace/team,即 `config.workspace`):

- **增量(默认)**:`mcp__linear__list_issues(team: config.workspace, updatedAt: "<last_sync>", includeArchived: true, limit: 250, orderBy: "updatedAt")`,有 `hasNextPage` 就带 `cursor` 翻页拉全;按 `id` upsert 进 issues.jsonl(同 id 新数据覆盖旧行),重算 meta.json
- **全量(首次 / 用户显式要求 / 怀疑索引损坏)**:同上但不带 `updatedAt`,重写整个文件
- **staleness 自动刷新**:查询前看 `meta.json`,`last_sync` 距今 > 24h 先做增量刷新再查
- upsert/重算用 python3 临时脚本处理(MCP 返回 JSON → 挑字段 → JSONL),不要手工逐条转写
- **大返回必走落盘文件**:limit 250 的返回会超 token 上限被 harness 自动落盘到 `tool-results/mcp-linear-list_issues-*.txt`,tool result 里给出路径——直接让 python 读该文件转换,零上下文消耗,这是常态路径不是错误;小增量(几条)返回会直接进上下文,同样用 python heredoc 内联数据处理

字段映射(MCP 返回 → 索引):`priority` 取 `.priority.name`,`milestone` 取 `.projectMilestone.name`,`desc` 取 `.description` 去换行后截 400 字符;`assignee`/`createdBy`/`team`/`gitBranchName`/`sla*` 不入索引。

## 归档

- **归档后 MCP 查询不受影响**:`get_issue` 按 ID 仍返回完整 description / stateHistory / project / url(`archivedAt` 非 null),`list_comments` 同样可用;`list_issues` 的 `includeArchived: false` 会过滤归档 issue(默认 `true` 不过滤)。归档只影响 UI 列表可见性,不丢数据。
- **Linear MCP 没有归档工具**(`save_issue` 无 archive 参数,archive 也不是 workflow state)。归档走 GraphQL `issueArchive` mutation(api key 路径见 `config.api_key_path`,Authorization header 直接放 key 不带 Bearer),或用户在 UI 手动。
  - **`issueArchive(id:)` 直接吃 identifier**(`issueArchive(id: "ABC-N"){success}`,**无需先查 UUID**)。
  - **批量归档用 alias 一个请求多个 mutation**:`mutation { a0: issueArchive(id:"ABC-X"){success} a1: issueArchive(id:"ABC-Y"){success} ... }`,每批 ~30 个稳妥(实测一次 71 个分 3 批全 success)。
- **归档不更新 `updatedAt`**(实测:archivedAt 写入后 updatedAt 纹丝不动),所以按 `updatedAt` 过滤的增量同步**抓不到**归档状态变化。执行的归档必须当场手动改索引(该行 `archivedAt` + meta `counts.archived`);怀疑外部归档过 issue 时做全量重建。

## 落 issue 选 milestone(归桶)

落 issue 选 milestone:**读 `config.local.json` 的 `milestone_buckets`,按角色取 id**,不必每次 `list_milestones`:

- **followup** —— 所有非「用户反馈 / 版本追踪」的 issue(协议 / 跨端 / 安全 / 产品化 / 泛 followup 全进这)→ `milestone_buckets.followup.id`
- **user_feedback**(持续)—— GitHub 同步 issue / 用户实报 bug → `milestone_buckets.user_feedback.id`
- **version_tracking**(持续)—— 上游版本 sub-issue、版本 roadmap → `milestone_buckets.version_tracking.id`

- **followup 桶通常用「name 含 `followup` 字样」标记 active 接收点,同一时间仅一个**。当把字样挪到更新的 milestone(新建带 Followup 的桶、旧桶改名去字样)时,**更新 `config.local.json` 中 `milestone_buckets.followup` 的 name + id**。
- **封存 / 不收新桶**(新 issue 一律改走 followup 桶):已封口的语义桶(如旧协议 / 跨端桶)不收新;现有 in-progress 桶不动、不收新。
- **兜底**:落完若怀疑 config 过期(归错桶),`list_milestones` 校对 name 含 `followup` 的唯一桶,并回头修 `config.local.json`。

## 配套写入规范

自建 issue 的 description 按双区结构写:前 400 字符是「索引区」(症状原文关键词 + 组件 / 协议名 + 关联编号 + 中英别名双写),`---` 分隔后才是正文。这样较新自建 issue 的 `desc` 字段头部就是高密度检索词,关键词搜索优先信任它;老 issue(规范生效前)的 `desc` 可能是背景叙事开头,搜不到时退回 title 搜索或 MCP `query` 直查。

## 硬性规则

- 索引只用于**定位与筛选**。任何写操作(状态 transition、评论、改 label/milestone/priority)前,必须用 MCP 实时拉该 issue 确认当前状态,禁止凭索引旧数据做决策。
- 归档状态变化增量同步抓不到(归档不 bump `updatedAt`,见「归档」节),归档操作必须当场手动同步索引;若发现某 issue 索引里没有而 Linear 里有(或反之),做一次全量重建。
- 索引文件是生成物,不进任何 git 仓库,不要 commit。
- `config.local.json` 含真实实例值(workspace / milestone id 等),**不提交**(应 gitignore);提交的是 `config.example.json` 占位模板。
