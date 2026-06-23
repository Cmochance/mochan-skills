# 前端 JavaScript 逆向

本域聚焦定位接口签名、加密参数、风控字段的实际生成逻辑。典型任务：

- 某请求带一个 `sign` / `token` / `x-bogus` / `_signature` 参数，要还原它怎么算的
- 某请求体被整体加密 / 编码,要找加解密函数链路
- 风控字段(设备指纹、环境采集结果)由哪段脚本采集、依赖哪些浏览器对象
- 追踪某个 XHR/Fetch/WebSocket 的触发点和调用来源

不属于本域:二进制(PE/ELF/Mach-O)、APK/Android、iOS、WASM、固件 —— 改走对应子域。

## 核心原则

- **Observe-first**:先看清请求链路与脚本来源,再动手。不要一上来猜环境。
- **Hook-preferred / Breakpoint-last**:优先用轻量 Hook / 运行时采样拿入参返回值,断点是更重的手段,留到轻量观察不够时再上。
- **Evidence-first**:本地补环境的每一步都要有页面观测证据支撑,禁止空想式补 `window/document/navigator/crypto`。
- **Rebuild-oriented**:目标是把页面证据搬到 Node 本地能稳定复现出目标参数,而不是只在浏览器里看一眼。
- **最小化**:一次只补一个环境缺口,补完立即复测,记录 first divergence 是否前移。

## 工作流:Observe → Capture → Rebuild → Patch → DeepDive

### 1. Observe(确认目标,不猜环境)

目标:锁定目标请求、相关脚本、候选函数。产出:目标请求 URL/特征、initiator 线索、可疑脚本 URL。

推荐开场顺序(MCP 工具名见下文):

1. 打开/导航到目标页面(`new_page` / `navigate_page`)
2. 列最近网络请求(`list_network_requests`),找到目标请求
3. 取请求的 initiator 调用栈(`get_request_initiator`)回溯调用来源
4. 列脚本(`list_scripts`)建立脚本范围
5. 在源码里搜请求路径、参数名、函数名(`search_in_sources`),缩小到几个可疑脚本/函数

DevTools 手动等价物:Network 面板看 Initiator 列(展开成调用栈)→ Sources 面板 Ctrl+Shift+F 全局搜参数名 → 右键脚本 "Pretty print" 格式化压缩代码。

### 2. Capture(最小侵入采样)

目标:对目标请求做最小侵入采样,拿到参数样例、调用顺序、运行时值。

手段优先级:

- 优先 **XHR/Fetch 断点**(`break_on_xhr`,只填能稳定命中的 URL 片段),命中后整条调用栈在手
- 优先 **轻量运行时观察**(`evaluate_script`),例如直接读全局变量、调一次目标函数看返回
- 命中暂停后先看 `get_paused_info`(默认 frameIndex=0,即栈顶帧),读调用栈与局部变量
- 不够时再用 **函数文本断点**(`set_breakpoint_on_text`),按代码片段下断
- WebSocket 场景用 `get_websocket_messages` 看收发帧

关键产出:目标参数在哪个函数生成、入参从哪来、输出长什么样、调用顺序。

### 3. Rebuild(搬到 Node)

页面侧先确认清楚这些,再回 Node:

- 真实入口函数(签名/加密的那个,不是包装层)
- 调用顺序(谁先算什么)
- 参数来源(哪些来自用户输入、哪些来自全局状态)
- 依赖的浏览器对象,以及是否依赖时间、随机数、storage、cookie、UA、canvas、crypto

Node 侧默认顺序:

1. 把目标脚本(尽量原样,别提前删改)导入到一个 Node 脚本里
2. 给宿主对象做**最小 shim**(只补眼下确认要用的)
3. 跑入口函数
4. 记录首个异常或 first divergence(本地输出与页面真值第一处不一致的点)
5. 回到页面证据补齐那个缺口,再跑

不要一次性模拟整个浏览器。先让脚本跑到第一个报错,缺什么补什么。

### 4. Patch(按报错驱动补环境)

规则:

- **先看缺什么,再补什么** —— 让脚本自己报 `xxx is not defined` / `Cannot read property of undefined`,顺着报错补
- **一次只补一个最小因果单元**,补完立即复测
- 补的层次顺序:**先补值,再补函数壳,再补返回对象契约**
  - 补值:`navigator.userAgent`、`screen.width`、固定的 cookie 字符串等
  - 补函数壳:被调用但返回值不参与计算的函数,先给空壳让它别崩
  - 补返回对象契约:函数返回值会被后续读字段的,要补到字段结构对得上
- 每次补丁后检查 first divergence 是否前移(前移=方向对)
- 常见补环境对象:`window`、`document`、`navigator`、`location`、`screen`、`localStorage`/`sessionStorage`、`document.cookie`、`crypto`/`crypto.subtle`、`btoa`/`atob`、`canvas`(指纹常用)、`performance.now`、`Date`/`Math.random`(需要时固定成页面采样到的值)
- 验证手段:同一组输入,本地输出 == 页面真值,且换输入也对得上,才算稳定复现

时间/随机数依赖处理:如果签名依赖 `Date.now()` 或 `Math.random()`,复现时先固定成抓包时的值对齐验证,确认算法对了,再考虑动态化。

### 5. DeepDive(去混淆 / 逻辑提纯,按需)

前提:页面取证和本地复现已基本跑通。**不要在跑通前就把主要精力砸在大规模 AST 清洗上** —— 很多时候原样跑通就够了,清洗是为了长期复用。

- 如果当前任务只是出一次签名,这一阶段可降级跳过
- 如果要长期复用算法链路(产品化、批量),才值得做完整去混淆
- 去混淆手段见下文 AST 一节

## MCP 工具:js-reverse / jshookmcp

前端 JS 逆向常用一组 `js-reverse_*` MCP 工具(驱动浏览器 + CDP)。常用工具与职责:

| 能力 | 工具 | 用途 |
|------|------|------|
| 列脚本 | `js-reverse_list_scripts` | 建立脚本范围 |
| 取源码 | `js-reverse_get_script_source` | 读小片段(整份大文件优先存盘再看) |
| 搜源码 | `js-reverse_search_in_sources` | 搜路径/参数名/函数名,默认 `excludeMinified=true` |
| XHR 断点 | `js-reverse_break_on_xhr` | 按 URL 片段在请求发出处断 |
| 文本断点 | `js-reverse_set_breakpoint_on_text` | 按代码片段下断 |
| 执行脚本 | `js-reverse_evaluate_script` | 页面上下文里跑表达式,轻量观察 |
| 暂停信息 | `js-reverse_get_paused_info` | 断住后看调用栈/局部变量(默认 frameIndex=0) |
| 网络请求 | `js-reverse_list_network_requests` | 列最近请求(先看首页结果,不足再翻页) |
| initiator | `js-reverse_get_request_initiator` | 回溯请求触发的调用栈 |
| WebSocket | `js-reverse_get_websocket_messages` | 看 WS 收发帧 |
| 页面控制 | `js-reverse_new_page` / `navigate_page` / `select_page` / `select_frame` / `pause_or_resume` | 开页/导航/切页/切 frame/暂停恢复 |
| 截图 | `js-reverse_take_screenshot` | 留证 |

工具默认值习惯:

- `list_network_requests`:先看第一页,不足再翻页
- `search_in_sources`:默认排除压缩代码(`excludeMinified=true`),搜不到再放开
- `get_script_source`:只读小片段;整份源码先落盘(如 `save_script_source`)再分析
- `break_on_xhr`:只填能**稳定命中**的 URL 片段,太宽会断到无关请求
- `get_paused_info`:默认看栈顶帧(`frameIndex=0`),再按需往下翻帧

**jshookmcp 定位**:`js-reverse` 的增强执行面(更强的浏览器自动化 / CDP 调试 / JS Hook / 网络拦截 / SourceMap 重建 / AST 辅助),不是独立总控。任务提到 `jshookmcp`、JS hook、CDP、浏览器断点、网络拦截、SourceMap、AST 去混淆时,仍按 `Observe → Capture → Rebuild` 走,只是 Observe/Capture 阶段优先调它的 Hook 与浏览器能力。它是需要先在 MCP 客户端里注册并启用的 server(如 `@jshookmcp/jshook`),不是本地裸命令;没接入时这组工具不可调用。

**anything-analyzer**:另一个浏览器/网络侧取证 MCP(本地 HTTP 服务,默认端口 23816)。与 jshookmcp 互补 —— anything-analyzer 偏 **HTTP 抓包与分析、请求重放**,jshookmcp 偏 **JS 运行时、CDP、Hook、源码理解**。需要看完整请求/响应、重放改包验证签名时用前者;需要在运行时 hook 函数、追调用栈时用后者。同样是需要先启用的 MCP server。

无 MCP 时的等价路径:Chrome DevTools(Network/Sources/断点/Console)手动做 Observe/Capture;`curl` / Postman / mitmproxy 做抓包与请求重放;Node + jsdom/手写 shim 做本地复现。

## HTTP 抓包与请求重放

定位到签名算法后,重放是验证手段:

1. 抓一个**真实成功请求**的完整报文(URL、method、headers、body、以及目标签名参数的真值)
2. 本地复现算法,用同一组输入算出签名,先和真值逐字节比对
3. 比对一致后,改一个无关字段(如时间戳/随机串)重新算签名,带新签名重放请求,看服务端是否仍接受 —— 接受才证明算法真的对(而不是恰好对上了那一次缓存值)
4. 风控字段同理:换不同环境采样值,看哪些字段是真校验、哪些是占位

抓包工具:浏览器 Network 面板导出 / mitmproxy / Charles / anything-analyzer 的 HTTP 能力。重放:`curl`、Python `requests`、Node `fetch`,或 anything-analyzer 的重放面。

## AST 反混淆

混淆常见形态与对策(`@babel/parser` + `@babel/traverse` + `@babel/generator`,或 babel-plugin 形式批量改写):

- **字符串数组 / 解密函数**:整个文件字符串被搬到一个数组,运行时经一个解密函数取下标还原。还原法:在本地把那个解密函数原样跑起来,遍历 AST 把所有 `_0xabc(0x1, ...)` 调用替换成它的实际返回字符串(常量折叠)。
- **控制流平坦化**(while+switch 状态机):把线性逻辑拆成 `switch(state)` 跳转。还原靠按状态序列重排 case 回线性,工具如 `webcrack`、`restringer` 能处理一部分。
- **数值/字符串混淆、死代码、冗余分支**:常量折叠 + 死代码消除(DCE)pass。
- **标识符重命名**:`_0x1a2b` 这类无意义名,跑通后按行为重命名成可读名(这是 DeepDive 的提纯,不是跑通的前提)。

实用工具:`webcrack`(综合解混淆,处理 webpack 打包 + 常见混淆器)、`restringer`(REStringer,针对性还原)、AST Explorer(astexplorer.net,在线看 AST 结构调试改写规则)。**有 SourceMap 就先找 SourceMap**(`//# sourceMappingURL=` 或 `.map` 文件),能直接还原原始源码,远胜手工去混淆。

纪律:去混淆是为了可读和复用,不是跑通的前提。任务只要出一次签名就别陷进去。

## 取证与标注纪律

每个任务保留可追溯的证据链(对自己复盘、对交接都有用):

- 目标请求样例(URL/method/headers/body/签名参数真值)
- initiator 调用栈
- 可疑脚本 URL(必要时落盘的源码副本)
- 关键断点位置
- 关键函数入参/返回值样例
- first divergence 记录(本地与真值第一处分歧)
- 每次补环境补丁的说明(补了什么、为什么、复测结果)

可用如下结构记录进展:

```md
## Observe   目标请求 / initiator / 可疑脚本
## Capture   采样方式 / 命中位置 / 关键入参 / 关键返回
## Rebuild   入口函数 / 依赖脚本 / 环境缺口
## Patch     first divergence / 本次补丁 / 复测结果
## Output    是否拿到参数 / 是否可稳定复现 / 剩余风险
```

最终交付至少说清:目标请求和参数位置、哪个脚本哪个函数参与生成、证据来源(请求/调用栈/断点/运行时值)、当前是否能稳定复现、若未完成还差哪个环境缺口。

## 回退策略

某条路径卡住没进展时,按由重到轻回退,而不是在原地加码:

1. 从断点回退到请求观察(断点没收获 → 先把请求链路看全)
2. 从源码猜测回退到运行时证据(看代码猜不出 → 实际 hook 一次拿真值)
3. 从 Node 补环境回退到页面取证(本地补不动 → 回页面再观测一遍依赖)
4. 从深度去混淆回退到最小可复现链路(去混淆陷太深 → 退回原样跑通能出签名即可)
