---
name: transfer-bug-recorder
description: 记录与分类「在 Codex 桌面界面有明确报错语句」的 codex-app-transfer 问题。按 Codex UI 报错语句建索引,命中已知记录直接给分类+排查路径+根因;未命中则按方法论诊断、完事归档一条。当遇到/排查 Codex 界面报错(如 "stream disconnected before completion"、"error sending request for url"、"Reconnecting N/5" 等),或刚诊断完一个这类 bug 需要存档时使用。
---

# transfer-bug-recorder

把「Codex 界面有明确报错语句」的 transfer 问题做成**可检索知识库**:按报错语句分类引导 → 走对应排查路径 → 记录根因/修复/是否真 bug。目标是下次同类报错**快速定位**,不再从零长链路瞎查。

> ⚠️ **记录只是参考线索,不是定论。** 报错语句匹配到某条记录,只意味着"这是一个候选假设",**不等于根因相同** —— 同一句 Codex 报错完全可能是不同原因(本 skill 诞生那次就反复锚错方向)。命中记录后**必须按方法论结合当前实际去验证**(尤其方法论 #4「监控 Codex 进程真实 TCP 连接」、#2「代码+测试+观测三结合」)确认后才下结论。**把记录当起点假设,不当终点结论。** 验证与记录冲突 → 信实际,并补/订正记录。

## 何时用
- **查(LOOKUP)**:遇到 Codex 界面报错 → 先来 `records/INDEX.md` 按报错语句片段匹配。命中 → 读对应记录、照它的「决定性诊断」走。
- **记(RECORD)**:刚诊断完一个有明确 Codex UI 报错的 transfer 问题 → 按下方模板写一条 `records/<slug>.md` + 在 `records/INDEX.md` 加一行。

## 流程
1. **拿到报错原文**(verbatim,含 URL/端口/HTTP 码 —— 这些是分类钥匙)。报错若是 `Reconnecting N/5` 这种中间态,**等轮次真 settle 再读最终报错**(driver 完成信号会被中间态骗,见方法论 #5)。
2. `rg "<报错片段>" records/INDEX.md` → 命中走记录;未命中 → 按「分类引导」定层 + 「排查方法论」诊断。
3. 诊断完 RECORD 归档。

## 分类引导(按 Codex UI 报错语句定"层"+ 首要方向)

| 报错语句片段 | 层 | 首要排查方向 |
|---|---|---|
| `error sending request for url (http://127.0.0.1:PORT/...)` | 传输/连接层(reqwest 连不上) | **查 Codex 实际连哪个远端**(方法论 #4)。常见:`.codex/.env` 的 `HTTP_PROXY` 把本地回环也代理了、且代理端口死/变 → `records/proxy-port-stale-env.md` |
| `stream disconnected before completion` | 流式中断(连上又断) | 区分 WS 传输 / 上游掉流 / proxy 中断。开 `CAS_DIAG_TRACE=1` 看 forward-trace 上游码 |
| `Reconnecting N/5`(循环) | 传输重试耗尽 | 多是上面两类的表象;**等 settle 看最终报错**,别拿"Reconnecting"当结论 |
| 报错含 HTTP `4xx/5xx` | 上游 / adapter | forward-trace 的 outbound;provider 限流(429/503)/ 参数被剥 / schema 400 |
| `Thinking` 卡死 / 无文本输出 | 模型 / 审批 | 模型慢 / 等桌面端审批(M1 不支持远程批准)/ 纯工具轮无文本 |

> "层"判错是最大的坑:`error sending request` 是**传输层**(根本没连上目标),别当成 transfer 的业务/协议 bug。

## 排查方法论(2026-06-17 一次 proxy-port 惨痛长查的血泪)

1. **报错语句先定"层"**,按上表。传输层错 → 先问"Codex 到底连到哪了",而不是钻 transfer 协议逻辑。
2. **代码 + 测试 + 真实观测,缺一不可**。只看测试结果瞎猜会反复锚错方向(被用户点名批过)。
3. **proxy 侧先洗清**:直接探 transfer proxy 的 `/responses`,**HTTP/1.1 + h2c + WS 真帧三种传输各打一遍**(零依赖 Node 探针:`http.request` / `http2.connect` / 手搓 WS 帧)。三种都能完整回流 SSE = proxy 无辜,问题在 Codex 侧/环境。
3a. proxy WS 行为速查:native-responses provider 的 WS upgrade 回 426 让 Codex 降级 HTTP;chat provider(openai_chat)接受 WS 走 ws→http;warmup 帧(`generate:false`/空 input)回 Close 1003。
4. **★ 最决定性的一招:监控 Codex 进程的真实 TCP 连接**。
   ```powershell
   $end=(Get-Date).AddSeconds(30); $seen=@{}
   while((Get-Date) -lt $end){ $p=(Get-Process Codex,codex -EA SilentlyContinue).Id
     Get-NetTCPConnection -EA SilentlyContinue | ?{ $_.OwningProcess -in $p -and $_.RemoteAddress -notin @('0.0.0.0','::') } |
       %{ $k="$($_.RemoteAddress):$($_.RemotePort)"; if(-not $seen[$k]){$seen[$k]=1; Write-Output "$k $($_.State)"} }
     Start-Sleep -Milliseconds 250 }
   ```
   触发一轮(driver 或人工发消息),看它连的真实远端。proxy/MITM 都收不到时,这步直接看出"Codex 连的是代理口、不是目标端口"。
5. **截 settled 后的 Codex 界面**:有些报错只在轮次真结束后渲染;driver 的完成信号 `[data-local-conversation-final-assistant]` 会被"Reconnecting"中间态提前触发抓到假回复(见 codex-e2e-test skill)。远程机经 UU远程 + computer-use 截。
6. **`.codex/.env` 的代理会代理回环**:`HTTP_PROXY` 让 Codex 把 `127.0.0.1:18081`(transfer proxy)也走代理。代理端口死/变 → 整个 transfer 模式挂,但 **transfer 本身没毛病、与版本无关**。修法是改 `.env` 端口或加 `NO_PROXY=127.0.0.1,localhost,::1`。**这类是用户环境问题,别改 transfer 代码、别自作主张覆盖用户代理意图。**
7. **MITM 抓包的坑**(方法论 #4 通常已够,#4 不够才架):SSH 起 GUI app(Codex/transfer)落 **session 0**(用户看不见、半残、网络行为可能异常);后台进程要 **WMI `Win32_Process Create` 或计划任务(S4U)** 才脱离 SSH 会话;捕获日志用 **append 别 truncate**(每次重启 truncate 会丢数据);**IPv4 `127.0.0.1` 和 IPv6 `::1` 都要监听**(Codex 可能走 IPv6)。远程 Windows 测试机的 SSH 访问按你的本地配置(主机别名 / 凭据)。

## 记录模板(写到 records/<slug>.md)
```
---
error_signatures:        # 匹配用的报错原文片段(可多条,保留原文标点/URL)
  - "error sending request for url (http://127.0.0.1"
symptom: 一句话症状
layer: 传输层 | 流 | 上游 | 模型
is_transfer_bug: false   # 是否真 transfer 代码 bug(false=环境/外部,别改代码)
---
- **现象**:Codex 界面报 `<原文>`
- **走过的弯路**:别人少踩(本次锚错了哪些方向)
- **决定性诊断**:哪一步一锤定音 + 命令/证据
- **根因**:...
- **修复**:...
- **关联**:`records/<其它记录 slug>.md` / issue 编号 / commit
```

---

## 来自 auto-memory 的实证补充(2026-07-03 迁移,如与上文重复以上文为准)

`~/.claude/skills/transfer-bug-recorder/`(2026-06-17 建)。把「Codex 桌面界面有明确报错语句」的 transfer 问题做成可检索知识库:**按报错语句建索引,命中已知记录直接给分类+排查路径+根因;未命中按方法论诊断、完事归档一条**。

- **何时用**:遇到/排查 Codex 界面报错(`stream disconnected before completion` / `error sending request for url` / `Reconnecting N/5` / HTTP 4xx-5xx / `Thinking` 卡死等),或刚诊断完这类 bug 要存档。
- 结构:`SKILL.md`(分类引导表 + 排查方法论 + 记录模板)+ `records/INDEX.md`(报错语句索引,`rg` 匹配)+ `records/<slug>.md`(每条 bug 详录)。
- 排查方法论核心:① 报错先定"层"(`error sending request`=传输层、先问 Codex 连到哪);② **监控 Codex 进程真实 TCP 连接(`Get-NetTCPConnection` by Codex/codex pid)是最决定性一招**;③ 代码+测试+真实观测缺一不可,别只看测试结果瞎猜。
- 配套:[[reference_windows_test_machine_ssh_access]]、[[reference_codex_responses_ws_transport_fallback]]、skill `codex-e2e-test`。
