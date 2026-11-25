---
name: multi-pr-sop
description: 大型任务拆多个 stacked PR + 双工具 review 的完整 SOP(A-H 章节):CI trigger 适配 stacked PR、单 PR 全程双轨记录、CI 绿即 mark ready、PR-comment Monitor 与子代理 fix 判断表、stacked 链 retarget/force-push、hotfix 盘点、review 反馈循环、SOP 自进化机制。规划或推进多 PR / stacked PR 的重构、清理类大型任务时使用。
---

# 多 PR / Stacked PR 大型任务 SOP

> 来源:项目 auto-memory 迁移(2026-07-03)。深层 stacked squash merge 的收尾操作另见 merge-closeout skill 附录 E。


适用场景:大型任务拆成多个 stacked PR, Claude 写代码 + codex 后台 review, 典型如本仓库 cleanup-plan Phase 1-4 + hotfix。

## A. 前期准备

**A1. CI trigger 必须支持 stacked PR**
做 stacked PR 链之前先确认 `.github/workflows/ci.yml` 的 `on.pull_request.branches:` **不限 main**(用 `pull_request:` 不带 branches 字段)。否则 base=feature/* 的 stacked PR 不触发 CI, review 时只看 mergeable_state 会误判"没问题"。

**A2. dispatch-only workflow 的"合并前验证"是个伪命题**
`workflow_dispatch` 要求 workflow 文件已存在于 default branch (main)。新增 release.yml 这种 PR, **合并前**根本没法 dispatch test (workflow 还在 feature branch)。验证只能合并后做 — 因此 release pipeline 类 PR 必须接受"先合 → dispatch → 暴露问题 → hotfix PR"循环, 不要在 PR description 里写"合并前必须 dispatch test"这种做不到的事。

## B. 单 PR 全程

**B1. PR description + 评论双轨写"剩余在你侧"**
PR description 写一份, ready 时再 `gh pr comment` 写一份。用户 review 看的是评论, 不会回头读 description。

**B2. 文档不能 over-claim**
归档/完成态文档必须等 PR 真正合并后才写。期间用"待 PR #X 合后归档"或"Phase N PR ready 待合"等中性表述。反例:phase-4 顶部写"Phase 1-4 全部完成"被 review 抓到事实不一致。

**B3. CI 全绿后立即 mark ready + 接续下一轮**
不等用户合并。新工作走 stacked PR (base 设上一个 feature 分支)。同步给下轮任务树。

**B4. CI 跟踪默认 step-level + 不问**
`gh run list` 拿 ID + 立即起 Monitor (step-level + 240s heartbeat 带 in_progress step + elapsed)。多 PR 并发起多 Monitor。不问"要我跟踪吗"。

**B5. 4min30s 内必有输出**
防 prompt cache miss。Monitor heartbeat 给的是这个保障; 静默工作期间也要主动文本汇报当前状态。

**B6. PR ready 后立即起 PR-comment Monitor + 子代理 fix 模式**
PR ready (CI 全绿) 后立即起 persistent PR-comment Monitor (命令模板见附录 X1):
- 触发条件: 新 comment id 不在 last_seen 文件 + body 不含 `🤖 Generated with [Claude Code]` footer
- 自停条件: PR state ≠ OPEN (MERGED/CLOSED 自动 exit, 无残留进程)

收到 Monitor 通知后, 主 Claude 必须**先判断评论性质**, 再决定是否起子代理:

| 评论类型 | 处理方式 |
|---|---|
| **review 反馈含具体阻塞点 / 代码改动建议** | 起子代理 fix (`Agent({ subagent_type: "general-purpose", isolation: "worktree", run_in_background: true })`, prompt 模板见附录 X2) |
| 测试 / 闲聊 / 询问 / 通知性 | 主 Claude 直接 `gh pr comment` 简短回应, 不起子代理 |
| 致谢 / "looks good" / "thanks" | 主 Claude 一句 `gh pr comment` 致谢回, 不起子代理 |
| 含 `?` 的开放问题 | 主 Claude 直接答, 不起子代理 |

**判断启发式**: 评论含"建议 / 应该 / 修 / fix / 改成 / 必须"等动词 + 引用代码/文件路径 → 起子代理; 否则主 Claude 自处理。模糊不清宁可起子代理 (主 Claude 不容易被打断), 不要漏处理。

**自我循环防范** (已实战验证):
- Claude 自己写的评论 footer 含 `🤖 Generated with [Claude Code]`, Monitor 已过滤
- 子代理 push 触发的新 CI 评论是 GitHub bot, author 不是 Cmochance, 不触发误判
- 子代理在 PR 评论里也带 footer, 不会引发自循环

## C. Stacked PR 链

**C1. GitHub 不会自动切 base**
base PR squash-merge 到 main 后, stacked PR 的 base 字段**不会自动**改。必须:
1. `gh pr edit <stacked> --base main` 显式 retarget
2. 本地 `git rebase origin/main` 或 reset+cherry-pick 重新 base 到 main
3. `git push --force-with-lease`

**C2. retarget + force-push 后 CI 可能不触发**
GH 偶发不识别 force-push 为有效变更。立即 `gh workflow run ci.yml --ref <branch>` 手动触发, 不要等。

**C3. retarget 时同步合入新 review 反馈**
如果上游 PR (base PR) 暴露了问题已经在另一个 hotfix PR 修了, retarget stacked PR 时把 hotfix 也 cherry-pick 进来, 这样 stacked PR 独立合并即获完整修复。

**C4. stacked PR retarget to main 后 diff 看起来含上游 commits**
正常现象。等上游 PR squash-merge 到 main, GH 重算 diff 自动 dedup, 只剩 stacked PR 自己的 unique commits。在 PR 评论里说明这一点, 避免 reviewer 担心"会把上游问题带进来"。

## D. Hotfix 出现时

**D1. 盘点所有 ready PR 是否含同样 bug**
hotfix 第一时间, 盘点其他 ready PR 是否也包含同 bug (尤其 stacked PR)。统一在所有受影响 PR 修 (cherry-pick 或同源 commit), 避免 hotfix 合后其他 PR 又出同样问题。

**D2. hotfix PR 与含 hotfix 的主线 PR 二选一合**
两个都修后会冗余。合主线 PR (含修复) 的 hotfix PR 关掉; 反之合 hotfix PR 的主线 PR rebase 后该 commit 自动消失。

## E. 双工具 review 反馈循环

**E1. 完整读所有 review 阻塞点再修**
不要只修第一条就 push。review 通常给完整列表, 漏修一条又会再 review 一轮。

**E2. 修复 commit message + PR 评论必须明确对应反馈点**
"PR #X commit Y 修了 review #Z 的第 N 点"。让 reviewer 一眼能对账。

**E3. 接受 dispatch test 失败 → hotfix → 再 dispatch 的多轮循环**
release pipeline 这种集成度高的工作, 一次 dispatch 通常暴露多层问题 (project bug / runner 抖动 / secret 配置)。每轮 hotfix 修一类问题。本次 cleanup 系列实际用了 4-5 轮。

**E4. macOS GH runner 网络抖动 (DNS) 不算项目 bug**
日志看到 `codeload.github.com: nodename nor servname provided` 之类是 runner 网络问题, 用 `gh run rerun --failed` 重跑即可, 不要在项目代码里加 retry 兜。

## F. 外部调研 vs 实测

**F1. 工具配置以实际校验为准**
Tauri config 字段 / Rust crate API 等, 调研给方向但不能信。落地必须本地 `cargo check` / 工具 lint 确认通过, 不依赖 CI 兜底。

**反例**:Agent 调研给的 Tauri 2 `bundle.fileName` 字段, 实际 `tauri-build` schema 不存在, 第一次 CI 才报 "unknown field"。应该本地 cargo check 先确认。

**F2. secret 在 GH Actions 不存在时仍传空字符串**
工具会把空字符串当成"指定值"用 (典型 codesign 用空 identity 找 keychain → 失败)。必须 `_RAW` 后缀接 secret + run 内 `[[ -n ]]` 判空再 export。

## G. Memory 管理

**G1. 发现新模式立即写 feedback memory**
每次成功/失败的非显然规则, 当场写 feedback (规则 + Why + How to apply 三段式)。不要等"以后再补"。

**G2. MEMORY.md 索引行简短**
每条 1 行 ~150 字符内, 用户/Claude 读 MEMORY.md 时一目了然该取哪条。详细规则在子文件。

## 流程图(总览)

```
任务起 → 拆 Phase → 每 Phase 1 PR
     ↓
[A1] 检查 ci.yml trigger 支持 stacked PR
     ↓
Phase 1 PR (base=main) → CI 全绿 → ready → 评论行动项 → 用户合
     ↓
[B3] 立即接续 Phase 2 (base=phase-1, stacked draft)
     ↓
[A2] release pipeline 类 PR: 接受合并后 dispatch test
     ↓ (用户合 phase-1 后)
[C1] phase-2 PR retarget base=main + rebase
[C2] 手动触发 CI
     ↓
phase-2 合 → dispatch test → 暴露问题
     ↓
[D1] 盘点所有 ready PR 是否含同 bug
[D2] hotfix PR 或 cherry-pick 进 ready PR (二选一)
     ↓
[E3] 多轮 hotfix → dispatch 循环直到 release pipeline 真正绿
     ↓
[B2] 全部合后再写"清理已完成"归档文档
```

## H. 本文档自身的进化机制

**H1. 何时更新**
每次完成一个多 PR 任务后(无论成功还是失败), Claude **主动 review 本 SOP**:
- 实际过程是否完全按 SOP 走? 偏差在哪?
- 是否遇到 SOP 没覆盖的场景?
- 已有规则是否被反例打破?

**H2. 怎么更新**
- **追加新规则** → 在对应章节(A-G)末尾加新编号(A4/B6/C5...)
- **修订已有规则** → 直接改原条目, 在条目末尾加 `(修订:<日期>, 因 <原因>)`
- **删除过时规则** → 不真删, 改成 `**(deprecated <日期>)**` + 一句替代说明
- **重大流程改动** → 在文档最末尾加"修订日志"小节(`| 日期 | 改动 | 原因 |`)
- **流程图同步** → 任何 A-G 改动影响流程的, 流程图同步更新

**H3. 谁触发**
Claude 自动在以下时机 trigger:
- 任务汇报完成("4 个 PR 全合"等)的同一个 turn 内, 主动给"SOP 进化提议", 列改动 + 等用户确认后写入
- 遇到本 SOP 没覆盖的全新场景时, 先按当时最优解处理, 处理完立即提议补充
- **不要静默改**, 任何 SOP 改动必须先在对话里给草稿, 用户确认后再 Write/Edit memory

**H4. 防过度膨胀**
SOP 不是日志。每次更新前先问:这条规则是不是已经被 A1-G2 某条覆盖了?如果是, 合并到那条而非新建。
单条规则 > 5 行时拆成子条目;整个 SOP 超过 200 行时考虑把某章节拆出独立 memory。

## 附录 X. 命令模板

### X1. PR-comment Monitor (B6 用)

```bash
PR=<#>
LAST_FILE=/tmp/pr-comment-watch-$PR.lastid
echo "[PR$PR] watch started, persistent, polls 120s"
while true; do
  data=$(gh pr view $PR --json state,comments 2>/dev/null) || { echo "[PR$PR poll fail, retry 60s]"; sleep 60; continue; }
  state=$(jq -r '.state' <<<"$data")
  if [ "$state" != "OPEN" ]; then
    echo "[PR$PR] state=$state, monitor exits"
    break
  fi
  latest=$(jq -c '.comments[-1] // empty' <<<"$data")
  if [ -z "$latest" ]; then sleep 120; continue; fi
  latest_id=$(jq -r '.id' <<<"$latest")
  prev=$(cat "$LAST_FILE" 2>/dev/null || echo "")
  if [ "$latest_id" = "$prev" ]; then sleep 120; continue; fi
  body=$(jq -r '.body' <<<"$latest")
  author=$(jq -r '.author.login' <<<"$latest")
  if echo "$body" | grep -qF "🤖 Generated with [Claude Code]"; then
    echo "[PR$PR self-comment by $author, skip] id=$latest_id"
    echo "$latest_id" > "$LAST_FILE"
    sleep 120; continue
  fi
  preview=$(echo "$body" | head -c 500 | tr '\n' ' ')
  echo "[PR$PR new comment from $author] id=$latest_id"
  echo "[PR$PR preview] $preview"
  echo "$latest_id" > "$LAST_FILE"
  sleep 120
done
```

通过 `Monitor({ persistent: true, command: <上述脚本, 替换 PR=<#>> })` 启动。

### X2. 子代理 PR-fix prompt (B6 用)

```
你是 Claude Code 的子代理, 任务: 修 PR #<X> 的最新 review 反馈。

仓库: <owner/repo>
PR 分支: <branch>
当前 head sha: <sha>

Review 评论原文 (来自 codex / 用户):
<完整 body>

按照仓库 SOP (~/.claude/projects/.../memory/feedback_multi_pr_review_sop.md
的 E 章节"双工具 review 反馈循环") 处理:
- E1: 完整读所有阻塞点再修, 不要漏修
- E2: commit message + PR 评论必须明确对应反馈点
- E4: macOS DNS 抖动不算 bug, 见到这种日志在 PR 评论说"GH runner 网络问题, 已建议 rerun"

工作流程:
1. git fetch + git checkout <branch> 拉最新 head
2. 按 review 每点修代码
3. cargo fmt --all && cargo check --workspace 本地必须先过
4. git add -A && git commit -m "fix(<scope>): 修 PR #<X> review 反馈点 <编号>"
5. git push (force 必需用 --force-with-lease)
6. gh pr comment <X> 写: "✅ commit <sha> 修了 review 反馈第 N 点 (摘要)"
7. 报告 (返回 result): commit sha + push 是否成功 + gh pr comment URL

失败 fallback: 第 2-5 步任意步骤卡住, 不要硬干, 在最终 result 里说明
"卡在 X 步, 原因 Y", 让主 Claude 接管.

**禁止**:
- 不要起 sub-Monitor / sub-Agent (避免套娃)
- 不要修改本 PR 之外的任何文件
- 500 字内完成全部 7 步动作 + 最终 commit URL
```

通过 `Agent({ subagent_type: "general-purpose", isolation: "worktree", run_in_background: true, prompt: <上述, 替换 <X> <branch> <sha> <body>> })` 启动。
