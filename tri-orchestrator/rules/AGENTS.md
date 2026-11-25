# Tri-Tier Orchestrator 路由准则

## 递归、角色与自举守卫（最高优先级）
先判断当前会话角色与模型，命中任一守卫即**禁止调用 `tri-router`**，直接用原生工具（`read_file`、`edit_file`、`write_file`、`run_command` 等）原地完成：
0. **原生 Orchestrator 模式守卫**：当前会话模型本身已是 `Orchestrator (...)`（如 `Orchestrator (Neon)`、`Orchestrator (Carbon)`、`Orchestrator (Argon)`）时，说明原生双模编排已接管会话——**禁止调用 `tri-router`**，直接按当前会话原生工作流完成任务，避免双重编排浪费额度。
1. **MCP 子会话守卫**：当前可用 MCP 工具中不包含 `tri-router`（`neon_analyze`、`carbon_planner`、`execute_with_review`、`carbon_reviewer`、`neon_coder`、`await_pipeline`、`cancel_pipeline`）。
2. **Swarm Worker / Subagent 守卫**：你是 `/swarm` 看板上的 Worker（如 `architect`、`coder-*`、`scout-*`、`monitor`、`narrator`）或被 `invoke_subagent` 唤起的子代理——你已绑定目标模型，严禁再调 `tri-router` 套娃。
3. **插件自举豁免**：目标改动路径位于 `~/.gemini/config/plugins/tri-orchestrator/` 时，直接在当前会话修改并自测，禁止调用 `tri-router`。

---

## 五级任务路由与豁免策略（仅前台顶层调度台生效）
1. **简单调研、快速问答、概念解释、轻量查看（Hydrogen 原地直出）**
   - 直接由当前会话原地作答（最多 1–2 次只读本地检索或 `search_web`），**禁止**调用 `tri-router`。
2. **微改动快速通道（≤10 行非核心微调豁免）**
   - 仅涉及单文件 `≤ 10` 行的纯文案、注释、拼写或简单配置键值微调（不涉及业务逻辑、接口契约、并发或安全边界）时，允许当前会话直接 `edit_file` 并做语法/状态校验，免启动多进程闭环（用户显式要求审查除外）。
3. **总结分析、跨文件模块梳理、复杂日志/性能根因分析（Neon Medium）**
   - 若当前前台模型已是 `Neon`，可原地只读完成；否则调用 `tri-router` 的 `neon_analyze`（传入 `prompt` 与目标绝对路径 `cwd`）。
4. **项目规划、架构设计、复杂特性拆解（Carbon High）**
   - 若当前前台模型已是 `Carbon` 且仅需出方案，可原地只读完成；否则调用 `tri-router` 的 `carbon_planner`（只读）。
   - 若用户仅要求出方案或存在需要拍板的架构分歧，先向用户展示方案并记住返回的 `plan_session_id`；若用户明确要求“直接规划并实现”，拿到方案与 `plan_session_id` 后直接调用 `execute_with_review`。
5. **实质代码编程、重构、修 Bug、写测试（Neon XHigh 编码 + Carbon High 自动终审/二审闭环）**
   - **默认一律调用 `tri-router` 的 `execute_with_review`**（传入项目绝对路径 `cwd` 及可选的 `plan_session_id`）。
   - **长耗时安全窗口续等**：若 `tri-router`（`execute_with_review` 等）在 `150s` 安全窗口处返回 `Status: RUNNING` 与 `job_id`（防宿主 `3m0s` 硬超时切流），**必须立即调用 `await_pipeline(job_id=...)` 持续等待直至拿到最终报告**，严禁在后台任务仍运行期间自行绕过改动代码。
   - **禁止**前台会话绕过 `execute_with_review` 自己直接 `edit_file`/`write_file` 修改实质业务代码，也不要裸调 `neon_coder` 跳过终审（除非用户明确说“跳过审查”）。
   - 拿到闭环报告后，向用户清晰汇报：① 最终门禁状态（若为 `FIXED_POST_R2_UNVERIFIED` 须显式提示未复审风险）；② 实际修改文件与核心逻辑；③ Carbon 一审（及大改动/高危修复自动触发的二审）检出的问题与 Neon 修复详情；④ 编译/测试验证状态。
6. **独立代码审查（Carbon High）**
   - 当用户仅要求审查现有改动或分支时：若当前前台模型已是 `Carbon` 可基于增量 Diff 原地只读深审，否则调用 `tri-router` 的 `carbon_reviewer`（若用户显式指定 `/adaptive-review`，则尊重用户选择执行该 skill）。
