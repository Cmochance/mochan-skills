---
name: release-flow
description: 发版/release 全流程 SOP:dispatch 前预发布微 PR(版本号全盘 grep bump、双语 release notes 硬模板 2500-3200 字符、release-notes/vX.Y.Z.md CI 门禁)、release.yml workflow_dispatch 版本校验、merge cleanup 顺序、build 完保持 draft 等用户显式确认才转 Latest。用户说「发版/准备 release/触发 release workflow」时使用。
---

# Release 发版 SOP

> 来源:项目 auto-memory 迁移(2026-07-03)。触发:发版/release 类指令。
> 铁律:build 完保持 draft,只有用户显式说「发为 Latest / publish 正式版 / 转正式」才 publish(全局 CLAUDE.md 规则,hook 强制确认)。


## 预发布微 PR SOP(dispatch 前必走)

用户说『触发 workflow』/ release 类触发词时,**默认 SOP**:

### Step 0-pre: 写 SOP 整体许可 marker(开始即做)

release 触发词即这次发版的整体授权。**先写 grant marker**,其间的 `gh pr merge`(微 PR)/ open app / pkill 中间步不再被 guard-destructive 逐个弹确认。marker 限时 2h(兜底)+ 限本仓 cwd。**`gh release edit 转正式`(--draft=false/--latest)不在覆盖内,仍会 ask**(对齐「build 完留 draft 等用户显式确认」铁律)。build 完到「留 draft 等你确认」那步(见下方 Step 3 / How to apply)**清掉 marker**。

```bash
# 发版 SOP 开始:写整体许可 marker(限本仓根 + 2h 兜底过期)
python3 - <<'PY'
import json, os, subprocess, time
cwd = os.getcwd()
root = cwd.split("/.claude/worktrees/")[0] if "/.claude/worktrees/" in cwd else (
    subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip() or cwd)
json.dump({"sop": "release", "expires_at": int(time.time()) + 7200, "cwd_prefix": root},
          open(os.path.expanduser("~/.claude/.sop-grant.json"), "w"))
print("SOP grant written:", root)
PY
```

## Step 1: 开『预发布微 PR』(draft 模式让 CI 跳)

PR 标题: `chore(release): prepare vX.Y.Z`

任务三件:

### A. 全盘扫描更新版本号

**新版本号默认 patch +1**(如 2.3.1 → 2.3.2)。用户没显式指明 bump 档位时,**不**按改动内容(feat 多寡)自行推 minor/major;只有用户明说(如『发 2.4.0』『升 minor』)才用更大档位。Why:2026-06-13 发版我按 feat 数量推了 2.4.0,用户撤回纠正为 2.3.2 并指示『以后我没有指明的话默认只提升一个小版本』。

不止 [[feedback-release-dispatch-version-bump]] 提到的 2 文件,**全仓 grep 当前版本号**确认没漏:

```bash
OLD=$(gh release list --limit 1 --json tagName -q '.[0].tagName' | sed 's/^v//')
NEW="X.Y.Z"
rg -l "\b$OLD\b" --type-not lock | head -20
```

必改:
- `src-tauri/Cargo.toml` `[package].version`
- `src-tauri/tauri.conf.json` top-level `"version"`
- `Cargo.lock`(`cargo check -p codex-app-transfer` 自动 sync)

可能要改(grep 后判断):
- `README.md` / `README.en.md` stability rollups / version table(若有提及当前版本)
- `CHANGELOG.md` 若存在
- `ACKNOWLEDGEMENTS.md` 不动(借鉴清单与版本号无关)
- 任何含上版本号的 docs(本项目 `docs/` gitignored,跳)

### B. 撰写 release notes(写到 PR body)

按 [[feedback-release-notes-template]] v2.1.7 模板:**单 `###` 主题 + bullets 列改动**。

收集 PR 列表:
```bash
gh pr list --search "is:merged base:main merged:>=$(date -u -v-7d +%Y-%m-%d)" --json number,title --limit 30
git log --oneline v$OLD..main
```

整合成主题(综合标题 + 各 PR 单 bullet),禁强调标记(粗体/斜体/删除线/中文引号),允许 inline code + code block 包技术名词。中英双栏(`## 中文` + `## English`)。

写到 PR body **顶部 fenced block** 标 `<!-- RELEASE-NOTES -->` 围栏,merge 后:
```bash
# 从 PR body 提取 release notes(用 marker 界定)
gh pr view <N> --json body -q .body \
  | awk '/<!-- RELEASE-NOTES-START -->/,/<!-- RELEASE-NOTES-END -->/' \
  > /tmp/release-notes.md
# 等 release.yml workflow 跑完后注入
gh release edit vX.Y.Z --notes-file /tmp/release-notes.md
```

### C. notes 文件 commit 进 `release-notes/vX.Y.Z.md`(MOC-66 CI 门禁,2026-06-13 起强制)

notes 除了写 PR body,**同一个微 PR 必须把同样内容落成 `release-notes/vX.Y.Z.md` commit 进仓库**(格式 = GitHub body 原文,LF、单尾换行,与既有文件一致)。`release.yml` 两个 job 各有一步 `Verify release notes present`(`scripts/check_release_notes_present.py`)校验该文件存在且非空,**缺失 = 4 平台 build 全 fail**;push tag 触发 checkout 的是 tag commit,文件必须在打 tag 前进仓库。

有了仓库文件,merge 后注入可直接用它(替代从 PR body 提取):
```bash
gh release edit vX.Y.Z --notes-file release-notes/vX.Y.Z.md
```

**Why**:只写 PR body 不 commit 文件的旧 SOP 让 MOC-65 回填后又复发 —— v2.2.0 / v2.2.1 / v2.3.0 / v2.3.1 四版「GitHub body 有、仓库缺」,2026-06-13 MOC-66 实施门禁时一并回填。

## Step 2: PR 模式

- **开 draft PR**(`gh pr create --draft`): CI 已有 `if: pull_request.draft == false` skip 逻辑,自动跳过 Rust check / no-ai-coauthor / detect-paths
- **Devin Review 无法 skip draft**(GitHub App,本项目无 paths-ignore 配置 — 接受它跑一次,通常 1-3min)
- **ready_for_review → squash merge** 进 main

## Step 3: trigger release.yml

```bash
gh workflow run release.yml -f version=X.Y.Z
```

Monitor step-level,build 完留 **draft** state(`isDraft=true`),用第 1 步收集的 release notes `gh release edit` 注入 body,然后**继续保持 draft 等用户**显式说『发为 Latest』再 publish([[feedback-release-default-draft]] 同款)。

## Step 4: 转 Latest 的 tag 重跑坑(workflow_dispatch 发版特有 — 2026-05-29 v2.1.17 实证)

⚠️ **用 `gh workflow run release.yml`(workflow_dispatch)发版时,build 阶段不创建 git tag**(release.yml 无 git tag push 步骤),softprops 只建 draft release(`tag_name` pending,git 里没有该 tag)。

→ 用户说『转 Latest』执行 `gh release edit vX --draft=false --latest` 时,GitHub **首次创建 git tag vX** → 撞上 release.yml 的 `on: push: tags: ['v*']` → **触发重跑**;重跑的 softprops 是 `draft: true` + 空 body,会把 release **打回 draft** + 重新 build 4 平台(~20min 浪费)+ 重传 assets。

**解决(转 latest 后立即 cancel 重跑;cancel 窗口 ~15min,在 build 阶段远早于末尾 softprops)**:
```bash
SHA=$(git -C <main> rev-parse HEAD)   # tag 指向最新 main,与注入的 body 一致
gh release edit vX.Y.Z --draft=false --prerelease=false --latest --target "$SHA"
sleep 16
RERUN=$(gh run list --workflow release.yml --event push --limit 1 --json databaseId,status \
  --jq '.[0]|select(.status=="in_progress" or .status=="queued").databaseId')
[ -n "$RERUN" ] && gh run cancel "$RERUN"
# verify: gh api repos/<owner>/<repo>/releases/latest --jq .tag_name   == vX.Y.Z
#         gh run view $RERUN --json conclusion                          == cancelled(没打回 draft)
```

**根治替代**:发版改用 **push tag**(`git push origin vX.Y.Z`)而非 workflow_dispatch —— tag 发版起点就创建,build 经 on-push-tag 一次完成,publish(--draft=false)时 tag 已存在不重新创建 → **不重跑**(历史 v2.1.15/16 标准流程)。workflow_dispatch 仅适合不转 Latest 的测试 build。

## Why

- 上次(2026-05-27)直接 dispatch v2.1.16,main 上版本号还是 2.1.15,4 平台 build 全 fail `Verify release version sources` step,浪费 ~3min CI 时间 + cancel
- 没有 release notes 时 release body 为空,publish 后用户看不到这版改了啥;事后补 notes 又违反 [[feedback-release-no-auto-body-edit]](默认不主动改 body)

**关联**: [[feedback-release-dispatch-version-bump]] / [[feedback-release-notes-template]] / [[feedback-release-default-draft]] / [[feedback-main-branch-pr-workflow]]


## Release notes 硬模板(2500-3200 字符)

`Cmochance/codex-app-transfer` 仓库的所有 GitHub Release notes 必须以 **v2.1.7** 为标准模板(2026-05-13 用户明确指示)。

**【硬性标准 — 2026-05-17 用户明示】**:本文档定义的所有规则(模板结构 / 长度区间 / 字体规则 / 禁忌)是**硬性标准 (hard requirements)**,**不是软偏好**。任何 case 不允许例外。超出长度区间或破坏结构规则必须立刻精简 / 重写后再发布,不接受"这次特殊"/"少超一点没事"等理由。本规则覆盖之前 description 里"~3000 字符"暗示的弹性语义。

**Why**:
- 此前 v2.0.10 / v2.0.11 / v2.1.6 等版本 6500-11000 字符,**太详细**;用户 2026-05-13 反馈:那些详细内容应该属于 `docs/CHANGELOG.md` 逐版本更新内容记录,**不是** release notes
- v2.1.7 实际发出去 **2935 字符**,1 个修复主题 + 5 条改动 bullets + 7 条验证 bullets + 英文镜像 — 这是用户认可的标准格式
- README 重构(PR #149)+ CHANGELOG 独立后,release notes 不再需要承担"历史档案"职责,聚焦本版关键修复即可

**模板获取**:`gh release view v2.1.7 --repo Cmochance/codex-app-transfer --json body -q '.body'`

**模板结构(必须保持)**:

```markdown
# Codex App Transfer v<version>

## 中文

### <一句话主题:修复 / 新增 / 重构 ...>

<1-3 段引言:症状 / 根因 / 设计思路,**不展开代码 file:line**,**不展开 wire-level 细节**>

本次修复(或本版本改动):

- <bullet 1:1 行,关键词 + 简单描述,inline code 引用关键 fn / 字段名>
- <bullet 2>
- <bullet 3-7,通常 5 条左右>

### 验证

- `cargo fmt --check`
- `cargo test -p <crate> <test_filter>`
- (其他验证命令,~5-7 条)

## English

### <Same theme in English>

<Same 1-3 paragraphs mirrored>

Changes in this release:

- <Same bullets mirrored>
```

**长度规则【硬性】**(2026-05-13 用户精修阈值,2026-05-17 升级为硬性标准):
- **硬性下限 2500 字符,硬性上限 3200 字符**(v2.1.7 = 2935 字符是中位数标杆)
- 中文 / 英文各 1200-1500 字符
- **超出 [2500, 3200] 任一端必须立刻精简或扩展后再发布**,不接受任何理由的例外
- 阈值适用 raw 文件(`wc -c`);GitHub 渲染后通常短 ~10%,以 raw 为准
- 历史 v2.1.8 (5091 字符) / v2.1.9 (3804 字符) 已超标但不回改,仅对 2026-05-17 之后的新版本硬性约束

**结构硬规则**:

- 严格单主题 — 每版 release 只写 1 个 `### 主题`,不允许 2 个或更多 `###` 平级主题段。本版有多个修复点时合并成 1 个综合主题(如"多家上游协议修复与跨层 silent failure 观测增强"),用 5 条 bullets 列各点。多主题写法已废弃。
- 段落只用普通文本 + bullets + inline code / code block(反引号)。强调语法(粗体 / 斜体 / 删除线 / 中文引号等)不用。

**字体使用规则**(细化,2026-05-13 用户澄清):

- ✅ 允许且鼓励:`inline code`(单反引号)— 技术名词 / fn 名 / 字段 / 路径 / 命令 / 协议字段。v2.1.7 大量使用,如 `cargo fmt --check` / `function_call_output` / `/responses/compact` / `tool.content`
- ✅ 允许:三反引号 code block — 用于贴命令清单或必要的小段示例(v2.1.7 验证段不用 fence,直接用 inline code 列 bullet)
- ❌ 禁用:`**粗体**` — v2.1.7 全文零使用,不用来强调技术名词或重要语义(用 `inline code` 替代)
- ❌ 禁用:`*斜体*` / `_斜体_` — 同上,无必要
- ❌ 禁用:`~~删除线~~` — release notes 不展示"已删除/已弃用"语义
- ❌ 禁用:中文引号「」『』 / 中文双引号 / 中文单引号 — 用英文标点或 `inline code` 代替

判断准则:技术名词、命令、字段名、路径、错误码 → `inline code`;普通文本叙述 → 不加任何强调;**不要**用粗体来表示"重要"。

**禁忌**:
- ❌ 绝不写 provider 兼容矩阵(那是 README 责任)
- ❌ 绝不写平台 / 二进制资产清单 / 签名说明(那是 README 责任)
- ❌ 绝不写 What's Changed PR 列表 / Full Changelog footer
- ❌ 绝不用粗体 / 斜体 / 删除线 / 中文引号等强调(细则见上方"字体使用规则")
- ❌ 不展开 wire-level 细节(协议字段名、字节偏移、SSE 帧 schema 等 — 那是 `docs/release-notes/v*.md` / `docs/investigation/*.md` 责任)
- ❌ 不写完整代码引用 / file:line / 单测数 / 反向工程过程(那是 CHANGELOG 责任)
- ❌ 不写多个 `###` 平级主题(单主题硬规则,合并 bullets)
- ❌ 不在 release notes 里教用户怎么用(README 责任)
- ❌ 不对每个 PR 加 PR ref(release notes 整体讲"本版改了什么",不分 PR 归属)

**写完必须查验**:

- `gh release view <tag> --json body -q '.body' > /tmp/notes.md` 拉下来
- `wc -c /tmp/notes.md` 验长度 2500-3200(raw 文件;GitHub 渲染后会短 ~10%)
- `grep -c '^### ' /tmp/notes.md` 应返 **4**(中文 + 英文段各 1 主题 `###` + 各 1 个 `### 验证`);返 ≥6 说明多了 `###` 主题
- `grep -cE '\*\*[^*]+\*\*|~~[^~]+~~|[「」『』]' /tmp/notes.md` 应返 **0**(零粗体 / 删除线 / 中文引号);**注意**不查反引号 inline code(那是允许的)
- `grep -cE '^## What|^\*\*Full Changelog|provider 矩阵|平台说明' /tmp/notes.md` 应返 **0**

**How to apply**:

- 写之前先 `gh release view v2.1.7 --json body -q '.body' > /tmp/template.md` 对照
- 写完先跑上述 4 条 grep / wc 校验,任一不通过立刻精简
- 多修复点时先写 1 段综合主题引言,再写 5 条 bullets 各占一行(每条 80-120 字符),不要拆 2 个 `###`
- 引言段总长控制在 ~600 字符(中英各 ~300),bullets 总 ~800 字符(中英各 ~400),验证段 ~300(中英各 ~150),合计 ~1700-2000 raw,留余量到 3200 上限
- 详细变更归 `docs/CHANGELOG.md` 或 `docs/release-notes/v*.md`(项目内),release notes 只放本版核心修复
- 已发的历史 release notes(v2.0.x / v2.1.0 ~ v2.1.5)**不回头改**,只对 v2.1.6+ 及之后生效(v2.1.6 在 2026-05-13 已按本模板回写)

**Release workflow 等待期自动起草 + 落地即写入(2026-05-16 新增)**:

- tag push 触发 release workflow 后,build matrix 跑完三平台 + release-bundle 收口通常 8-15 min。这段时间**默认起 release notes 草稿**,不要等 workflow 结束才开始动笔。
- 监控 build matrix 各 job step 进度的同时,**并行**:
  - 拉 v2.1.7 模板对照(`/tmp/template.md`)
  - 按本版改动 PR(merge commit message + PR body)起草中英 release notes 到 `/tmp/<tag>_draft.md`
  - 跑 `wc -c` + `grep` 校验(`### ` 应返 4 / 强调字符应返 0 / 字符数 2500-3200,超出要精简)
- draft release 一落地(22 assets 齐 / `isDraft=true` 验证通过),**立刻** `gh release edit <tag> --notes-file /tmp/<tag>_draft.md` 写进 draft body,**不需要再问用户是否要写**;同时 **`rm -f ~/.claude/.sop-grant.json` 清掉 SOP 整体许可 marker**(发版活跃段已过,后续「转 Latest」是独立 ask,不需 grant)。
- 写完才向用户报告 "v<x.y.z> 已 build 成功 + body 已填,留 draft 等你确认",用户第一眼看到的报告就已经带完整 body。
- 用户 review body 后如果要改可以让我再 `gh release edit --notes-file` 重写;**仍然不主动** `gh release edit --draft=false --latest`(转 Latest 必须用户显式指示,这条不变)。
- 例外:用户显式说"先不写 body"才跳过(罕见,目前未出现过)。

**Why**:用户 2026-05-16 反馈,workflow 等待期间只汇报 step 级进度是浪费,该用来并行起草 release notes,workflow 一落地就直接写入 body,把"草稿 / 写入 / 报告"三步合成一步。这条规则覆盖了之前"改 release body 必须用户显式指示"的限制 —— 限制只对**修改**已有 body 适用,**首次填空 draft body**不需要再问。

**How to apply 时序**:

1. `git push origin v<x.y.z>` 触发 workflow
2. `gh run list --workflow release.yml --limit 1` 拿 RUN_ID
3. Monitor 起 per-job step 级跟踪
4. 同步(不等 Monitor 事件):拉 v2.1.7 模板 + 起草 `/tmp/<tag>_draft.md` + 校验
5. Monitor 报 `ALL JOBS DONE` + `gh release view` 验 `isDraft=true / asset_count=22`
6. `gh release edit <tag> --notes-file /tmp/<tag>_draft.md`
7. 向用户报告(此时 body 已填好)

**v2.1.7 模板片段示例**(`gh release view v2.1.7 ...` 输出供参考):

```markdown
# Codex App Transfer v2.1.7

## 中文

### 修复大型调研后的 compact 超上下文

本版本修复 Kimi Code 在新对话第一条消息执行大型调研后,自动触发 `/responses/compact` 时请求体反而超过模型上下文上限的问题。

根因不是单纯的触发阈值设置过高。长 web/search/tool 结果此前会作为普通 Chat `tool.content` 进入对话历史,compact 请求又会在原始历史后追加本地总结指令,并且没有单独的 compact 输入预算,导致触发前接近阈值,触发后请求继续增长。

本次修复:

- 对长 `function_call_output` 增加共享归一化入口,避免完整工具输出直接写入模型可见历史。
- 将原始长工具结果保存到 sidecar artifact store,并在模型上下文中保留 artifact ID、tool call ID、原始规模、路径或 URL 线索、头尾片段和省略说明。
- 为 `/responses/compact` 增加 compact-only 输入预算,优先保留最终总结 prompt 和最新有效消息块。
- 保留 assistant tool calls 与后续 tool responses 的成组关系,避免裁剪后产生孤立 tool message。
- Gemini native 的相关工具结果路径也接入相同的 bounded tool-output 处理。

### 验证

- `cargo fmt --check`
- `cargo test -p codex-app-transfer-adapters build_compact_chat_request_`
- ...

## English

### Fixed compact requests exceeding context after large research turns

<mirror>
```


## dispatch 版本校验 + merge cleanup 顺序

`scripts/check_release_version.py` 在 release.yml 每个平台 build 第一步跑(`Verify release version sources`),校验:
- `src-tauri/Cargo.toml` `[package].version`
- `src-tauri/tauri.conf.json` top-level `"version"`

两者必须**完全等于** `workflow_dispatch` 输入的 `version`(不带 `v` 前缀)。不一致 → 所有 4 平台 build 第一步就 fail,整个 release 流程崩。

**Why**: 2026-05-27 我直接 `gh workflow run release.yml -f version=2.1.16`,但 main 上两文件还是 `2.1.15`(上版本 release 后无人 bump),4 平台同时挂在 verify step。浪费 ~3min CI 时间 + cancel run。

**⚠️ merge cleanup 顺序硬约束**(2026-05-27 第二次踩坑):**先 verify PR 真 merge 成功 再 cleanup**!错误顺序 = `gh pr merge` 报需要 admin → 我跑了 push --delete + worktree remove + branch -D → 真 merge 失败 → PR 自动 close 因 head ref 删 → `gh pr reopen` 报"could not open" → 只能开新 branch + 新 PR。正确顺序:
1. `gh pr merge --squash` 必须看到 ✓ Merged 输出才进下一步
2. `gh pr view N --json mergedAt` 二次 verify `mergedAt != null`
3. **mergedAt 确认后**才 `git pull --ff-only` / `git push --delete` / `git worktree remove`

**How to apply**(用户说"远端触发 workflow" 或类似 release 触发词时):

1. **先核查版本号**:
   ```bash
   grep "^version" src-tauri/Cargo.toml
   grep '"version"' src-tauri/tauri.conf.json
   gh release list --limit 1
   ```
2. **若不一致**:先起 bump PR(memory: main 必走 PR squash,enforce_admins,不用 --admin):
   - 改 `src-tauri/Cargo.toml` + `src-tauri/tauri.conf.json`
   - `cargo check -p codex-app-transfer` 让 `Cargo.lock` 自动 sync
   - 起 PR commit `chore(release): bump version to X.Y.Z`,等 CI 全绿 + merge
3. **bump PR merge 后再** `gh workflow run release.yml -f version=X.Y.Z`
4. release 全绿后**留 draft**(memory rule),等用户显式说"发为 Latest"才 publish

**关联**: [[feedback-release-notes-template]] / [[feedback-main-branch-pr-workflow]]
