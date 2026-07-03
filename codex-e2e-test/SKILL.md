---
name: codex-e2e-test
description: 通过 CDP 注入驱动真实运行的 Codex Desktop 跑一轮对话并读回 assistant 回复,对 codex-app-transfer 的 Codex 集成做 E2E/冒烟测试(验证 provider 路由 / 协议适配 / 注入 / 代理链路端到端是否真的工作),替代很多手搓 E2E。默认新建独立会话测试、结束精准归档,绝不动用户已有会话。当需要"在真实 Codex 里发一句 prompt 看实际效果"而不仅是跑单测时使用。
---

# codex-e2e-test

用 CDP 驱动**真实运行的** Codex Desktop 跑一轮对话、读回最终 assistant 文本 —— 把"在真机 Codex 里实测某行为"这类 E2E 自动化掉。

## 何时用
- 验证 transfer 改动后 Codex 的**真实**行为:某 provider 路由是否生效、某模型是否能正常回答、协议适配 / 注入 / 代理链路端到端是否打通。
- 任何"我需要在真实 Codex 里发一句话看结果"的测试。

## 第一原则:能 skill 跑的测试,skill 自己跑
**只要能用本 skill 完成的 Codex 实测,就由 skill 自动跑完并读回结果判定,不要把这种测试丢给用户手动操作。** 用户要的是结论,不是操作步骤。

## 前提
- Codex.app 正在运行,且带 `--remote-debugging-port`(写出 `~/Library/Application Support/Codex/DevToolsActivePort`)。
- 缺端口时 driver 会报 actionable 错误,不会静默失败。
- **若要抓 proxy wire(forward-trace 验上游 200/400):只需 transfer 当前「诊断模式」为开即可**——诊断是**运行时即开即用**的(app 内「诊断 / 流量查看器」toggle → `set_forward_trace_enabled`,gate 见 `proxy::diagnostics::forward_trace_enabled`;`main.rs:199-204` 启动不读持久 config、纯运行时 toggle)。**不需重启 transfer、不需 `CAS_DIAG_TRACE` 环境变量、不需 pkill**。`CAS_DIAG_TRACE=1` 只是「启动时自动开」的一种便利途径,不是必需;运行时 toggle 才是常态。
  - **默认关**(未 toggle 时零采集);**运行时状态,不持久化 → 重启 transfer 即关**,重开需再 toggle。
  - **刚 toggle 开时,今天的 `~/.codex-app-transfer/forward-trace/<YYYYMMDD>.jsonl` 可能还不存在**——它在**第一条请求流过后**才创建。文件为空 / 不存在 ≠ 诊断没开,只是还没请求流过;直接驱动一轮 Codex,trace 就会写出来。

## 启动:让 transfer(带诊断)+ Codex(带 CDP)就位(macOS,2026-06-17 实测可行)

> **⚠️ transfer 实例铁律(2026-07-03 用户收严,撤销 2026-06-17 "为测试可自行 pkill+open" 放宽)**:**transfer 的任何新实例(dev 模式 tauri dev/cargo run 或任何 build 产物)一律不自行启动/重启,e2e 目的也不例外,必须先明文申请许可**——新实例与在跑实例抢 18080 端口/单实例锁。默认路径:**复用当前在跑的 transfer 实例**;需要 forward-trace 就用**运行时诊断 toggle**(见「前提」节,即开即用,无需重启)。下面 step 1 的"杀旧+带诊断起新 transfer"仅在拿到用户明文许可后才执行。驱动 Codex.app(OpenAI 客户端)做 CDP 不在此禁令内,且优先复用已带 CDP 端口的在跑 Codex(有 DevToolsActivePort 就直接用,跳过 step 2)。

> **背景**:transfer 的 admin `/api/*` 路由走 Tauri `cas://localhost/` 同进程、**不绑 TCP**(`src-tauri/src/admin/mod.rs`),所以 `restart_codex_app` 端点**无法 curl**,"经 transfer 重启 Codex"是 UI 驱动的。自动化时直接**复制 transfer 内部那条 open 命令**(`process.rs::open_command` / `should_attach_debug_port`)拉 Codex。**`/Applications/` 已装版绝不擅动;验证改动用 `dist/mac` 新 build。**

> **运行参数**(`REPO` / `APP_BIN` / CDP 端口)见 `config.example.sh`,复制为 `config.local.sh` 填你的本地路径,启动前 `source` 它(`config.local.sh` 含真实路径,应 gitignore)。

```bash
source ~/.claude/skills/codex-e2e-test/config.local.sh   # 提供 REPO / APP_BIN / CDP_PORT

# 1. 【必须先拿到用户明文许可】带诊断起 transfer。先杀旧 transfer 避免单实例锁
#    (默认不走这步:复用在跑实例 + 运行时诊断 toggle 即可)
pkill -f "Codex App Transfer.app" 2>/dev/null; sleep 2
CAS_DIAG_TRACE=1 "$APP_BIN" >/tmp/cas_transfer.log 2>&1 &

# 2. 杀净 Codex 再 open 带 CDP。**关键坑**:
#    - 必须杀含 helper 的**全部** `Codex.app/Contents/` 进程(只杀主进程 → open -a 只 activate 不传 --args → 无 CDP);
#      模式 `Codex.app/Contents/` 不会误伤 `Codex App Transfer.app`(其路径是 `Transfer.app/Contents`)。
#    - zsh 下 `--remote-allow-origins=*` 的 `*` **必须引号**,否则 glob 报 "no matches found" 中止整条命令。
while pgrep -f "/Applications/Codex.app/Contents/" >/dev/null 2>&1; do
  pkill -9 -f "/Applications/Codex.app/Contents/"; sleep 1
done
sleep 5
rm -f "$HOME/Library/Application Support/Codex/DevToolsActivePort"
open -a "/Applications/Codex.app" --args --remote-debugging-port="$CDP_PORT" "--remote-allow-origins=*"

# 3. 轮询就绪(~5–60s 起来),等到 composerPresent:true
for i in $(seq 1 24); do sleep 5
  node ~/.claude/skills/codex-e2e-test/codex-driver.mjs status 2>/dev/null | tail -1 | grep -q '"composerPresent":true' && { echo READY; break; }
done
```

- `open -a Codex --args --remote-debugging-port=$CDP_PORT`(`CDP_PORT=0` 即自动分配)直接给 CDP,**不依赖** transfer 设置里的 CDP 功能开关(transfer 自己拉 Codex 时才按 `should_attach_debug_port` 的 theme/quota/plugin_unlock gating 决定带不带端口)。
- 验 proxy wire:跑 e2e 前记 `~/.codex-app-transfer/forward-trace/<YYYYMMDD>.jsonl` 字节偏移,跑完只读新增字节,找 `outbound` 看上游响应码 / 报文(每行一请求:`inbound`/`outbound`/`response`)。
- **授权(2026-07-03 收严)**:transfer 新实例(dev/build)一律**先明文申请**,e2e 也不例外(见顶部铁律);Codex.app 的 pkill+open 拉 CDP 仍可为测试自行执行,但优先复用已带端口的在跑实例。非测试场景一律遵守"build 完不自动 open"。

## Windows 端测试(2026-06-17 实测,经 Tailscale `ssh win` 远程驱动)

> 场景:transfer + Codex 跑在远程 **Windows** 机(经 Tailscale `ssh win` 可达,主机别名 / 凭据按你的本地配置),从 Mac 上的 Claude 驱动。
> **关键:driver 唯一的 macOS 假设就是端口文件路径**(`portFile()` = `os.homedir()/Library/Application Support/Codex/DevToolsActivePort`)。在 Windows 把这个**同名路径文件造出来、写入端口号**,driver 即可零改在 Windows 本地跑(`localhost` 直连 CDP,**不用 SSH 隧道、不跨主机**)。

```bash
# 1. 查 Windows Codex 的 CDP 端口(transfer 按 should_attach_debug_port gating 通常已自动带,无需重启 Codex)
ssh win 'Get-CimInstance Win32_Process -Filter "Name=''Codex.exe''" | ? { $_.CommandLine -match "remote-debugging-port" } | % { $_.CommandLine -replace ".*--remote-debugging-port=(\d+).*","$1" } | Select -First 1'
#   Windows 的 DevToolsActivePort 官方路径(%APPDATA%\Codex、%LOCALAPPDATA%\Codex)实测**可能不写**,
#   所以端口从 Codex.exe 命令行(或 `Get-NetTCPConnection -State Listen` 找 Codex pid 的 127.0.0.1 监听口)拿最可靠。
#   查出来为空 = Codex 没带端口 → 让 transfer 开任一 CDP 功能后重启 Codex;自行带端口拉起会动用户 Codex,**先问**。

# 2. driver 拷到 Windows + 在「Windows 的 macOS 风格路径」造端口文件(写入第 1 步的端口,如 11751)
scp -q ~/.claude/skills/codex-e2e-test/codex-driver.mjs win:codex-driver.mjs
ssh win 'New-Item -ItemType Directory -Force "$env:USERPROFILE\Library\Application Support\Codex" | Out-Null; Set-Content -LiteralPath "$env:USERPROFILE\Library\Application Support\Codex\DevToolsActivePort" -Value "<PORT>" -Encoding ascii'

# 3. 在 Windows 本地跑 driver(Windows 需 Node ≥20;实测 v24 自带 fetch+WebSocket)。`ssh win` 默认 shell 已是 pwsh
ssh win 'node "$env:USERPROFILE\codex-driver.mjs" status'                       # 验连通:composerPresent:true
ssh win 'node "$env:USERPROFILE\codex-driver.mjs" run-isolated "<prompt>" --timeout 180'
```

- **零干扰**:Codex 已带端口时全程**不重启 Codex、不动用户会话**(run-isolated 仍只归档自己新建的;运行前已有 N 会话做安全闸基线)。
- forward-trace 验上游同样需 Windows transfer 以 `CAS_DIAG_TRACE=1` 重启才写 `%USERPROFILE%\.codex-app-transfer\forward-trace\` —— 但这会**重启用户在用的 transfer,先确认**。

## 怎么用
driver:`~/.claude/skills/codex-e2e-test/codex-driver.mjs`(零依赖,Node ≥20 用内建 WebSocket)。输出**最后一行是 JSON 结果**,前面是进度日志(stderr)。

### 默认:独立会话 + 精准清理(强烈推荐)
```bash
node ~/.claude/skills/codex-e2e-test/codex-driver.mjs run-isolated "<prompt>" [--timeout 180] [--keep]
```
流程:**新建一个独立测试会话** → 灌入 prompt → 提交 → 轮询读回**最终 assistant 文本** → **归档该测试会话**。
结果 JSON:`{ok, mode, reply, threadId, timedOut, archived, archiveNote, [rawTail, note]}`
- `reply`:模型最终回复文本(已剥时间戳 / "Thinking" / "Worked for" 等 UI 噪声)。拿它做断言。
- `reply` 为空时看 `rawTail` / `note`:多半是模型仍在思考 / 等待**桌面端批准**(M1 不支持远程批准)/ 纯工具轮无文本。
- `archived:true` + `archiveNote` 含"已从列表移除,确认" = 测试会话已精准清理。
- `--keep`:不归档(留会话供人工查看,事后可 `archive <thread-id>` 清理);`--timeout`:秒,默认 180。

### 仅当测试必须复用已有上下文:在当前会话测
```bash
node ~/.claude/skills/codex-e2e-test/codex-driver.mjs run-here "<prompt>" [--timeout 180]
```
在 Codex **当前打开的会话**里发一轮。**绝不归档任何会话**(保护用户已有会话)。只有当测试确实需要现有对话上下文时才用;否则一律 run-isolated。

### 辅助
```bash
node ... status                     # {composerPresent, submitting, activeThreadId, threadCount}
node ... archive "<thread-id>"      # 手动归档指定会话(仅用于清理 --keep 留下的测试会话)
```

## 安全保证(skill 内置 + 调用方须遵守)
1. **默认 run-isolated**(独立会话),不污染用户工作区。
2. **精准清理**:run-isolated 只归档它**自己新建**的会话 —— 归档前用「运行前已存在的 thread-id 集合」做安全闸,目标 id 必须不在该集合里(证明是新建的)才归档;捕获不到新 id → **跳过归档**而非乱删。
3. **绝不删用户已有会话**:run-here 永不归档;`archive` 只接受显式传入的 thread-id。
4. 归档 = Codex 原生「移除出列表」(`onArchive`,可在 Archived 里找回),**非硬删**,比删除更安全。
5. Codex 桌面端已有一轮在跑(`submitting=true`)时 run-isolated 会**拒绝注入**,避免与桌面操作互相干扰。

## 判定 / 断言
读结果 JSON 的 `reply` 断言(包含某子串 / 等于某值 / 非空)。`timedOut:true` 或 `reply` 空且 `rawTail` 显示 `Thinking` / `Approve for me` → 模型未产出文本(可能需桌面批准或模型慢),据此判定失败或重试。

## 截图佐证:有些故障只在 Codex 界面显示 + 完成信号会被"重连中"骗(2026-06-17 实证)

driver 只读 `[data-local-conversation-final-assistant]` 文本,有两个盲区,**怀疑时必须 computer-use 截 Codex 实时界面佐证**:

1. **完成信号会被中间态提前触发**:上游流不稳时 Codex 显示 `Reconnecting N/5`,这段"重连中"文本会让 `[data-local-conversation-final-assistant]` 提前出现 → driver 把 `reply` 抓成 `"Reconnecting\n0\n1...\n9\n/5"` 且 `timedOut:false`,**误当最终回复**。实际那一轮还在重试,**真正的结果(成功答案 / 错误 banner)要等重连耗尽、轮次真结束才渲染**。
2. **关键报错只在界面**:本案 driver 的 `reply` 只有 `Reconnecting/.../5`,**等轮次真结束后截图**才看到真因 —— 助手区红字 `⊘ stream disconnected before completion: error sending request for url (http://127.0.0.1:18081/responses)`(transfer proxy 层流中断,18081=proxy 端点),底部模型 `mimo-v2.5-pro`、右侧 `81 token/s`。光看文本会误判成"路由失败",截图才定位到"路由对了、是 18081 proxy 这条响应流断了"。

**流程(纳入每次 e2e)**:`reply` 含 `Reconnecting` / 含 `Thinking` / 含 `Approve` / 为空 / `timedOut` → **不要信 `reply`**,**先等几秒让轮次真结束**(再跑 `status` 看 `submitting` 转 false 且界面不再 Reconnecting),再 computer-use 截图 + `zoom` 读:助手区错误 banner、底部实际模型、右侧 Usage(token/s、累计)、approval 弹窗。
- 本机 Codex:Codex 在前台,直接 computer-use 截。
- **远程 Windows Codex**:driver 跑在 Windows 本地、**不会把窗口拉到前台** → 经远程桌面截(UU远程 `com.netease.uuremote`,窗口在外接屏需 `switch_display`;必要时先点 Windows 任务栏 Codex 图标前置)。
- (driver 可改进项:把 `reply` 含 `Reconnecting`/`stream disconnected` 视为未完成、继续轮询到真 settle,避免误报 —— 暂未做,先靠截图兜底。)

## 实现机制(漂移时按此重新探测)
- 输入框 = `.ProseMirror`(ProseMirror);灌字 = `execCommand('insertText')`(全选替换 + 校验防残留草稿)。
- 提交 = 点 `button[class*="size-token-button-compose"]`,回退爬 fiber 调 `handleSubmit()`。
- **完成信号**(关键)= `[data-local-conversation-final-assistant]` 出现且有非空文本(最终答案渲染好才出);**不**单靠 fiber `isSubmitting`(它在 Thinking/streaming 阶段会提前读 false → 误判完成抓空)。
- 读回 = `[data-local-conversation-final-assistant]` 克隆后剥用户气泡 + 时间戳叶子;兜底用 `[data-user-message-bubble]` + 排除 composer 的滚动容器。
- 移除会话 = thread 行(`[data-app-action-sidebar-thread-id]`)fiber 的 `onArchive()`。
- 端口 = `~/Library/Application Support/Codex/DevToolsActivePort` 首行(`portFile()` 写死此 macOS 路径)。**Windows 端无此文件 → 在 `%USERPROFILE%\Library\Application Support\Codex\DevToolsActivePort` 造同名文件、写入从 Codex.exe 命令行查到的端口,即可零改 driver 在 Windows 本地跑(见上「Windows 端测试」)。**
