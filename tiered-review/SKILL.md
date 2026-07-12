---
name: tiered-review
description: 分级路由的代码审查:把多维度审查的「广度发现」层 offload 到 grok CLI(用 grok 订阅省 Claude 额度),Claude 只做高档对抗验证 + 综合。当多 agent 审查(pr-review-toolkit:* 子 agent)或 code-review workflow 被触发时,PreToolUse hook 会 deny 并把发现层改道到本 skill 的 grok 编排器。grok-only MVP(agy 第三腿暂缓)。
---

# tiered-review — 审查发现层 offload 到 grok,Claude 只验收

**目的**:一轮多 agent 审查在 Opus 上约等于单次审查的 10-30× token(finders + findings×verifiers)。把**广度发现**(最烧 token 的那层)offload 到 **grok CLI**(用户的 grok 订阅,不烧 Claude 额度);**Claude 只承担高档验收**(对抗验证杀假阳性 + 去重 + 综合)。

## 安装(install-and-use)

装好 skill 目录后**跑一次安装脚本**(幂等):

```bash
bash ~/.claude/skills/tiered-review/install.sh
```

它做三件事:① `config.example.json` → `config.local.json`;② 把 PreToolUse hook 注册进
`~/.claude/settings.json`(`Task|Workflow` matcher,改动前备份 `.bak`);③ 检查 `grok` / `jq` 前提。

**前提**:
- **grok CLI** 已装且 `grok login`(Grok Build CLI,auth 存 `~/.grok/auth.json`)—— 这是发现层后端。
- **jq**(脚本解析用)。
- hook 注册后**重开一次 Claude Code session** 才必定生效(settings 热加载不保证即时)。

卸载:删 `~/.claude/settings.json` 里 `matcher:"Task|Workflow"` 那条 PreToolUse hook(或还原 `.bak`)。

## 触发(两个明显信号,由 PreToolUse hook `hooks/route-review.py` 拦截)

- **信号 A —— 多 agent 审查**:`Task` 工具 + `subagent_type ∈ pr-review-toolkit:*`(adaptive-review 的 Fan-out / `/review-pr` / 手动 spawn)。
- **信号 B —— code-review workflow**:`Workflow` 工具 + review 脚本。
- hook 对这两个信号 **deny**,reason 里给出改跑 `tiered-review.sh` 的命令。云端 `/code-review ultra`(已在远端计费)不受此限。

> 与 [[adaptive-review]] 的关系(option A,确定性改道):adaptive-review 的 **Step 2 Fan-out 直接调本 skill 的 grok 编排器**,不再 spawn pr-review-toolkit 子 agent;hook 的 deny 只是兜底守门(万一漏走了直接 spawn)。

## 用法(Claude 收到 deny 或走 adaptive-review Fan-out 时)

### 1. 发现层 → grok(一条命令,多维度并发)

```bash
bash ~/.claude/skills/tiered-review/tiered-review.sh \
  --dims correctness-linescan,silent-failure,test-coverage,comment-accuracy \
  --base main            # 或 --diff <file>;缺省审工作区 git diff
```

- `--dims` 的值 = **lens 名**(= `config.local.json` 的 `lens_prompts` key,= adaptive-review 的 lens 名)。可用:`correctness-linescan silent-failure test-coverage comment-accuracy type-design simplification removed-behavior cross-file-impact language-pitfall wrapper-proxy dependency concurrency`。**只传本次改动实际命中的维度**(对齐 adaptive-review 的 Route:恒跑 `correctness-linescan`,加命中信号的 lens),别全上。
- (hook 从 `pr-review-toolkit:<agent>` deny 时已自动把 agent 名映射成 lens 名传进来。)
- 输出:stdout 每行一个 lens 的 JSON:`{"lens":..,"backend":"grok","findings":[{file,line,severity,summary,failure_scenario},...]}`;失败的 lens 是 `{..,"error":..}`(不中断其它)。
- grok 用 `--json-schema` 约束结构化输出(schema 见 `schemas/findings.json`),可靠可解析。

### 2. 验收层 → Claude(高档,你亲自做)

收到 grok 的 findings 后:

1. **对抗验证**(必做,杀假阳性):grok 广度发现的误报率比 Opus 高 —— 对每条 finding **逆向 refute**(主循环直接判,或派 `general-purpose`/`claude` 子 agent;**绝不再 spawn `pr-review-toolkit:*`,会被 hook 再 deny**)。判 `CONFIRMED / PLAUSIBLE / REFUTED`,REFUTED 丢弃。
2. **去重 + 排序**:跨 lens 按 `file:line` 去重,按 severity(critical→low)排。
3. **报告**:每条带 `[grok:<lens>]` 来源 + 验证结论 + `file:line` + 一句话 + 修法。`error` 的 lens 显式说明(如「grok 未登录,该维度未审」),不当作「无问题」。

## 前提 / 兜底

- **grok CLI 必须已登录**:`grok login`(auth 在 `~/.grok/auth.json`)。未登录时脚本对该 lens 输出 `error`(带「疑未登录」提示),Claude 报告里显式说明该维度未覆盖 —— **不能静默当无问题**。
- grok 输出非合法 JSON:脚本 `jq` 兜底抽 `[...]` 段;仍失败则该 lens `error`,Claude 可对该维度回退用主循环自审。
- 维度不确定 → 默认 `code-reviewer` lens(config `lens_prompts.default`)。

## 配置

- `config.local.json`(gitignore):`backends.grok.model`(默认 `grok-4.5`)、`common_preamble`、各 lens 的 `lens_prompts`。改档位/模型/prompt 都在这。模板见 `config.example.json`。

## 边界

- **grok-only MVP**:agy(antigravity CLI,低档第三腿)暂缓 —— agy 无 `--json-schema`、结构化不稳,后续再加。
- 本 skill **只管发现层 offload + 验收编排**,不改 adaptive-review 的 Route/Verify/Synthesize 语义(那套仍由 Claude 主导,只是发现的执行后端从 Claude 子 agent 换成 grok)。
