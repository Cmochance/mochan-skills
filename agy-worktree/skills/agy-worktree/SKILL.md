---
name: agy-worktree
description: >-
  Manage Git worktrees for Antigravity CLI (agy) sessions with agy-wt (enter,
  exit, close, status, list, strict, init-config, doctor), enforce main-repo
  and protected_paths guards via PreToolUse hooks, sync active worktree display
  with agy-statusline, and execute the full 6-step post-merge closeout SOP
  including ignored-file safety checks, shared build cache + lockf serialization
  recipes, and macOS .app LaunchServices cleanup. Use when entering/exiting a
  worktree, configuring strict_main_repos, cleaning up after PR merge, or
  troubleshooting worktree workflows.
---

# agy-worktree — Git Worktree 完整工作流与工程手册

面向 Antigravity CLI（`agy`）的三层 Worktree 工作流插件：
- **Layer 1（显式生命周期）**：`agy-wt enter` / `exit` / `close` 写入会话私有状态 `<appDataDir>/brain/<cid>/scratch/worktree.json`，与 `agy-statusline` 状态栏实时联动（多窗口完全隔离）。
- **Layer 2（被动兜底感知）**：即使未调用 `agy-wt enter`，`agy-statusline` 仍通过增量扫描 `transcript.jsonl` 尾部识别同仓库 linked worktree（显示 `~<branch>` 提示）。
- **Layer 3（硬护栏）**：插件根 `hooks.json` 的 `PreToolUse` 钩子 `scripts/worktree-guard.py`，保护已 `enter` 或列入 `strict_main_repos` 的主仓库不被误写，并拦截 worktree 内误执行 `make install`。

> **优先级约定**：若项目根目录 `AGENTS.md` 对构建命令、安装目标、应用名、保留路径有具体规定，以项目 `AGENTS.md` 为准；本手册作为通用完整规则和执行引擎。

---

## 1. `agy-wt` CLI 速查

直接作为独立命令调用 `agy-wt`（需要写 `.git/worktrees/` 或兄弟目录时用 `BypassSandbox: true`，不要串联 `&&` 或环境变量前缀，以保留 CLI 前缀自动审批）：

```bash
# 进入或新建 worktree（自动绑定当前 agy 会话）
agy-wt enter feat/my-feature
agy-wt enter feat/my-feature --base main
agy-wt enter feat/my-feature --existing        # 仅绑定已有 worktree，不新建
agy-wt enter feat/my-feature --no-pull         # 跳过主目录 git pull --ff-only

# 退出当前会话的 worktree 绑定（默认保留目录）
agy-wt exit
agy-wt exit --remove                           # 安全检查通过后移除目录（绝不用 --force）

# PR 合并后完整 6 步自动收尾
agy-wt close                                   # 关闭当前会话绑定的 worktree
agy-wt close feat/my-feature                   # 关闭指定分支对应的 worktree

# 查看与配置
agy-wt status
agy-wt list
agy-wt strict list
agy-wt strict add ~/path/to/repo               # 省略路径时自动取当前仓库主目录
agy-wt strict remove ~/path/to/repo
agy-wt init-config
agy-wt doctor
```

> 会话绑定优先级：`--brain-dir` > `--session` > 环境变量 `AGY_CONVERSATION_ID` / `AGY_SESSION_ID` > `PreToolUse` 自动写入的短期私有会话提示（消费即清理）。在 `agy` 会话内直接执行 `agy-wt`（含 `cd <repo> && agy-wt` 或 `--repo <repo>`）时可自动绑定，无需手动传 `--session`；从外部终端调用时可显式传 `--session <cid>` 或 `--brain-dir <path>`。

---

## 2. 本地开发用 Worktree 完整规则

1. **主目录只停默认主分支（`main`）**：
   - 不在主目录建分支、改跟踪文件、新建未忽略源码文件或 commit。
   - 主目录仅用于：读取 `AGENTS.md`、`git pull --ff-only`、执行全局安装（如 `make install`）、存放不入库的本地文件。
2. **兄弟目录布局与命名**：
   - 默认路径模板：`../{repo}-worktree/{repo}-{branch_slug}`，分支名 `/` 替换为 `-`（例如 `feat/status-item-menu` → `../myrepo-worktree/myrepo-feat-status-item-menu`）。
   - 多个 worktree 可同时开发，互不干扰。
3. **创建方式**：
   - 先在主目录执行 `git pull --ff-only`，再 `git worktree add -b <分支> <wt_path> <base>`（由 `agy-wt enter` 自动完成）。
   - **禁止用 `cp` 拷贝仓库目录**。linked worktree 里的 `.git` 是指向主目录 `.git/worktrees/<name>` 的指针文件，对象库始终在主目录。同一分支不能同时在两个目录检出，因此主目录始终不离开 `main`。
4. **会话 `cwd` 与路径使用**：
   - 会话工作目录保持在主目录，确保读取到的始终是主目录的 `AGENTS.md`。
   - 读写文件一律使用 worktree 的绝对路径；`git` / `make` / 测试以 worktree 路径作为执行目录（如 `git -C <wt_path>`、`make -C <wt_path>`）。
   - 修改 `AGENTS.md` 本身时，在 worktree 内修改并走正常 PR 合并，待主目录 `git pull --ff-only` 后生效。
5. **禁止在 Worktree 内执行 `install`**：
   - 像 `make install` 这类命令常将 `~/.local/bin/<bin>` 软链到当前目录的构建产物；在 worktree 内执行后，一旦 worktree 合并删除，全局命令行会立刻变成悬空死链。
   - 需要手测时直接运行 worktree 构建产物（如 `open "<wt_path>/build/MyApp.app"`）；若应用有单实例锁，先退出正在运行的旧实例。
6. **不入库的本地文件与忽略规则**：
   - 本地调试文件、私有脚本、临时配置只放主目录，不拷贝进 worktree；worktree 需要使用时按主目录绝对路径读取。
   - 仅本机使用的忽略规则写入主目录 `.git/info/exclude`（自动对所有 worktree 生效，无需开 PR）。
   - 需要全团队共享的忽略规则才在 worktree 内修改 `.gitignore` 提交 PR。
   - 主目录中的未跟踪文件不影响 `git pull --ff-only`（除非远端新增了同名路径）。

---

## 3. 编译型多 Worktree 共享缓存与并发排队配方

对 Swift / Rust / C++ 等编译较慢的项目，避免每个 worktree 重复拉依赖和重编译全量缓存：

1. **共享编译缓存**：在 `Makefile` / 构建脚本中通过 `git rev-parse --path-format=absolute --git-common-dir` 找到主仓库 `.git` 的父目录，将主目录的 `.build/`（或 `target/`）作为统一缓存路径传入编译器（如 Swift 的 `--scratch-path <main_dir>/.build`、Cargo 的 `CARGO_TARGET_DIR=<main_dir>/target`）。
2. **并发排队锁（`lockf`）**：多个 worktree 共享同一编译缓存时，必须用文件锁（macOS `/usr/bin/lockf`、Linux `flock`）同时包住 **“编译”和“把产物拷到各自 worktree 的 `build/`”** 两个阶段：
   - 如果只锁编译不锁拷贝，A 分支刚编完还没拷走，B 分支就开始重编覆盖共享缓存里的同名二进制，会导致 A 拿到 B 的产物。
   - 锁被占用时打印提示并等待前一个任务完成。
3. **禁止绕过封装**：项目一旦提供了封装缓存与锁的 `make build` / `make test` / `make dist`，严禁直接执行裸 `swift build` / `swift test` 等命令绕过排队锁或在 worktree 里另建一份孤立缓存。

参考 `Makefile` 片段（macOS，兼容路径空格与非 git 目录回退，且在等待锁时打印提示）：
```makefile
MAIN_REPO_DIR  := $(shell common="$$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" && dirname "$$common" || pwd)
SHARED_SCRATCH := $(MAIN_REPO_DIR)/.build
BUILD_LOCK     := $(SHARED_SCRATCH)/project-make.lock

build:
	@mkdir -p "$(SHARED_SCRATCH)" build
	@{ /usr/bin/lockf -k -t 0 "$(BUILD_LOCK)" true 2>/dev/null || echo "Waiting for build lock $(BUILD_LOCK)..."; }
	@/usr/bin/lockf -k "$(BUILD_LOCK)" sh -c 'swift build --scratch-path "$(SHARED_SCRATCH)" && cp "$(SHARED_SCRATCH)/debug/mybin" build/mybin'
```

---

## 4. 合并后 6 步完整收尾 SOP

> **前置硬约束**：合并 PR 必须由用户在当条消息中明确指示。PR 合并完成后，默认连续执行以下 6 步（优先直接调用 `agy-wt close`，以下列出每步校验语义供手工兜底与排障）：

1. **校验分支内容与合并后的主分支一致**：
   - 在主目录执行 `git fetch --prune`，再执行 `git diff --quiet origin/main <分支>`。
   - 若存在任何差异，**立即中止并报告差异文件，绝不删除**。
2. **检查 worktree 脏状态与“被忽略文件静默删除陷阱”**：
   - 在 worktree 执行 `git status --short --ignored`。
   - 有任何已修改/暂存文件 → 立即中止报告。
   - 有任何未跟踪文件（`??`）→ 中止报告，逐个确认丢弃或搬回主目录。
   - 有任何被忽略文件（`!!`）且**不在 `exit.ignored_safe_dirs`（如 `build/`、`dist/`）中** → **立即中止并逐个确认**。
   - **原因**：`git worktree remove` 遇到未跟踪文件会拒绝删除，但**遇到被忽略文件会不加任何提示直接删除**。需要保留的被忽略文件必须先搬回主目录。
3. **主目录快进更新与合并后安装**：
   - 确认主目录停在默认主分支后执行 `git pull --ff-only`。
   - 按仓库配置执行 `exit.post_merge_commands`（如项目需要 `make install` 刷新全局二进制软链）。
4. **清理 worktree 产出的 macOS `.app` 并安全移除 worktree**：
   - 若为 macOS 且 worktree 的 `build/` 或 `dist/` 下存在非软链的 `.app` 包：
     1. 通过 `ps -axo pid=,comm=`（或 `pgrep -fl "<AppName>.app"` 并核对可执行文件路径前缀）检查进程，**仅退出可执行路径严格位于本 worktree `.app/` 内的进程**（不动主目录、其他实例或编辑/查看该路径的终端进程）。
     2. 对 worktree 内的每个 `.app` 执行 `/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -u "<app_path>"`，防止系统 LaunchServices 数据库残留指向已删路径的僵尸条目。
   - 执行 `git worktree remove <wt_path>`（**严禁带 `--force`**；若被拒绝，回到第 2 步排查残留文件），并核对目录已不存在。
5. **删除本地分支与远端分支并修剪**：
   - 删除本地分支：`git branch -D <分支>`（`-D` 兼容 GitHub squash merge）。
   - 删除远端分支：`git push origin --delete <分支>`（若仓库已开启合并自动删分支，跳过即可）。
   - 执行 `git fetch --prune`。
6. **双重核对与作用域隔离**：
   - 执行 `git worktree list` 与 `git branch -a`，确认目标 worktree、本地分支、远端跟踪分支均已消失。
   - 每次**只删除刚合并 PR 对应的 worktree 与分支**，严禁误碰其他并行开发中的 worktree。

---

## 5. 残留清理边界红线

当用户要求清理构建/测试残留时：
1. 删除 `build/`、`dist/`、`/tmp` 或系统临时目录中本项目生成的测试产物前，必须先核对归属确认确为本项目产生。
2. **严禁删除主目录共享编译缓存**（如 `.build/`、`target/`），否则下次构建需全量重编。
3. **严禁删除全局软链指向的已安装二进制及用户状态/账号数据目录**：在全局或 `repos.<repo>.protected_paths` 中声明后，`PreToolUse` 护栏会直接拦截针对这些路径（及其父目录）的 `rm`/`rmdir`/`unlink`。

---

## 6. 配置文件参考（`~/.gemini/config/agy-worktree.json`）

运行 `agy-wt init-config` 生成初始配置（模板见插件目录 `config.example.json`）。支持全局默认值 + `repos` 按仓库覆写（含 `guard.enabled`/`guard.mode`/`protected_paths`）：

```json
{
  "strict_main_repos": ["~/projects/my-strict-repo"],
  "path_template": "../{repo}-worktree/{repo}-{branch_slug}",
  "branch_slug_separator": "-",
  "default_base_branch": "auto",
  "protected_paths": [],
  "guard": {
    "enabled": true,
    "mode": "active-and-strict",
    "block_install_in_worktree": true,
    "install_command_patterns": ["\\bmake\\s+(?:.*\\s)?install\\b"],
    "allow_main_paths": [".git/info/exclude"]
  },
  "enter": {
    "auto_pull_main": true,
    "post_create_commands": []
  },
  "exit": {
    "default_action": "keep",
    "ignored_safe_dirs": ["build", "dist", ".build", "target", "node_modules", ".pytest_cache", "__pycache__", ".venv"],
    "cleanup_macos_app_bundles": "auto",
    "delete_remote_branch": true,
    "post_merge_commands": []
  },
  "repos": {
    "~/projects/my-strict-repo": {
      "ignored_safe_dirs": ["build", "dist"],
      "post_merge_commands": ["make install"],
      "protected_paths": [".build", "build/my-bin", "~/.my-app"]
    }
  }
}
```
