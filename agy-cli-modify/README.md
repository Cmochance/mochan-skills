# agy-cli-modify

面向 **Antigravity CLI（`agy`）** 的轻量常驻提速插件（`plugin.json` + `rules/AGENTS.md`）。

## 定位

- **0 额外读取回合**：以原生 Plugin 常驻规则直接注入上下文（仅约 400 tokens，占默认 20k 规则预算约 2%），无需每次触发时先 `read_file` 读取 `SKILL.md`。
- **与 `oil-oil/agy-fast-io`（MIT）的差异与适配**：
  - **剥除桌面端静态白名单限制**：`agy` CLI 运行于本地沙盒，不存在 Antigravity Desktop 的云端小模型命令排队审查；恢复了 `rg`、`jq` 与管道限流（`| head -n 80`），避免退回 `grep -rn` 扫入构建目录与 `.gitignore` 文件。
  - **对齐 CLI 800 行 / 46KB 上限与双阶段架构**：区分「准备修改的文件（≤800 行一次整读；>800 行并发读文件头 + 目标段）」与「只读追踪 / 大文件（`rg -n` 定位后按前 25 行 + 后 150 行并发切片）」，压缩高成本 Plan 调查阶段往返回合。
  - **macOS `zsh` 防阻塞规范**：glob 参数强加单引号规避 `zsh` 默认 `NOMATCH` 报错；Git 查看命令统一 `--no-pager` 与条数上限。
  - **沙盒分层与免审批前缀保护**：沙盒内步骤用 `&&` / `;` 合并；跨 `BypassSandbox: true` 边界的命令保持独立单条并直调目标二进制，不破坏 `"always allow"` 前缀匹配。
  - **高信噪比回答（带场景豁免）**：结论先行、用 `file://` 行号链接代替贴回大段代码、常规回答控在 1500 字内；方案评审 / Plan 交接 / 明确要求深讲时自动豁免。

## 安装与管理

在仓库外或 `<mochan-skills>` 目录下执行：

```bash
# 1. 严格校验插件清单与规则文件
agy plugin validate <mochan-skills>/agy-cli-modify --strict

# 2. 安装到本地 agy 配置目录（~/.gemini/config/plugins/agy-cli-modify）
agy plugin install <mochan-skills>/agy-cli-modify

# 3. 查看已安装插件与启用状态
agy plugin list

# 4. 按需开关
agy plugin disable agy-cli-modify
agy plugin enable agy-cli-modify
```

## 来源与致谢

工作流思路借鉴社区项目 [`oil-oil/agy-fast-io`](https://github.com/oil-oil/agy-fast-io)（MIT License），规则正文针对 macOS 下的 `agy` CLI 从零重写。详见 [`NOTICE`](NOTICE)。
