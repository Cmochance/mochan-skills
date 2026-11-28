# agy-worktree — Git Worktree 工程开发规则

适用于启用 worktree 隔离开发的仓库（已执行 `agy-wt enter` 或列入 `~/.gemini/config/agy-worktree.json` 的 `strict_main_repos`）。若项目根目录 `AGENTS.md` 对构建命令、安装脚本、应用名称或保留目录有具体约定，**以项目根目录 `AGENTS.md` 为准**。

## 1. 主目录与 Worktree 隔离

- **主目录只停默认主分支（如 `main`）**：禁止在主目录建分支、改跟踪文件、新建源码文件或 commit。主目录只做四件事：读规则、`git pull --ff-only`、执行全局安装命令、存放不进仓库的本地文件。
- **使用 `agy-wt` 进出 Worktree**：
  - 开工或切换分支前执行 `agy-wt enter <分支名>`（自动按 `../<repo>-worktree/<repo>-<branch-slug>` 建或复用 worktree，并同步当前会话状态给 `agy-statusline` 与 `PreToolUse` 护栏；建新 worktree 前自动在主目录 `git pull --ff-only`，禁止用 `cp` 拷贝仓库）。
  - 离开工作区但保留分支目录时执行 `agy-wt exit`；PR 合并后走完整收尾执行 `agy-wt close`（详见 `/agy-worktree` skill）。
- **保持主目录为会话 `cwd`**：规则始终以主目录 `AGENTS.md` 为准；读写文件一律传 worktree 绝对路径，`git` / 构建 / 测试以 worktree 路径作为执行目录（如 `git -C <wt_path>`、`make -C <wt_path>`）。要修改 `AGENTS.md` 本身时，在 worktree 内修改，待合并后主目录 `git pull --ff-only` 生效。

## 2. 构建缓存、安装与本地文件红线

- **不绕过项目构建封装**：若项目通过 `Makefile` / 构建脚本封装了共享编译缓存（如 `--git-common-dir` 定位主目录 `.build/`）与并发锁（如 `lockf`），一律调用封装目标（如 `make build` / `make test`），禁止直接调用底层编译器命令绕过排队锁。
- **禁止在 Worktree 内执行 `install`**：在 worktree 内执行 `make install` 等安装目标会把 `~/.local/bin/<bin>` 等全局入口软链到即将删除的临时目录；安装只在合并后回主目录执行。手测直接运行 worktree 构建产物；单实例桌面应用启动前先退出已运行的旧实例。
- **本地文件与忽略规则**：不入库的本地文件只放主目录，worktree 内按主目录绝对路径读取、不拷贝。仅本机使用的忽略规则写入主目录 `.git/info/exclude`（自动对所有 worktree 生效、无需 PR）；需要入库的忽略规则才在 worktree 中改 `.gitignore`。

## 3. 合并后收尾与残留清理红线

- **合并 PR 仍需用户当条明确确认**；合并完成后立即加载 `/agy-worktree` skill 并优先通过 `agy-wt close` 执行完整 6 步收尾（diff 核对 → `status --short --ignored` 防静默删忽略文件 → 主目录 `pull --ff-only` + 安装 → macOS `.app` 进程退出与 `lsregister -u` 注销 + 无 `--force` 移除 worktree → 删本地 `-D` 与远端分支 + `fetch --prune` → `worktree list` 与 `branch -a` 双重核对）。每次仅清理刚合并的 PR，不动其他 worktree。
- **严禁误删共享资产**：清理构建/测试残留前必须核对归属；**绝不删除主目录共享构建缓存（如 `.build/`）**、全局软链指向的已安装二进制以及用户数据目录。
