# MCP Server for Bilibili Video Info

[![English](https://img.shields.io/badge/language-English-blue.svg)](./README.md) [![中文](https://img.shields.io/badge/language-中文-red.svg)](./README.zh.md)

Bilibili MCP Server，可以根据视频 url 获取视频的元信息、字幕、弹幕和评论信息。

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

### 3. 获取视频弹幕

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

### 4. 获取视频评论

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

不是必须的。`get_video_info`、`get_danmaku`、`get_comments` 均可匿名使用，无需 SESSDATA。只有 `get_subtitles`（获取字幕列表）需要 SESSDATA——B站字幕接口要求登录态，匿名请求恒返回空列表。未配置 SESSDATA 时调用 `get_subtitles` 会在返回结果里附带提示，告知你配置 SESSDATA 后重试。

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
