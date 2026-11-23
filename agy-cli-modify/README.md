# agy-cli-modify

面向 **Antigravity CLI（`agy`）** 的轻量提速插件（`plugin.json` + `hooks.json` `SessionStart` + `rules/AGENTS.md`）。

## 架构与能力（v1.1.0）

- **1. 零阻塞首帧工作区快照（`hooks.json` + `scripts/session-start.sh`）**
  - 仅注册 `SessionStart` 钩子（`PreToolUse` / `PostToolUse` 保持零拦截、0ms 额外开销），以 POSIX `sh` + `jq` 在 `<40ms` 内完成注入，失败自动静默回退 `{}` 不阻塞会话启动。
  - **双模式自动感知**：
    - `mode=git-repo`：处于 Git 仓内时，注入根路径、当前分支、脏文件计数/样本、顶层源码目录及最近 3 条提交。
    - `mode=multi-dir`：处于多仓父目录时，自动识别各子目录工程标记（`git` / `Swift` / `Rust` / `Node` / `Py` / `Go`）及根目录关键构建/说明文件，过滤噪声产物目录与无关个人数据文件。
- **2. 常驻提速规则（`rules/AGENTS.md`）**
  - **定位、符号骨架与切片读取**：利用 `[workspace snapshot]` 免去开局 `ls` 探路；`rg -n` 先拿行号；`> 800` 行陌生大文件先抽符号骨架再切片；待编辑文件 `≤ 800` 行整读，只读追踪按「前 25 行 + 后 150 行」并发切片；跨 `≥ 8` 文件广域摸底交给 `research` 子代理隔离主对话历史。
  - **macOS `zsh` 防阻塞**：恢复沙盒内 `rg`、`jq` 与管道限流；glob 强加单引号规避 `zsh` 默认 `NOMATCH`；Git 查看命令统一 `--no-pager`。
  - **沙盒分层与静默构建（Quiet-on-Success）**：沙盒内编译/单测用 `&&` 合并并默认带静默标志（`-q` / `--quiet` / `--silent`），通过零刷屏、失败保留完整报错栈；跨 `BypassSandbox: true` 边界保持独立单条命令并直调目标二进制，保护 `"always allow"` 前缀匹配。
  - **零中间废话与高信噪比回答**：连续工具调用轮零过程播报；结论先行、`file://` 行号链接代贴码、常规回答控在 1500 字内（方案评审 / Plan 交接 / 明确要求深讲时自动豁免）。

## 安装与管理

```bash
# 1. 严格校验插件清单、规则与 hooks
agy plugin validate <mochan-skills>/agy-cli-modify --strict

# 2. 安装/更新到本地 agy 配置目录（~/.gemini/config/plugins/agy-cli-modify）
agy plugin install <mochan-skills>/agy-cli-modify

# 3. 查看已安装插件与启用状态
agy plugin list

# 4. 按需开关整套插件，或仅在 hooks.json 中置 "enabled": false 关闭首帧快照
agy plugin disable agy-cli-modify
agy plugin enable agy-cli-modify
```

## 来源与致谢

规则与脚本针对 macOS 下的 `agy` CLI 从零编写，工作流思路综合借鉴了 `oil-oil/agy-fast-io`（MIT）、`INK-Q/agy-fast`、`rtk-ai/rtk`、`JuliusBrussee/caveman` 等社区项目。详见 [`NOTICE`](NOTICE)。
