---
name: adaptive-review
description: 用户显式触发的本地代码审查:按 diff 特征自动从 lens 池选 3-6 个相关审查维度(不是固定 3-agent、也不是几十 agent 的 workflow),跑 Route→Fan-out→Verify→Synthesize,对抗式 verify 杀假阳性后按严重度出报告。替代项目「固定 3-agent 本地审查」约定。三档 quick/standard/thorough,默认 standard;thorough 复用现有 /code-review Workflow 不重造。仅用户显式触发,不自动跑。
---

# adaptive-review — 按改动自选多维度的本地代码审查

把「提交前本地审查」从**固定 3-agent**(死板、不按改动选)升级成**按 diff 特征自动选 3-6 个相关 lens** 的自适应审查:既比固定 3-agent 全面(该上的维度自动上),又比 `/code-review` 的几十 agent workflow 省额度(只跑相关的、用 Agent subagent 不走 Workflow)。

> 来源:MOC-303(2026-07-08 定案,grok PR #590 收尾后落地)。替代项目 CLAUDE.md 里「本地 3-agent 审查」约定。
> **仍是用户显式触发**(遵 2026-07-05「多 agent 审查不自动跑、用户显式触发」决策)——不在每次写完代码后自动跑。

## 何时用 / 不用

- **用**:用户说「跑 adaptive review」/「审查一下改动」/「提交前审查」/ `/adaptive-review`;或 SOP(如 grok PR 那样)到了「提交前本地审查」这一步。
- **不用**:用户只要快速看一眼某函数对不对(直接读)/ 要的是 PR 上 AI bot review(那是 push 后 chatgpt-codex-connector 的事)/ 要跨 repo 深审用 `/code-review ultra`(云端、计费,用户自己触发)。

## 核心:Route → Fan-out → Verify → Synthesize

1. **Route(便宜,零/一 agent)**:抓 `git diff`,启发式 grep 出改动信号 → 选中「恒跑核心 + 命中信号」的 lens(典型 3-6 个)。歧义时才花 1 个便宜 router agent 微调。
2. **Fan-out(N subagent 并发)**:只跑选中的 lens,每个 lens 用它对应的 agent(pr-review-toolkit 专用 agent / codex-style angle finder),scope 限定到本次改动文件。**用 Agent 工具的 subagent,不走 Workflow**(成本可控)。
3. **Verify(对抗式,杀假阳性)**:收齐 findings,每条派一个独立 verifier 逆向 refute,判 `CONFIRMED / PLAUSIBLE / REFUTED`;REFUTED 丢弃,PLAUSIBLE 标注保留。standard 档默认带。
4. **Synthesize**:按 (file,line,category) 去重、按严重度排序、封顶,出结构化报告(BLOCKER/HIGH/MEDIUM/LOW,带 file:line + 一句话 + 修法)。

## 三档(默认 standard)

| 档 | lens 数 | verify | 用途 | 承载 |
|---|---|---|---|---|
| **quick** | 2-3(恒跑核心 + top1-2 信号) | 无(单票) | 小改动 / 快速冒烟 | Agent subagent |
| **standard**(默认) | 3-6(恒跑核心 + 全部命中信号,封顶 6) | **带**(每 finding 1 verifier) | 提交前常规审查 | Agent subagent |
| **thorough** | 全相关 lens + 多票对抗 + sweep | 多票 | 高风险/大重构/安全面 | **复用现有 `/code-review` Workflow,不在本 skill 重造** |

- 用户没指定档 = **standard**。
- 用户说「快点/小改动/简单看看」→ quick;说「彻底/深审/高风险/大重构」→ thorough(直接引导走 `/code-review`,或其 ultra 变体)。

## Lens 池(~12)+ 触发信号 + 承接 agent

启发式 = 对 `git diff`(默认)或目标 range 做 grep,命中信号则点亮对应 lens。`correctness-linescan` **恒跑**。

| lens | 触发信号(grep 本次 diff) | 承接 agent |
|---|---|---|
| **correctness-linescan** | 恒跑 | `pr-review-toolkit:code-reviewer` |
| **silent-failure** | 新增 `catch`/`unwrap_or`/`.ok()`/`?` 吞错/`fallback`/空 `except`/`\|\| default`/`rescue` | `pr-review-toolkit:silent-failure-hunter` |
| **type-design** | 新增 `struct `/`enum `/`interface `/`type `/`trait ` | `pr-review-toolkit:type-design-analyzer` |
| **comment-accuracy** | 新增断言协议/wire/版本/字段/端点的注释 | `pr-review-toolkit:comment-analyzer` |
| **test-coverage** | 非测试文件加了逻辑,无对应 test 文件改动 | `pr-review-toolkit:pr-test-analyzer` |
| **simplification** | 大新增(>~80 净增行)或疑似重复/镜像代码 | `pr-review-toolkit:code-simplifier` |
| **removed-behavior** | 有实质删除行(`^-` 去掉非空非注释的逻辑) | codex-angle finder(下方) |
| **cross-file-impact** | 改了函数/方法签名、`pub`/导出接口、公共类型 | codex-angle finder |
| **language-pitfall** | 语言特有危险:Rust `.unwrap()`/`.expect(`/`as `/`mem::`;TS `any`/`==`/`!` 非空断言;Go 忽略 `err` | codex-angle finder |
| **wrapper-proxy** | 新增 wrapper/proxy/adapter/middleware 型转发代码 | codex-angle finder |
| **dependency** | `Cargo.toml`/`package.json`/`*.lock` 改动 | codex-angle finder |
| **concurrency** | 新增 `async`/`await`/`Mutex`/`RwLock`/`Arc`/`spawn`/`tokio::`/`Ordering::` | codex-angle finder |

**前 6 个 lens** 直接映射到 pr-review-toolkit 的 6 个专用 agent(`subagent_type` 用表里的名字)。
**后 6 个 codex-angle lens** 没有专用 agent → 用 `general-purpose` subagent,prompt 收窄到该 angle(见下方 Fan-out 模板),对齐 codex-review「多 correctness angle finder」的做法。

## Step 1 — Route(启发式预筛)

```bash
# 取本次改动(默认:未提交 + 已暂存的近期工作);也可传 PR / commit range
DIFF=$(git diff HEAD)            # 或 git diff <base>...<head> / gh pr diff <PR#>
FILES=$(git diff --name-only HEAD)
```

对 `$DIFF` / `$FILES` 逐信号 grep(零额外 agent),点亮 lens。示例判据:
- `silent-failure`:`git diff HEAD | rg '^\+' | rg 'unwrap_or|\.ok\(\)|catch|fallback|except|\|\| *(default|null|None)'`
- `type-design`:`rg '^\+.*\b(struct|enum|trait|interface|type) '`
- `dependency`:`echo "$FILES" | rg 'Cargo\.toml|package\.json|\.lock$'`
- `cross-file-impact`:diff 里有 `^[+-].*\bfn |^[+-].*\bpub |^[+-].*(export |function )` 且签名行两侧都动
- `concurrency`:`rg '^\+.*(async|await|Mutex|RwLock|Arc<|tokio::|spawn|Ordering::)'`
- `removed-behavior`:`git diff HEAD | rg '^-' | rg -v '^--- ' | rg -v '^-\s*(//|#|\*|$)'` 有实质删除
- 其余同理(comment-accuracy 看新增注释含协议/版本/wire 断言词;wrapper-proxy 看新增 adapter/proxy/wrapper 命名 + 转发调用)。

**选择规则**:`correctness-linescan` 恒进;每个命中信号的 lens 进;**standard 封顶 6**(超了按严重度优先级保留:silent-failure > correctness > cross-file-impact > removed-behavior > type-design > concurrency > language-pitfall > dependency > 其余,并 `log()`/在报告里说明砍了哪些)。**quick 封顶 3**(核心 + top2)。

**歧义才上 router agent**(默认不上):当 diff 大而杂、信号交叉难定 top-N 时,派 1 个便宜 `general-purpose`(可 `model: haiku`)agent:「给你 diff 的文件清单 + 信号命中表,从 lens 池选最相关的 3-6 个并排序,只回 JSON」。否则纯启发式即定。

## Step 2 — Fan-out(发现层 → grok,省 Claude 额度)

**发现层改走 grok CLI**([[tiered-review]] skill,2026-07-12 定案 option A):**不再** spawn pr-review-toolkit / general-purpose finder 子 agent(那烧 Claude 额度)。把 Route 选中的 lens 一次性交给 grok 编排器,用 grok 订阅出结构化 findings:

```bash
bash ~/.claude/skills/tiered-review/tiered-review.sh \
  --dims <Route 选中的 lens 逗号拼,如 correctness-linescan,silent-failure,test-coverage> \
  --diff <Step 1 的 DIFF 文件>        # 或 --base <ref>;缺省审工作区 git diff
```

- `--dims` 用 Route 选中的 **lens 名**(= tiered-review `config.lens_prompts` 的 key,含 6 pr-toolkit + 6 codex-angle 全部 lens)。
- 输出:每 lens 一行 JSON `{lens, backend:"grok", findings:[{file,line,severity,summary,failure_scenario}]}`;grok 用 `--json-schema` 约束结构化,可靠可解析。
- **`error` 的 lens** 在报告里**显式说明**「grok 该维度未审(原因)」,**不当作无问题**。
- **前提**:grok 已 `grok login`(auth `~/.grok/auth.json`)。未装/未登录 → tiered-review.sh 对该 lens 回 error;此时回退老路(spawn subagent)或提示用户登录。
- PreToolUse hook `tiered-review/hooks/route-review.py` 会 deny 直接 spawn 的 `pr-review-toolkit:*` 子 agent 作兜底守门(防漏走成 Claude 额度)。**验证/综合仍用 Claude(见 Step 3/4),别在那里 spawn pr-review-toolkit(会被再 deny)。**

## Step 3 — Verify(standard/thorough 带;quick 不带)

收齐所有 lens 的 findings,**每条**派 1 个独立 `general-purpose` verifier(和 finder 不同 agent,避免自证):
> 逆向核验这条 finding:<finding>。回到 `<file:line>` 真实代码,尝试**证伪**它。判定 `CONFIRMED`(能给出具体触发输入→错误结果)/ `PLAUSIBLE`(合理但无法坐实)/ `REFUTED`(假阳性/读错代码/pre-existing/不适用)。不确定倾向 REFUTED。回 `{verdict, reason, (CONFIRMED 时)repro}`。

- **REFUTED 丢弃**;CONFIRMED 保留;PLAUSIBLE 保留但报告里标 ⚠️「待人确认」。
- findings 多时 verifier 并发(barrier:全 verify 完再 synthesize)。

## Step 4 — Synthesize + 报告

- **去重**:同 (file, 邻近 line, category) 合并,多 lens 命中同一处 = 该条置信度更高,合并保留最具体的描述。
- **排序**:BLOCKER → HIGH → MEDIUM → LOW;同级按 file 聚。
- **封顶**:默认 top ~15,超出在末尾注明「另有 N 条 LOW 已折叠」。
- **报告格式**(给用户,对齐旧 3-agent 审查产出):
  ```
  ## adaptive-review(standard 档,跑了 N 个 lens:<列出>)
  ### 🔴 BLOCKER / HIGH
  - `file:line` [lens] 一句话问题 → 触发场景 → 修法
  ### 🟡 MEDIUM / LOW
  - …
  ### ⚠️ PLAUSIBLE(verify 未坐实,待你判断)
  - …
  > 砍掉的 lens:<若封顶砍了哪些>;REFUTED 假阳性:<N 条,不列>
  ```
- 若零 CONFIRMED/PLAUSIBLE:明确回「N 个 lens 跑完,verify 后无存活问题」(不硬凑)。

## 成本纪律

- quick/standard **只用 Agent subagent**,不用 Workflow(几十 agent 那套只在 thorough 且由 `/code-review` 承载)。
- 典型 standard = 3-6 finder + 其 findings 数个 verifier,量级远低于 `/code-review` 的全量 angle×verify×sweep。
- router agent 默认不起(纯启发式);只有 diff 大而杂才花 1 个便宜的。
- **不静默砍覆盖**:因封顶/信号漏判而没跑的 lens,必须在报告里列出(让用户知道哪些维度没审)。

## 与既有资产的关系

- **复用**:pr-review-toolkit 的 6 个 agent 定义(不重写)、codex-review 的 angle/verify 结构思路。本 skill 的增量 = **router(自动选 lens)+ 分档 + 统一 synthesize**。
- **thorough 不重造**:直接引导用户走 `/code-review`(或 `/code-review ultra` 云端计费版),本 skill 不复制其 Workflow。
- **替代**:项目 CLAUDE.md「提交前跑固定 3-agent 本地审查」约定,今后指向本 skill 的 standard 档。
