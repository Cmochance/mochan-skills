---
name: plane-index
description: 本地 Plane work item 索引(Plane Cloud)。需要定位、查找、回忆 Plane work item 时(按编号/关键词/状态/标签/project/归档),先查本地索引再按需 MCP 拉详情;也负责索引的增量/全量刷新。与 linear-index 同构,但适配 Plane(原生归档、无限 issue、PQL、external_id 回链 Linear)。
---

# Plane 本地索引

> **实例配置**(workspace slug / 索引目录 / project 标识→uuid 映射 / api key)读本目录 `config.local.json`(模板见 `config.example.json`)。下文凡出现 `config.<字段>` 均指读该文件对应字段;示例命令里的 `<index dir>` 替换为 `config.index_dir`。

索引位置:`config.index_dir`(如 `~/.claude/plane-index/<workspace slug>/`)

- `work_items.jsonl` — 一行一个 work item(字段见下)
- `meta.json` — `last_sync`(ISO)、`workspace`、`projects`(identifier→name→uuid)、统计 `counts`(total / archived / 按 stateGroup 分布)

work_items.jsonl 每行字段:
`id`(标识符如 `ABC-50`)、`uuid`(work item UUID,**写操作必需**)、`title`、`state`(状态名)、`stateGroup`(backlog|unstarted|started|completed|cancelled)、`priority`(urgent|high|medium|low|none)、`labels`(名数组)、`project`(名)、`projectId`(uuid)、`cycle`、`module`、`archived`(bool)、`archivedAt`、`createdAt`、`updatedAt`、`completedAt`、`url`、`externalId`/`externalSource`(迁移来源,如 linear 的 `MOC-261`)、`desc`(description_html 去标签去换行后截 ≤400 字符)

> Plane 与 Linear 的关键差异:① **issue 无限量**(无 Linear 的 250 阈值预警,Plane 不套用);② **有原生归档工具**(见「归档」节);③ 标识符是 `PROJECT-N`;④ 迁移自 Linear 的条目带 `externalId`(原 Linear 编号)可互查。

## 查询(默认路径)

1. **先查本地索引**,不要上来就翻 MCP(下例 `<index dir>` = `config.index_dir`,`ABC` 为 `config.projects` 里的某 project 标识):
   - 按编号:`jq -c 'select(.id=="ABC-50")' <index dir>/work_items.jsonl`
   - 按原 Linear 编号(迁移条目):`jq -c 'select(.externalId=="MOC-261")' work_items.jsonl`
   - 按关键词(搜 title+desc):`rg -i '关键词' work_items.jsonl | jq -r '[.id,.state,.title] | @tsv'`
   - 按状态组:`jq -r 'select(.stateGroup=="started") | [.id,.title] | @tsv' work_items.jsonl`
   - 未归档的未完成项:`jq -r 'select(.archived==false and (.stateGroup|test("backlog|unstarted|started"))) | [.id,.state,.title] | @tsv' work_items.jsonl`
   - 按 project / 标签:`jq -r 'select(.project=="<project name>") | ...'` / `jq -r 'select(.labels|index("Bug")) | ...'`
2. 命中后需完整描述 / 评论 / 关系 / 附件 → `mcp__plane__retrieve_work_item`(按 uuid)或 `mcp__plane__retrieve_work_item_by_identifier`(按 `ABC-50`);评论 `list_work_item_comments`、关系 `list_work_item_relations`、附件 `list_work_item_attachments`。
3. 本地查不到(可能索引后新建)→ 先增量刷新再查;仍无 → `mcp__plane__search_work_items(query=...)` 全文直查,或 `list_work_items(pql=...)` 结构化直查。

## 刷新

读 `meta.json` 拿 `last_sync`,然后用 `mcp__plane__list_work_items`(**省略 project_id = 全工作区**):

- **增量(默认)**:`list_work_items(order_by="-updated_at", per_page=100, expand="state,labels", pql='updatedAt > "<last_sync>"')`;响应有 `next_cursor` 就带 `cursor` 翻页拉全;按 `id` upsert 进 jsonl(同 id 覆盖旧行),重算 meta。`total_count` 是真实总数(非本页),可直接用于核对。
- **全量(首次 / 显式要求 / 怀疑损坏)**:同上但不带 `pql`(`order_by="-updated_at"` 全量翻页),重写整个文件。
- **归档项**:`list_work_items` **不返回已归档**(active 列表)。要同步归档态,对每个 project 调 `list_archived_work_items(project_id, per_page=100)` 翻页,把命中的 `id` 在索引里置 `archived=true`+`archivedAt`。project 列表用 `config.projects`,或 `list_projects` 核对。
- **staleness 自动刷新**:查询前看 `meta.json`,`last_sync` 距今 > 24h 先增量刷新再查。
- **统计**:`count_work_items(group_by="state__group")` 一次拿到各状态组计数,写进 meta.counts(比遍历快)。
- upsert/重算用 python3 临时脚本(MCP 返回 JSON → 挑字段 → JSONL),不要手工逐条转写。
- **大返回必走落盘文件**:per_page 100 多页或全量返回会超 token 上限被 harness 落盘到 `tool-results/mcp-plane-list_work_items-*.txt`,tool result 给路径——直接让 python 读该文件转换,零上下文消耗,这是常态路径不是错误。

字段映射(MCP `list_work_items` 返回 → 索引):`id`←`<project.identifier>-<sequence_id>`(需 project identifier,见 `config.projects` / meta.projects / list_projects);`uuid`←`.id`;`title`←`.name`;`state`/`stateGroup`←展开的 `.state`(name / group);`priority`←`.priority`;`labels`←展开的 `.labels[].name`;`project`/`projectId`←`.project`(uuid,名查 config.projects / meta.projects);`desc`←`.description_html` 去标签去换行截 400;`externalId`/`externalSource`←同名字段。`fields` 稀疏集要显式包含 `description_html`(否则 desc 回 null)。

## 归档(Plane 原生,与 Linear 不同)

- **Plane 有原生归档工具**:`mcp__plane__manage_work_item_archive(project_id, work_item_id, archive=true)`,**仅 completed/cancelled 状态可归档**(否则报错)。批量归档就循环调用(无 bulk archive 单调用,但工具直接可用,无需像 Linear 那样走 GraphQL)。
- 归档后该 work item 不再出现在 `list_work_items`(active),改由 `list_archived_work_items` 列出;`retrieve_work_item` 按 uuid 仍可读。
- **执行归档后当场改索引**(该行 `archived=true`+`archivedAt`,meta `counts.archived`),避免与远端不同步;怀疑外部归档过则对相关 project 跑一次 `list_archived_work_items` 重建归档标记。
- 因 Plane issue 无限量,**不存在 Linear 那种"逼近 250 要预警归档"的硬约束**。
- **默认不归档**:Plane 里完成项用 **Done/Cancelled 状态**表达即可,`manage_work_item_archive` 除非显式要求否则不用。

## 硬性规则

- 索引只用于**定位与筛选**。任何写操作(改 state / 评论 / 改 label / priority / 归档)前,必须用 MCP(`retrieve_work_item` / `_by_identifier`)实时拉该 work item 确认当前状态,禁止凭索引旧数据做决策。
- 写操作多需 `project_id` + `work_item_id`(uuid),索引里 `projectId` + `uuid` 就是为此存的;project uuid 也可从 `config.projects` 按标识符取。
- 索引文件是生成物,不进任何 git 仓库,不要 commit。
- `config.local.json` 含真实实例值(workspace slug / project uuid 等),**不提交**(应 gitignore);提交的是 `config.example.json` 占位模板。
