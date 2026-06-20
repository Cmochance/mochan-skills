# mochan-skills

Cmochance 自建的 Claude Code skill 集合。每个 skill 采用**两层结构**:
**通用方法**(`SKILL.md`,可公开)+ **实例配置**(`config.local.*`,含 workspace/项目/id 等本地值,**不提交**)。

## Skills
- **linear-index** —— Linear issue 本地索引:按编号/关键词/状态/标签/里程碑/归档检索,先查本地索引再按需 MCP 拉详情;含增量/全量刷新。
- **plane-index** —— Plane work item 本地索引:同上,适配 Plane(原生归档、无限 issue、PQL、external_id 回链)。
- **transfer-bug-recorder** —— 按 Codex 桌面 UI 报错语句分类/记录 bug 的方法与知识库结构。
- **codex-e2e-test** —— 经 CDP 注入驱动真实运行的 Codex Desktop 跑一轮对话做 E2E/冒烟。

## 安装
1. 复制对应目录到 `~/.claude/skills/`。
2. 把 `config.example.*` 复制为 `config.local.*`,填入你的实例值(workspace / project / id / 本地路径等)。`config.local.*` 不进版本库。
3. 索引类 skill 的数据(`*.jsonl`)是生成物,不在本仓(各 skill 首次运行时自建)。

## 约定
- `SKILL.md` 只放可复用方法,**不含实例/敏感值**;实例值一律走 `config.local.*`。
- skill 创建或修改后,提交并推送到本仓。
