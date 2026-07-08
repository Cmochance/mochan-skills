# MCP Server for Bilibili Video Info

[![English](https://img.shields.io/badge/language-English-blue.svg)](./README.md) [![中文](https://img.shields.io/badge/language-中文-red.svg)](./README.zh.md)

Bilibili MCP Server，可以根据视频 url 获取视频的元信息、字幕、转录文本（ASR 兜底）、弹幕和评论信息。

## 使用方法

MCP Server 支持三种通信方式：
1. **stdio**
```json
{
    "mcpServers": {
        "bilibili-video-info-mcp": {
            "command": "uvx",
            "args": [
                "bilibili-video-info-mcp"
            ],
            "env": {
                "SESSDATA": "your valid sessdata（可选，仅字幕列表需要，见下方常见问题）"
            }
        }
    }
}
```

2. **sse**（服务器发送事件）
在 sse 模式下运行 bilibili-video-info-mcp
``` bash
cp .env.example .env
uvx run --env .env bilibili-video-info-mcp sse
```
然后配置你的mcp客户端
```json
{
    "mcpServers": {
        "bilibili-video-info-mcp": {
            "url": "http://{your.ip.address}:$PORT$/sse"
        }
    }
}
```

3. **streamable-http**（HTTP流式传输）
在 streamable-http 模式下运行 bilibili-video-info-mcp
``` bash
cp .env.example .env
uvx run --env .env bilibili-video-info-mcp streamable-http
```
然后配置你的mcp客户端
```json
{
    "mcpServers": {
        "bilibili-video-info-mcp": {
            "url": "http://{your.ip.address}:$PORT$/mcp"
            }
        }
    }
}
```

## MCP 工具列表

### 1. 获取视频元信息

```json
{
  "name": "get_video_info",
  "arguments": {
    "url": "https://www.bilibili.com/video/BV1x341177NN"
  }
}
```

返回 bvid/aid、title、desc、UP主（owner）、时长 duration（秒）、pubdate、播放数据 stat（view/danmaku/reply/favorite/coin/share/like）以及分P列表 pages。多P视频的 `pages[].page` 就是其他三个工具 `page` 参数要传的值。

### 2. 获取视频字幕列表

```json
{
  "name": "get_subtitles",
  "arguments": {
    "url": "https://www.bilibili.com/video/BV1x341177NN",
    "page": 1,
    "lang": "zh-CN"
  }
}
```

`page`（默认1，多P视频用第1步拿到的分P号）和 `lang`（字幕语言码，如 zh-CN / ai-zh / en，默认优先中文）均为可选。返回 `{title, page, lan, available_languages, lines: [{t: 秒, text}]}`，`lines` 保留每条字幕的起始时间戳 `t`（秒）。若该视频没有字幕，返回 `{title, notice, description}`，用简介兜底。

### 3. 获取视频转录文本

```json
{
  "name": "get_transcript",
  "arguments": {
    "url": "https://www.bilibili.com/video/BV1x341177NN",
    "page": 1,
    "lang": "zh"
  }
}
```

`page`（默认1）、`lang`（走 CC 字幕时指定字幕轨；走 ASR 时指定识别语言，默认中文优先/zh）、`force_asr`（布尔，默认 `False`，为 `True` 时跳过 CC 字幕直接走音频转写）均为可选。返回 `{title, page, source, lines: [{t: 秒, text}]}`，其中 `source` 为 `'cc'`（官方 CC 字幕，内容同 `get_subtitles`）或 `'asr'`（机器转写）。这个工具解决的是"视频没有 CC 字幕就拿不到正文"的问题：优先取 CC 字幕，若该视频没有字幕（或指定了 `force_asr`），则自动下载音频并在本地做语音识别转写兜底。

> **关于 ASR 路径的几点说明：**
> - **较慢**：需要下载音频轨并跑转写，首次运行还会下载 ASR 模型，整体耗时可能到分钟级。调用方（MCP client）应容忍这个长耗时，或者先调用 `get_subtitles` 确认该视频是否已有 CC 字幕。
> - **准确度较低**：`source='asr'` 返回的文本是语音识别结果，准确度略低于官方字幕，专有名词/人名可能识别有误。
> - **依赖外挂，不进本包依赖**：ASR 不是本包的依赖项，而是以子进程形式外挂调用，以保持本包轻量、跨平台。默认经 `uvx` 拉起 **mlx-whisper**（仅支持 Apple Silicon），首次调用会下载模型。
> - **相关环境变量**（用于在非 Apple Silicon 平台等场景下切换后端）：
>   - `BILIBILI_ASR_CMD` — 自定义转写命令模板，支持占位符 `{audio}` `{output_dir}` `{model}` `{lang}`；该命令须在 `{output_dir}` 下产出一份含 `segments` 的 whisper 格式 json。
>   - `BILIBILI_ASR_MODEL` — 模型名，默认 `mlx-community/whisper-large-v3-mlx`。
>   - `BILIBILI_ASR_LANG` — 识别语言，默认 `zh`。

### 4. 获取视频弹幕

```json
{
  "name": "get_danmaku",
  "arguments": {
    "url": "https://www.bilibili.com/video/BV1x341177NN",
    "page": 1,
    "limit": 1000
  }
}
```

`page`（默认1）和 `limit`（默认1000，弹幕池超过 limit 时按时间轴均匀采样）均为可选。返回 `{title, page, source, total, returned, sampled, items: [{t: 视频内秒, text, sent: 发送时的unix时间, user: 发送者hash}]}`。`source` 为 `seg+xml`（合并 protobuf 弹幕分段接口与传统 XML 接口并去重，覆盖比旧版单 XML 接口更全），每条弹幕保留时间戳与发送者信息。

### 5. 获取视频评论

```json
{
  "name": "get_comments",
  "arguments": {
    "url": "https://www.bilibili.com/video/BV1x341177NN",
    "limit": 20,
    "mode": 3
  }
}
```

`limit`（默认20）和 `mode`（3=按热度，默认；2=按时间）均为可选。返回热评列表 `[{user, content, likes}]`。

> 说明：B站已将旧版评论接口降级为仅返回3条。本工具改用 WBI 签名接口获取完整首页（约20条热评），但**不支持深翻页**（page2 及以后会被B站反爬拦截），因此只能拿到按热度/时间排序的首页评论。

## 常见问题

### 1. 必须配置 SESSDATA 吗？

不是必须的。`get_video_info`、`get_danmaku`、`get_comments` 均可匿名使用，无需 SESSDATA。只有 `get_subtitles`（获取字幕列表）需要 SESSDATA——B站字幕接口要求登录态，匿名请求恒返回空列表。未配置 SESSDATA 时调用 `get_subtitles` 会在返回结果里附带提示，告知你配置 SESSDATA 后重试。`get_transcript` 的 CC 字幕路径调用的是同一个字幕接口，因此有同样的限制；但它的 ASR 兜底路径不需要 SESSDATA——只需公开可访问的音频流即可转写。

### 2. 找不到 SESSDATA 怎么办？

1. 登录 Bilibili 网站
2. 打开浏览器开发者工具 (F12)
3. 进入 Application/Storage -> Cookies
4. 找到 SESSDATA 对应的值

配置好后按上方 stdio 配置示例，将其填入 `env.SESSDATA` 或环境变量：

```bash
export SESSDATA="你的SESSDATA值"
```

### 3. 视频链接支持哪些格式？

支持标准的 Bilibili 视频链接，例如：
- https://www.bilibili.com/video/BV1x341177NN
- https://b23.tv/xxxxx (短链接)
- 包含 BV 号的任何链接

## 许可证

MIT
