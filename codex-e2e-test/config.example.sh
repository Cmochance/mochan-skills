# codex-e2e-test 运行参数(占位模板)
# 复制为 config.local.sh 后填你的本地路径,在启动脚本里 `source` 它。
# config.local.sh 含真实本地路径,应 gitignore;提交的是本占位模板。

# transfer 仓库根(或 worktree 根)
REPO=/path/to/codex-app-transfer

# 待测 transfer 可执行文件(用 dist/mac 新 build,绝不动 /Applications 已装版)
APP_BIN="$REPO/dist/mac/Codex App Transfer.app/Contents/MacOS/codex-app-transfer"

# Codex CDP 远程调试端口。0 = 让 Codex 自动分配(端口写进 DevToolsActivePort,driver 自动读),
# 填具体端口号则固定监听该口。
CDP_PORT=0
