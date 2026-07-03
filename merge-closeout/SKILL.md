---
name: merge-closeout
description: 用户说「merge 收尾」时的固定收尾 SOP(step0-6):stacked child PR base 解耦、squash merge、.app 转移加 test 前缀、清理远端/本地/worktree 并逐项 verify、关联 GitHub issue、Linear MOC transition + step6.2 强制扫描未完成 issue 挂强相关。含搭车改动补 Done issue、外部 contributor workflow approve、fork PR 收尾差异、深层 stacked squash、reviewThreads 分页坑等变体。没听到「merge 收尾」明确指令绝不主动 merge。
---

# merge 收尾 SOP

> 来源:项目 auto-memory 迁移(2026-07-03),原文归档于 ~/alysechen/github/archives/claude-memory-migration-2026-07/。
> 触发:用户当条消息说「merge 收尾/合并收尾」。**开本文全文执行,勿凭记忆摘要跑流程。**


## 主流程(step 0-6)

**触发**: 用户显式说"**merge 收尾**" / "merge 收尾一下" / "收尾" 等。**不要**在没听到这个明确指令时主动 merge。

**Why**: 用户 2026-05-17 PR #185 完成时一次性把"merge + .app 转移 + 回 main + 清理"4 步打包成一个动词"merge 收尾"。这是高频固定流程,每条手敲会浪费来回 round-trip。

**How to apply**(必须按顺序,每一步 verify 再下一步):

### 0. (stacked PR only) 解耦 child PR 的 base — 必须 merge 前做

**触发**: 本 PR 是 stacked PR 中间层(main ← 本 PR ← child PR)。先查:

```bash
# 列所有以本 PR head branch 为 base 的 open PR
gh pr list --base <本 PR head branch> --state open --json number,headRefName,title
```

**如有 child PR**: **必须先把每个 child PR base 改到 main**(或本 PR 当前 base):

```bash
for CHILD in <child PR#>; do
  gh pr edit "$CHILD" --base main
done
```

**Why**: GitHub `gh pr merge --squash --delete-branch` 删 head branch 时, **以该 branch 为 base 的 open PR 会被 GitHub 自动关闭** (不是改 base, 是直接 CLOSED)。
**反例 (2026-05-20 PR #206 复盘)**: 直接 squash merge #206 时, stacked child PR #229 被自动 CLOSED + base ref 不存在导致 reopen 失败, 必须重建临时 base ref → reopen → 改 base → 删临时 ref 四步 API mutation 补救。

**Why 不能合并 stacked PR 先变单 PR 再 merge**: 那是另一条路径(child PR 先 merge 进 parent), 但 child PR 通常还在 review 阶段不能 merge, 否则会被 user 拦"另一 PR 需要审查"。解耦 base 让两个 PR 独立 merge 是更通用方案。

### 1. 展示 PR(给用户最后 last-look)→ `gh pr ready` → 等 CI 全绿 → merge

听到 merge 收尾指令后,**不要直接 ready+merge** — 先把 PR 展示给用户,留 last-look 窗口(catch 漏看的 review thread / 临时改变主意 / 想合并前再补一刀)。

```bash
# 1a. 展示 PR(给用户最后 review 入口 + 大块 stats)
# 用户 2026-06-06 指示收尾不 open app / 不开浏览器 → **跳过 --web**,只在对话里报 URL+stats
# gh pr view <PR#> --web                         # (默认跳过;需要时才浏览器打开 PR)
gh pr view <PR#> --json title,additions,deletions,changedFiles,baseRefName,headRefName \
  --jq '"=== \(.title) ===\nbase: \(.baseRefName)  head: \(.headRefName)\n+\(.additions) -\(.deletions) across \(.changedFiles) files"'
gh pr diff <PR#> --name-only                    # 改动文件列表(diff stat 也行)
# 同步在对话里给用户报告 PR URL + 大块改动 + 任何已知风险/followup

# 1b. 判断是否 draft;draft 必须先 ready 才能 merge(否则 mergeStateStatus 永远 BLOCKED)
IS_DRAFT=$(gh pr view <PR#> --json isDraft --jq .isDraft)
if [ "$IS_DRAFT" = "true" ]; then
  gh pr ready <PR#>              # 转 ready → 触发 ci.yml + no-ai-coauthor.yml
  # 等 CI 重新触发完成(2-5 min)
  gh pr checks <PR#> --watch
fi

# 1c. verify CI 已全绿,reviewDecision 不阻塞
gh pr checks <PR#> --json bucket --jq 'all(.bucket=="pass")'
# squash merge(项目默认 squash;subject 沿用 PR title 不改)
gh pr merge <PR#> --squash --delete-branch
```

**Why 展示 PR 这一步**: 用户 2026-05-26 显式指示 — 收尾时不能 ready+merge 一气呵成,先给 last-look 窗口。`gh pr view --web` 在浏览器开 PR 让用户能扫 review thread / Files Changed / Devin Review 评论;对话里同步报 URL + stats 是给用户一眼判断"哦这 PR 我没忘什么"的 anchor。展示完不需要等用户额外确认(merge 收尾指令就是确认),直接进 1b。

**Why `gh pr ready` 步骤**: 2026-05-26 起 CI workflow 改成 `pull_request: types: [..., ready_for_review]` + 加 `if: draft == false` job filter(省 push-time CI 资源,见 PR #277),draft PR 期间所有 required check 处于 SKIPPED,虽然 branch protection `mergeStateStatus=CLEAN`(skip 视作 pass),但 GitHub 仍拒绝 merge draft PR(`gh pr merge` 报 "Cannot merge draft pull request")。`gh pr ready` 触发 `ready_for_review` 事件,CI 才会真正跑出 4 个 success,且 PR 进入可 merge 状态。

**已经 non-draft 的 PR**(老流程遗留 / 用户手动 `Create pull request` 非 draft 模式):`gh pr ready` 对已 ready 的 PR 会报 "already ready" 但 exit 0,流程安全,可无脑跑。

`--delete-branch` 会同时删 GitHub 上远端 branch + 本地分支(如果 tracking)。如失败(分支保护 / chatgpt-codex unresolved thread)看 `~/.claude/CLAUDE.md` 顶部 "PR push 后必查 chatgpt-codex-connector review threads" 规则。

### 2. 把 worktree 内最新 .app 转移到主仓 dist/mac/(**必须加 `test ` 前缀**)

```bash
WORKTREE=/Users/alysechen/alysechen/github/codex-app-transfer-worktrees/<branch>
MAIN=/Users/alysechen/alysechen/github/codex-app-transfer
mkdir -p "$MAIN/dist/mac"
rm -rf "$MAIN/dist/mac/test Codex App Transfer.app"  # 老 test 版本清掉
cp -R "$WORKTREE/dist/mac/Codex App Transfer.app" "$MAIN/dist/mac/test Codex App Transfer.app"
# verify
stat -f %m "$MAIN/dist/mac/test Codex App Transfer.app/Contents/MacOS/codex-app-transfer"
```

**Why 加 `test ` 前缀**(2026-05-18 用户明示约定):用户 `/Applications/Codex App Transfer.app` 是日常用的正式版,项目仓 `dist/mac/` 是开发版。**两个 .app 同名时 Dock / Finder / Cmd-Tab 无法直观区分**,导致测试时分不清开的是哪个 binary。加 `test ` 前缀让开发版在 macOS UI 上一眼可辨;只动 `dist/mac/`,**绝不**改 `/Applications/` 用户正式版的名字。

**Why 转移而非保留 worktree**: 用户运行的 .app 是 `$MAIN/dist/mac/` 路径,worktree 删除后 .app 会失效;同时 worktree 也是别处 `make mac-app` 的副本,本身不持久化(`feedback_app_build_dest`)。

### 3. 回 main + 同步

```bash
# 如果当前在 worktree session,先 ExitWorktree action="keep"(让我自己 cleanup,
# 不要 remove 让 git worktree remove 干净 deinit)
# 然后:
cd "$MAIN"
git fetch origin main
git checkout main
git pull --ff-only origin main  # squash 后 main HEAD 是新 commit
```

### 4. 清理远端 + 本地 + worktree

**(2026-06-05 收严)清理本次任务涉及的【全部】分支/worktree,不只当前所在的那个** —— 收尾前先 `git worktree list` + `git branch --list` + `git ls-remote --heads origin` 全列出来,识别本任务创建 / 经手的所有 feature branch 与 worktree(含中途起的 verify/spike/debug 试验分支、被证伪 drop 的分支),**逐个清理干净**,避免一次任务留下多个残留 worktree/branch 堆积。用户 2026-06-05 显式指示。

```bash
# 远端 branch:gh pr merge --delete-branch 应该已删, 但 silent failure 模式:
# **如果 local branch 被 worktree 占用导致 local delete 报错, gh 可能也 skip
# 了 remote delete** (2026-05-17 #195/#197/#199 实测:3 个 branch 全部 remote
# 残留). 必须显式 verify + 手动补删:
git ls-remote --heads origin <branch> | wc -l  # 0 = 已删, >0 = 还在
# 还在 → 手动删:
git push origin --delete <branch>
# 跨多 PR 一次性 cleanup:
for b in <branch1> <branch2> <branch3>; do
  git push origin --delete "$b" 2>&1 | tail -1
done

# 本地 branch:必须先删 worktree 才能删 branch (worktree 锁住 branch)
git worktree remove "$WORKTREE"   # 没残留改动才允许;有的话先确认或 --force
git branch -D <branch>            # 删本地 branch(squash merge 后 git 不认 merged)
git worktree prune                # 清掉 worktree 元数据残留
```

**⚠️ 必须 verify remote 是否真空**: `git ls-remote --heads origin | awk '{print $2}'`
列完整远端 branch 清单。预期只剩:
- `refs/heads/main`
- `refs/heads/main-backup-*` (历史 backup, 不动)
- `refs/heads/migrate/egui-native-ui` ([reference_preserved_branches] 永久保留)
- 别人 / 别 session 的 active branch

任何本次 merge 的 feature branch 还在 = silent failure, **必须手动 push --delete**。

### 5. 关闭关联 issue

```bash
# 先 verify 是否已被 PR 自动 close(PR body 有 `Closes #N` 时 GitHub 自动关)
gh issue view <ISSUE#> --json state,closedByPullRequestsReferences \
  --jq '{state, closedBy: [.closedByPullRequestsReferences[].number]}'
# 已 CLOSED + closedBy 含本次 merge 的 PR# → 跳过,无需手动 close
# 仍 OPEN(PR body 用 `Refs #N` 而非 `Closes #N`,或 issue 跨多 PR)→ 手动 close:
gh issue close <ISSUE#> --comment "Resolved by PR #<PR#> (squash merge $(date -u +%Y-%m-%d))." --reason completed
```

**Why 分两路**: 用户偏好 `Closes #N`(`feedback_issue_before_pr` 提到"多 PR 各 Refs/Closes")让 GitHub 自动联动,但仍要主动 verify;遇到 `Refs` 类不会自动关,必须手动 close 否则 issue 一直挂着脏 backlog。

### 6. 更新 Linear MOC-N 状态 (本次 PR 关联的所有 Linear issue) — **默认必跑,不等用户声明**

**用户 2026-05-27 显式指示**:"PM 里的更新应该在 merge 收尾流程中默认执行,不要每次都要我声明状态更新"。SOP 之前 wording 写 "本次 PR 实施的 followup issue" 太狭窄,导致 PR 关联 GH issue + GH issue 对应 PM ticket(cross-reference)的场景被漏跑(2026-05-27 PR #287 → GH #266 → MOC-24 漏 transition 复盘)。

GitHub issue 自动 close 跟 **Linear backlog** 是**两套独立系统**,Linear MOC-N 必须手动 transition。

**Lookup 顺序(逐条扫,任何命中都要 transition)**:

1. **PR title / body / commit message 直接 mention MOC-N** → 立即对该 issue 跑 transition
2. **PR title / body / commit message 含 `Refs #N` / `Closes #N`(GH issue)** → 用 GH issue 编号反查 Linear 是否有 issue 在 title/description 提到 `#N`:

```bash
# 反查 Linear:把 GH issue # 当 query 搜 issue
mcp__linear__list_issues(query="#<GH issue#>")
```

任何 hit(issue title / description 含 `#<GH#>`)都对应本 PR 的 Linear ticket,**全部** transition。

```python
# 对每个命中的 Linear issue 跑(可能多个):
mcp__linear__save_issue(
    # 用 issue id 或 identifier=MOC-N
    state="Done",
    description=<原 description> + "\n\n- resolved by PR #<PR#> (YYYY-MM-DD)"
)
# (description 改 append-only,保留原始触发上下文 + 调研 + 决策)
```

完成后 PR 本身已 merge,Linear 这步 **不需要再开 PR / commit** — Linear API 调用即生效。

#### 6.2 扫未完成 issue + 挂强相关链(**强制独立子步骤,不是 transition 的附属说明;跳过=收尾失职**)

transition 完主 MOC-N 后,**必须真的执行一次 `mcp__linear__list_issues`** 拉 Linear 项目 codex-app-transfer 全部未完成态(`state` 分 In Progress / Todo / Backlog 几次拉过滤;量大常超 token 上限 → 会落到 tool-results 文件,用 `jq` 抽精简列表)。**禁止凭 "父/兄弟 issue 已 link" / "应该没强相关" 等 happy-path 借口跳过扫描本身** —— 没真扫 = 没做。

逐条按判定标准 judge,**挂不挂由你自行判断 + 直接执行;绝不把 "要不要挂" 抛回用户问**(这是收尾既定动作,不是决策点):
- **挂**(`mcp__linear__save_issue` 的 `relatedTo` 参数追加关系 + `mcp__linear__save_comment` 一条简评,指向本 MOC-N+PR#、说清关系):同子系统(共享代码/文件/模块,带 file:line 佐证)/ 同根因不同面 / 互为前置后继。
- **不挂**(避免噪音):仅 "工具↔用例" 泛关联(如 "这 bug 能用本次的调试工具调")、同领域但无代码/根因耦合。宁缺毋滥 —— 但**必须真扫过才能下 "无强相关" 结论**。

目的:后续处理相关 issue 时双向索引得到,避免各自孤立、半年后查不到彼此。用户 2026-06-05 显式指示。

**反例(2026-06-05 #401 / MOC-184 复盘)**:收尾时我凭 "父 MOC-169 已 link" 一句**跳过整个扫描**(happy-path 偷懒,verify 清单当时不含此步 → 零暴露);用户事后让我补扫,我扫出 MOC-110(同 `diagnostics.rs:345 is_credential_key` 脱敏漏洞、安全衍生)却又把 "要不要挂" 抛回用户问。两处都是该自己执行的动作没执行。**教训:扫描是强制动作不是可选;判断+挂链是 agent 职责不是用户决策点;且必须进 verify 自证(见下)。**

**同时 —— Linear 记录归档(见 [[feedback_linear_record_workflow]])**:transition 前先检查该 MOC-N 的 Linear 记录**有无遗漏**(对话关键处理步骤评论、长排查/分析/方案的文档附件、附件的简要说明评论是否都齐);把本任务产生的长文档**移到 `~/alysechen/github/archives/<项目>/`**(见 [[feedback_local_doc_archive_folder]]),并**更新 Linear 上指向文档的本地链接**(attachment / 评论里的路径)到归档后的新位置,避免文档移走后链接失效。

**如果 lookup 完全无 hit**(没有现成 Linear ticket)分两种处理:
- **本次彻底解决 / GH issue 已关 / 外部 contributor PR 修了非 tracked 问题** → 跳过 step 6,在收尾报告里**显式说**"PR 不关联 Linear ticket,跳过 step 6"(让用户知道你跑了 lookup 没漏)。
- **⚠️ 外部 reporter 报的 issue + 代码已 merge + GH issue 仍 OPEN 等 reporter 验证关闭**(`Refs #N` 不自动关,见 [[feedback_no_auto_close_others_issues]]) → **必须新建一条 Linear issue**(`mcp__linear__save_issue`),状态走 `Pending Close`(Linear Mochance team 的 backlog 类型自定义态;**绝不**用 Done/Cancelled 等完成态,否则 completion 会自动关掉别人的 GH issue,见 [[reference_github_linear_sync]])。字段:`project=codex-app-transfer` / `priority=Low(4)` / label 按类型(bug→`Bug`) / title 镜像 GH issue 标题 + `(#N)` / description 写根因+修复+PR# / 挂 GH issue & PR URL link。这是用户的固定追踪面,跟已有 `MOC-50 ↔ #295` 一个套路。**反例(2026-05-29 #249/#257 复盘)**:收尾时整步漏跑(凭 MEMORY.md 索引的"5 步"摘要执行,没开全文)→ #249 无 ticket → 不在 Pending Close,用户对账时发现漏,补建 MOC-63。**教训:收尾前开本文件全文,step 6 是默认必跑的第 7 步,不是 5 步。**

**反例(#287 漏 transition)**: PR #287 commit message `Refs issue #266 / PR #287`,GH #266 → Linear MOC-24(title `偶现codex模型选择界面未被注入#266`)。我跑 SOP 时只在 GH #266 留 close 邀请评论,**没**反查 PM,导致 MOC-24 仍 Todo。用户拉条目对账时发现漏跑。新 lookup 步骤强制反查。

跟 GitHub issue close 区别:
- GitHub issue: 用户面 backlog, 跟 GitHub release / PR 联动(用户报的问题)
- Linear MOC-N: 内部技术债 backlog, 半年后查"这条 followup 实施过吗"靠这查(agent / reviewer 识别的非 BLOCKER 改进点)

**反例 (2026-05-18 PR #197 / #199 复盘,old workflow 时代)**:
- ❌ 走完 5 步 SOP 后, 旧 `docs/followup/34-...md` 跟 `37-...md` 仍 `status: active` 没改;tracker 里 #34 / #37 仍在 Active 段。用户后查 followup backlog 看到"这两条还没做" → 错觉。迁 PM 系统后这类错觉风险降低(UI 更明显),但 **issue → Done 的 transition 仍要手动**。

**历史制度**:2026-05-24 前用 `docs/followup-tracker.md` + `docs/followup/<id>-<slug>.md` 详情文件维护 followup,迁 PM 系统后归档到 `docs/archive/followup-tracker.md` + `docs/archive/followup/`。详见 [[feedback_followup_tracker_doc]]。

### Verify(报告给用户前必跑)

```bash
gh pr view <PR#> --json state --jq .state  # MERGED
gh issue view <ISSUE#> --json state --jq .state  # CLOSED
git -C "$MAIN" branch | grep -c "<branch>"  # 0
git -C "$MAIN" worktree list                # 不含 <branch> 行
ls "$MAIN/dist/mac/test Codex App Transfer.app"  # 存在(test 前缀避免跟 /Applications/ 正式版混淆)
mcp__linear__get_issue(id="MOC-<N>")  # state=Done (Linear status transitioned)
```

报告必须带这 7 行 verify 的输出。

**外加 step 6.2 自证(专防跳过扫描)**:报告必须写明「已 `mcp__linear__list_issues` 扫 **N** 条未完成态 → 判定强相关 **X** 条,已挂关系(`save_issue` 的 `relatedTo`)+简评(列出 MOC-…);其余无代码/根因耦合,不挂」。只写 "扫过了 / 无相关" 而**不带 {扫描条数 N + 强相关结论 X + 已挂清单}** = 视为没扫(2026-06-05 #401 凭 "父已 link" 跳过扫描的反例)。这一条让 6.2 跳过会在 verify 暴露,不再零成本。

### 常见踩坑

1. **squash merge 后本地 branch 不被 git 认为 merged** — `git branch -d` 会失败,必须 `-D` 强删
2. **worktree 有 uncommitted changes** — `git worktree remove` 拒绝,先 ExitWorktree action="remove" discard_changes=true(危险),或者手动决定保留
3. **chatgpt-codex 留 unresolved thread** 阻塞 merge — 走 reply + resolve mutation(global CLAUDE.md 有 GraphQL 模板)
4. **merge 时 PR 还在 IN_PROGRESS** — 必须等 `gh pr checks --json bucket --jq 'all(.bucket=="pass")'` 返 true
5. **`gh pr merge --delete-branch` silent failure on worktree-locked branch** (2026-05-17 #195/#197/#199 复现) — local delete 报错时 gh 也跳过 remote delete, 用户后查看 `git ls-remote` 才发现 3 个分支残留。step 4 verify remote 必跑, 不能只 trust `--delete-branch` flag。
6. **stacked PR 自动 CLOSED 陷阱** (2026-05-20 #206 → #229 复现) — `--delete-branch` 删 head branch 时, 以该 branch 为 base 的 open child PR **不会**被改 base 到 main, 而是被 GitHub 自动 CLOSED。补救成本: 重建临时 base ref + reopen + change base + 删临时 ref (4 步 API mutation, auto-mode classifier 可能拒绝认为越权)。**step 0 解耦 child PR base 必跑**, 这是新加的预处理步骤。

### 不在收尾范围

- **不 open .app / 不开浏览器**(用户 2026-06-06 指示:收尾流程不需要 open app) —— step 2 的 .app **转移到 `dist/mac/` 仍做**(test 前缀,保留供运行),但**不 `open`**;step 1a 的 `gh pr view --web` 也跳过,改成对话里报 PR URL + stats 作 last-look anchor(不靠浏览器)
- 不动 `/Applications/Codex.app` / `~/Downloads/`([feedback_app_build_dest])
- 不主动起下一个 PR 任务(等用户给下一句指示)


## 附录 A:收尾时 Linear 留档分层

**Linear 留档分三层,各有去处**(用户 2026-06-01 显式指示)。

1. **长的排查结果 / 分析结果 / 处理方案 → 落成独立文档**,以**附件**挂到对应 Linear issue,并配一条**简要说明评论**(点明这份附件是什么、解决什么问题,给后续定位当索引)。**不要**把长内容直接灌进评论正文。
2. **对话中的关键处理步骤 → 落 Linear 评论**(过程留痕:跨会话能复原"当时一步步怎么做的、为什么这么决策")。
3. **merge 收尾处理 Linear 时**(在 [[feedback_merge_closeout_sop]] step 6 内执行):
   - **先检查 Linear 内容记录有无遗漏**:关键步骤评论齐不齐、长文档附件挂没挂、简要说明评论有没有 —— 补齐再往下。
   - 相关文档**移动到 `~/alysechen/github/archives/<项目>/`**(见 [[feedback_local_doc_archive_folder]])。
   - **更新 Linear 上指向该文档的本地链接**(attachment / 评论里的本地路径)到归档后的新位置,避免文档移走后链接失效。

**Why**: 长内容塞评论正文难读难检索;落成文档 + 挂附件 + 简要评论,Linear 上一眼看到"有这份排查/方案",点开就是全文;关键步骤进评论让过程可复原。收尾归档 + 更新链接保证长期可寻——本地归档兜底、Linear 附件做跨会话/跨设备主入口(见 [[feedback_local_doc_archive_folder]])。

**How to apply**:
- **挂附件方式**:Linear 附件走 `mcp__linear__create_attachment`(URL 直挂)/ `mcp__linear__prepare_attachment_upload` + `mcp__linear__create_attachment_from_upload`(本地文件上传)。
- **上传出问题 / API 报成功但用户在 UI 看不到时:不要反复折腾**(别再重试、别反复 retrieve verify、别长篇解释 UI 位置)。**直接把「本地文件绝对路径 + 目标位置」告诉用户,让用户手动上传**(用户 2026-06-02 MOC-130 ① 文档附件 API 创建成功但 UI 看不到时显式指示:"以后遇到上传附件出问题,不要乱折腾,直接把本地路径和需要上传到的位置告诉我就行")。
- **简要说明评论**:一两句话"这份附件是 X 的排查/分析/方案" —— 是定位索引,不是详情本身;详情在文档里。
- **关键步骤评论**:边做边记或阶段性补,用 Linear 评论(`mcp__linear__save_comment`;不回流 GitHub,只给自己/团队留档,见 [[reference_github_linear_sync]])。
- **收尾**:移归档**前**先核对 Linear 记录无遗漏;移完更新链接。
- 与 [[feedback_pr_remote_concise_detail_to_linear]](远端只写简洁)、[[feedback_issue_description_concise_detail_in_linear]](description 只写简要)协同:远端 / description 保持干净,详情全走"文档 + 附件 + 评论"这套。


## 附录 B:搭车改动补 Done issue(step6 补充)

merge 收尾跑 [[feedback-merge-closeout-sop]] step 6(Linear transition)时,不能只 transition PR 标题里的主 MOC-N —— 要审 **这个 PR 实际做了哪些独立主题的改动**。一个 PR 常搭车主任务之外的独立改动(CI 规则变更 / 基础设施 / 工具链 / 顺带修复),这些搭车主题如果没有对应 Linear issue,**收尾时要补建一条 Done 状态的 Linear issue**(Linear 项目 codex-app-transfer(MOC)/ 配 milestone+priority+label,见 [[feedback-linear-issue-autoconfig]];我经手关的贴 `logclose`,见 [[feedback-logclose-label-on-close]]),否则该改动没有 tracking,半年后查"为什么改成这样"无据。

**Why**: 用户 2026-06-01 指示 — 处理 #348(MOC-113)收尾时回顾 #341 收尾,发现 #341 = MOC-107(主,已 Done)+ no-ai-coauthor 正则收严(搭车,扩到拦所有 AI 署名)两个独立主题,我 step6 只 transition 了 MOC-107,no-ai-coauthor 收严没有任何 Linear issue 跟踪。补建了一条 Done issue 归档。

**How to apply**:
- 收尾 step6 lookup 主 MOC-N 后,再问一句"这个 PR 除了主任务还顺带做了什么?" —— 列 PR 的 commit / 文件改动主题
- 每个独立主题(尤其 CI / workflow / 基础设施 / 规则变更)若无 Linear issue → 补建 Done issue,description 简要写"#PR 搭车改动 + 做了什么",挂 PR link(见 [[feedback-issue-description-concise-detail-in-linear]])
- 跟 [[feedback-followup-separate-linear-issue]] 区分:那条是**未做的 followup** 开 Todo issue;这条是**已做的搭车改动**补 Done issue
- 不是每个微改动都建(1 行 typo / fmt / 版本 bump 不必);独立到"值得半年后能查到"的主题才建

**关联**: [[feedback-merge-closeout-sop]] / [[feedback-linear-issue-autoconfig]] / [[feedback-followup-separate-linear-issue]] / [[feedback-logclose-label-on-close]]


## 附录 C:外部 contributor 首次 PR 的 workflow approve(Step 1c 前)

外部 contributor 提的 PR(尤其首次贡献者),GitHub Actions 默认拦着 workflow run 不让自动跑,需 maintainer 手动 approve。表现:

- `gh run list --branch <PR-branch>` 看到 `status: completed, conclusion: action_required`
- `gh pr checks <PR#>` 卡在 expected / pending
- PR 页面有黄色 banner "First-time contributors need a maintainer to approve workflow runs"

**Approve 命令**(每个 run 独立调):

```bash
gh api -X POST repos/<OWNER>/<REPO>/actions/runs/<RUN_ID>/approve
```

仓库默认设置 `Fork pull request workflows from outside collaborators` = "Require approval for first-time contributors"(GitHub 默认)。

**重要**(2026-05-26 #278 实测踩坑):"first-time contributor" 定义是"还没 merged PR 进本仓",而**不是** "这个 PR 第一次 approve 后免"。即在 contributor 第一个 PR **merge 前**,他**每次 push 触发的新 run 都要重新 approve**。要 merge 进去了他才升级成 "contributor",之后开新 PR 才 auto-run。所以同一个 PR 里多次 push 修 fmt / lint 等,每次都要走一次 approve 命令。

如果设置改成 "Require approval for all outside collaborators",外部贡献者**每个 PR 每次 push 永远**都要 approve。

仓库设置入口:Settings → Actions → General → Fork pull request workflows from outside collaborators。

**对 merge SOP 影响**:外部 contributor PR 走 [[feedback_merge_closeout_sop]] Step 1 时,`gh pr update-branch` 后会产生新 SHA 触发 CI,但 CI 立刻进 `action_required` 静默不跑 → `gh pr checks` 永远 pending → SOP 卡死。**Step 1c 前必须**:

```bash
# 检查并 approve 外部 PR 的 action_required runs
gh run list --branch <PR-branch> --limit 5 --json databaseId,conclusion \
  --jq '.[] | select(.conclusion=="action_required") | .databaseId' \
  | while read RID; do
      gh api -X POST repos/<OWNER>/<REPO>/actions/runs/$RID/approve
    done
```

**Why**: 2026-05-26 PR #278(@Alpaca233114514 首次贡献)merge 时碰到。`gh pr update-branch` 后 ci.yml + no-ai-coauthor.yml 两个 run 都 `action_required`,等了一阵无进展才意识到。


## 附录 D:外部 fork PR 的收尾差异

外部 contributor 从 **fork** 提的 PR(如 ALPACA LI / Alpaca233114514 的 #323 codex/moc68),merge 收尾跟自家 branch PR 有几处差异(2026-05-31 #323 实证):

**1. maintainerCanModify=true 只给"push 更新"不给"删分支"权限**
- `maintainerCanModify:true`(查:`gh pr view N --json maintainerCanModify`)允许 maintainer **push 到** fork 的 PR head 分支(整理 commit / rebase / force-push 都行,用 `git push https://github.com/<forkowner>/<repo>.git <local>:<branch> --force-with-lease=...`)。
- 但 **`git push <fork-url> --delete <branch>` 会 `! [remote rejected] (permission denied)`** —— maintainer 删不了别人 fork 上的分支。`gh pr merge --delete-branch` 对 fork PR 也是 silent skip(删不掉,但不报错)。
- → fork 分支 merge 后**残留是预期的、不可清的**,别浪费 round-trip 反复试删。那是 contributor 自己 fork 的分支,他自己清;merged 分支留着无害。

**2. origin(主仓)远端本来就没这个分支**
- fork PR 的 head 在 fork,不在 origin。所以 SOP step 4 的"verify origin 远端无残留 feature 分支"对 fork PR **天然成立**(`git ls-remote --heads origin <branch>` = 0),不用补 `git push origin --delete`。只有自家 branch PR 才会出现 origin 残留。

**3. squash merge 作者归属**
- 2 commit(contributor 原始 + maintainer 加固)squash 后,GitHub 默认作者 = PR author(contributor),合适(credit 归他);maintainer 的加固 commit 内容并入。`no-ai-coauthor` check 仍要过(两个 commit 都得是人类账号,无 AI trailer)。

**4. merge 后关联 Linear issue 可能已被关闭 —— 但「谁/怎么关的」我查不到,别臆测**(2026-05-31 #323 血泪):
- GitHub 本身不认 PR body 里的 `Closes MOC-N`(只认自家 issue 编号),所以 GH 侧不关任何东西;SOP step 5(GH issue close)对纯 Linear 关联 = N/A。
- **Linear issue 的 status 可能在 merge 前后被改成 Done** —— 可能是协作者(如 Logan Alpaca)手动关、也可能是某种集成自动关。**Linear MCP 查不到 `completedBy`/操作历史**,我**无法判断谁关的、怎么关的**,所以**绝不能断言**(#323 我先后臆测「不会自动关」「集成自动 Done」两次都错,第二次被用户纠正"是另一个用户手动关的")。
- 正确做法:merge 后 **`get_issue` 只看 `status`/`completedAt`(事实),不推断 actor**;已 Done 就别重复 transition;[[feedback_logclose_label_on_close]] 的 logclose 只贴**我自己经手**关的,**别人/不确定谁关的不要贴**(贴错=语义谎报"由mochan手动done")。

关联:[[feedback_merge_closeout_sop]] / [[feedback_no_auto_close_others_issues]] / [[feedback_external_pr_workflow_approve]]


## 附录 E:深层 stacked PR 的 squash merge

深层 stacked PR 链(main ← A ← B ← C ← …,每个 PR base 指向前一个 head)用 **squash merge** 收尾时,普通 `gh pr update-branch` 会从第二个起 **CONFLICT**(`mergeStateStatus=DIRTY mergeable=CONFLICTING`)。

**机制**:squash-merge 底座 A 后,main 得到 A 的内容作**一个新 SHA 的 squash commit**;但 B/C/… 分支里仍带着 A 的**原始 commits**。`update-branch`(=merge main into B)是 3-way merge,两边都改了 A 的文件(一边 squash、一边原始 commits),git 认作冲突 —— 即便内容等价。

**解法 = rebase --onto 丢掉已合并前缀**(不是 merge):
```bash
# 把 B 自己的 commits 重放到 main 上,丢掉已在 main 的 A 前缀
git rebase --onto origin/main <A-tip-sha> <B-branch>
# <A-tip-sha> = B lineage 里 A 的最后一个 commit(注意:若对 A 跑过 update-branch,
# A 的 PR headRefOid 会是个 merge commit、**不在 B lineage**;要用 B 历史里真正的
# 那个 stage-tip,`git log --oneline <old_main>..B` 找 stage 边界)
```
rebase 干净(无冲突)因为 B 的 commits 本就建在 A 内容之上,重放到含 A 内容的 main 上 base 一致。

**深链(≥5 层)省事策略 = 收束**(2026-06-18 #503-509 七层重构实战,用户选):底座单独 squash;**最顶 PR**(含全部 stage)`rebase --onto main <底座-tip>` 去掉底座前缀 → 改 base 到 main → 一次 squash 合掉 stages 2-N → 中间 PR 全 `gh pr close`(内容已在顶 PR)。avoids N 轮 update-branch+CI+bot重审(每轮 ~10min + force-push 触发 bot 重审可能再生 thread)。代价:main 上该重构是 1-2 个 commit 而非 N 个分阶段 commit(GitHub 上 N 个 PR 仍留分阶段 review 历史)。

**rebase 后必验**(force-push 前):`git diff <backup> HEAD` 看是否只剩"main 独立进展"的预期差异(本任务 backup 基于更老 main,差异=底座 PR 累积的后端 commit + 上游独立 #502);跑 golden/workspace 测试 + npm + cargo check 确认 main 独立改动与重构改动 merge 后内部一致(presets_data.json ⟷ golden fixture 同步等),并 `git diff origin/main HEAD -- <后端文件>` 确认重构净改动**没反转 main 的独立后端改动**。

配套见 [[feedback_merge_closeout_sop]] step 0(解耦 child base 防 `--delete-branch` 误关)、[[feedback_worktree_dev_flow]]。


## 附录 F:reviewThreads 分页 100 截断(终判收敛必读)

长 bot-review 收敛(2026-06-20 PR #513 跑了 ~73 轮、107 条 thread)踩到的查询 gotcha:

**`reviewThreads(first:99)`(或 first:100)在 100 处硬截断**。PR thread 总数 >100 时,`first:99` 只返前 99 条 —— 而 **chatgpt-codex-connector bot 新 finding 总是 append 在末尾**(最新 thread 在列表尾),所以「看起来 0 unresolved」其实漏了末页的未决 thread。实测:`first:99` 报 0 unresolved + `mergeStateStatus=BLOCKED`(`required_conversation_resolution` 卡着),靠 `reviewThreads(first:100){totalCount pageInfo{hasNextPage}}` 才发现 `totalCount:100 hasNextPage:True` → 第 100/101 条是未决的迟到 thread。

**How to apply**(收敛轮询):
- 查 unresolved 用 **`reviewThreads(last:40)`**(新 finding 在尾部,last 取最新 N 条)+ 带 `totalCount` 追踪增长。`totalCount` 本轮不增 = bot 零新增。
- 终判收敛要 union 覆盖:`first:100`(前 100)+ `last:40`(后 40)都 0 unresolved,两段并集覆盖全部才算真清零。
- **确认窗口必跑**:bot 按 ~1 thread/窗口的节奏迟发,主 poll 报「0 + CLEAN」后**再等一窗**(~6min)复查;实测连续多轮主 poll 清零、确认窗口仍抓到 1 条迟到 thread。直到「主 poll + 确认窗口都零新增 + totalCount 不变」才是真收敛(见 [[feedback_default_track_ci]] 的「CLEAN 是瞬时态 merge 前再查」)。
- `BLOCKED` + 表面 0 unresolved + CI 全绿 + reviewDecision 空 + 无 CHANGES_REQUESTED review → 几乎一定是 reviewThreads 截断漏了未决 thread(分页查),不是 mergeState 滞后。
