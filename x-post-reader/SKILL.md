---
name: x-post-reader
description: 获取 X (Twitter) 帖子全文、>280字长推(note_tweet)、原生 X Article 长文及多楼串推(Thread)。当用户发来 x.com / twitter.com 链接或要求读取推文/长文/串推内容时触发，自动按三层架构路由提取干净 Markdown。
---

# x-post-reader — 三层路由获取 X 帖子全文

> **实例配置**（代理 / 缓存 / Tier 3 小号 `auth_token` & `ct0`）读本目录 `config.local.json`（模板见 `config.example.json`，已 gitignore）。

## 默认调用方式

直接以单命令调用 `x-read`（需联网时设 `BypassSandbox: true`，**不要拼环境变量前缀、管道或 `&&`**，以保留 CLI 前缀自动审批）：

```bash
x-read 'https://x.com/user/status/1234567890'
```

常用参数：
- **强制拉整串 Thread**（首楼未命中自动串推特征、或只想确保拿全上下文时）：
  `x-read 'https://x.com/user/status/1234567890' --thread`
- **强制按 X Article 长文提取**（标准 `/status/<id>` 帖内嵌文章时显式指定）：
  `x-read 'https://x.com/user/status/1234567890' --article`
- **附带前 N 条非作者精选回复**（需 Tier 3 就绪）：
  `x-read 'https://x.com/user/status/1234567890' --thread --include-replies 5`
- **诊断各层可用性与小号实网鉴权状态**（会自动调 `twitter status --json` 校验小号 Token）：
  `x-read --doctor`

## 三层自动路由机制

1. **Tier 1 (`FxEmbed` 零鉴权 API)** — 探针 + 情况 1（普通帖 / >280 字 `note_tweet` / 引用帖）、纯文本 `X Article` 快速直出，以及沿 `replying_to_status` 逆向回溯上游父帖。零账号风险、~300ms 响应。
2. **Tier 2 (`Jina Reader` `X-Timeout: 30`)** — 情况 2（含复杂排版或内嵌 `atomic` 媒体块的原生 `X Article`，或 `/article/` 链接）主通道，以及 Tier 1 失败后的免登录文本兜底；自动过滤登录墙空壳与死链页面，被拦截时自动升 Tier 3。
3. **Tier 3 (`twitter-cli` + `curl_cffi` TLS 指纹伪装)** — 情况 3（作者多楼自回复 `Self-Thread` 下行展开）及前两层撞墙/404 锁推时的终极兜底；自动过滤路人评论只保留同作者连通自回复链，并内置跨进程文件锁、请求间隔抖动与 401/403/429/326 熔断冷却。

## 硬性规则

1. **必须检查 YAML 头 `completeness` 字段**：
   - 仅当 `completeness: "full"` 时，才可按完整正文总结或引用。
   - 若为 `partial_root_only` 或 `partial_upstream_only`（例如检测到串推但 Tier 3 未配置，或复杂 X Article 降级后省略了 `atomic` 富媒体块），**必须在回复中明确告知用户仅获取了部分内容及缺失原因**，严禁脑补未获取到的内容。
2. **超大正文落盘切片读取**：当帖子/长文超过 `inline_max_chars`（默认 16000 字符）时，`x-read` 会以私有权限（`0700`/`0600`）自动将全文写入 `~/.cache/x-post-reader/out/<tweet_id>.md` 并打印 YAML 头 + 800 字导读 + 文件路径，此时用 `read_file` 分段读取该路径即可。
3. **禁止绕过小号隔离**：`config_file` 与 `env` 模式下会通过桩模块 `browser_cookie3.py` 彻底屏蔽本地浏览器 Cookie 与 macOS 钥匙串扫描，即使小号 Token 过期也绝不回退读取主力浏览器大号；不要擅自改为 `browser` 模式去读取用户主力浏览器钥匙串。

## 30 秒配置 Tier 3 小号 Cookie

1. 打开浏览器**无痕/隐私窗口**（Incognito），登录你的 X 备用小号。
2. 打开开发者工具（`Cmd+Option+I`）→ `Application` → `Cookies` → `https://x.com`，复制 `auth_token` 与 `ct0` 的值填入 `config.local.json` 的 `tier3.auth_token` 和 `tier3.ct0`。
3. **直接关闭无痕窗口（切勿点击 Exit/Log out，否则服务端会立即吊销该 Token）**，再运行 `x-read --doctor` 验证 `[OK] Tier 3 (twitter-cli): authenticated`。
