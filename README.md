# mochan-skills

Cmochance 自建的 Claude Code skill 集合。每个 skill 采用**两层结构**:
**通用方法**(`SKILL.md`,可公开)+ **实例配置**(`config.local.*`,含 workspace/项目/id 等本地值,**不提交**)。

## Skills
- **linear-index** —— Linear issue 本地索引:按编号/关键词/状态/标签/里程碑/归档检索,先查本地索引再按需 MCP 拉详情;含增量/全量刷新。PM conventions(issue 自动配置/milestone 归桶/followup 建档/同步机制)走 `config.local.pm-conventions.md`。
- **merge-closeout** —— 「merge 收尾」固定 SOP(step0-6):stacked base 解耦、squash merge、产物转移、清理 verify、Linear transition + 强制相关 issue 扫描;含 fork PR / 首次贡献者 approve / 深层 stacked / reviewThreads 分页等变体附录。
- **release-flow** —— 发版全流程:dispatch 前预发布微 PR(版本号 bump + 双语 release notes 硬模板 + notes 文件 CI 门禁)、版本校验、build 完保持 draft 等显式确认。
- **multi-pr-sop** —— 大型任务拆多个 stacked PR + 双工具 review 的 A-H 全流程 SOP。
- **transfer-bug-recorder** —— 按 Codex 桌面 UI 报错语句分类/记录 bug 的方法与知识库结构。
- **codex-e2e-test** —— 经 CDP 注入驱动真实运行的 Codex Desktop 跑一轮对话做 E2E/冒烟。
- **reverse-engineering** —— 逆向 / 授权安全研究 / CTF 的方法论与工具路由:`SKILL.md` 入口按目标分流,`references/` 分域(二进制/语言运行时/移动端/JS 前端/固件/模式识别/pwn/patch-diff/授权渗透/内网AD/LLM安全/game/恶意样本与供应链/CTF)。改写自社区 `reverse-skill`,**剥除了其全局注入 / 服从性工程 / 安全护栏绕过**机制,只保留知识价值;高危进攻域收敛在方法论+检测视角。
- **Rust-Skill** —— Rust 编程的方法论 + 路由 + 三层知识库:`SKILL.md` 入口按问题层级(语言机制/工程设计/领域)分流,`references/` 含 17 个概览子域(所有权/类型trait/错误/并发async/unsafe/宏 + api/性能/测试/cargo/可观测/serde + web/cli/embedded/wasm/systems)、`error-codes.md`(E0xxx→根因域)、`rules/`(265 条习惯/反模式,逐字移植 leonardomso MIT)、`recipes/`(28 篇任务配方)、`examples/`(18 篇概念用例)、`deep/`(37 章设计模式书,MPL-2.0)、`templates/`。架构思路借鉴 `actionbook/rust-skills`(仅结构,无文字拷贝),知识来源与许可见 `Rust-Skill/NOTICE`。
- **agy-cli-modify** —— 面向 Antigravity CLI（`agy`）的轻量常驻提速插件（`plugin.json` + `rules/AGENTS.md`，0 额外读取回合）：`rg -n` 精准定位 + 按编辑/只读场景非对称切片读取、macOS `zsh` 通配符与 `--no-pager` 防阻塞、沙盒分层命令合并与免审批前缀保护、高信噪比回答。思路借鉴社区 `oil-oil/agy-fast-io`（MIT），剥除了桌面端云端审查静态白名单（禁 `rg`/管道等）对 CLI 本地沙盒的反优化约束。通过 `agy plugin install <本仓路径>/agy-cli-modify` 安装。

## 安装
1. 复制对应目录到 `~/.claude/skills/`。
2. 把 `config.example.*` 复制为 `config.local.*`,填入你的实例值(workspace / project / id / 本地路径等)。`config.local.*` 不进版本库。
3. 索引类 skill 的数据(`*.jsonl`)是生成物,不在本仓(各 skill 首次运行时自建)。

## 约定
- `SKILL.md` 只放可复用方法,**不含实例/敏感值**;实例值一律走 `config.local.*`。
- skill 创建或修改后,提交并推送到本仓。
- 不再使用的 skill 移入 `archived/`(保留历史,不参与 Claude Code 注册):当前有 **plane-index**(PM 已于 2026-06-28 切回 Linear,Plane 弃用只读)。
