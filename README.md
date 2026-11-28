# mochan-skills

Cmochance 自建的 Claude Code skill 集合。每个 skill 采用**两层结构**:
**通用方法**(`SKILL.md`,可公开)+ **实例配置**(`config.local.*`,含 workspace/项目/id 等本地值,**不提交**)。

## Skills
- **linear-index** —— 全工作区多 Team 统一 Linear issue 本地索引与 `linear-idx` CLI（将 `linear-index/scripts/linear-idx` 软链至 `~/.local/bin/linear-idx`）：支持按编号/关键词/Team/Project/状态/标签/里程碑/归档毫秒级检索，先查本地索引再按需调 MCP 拉实时详情；支持 Claude Code 与 Antigravity CLI 双宿主增量/全量落盘同步与归档标记，可选项目级 PM 约定走 `config.local.pm-conventions.md`。
- **adaptive-review** —— 用户显式触发的本地代码审查:按 diff 特征自动从 lens 池选 3-6 个相关维度跑 `Route → Fan-out → Verify → Synthesize`,对抗式 verify 杀假阳性后按严重度出报告。
- **reverse-engineering** —— 逆向 / 授权安全研究 / CTF 的方法论与工具路由:`SKILL.md` 入口按目标分流,`references/` 分域(二进制/语言运行时/移动端/JS 前端/固件/模式识别/pwn/patch-diff/授权渗透/内网AD/LLM安全/game/恶意样本与供应链/CTF)。改写自社区 `reverse-skill`,**剥除了其全局注入 / 服从性工程 / 安全护栏绕过**机制,只保留知识价值;高危进攻域收敛在方法论+检测视角。
- **Rust-Skill** —— Rust 编程的方法论 + 路由 + 三层知识库:`SKILL.md` 入口按问题层级(语言机制/工程设计/领域)分流,`references/` 含 17 个概览子域(所有权/类型trait/错误/并发async/unsafe/宏 + api/性能/测试/cargo/可观测/serde + web/cli/embedded/wasm/systems)、`error-codes.md`(E0xxx→根因域)、`rules/`(265 条习惯/反模式,逐字移植 leonardomso MIT)、`recipes/`(28 篇任务配方)、`examples/`(18 篇概念用例)、`deep/`(37 章设计模式书,MPL-2.0)、`templates/`。架构思路借鉴 `actionbook/rust-skills`(仅结构,无文字拷贝),知识来源与许可见 `Rust-Skill/NOTICE`。
- **agy-cli-modify** —— 面向 Antigravity CLI（`agy`）的轻量提速插件（`hooks.json` `SessionStart` <40ms 首帧工作区快照 + `rules/AGENTS.md` 常驻规则，0 工具期阻塞）：自动感知单 Git 仓与多仓父目录免开局探路、`rg -n` 符号骨架与非对称切片读取、构建/单测静默通过（Quiet-on-Success）、广域摸底 `research` 子代理上下文隔离、macOS `zsh` 防阻塞与沙盒免审批前缀保护、零中间废话与高信噪比回答。综合借鉴 `oil-oil/agy-fast-io`、`INK-Q/agy-fast`、`rtk`、`caveman` 等思路针对 CLI 本地沙盒重写（详见 `agy-cli-modify/NOTICE`）。通过 `agy plugin install <本仓路径>/agy-cli-modify` 安装。
- **tri-orchestrator** —— 面向 Antigravity CLI（`agy`）的三模型分级编排与闭环审查插件（Hydrogen 前台直出秒回 + Neon 总结/编码 + Carbon 规划/一审/大改动二审闭环）：内置零依赖并发 MCP 路由（`tri-router`）、`PreToolUse` 只读隔离与原生 `Orchestrator (...)` 防双重编排守卫、基于临时 `GIT_INDEX_FILE`/`GIT_OBJECT_DIRECTORY` 的零污染增量 Diff 隔离，以及 `/swarm` 多模块并行协作技能 `tri-swarm`。通过 `agy plugin install <本仓路径>/tri-orchestrator` 安装。
- **x-post-reader** —— 三层路由获取 X (Twitter) 帖子全文（单帖/`note_tweet` 走 Tier 1 `FxEmbed`、复杂 `X Article` 走 Tier 2 `Jina Reader`、多楼 `Self-Thread`/404 兜底走 Tier 3 `twitter-cli` 并硬隔离本地浏览器钥匙串）。将 `x-post-reader/scripts/x-read` 软链至 `~/.local/bin/x-read`，如需 Tier 3 需额外执行 `uv tool install twitter-cli` 并在 `config.local.json` 填入备用小号 Cookie。
- **agy-stats** —— 面向 Antigravity CLI（`agy`）的 Claude Code `/stats` 风格用量统计与方格分布图工具：纯标准库增量解析 `transcript.jsonl` 与 `conversation_summaries.db`，渲染终端活跃度热力图（支持按模型拆分周度方格矩阵）、分模型 Token 分布条及 `statusline.py` 额度快照，支持交互式切换指标与 `/stats` Skill。将 `agy-stats/scripts/agy-stats` 软链至 `~/.local/bin/agy-stats`，并将 `agy-stats` 软链至 `~/.gemini/config/skills/stats`。
- **agy-statusline** —— 面向 Antigravity CLI（`agy`）的自定义单行状态栏渲染器与管理 Skill：热路径 `scripts/statusline.py` 纯标准库零子进程渲染工作区路径智能缩写、Git 分支 / Linked Worktree（含 `agy-worktree` 会话状态联动与 `transcript.jsonl` 增量尾扫兜底 `~<branch>`）+ dirty 标记、权限模式、当前模型、Context Window 占用、单步 Prompt 缓存命中率（`⚡89%`）及分模型（Gemini / 3P）配额与倒计时，并原子写入 `cache/quota_snapshot.json` 供 `agy-stats` 消费；配套 `agy-statusline` 管理 CLI（`install` / `uninstall` / `status` / `preview` / `doctor` / `init-config`）与 `config.local.json` 主题/模块/阈值定制。将 `agy-statusline/scripts/agy-statusline` 软链至 `~/.local/bin/agy-statusline`，将 `agy-statusline` 软链至 `~/.gemini/config/skills/agy-statusline`，并执行 `agy-statusline install`。
- **agy-worktree** —— 面向 Antigravity CLI（`agy`）的三层 Git Worktree 工作流插件（`plugin.json` + `hooks.json` `PreToolUse` 护栏 + `rules/AGENTS.md` + `skills/agy-worktree/SKILL.md` + `agy-wt` CLI）：提供 `agy-wt enter/exit/close/status/list/strict/init-config/doctor` 显式管理会话级 worktree（写入 `<brain>/<cid>/scratch/worktree.json` 与 `agy-statusline` 多窗口隔离联动）；内置 `PreToolUse` 主仓库与 `protected_paths` 防误改/误删护栏（支持 `strict_main_repos` 白名单、精准放行主目录维护命令与 `.git/info/exclude` 本地文件、并拦截 worktree 内误执行 `make install`）；完整固化合并后 6 步安全收尾（diff 校验、`status -z --ignored` 防静默删忽略文件、主目录 `pull --ff-only` + `post_merge_commands`、macOS `.app` 进程退出与 `lsregister -u` 注销、无 `--force` 移除与分支清理核对）以及编译型多 worktree 共享缓存 + `lockf` 排队配方。通过 `agy plugin install <本仓路径>/agy-worktree` 安装，并将 `agy-worktree/scripts/agy-wt` 软链至 `~/.local/bin/agy-wt`。

## 已归档（archived/）
以下组件已移入 `archived/`（保留历史，不再活跃使用或挂载）：
- **bilibili2mp3**（已归档）—— B 站视频音频提取为 MP3，内嵌 CC 字幕为 ID3 歌词（USLT/SYLT）+ 旁路 LRC。
- **tiered-review**（已归档）—— 分级路由的代码审查（发现层 offload 到 grok CLI，Claude 只做验收）。
- **merge-closeout**（已归档）—— 「merge 收尾」固定 SOP（step0-6）。
- **release-flow**（已归档）—— 发版全流程 SOP。
- **multi-pr-sop**（已归档）—— 大型任务拆 stacked PR + 双工具 review 的 A-H 全流程 SOP。
- **codex-e2e-test**（已归档）—— 经 CDP 注入驱动 Codex Desktop 跑 E2E/冒烟。
- **transfer-bug-recorder**（已归档）—— 按 Codex 桌面 UI 报错语句分类/记录 bug 的知识库。
- **bilibili-compact-mcp**（已归档）—— B 站视频信息 / 字幕 / ASR / 弹幕 / 评论 MCP Server。
- **plane-index**（已归档）—— Plane 本地索引（PM 已于 2026-06-28 切回 Linear，Plane 弃用只读）。

## 安装
1. 将对应 skill 目录软链（或复制）到 `~/.claude/skills/` 或 `~/.gemini/config/skills/`；插件通过 `agy plugin install <本仓路径>/<插件名>` 安装。
2. 把 `config.example.*` 复制为 `config.local.*`,填入你的实例值(workspace / project / id / 本地路径等)。`config.local.*` 不进版本库。
3. 索引类 skill 的数据(`*.jsonl`)是生成物,不在本仓(各 skill 首次运行时自建)。

## 约定
- `SKILL.md` 只放可复用方法,**不含实例/敏感值**;实例值一律走 `config.local.*`。
- skill 创建或修改后,提交并推送到本仓。
- 不再使用的 skill 移入 `archived/`(保留历史,不参与 Claude Code / AGY 注册)。
