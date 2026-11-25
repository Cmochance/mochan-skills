# tri-orchestrator

面向 **Antigravity CLI（`agy`）** 的三模型分级编排与闭环代码审查插件（`plugin.json` + `mcp_config.json` + `hooks.json` + `rules/AGENTS.md` + `skills/tri-swarm/SKILL.md`）。

以 **Gemini 4 Hydrogen** 担任零额外损耗的前台总调度台，按任务属性精准路由至 **Gemini 4 Neon**（分析/编码）与 **Gemini 4 Carbon**（规划/对抗审查），并在实质编码后自动执行 **一审 + 大改动/高危修复二审闭环**。

## 架构与能力（v1.2.0）

- **1. 五级智能路由与豁免（`rules/AGENTS.md`）**
  - **简单调研 / 快速问答**：前台 Hydrogen 原地直答，禁止调用 `tri-router`。
  - **微改动快速通道**：单文件 `≤ 10` 行非核心微调原地 `edit_file` 完成，免启动多进程闭环。
  - **总结分析（`neon_analyze`）**：`gemini-4-neon-medium` 只读跨文件梳理与日志/性能根因定位。
  - **项目规划（`carbon_planner`）**：`gemini-4-carbon-high` 只读架构拆解，返回 `plan_session_id` 供后续审查续接设计上下文。
  - **实质编码闭环（`execute_with_review`）**：`gemini-4-neon-xhigh` 实现并自测 → `gemini-4-carbon-high` 一审（检出 `BLOCKER`/`HIGH`/`MEDIUM` 自动回交 Neon 修复重测）→ 大改动（默认 `>= 120` 行或 `>= 4` 文件）或 R1 含 `BLOCKER`/`HIGH` 时自动触发二审验证。
  - **独立代码审查（`carbon_reviewer`）**：针对聚焦增量 Diff 执行只读审查。
  - **四重防套娃守卫**：自动识别原生 `Orchestrator (...)` 会话、MCP 子会话、Swarm Worker / Subagent 及插件自举修改，杜绝双重编排与递归。

- **2. 零依赖并发 MCP 调度引擎（`server/tri_router_mcp.py`）**
  - 纯 Python 标准库实现，兼容 newline-delimited JSON 与 `Content-Length` 双帧协议，支持 `ping` 心跳、进度通知与 `notifications/cancelled` 进程组强杀（`SIGTERM` → `SIGKILL`）。
  - **分级 Prompt 投递**：`≤ 32KB` 直接内联 `-p` 零额外往返；`> 32KB` 才落盘受限临时文件。
  - **基线零污染隔离**：基于临时 `GIT_INDEX_FILE` + `GIT_OBJECT_DIRECTORY` 抓取纯净增量 Diff，不向目标仓库 `.git/objects` 写入松散对象；非 Git 目录按 `(size, mtime_ns)` `O(1)` 跳过未改文件。

- **3. 只读安全与原生 Orchestrator 旁路钩子（`hooks.json` + `scripts/readonly-guard.py`）**
  - 仅挂载写/命令/子代理/路由相关工具的 `PreToolUse` 检查（纯读工具零冷启动开销）。
  - 在 `TRI_ORCHESTRATOR_ACCESS=readonly` 子会话中阻断写文件工具、外部 SaaS MCP、危险 Shell 重定向与 `git -c` 外部命令。
  - 当检测到前台处于 `Orchestrator (...)` 模式时，自动拦截 `tri-router` 调用，避免与原生编排重复耗额。

- **4. 并行 Swarm 协同（`skills/tri-swarm/SKILL.md`）**
  - 在显式触发 `/swarm` 或 `tri-swarm` 时，按 Carbon（架构/终审）+ Neon `share` 工作树（并行编码）+ Hydrogen（只读侦察）分工协作，并强制 Worker 禁用 `tri-router`。

## 安装与配置

```bash
# 1. 严格校验插件清单、规则、hooks 与 MCP 配置
agy plugin validate <mochan-skills>/tri-orchestrator --strict

# 2. 安装到本地 agy 配置目录（~/.gemini/config/plugins/tri-orchestrator）
agy plugin install <mochan-skills>/tri-orchestrator

# 3. 查看已安装插件与启用状态
agy plugin list

# 4. 建议将 CLI 默认前台模型设为 Hydrogen（Medium），充分发挥路由性价比
# 编辑 ~/.gemini/antigravity-cli/settings.json:
#   "model": "Gemini 4 Hydrogen (Medium)"
```

## 可选环境变量

| 变量名 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `TRI_MODEL_NEON_ANALYZE` | `gemini-4-neon-medium` | 覆盖总结分析模型标识 |
| `TRI_MODEL_NEON_CODER` | `gemini-4-neon-xhigh` | 覆盖编码实现模型标识 |
| `TRI_MODEL_CARBON_PLANNER` | `gemini-4-carbon-high` | 覆盖项目规划模型标识 |
| `TRI_MODEL_CARBON_REVIEWER` | `gemini-4-carbon-high` | 覆盖代码审查模型标识 |
| `TRI_PIPELINE_TIMEOUT_SEC` | `1200` | `execute_with_review` 单次全链路总超时预算（秒） |
