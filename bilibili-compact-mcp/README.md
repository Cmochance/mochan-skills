# MCP Server for Bilibili Video Info

[![smithery badge](https://smithery.ai/badge/@lesir831/bilibili-video-info-mcp)](https://smithery.ai/server/@lesir831/bilibili-video-info-mcp)
[![English](https://img.shields.io/badge/language-English-blue.svg)](./README.md) [![中文](https://img.shields.io/badge/language-中文-red.svg)](./README.zh.md)

A Bilibili MCP Server that can retrieve metadata, subtitles, danmaku (bullet comments), and comments information from videos using the video URL.

## Usage

This MCP server supports three transport methods:
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
                "SESSDATA": "your valid sessdata (optional, only required for subtitles — see FAQ below)"
            }
        }
    }
}
```

2. **sse** (Server-Sent Events)
run bilibili-video-info-mcp in sse mode
``` bash
cp .env.example .env
uvx run --env .env bilibili-video-info-mcp sse
```
then config your mcp client
```json
{
    "mcpServers": {
        "bilibili-video-info-mcp": {
            "url": "http://{your.ip.address}:$PORT$/sse"
        }
    }
}
```

3. **streamable-http** (HTTP Streaming)
run bilibili-video-info-mcp in streamable-http mode
``` bash
cp .env.example .env
uvx run --env .env bilibili-video-info-mcp streamable-http
```
then config your mcp client
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

## MCP Tools List

### 1. Get Video Metadata

```json
{
  "name": "get_video_info",
  "arguments": {
    "url": "https://www.bilibili.com/video/BV1x341177NN"
  }
}
```

Returns bvid/aid, title, desc, uploader (owner), duration (seconds), pubdate, stat (view/danmaku/reply/favorite/coin/share/like), and the part list `pages`. For multi-part videos, `pages[].page` is the value to pass as the `page` argument to the other three tools.

### 2. Get Video Subtitles

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

`page` (1-based part number, default 1) and `lang` (subtitle language code, e.g. zh-CN / ai-zh / en; defaults to preferring a Chinese variant) are both optional. Returns `{title, page, lan, available_languages, lines: [{t: seconds, text}]}` — `lines` keeps each subtitle line's start timestamp `t` (in seconds). If the video has no subtitles, returns `{title, notice, description}`, using the video description as fallback material.

### 3. Get Video Danmaku (Bullet Comments)

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

`page` (default 1) and `limit` (default 1000; when the pool exceeds `limit`, items are uniformly sampled across the timeline) are both optional. Returns `{title, page, source, total, returned, sampled, items: [{t: video-time seconds, text, sent: unix send time, user: sender hash}]}`. `source` is `seg+xml` (merges the protobuf danmaku-segment API with the legacy XML API and deduplicates, covering more than the old single-XML approach), and each item retains its timestamp and sender metadata.

### 4. Get Video Comments

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

`limit` (default 20) and `mode` (3 = by heat, default; 2 = by time) are both optional. Returns a list of top comments: `[{user, content, likes}]`.

> Note: Bilibili has downgraded its legacy comment API to return only 3 comments. This tool now uses the WBI-signed endpoint to retrieve the full first page (~20 comments), but **deep pagination is not supported** — page 2 and beyond are blocked by Bilibili's anti-crawling measures, so only the first page (sorted by heat or time) is available.

## FAQ

### 1. Is SESSDATA required?

No, it's optional. `get_video_info`, `get_danmaku`, and `get_comments` all work anonymously without SESSDATA. Only `get_subtitles` (listing subtitles) requires SESSDATA — Bilibili's subtitle endpoint needs a logged-in session; anonymous requests always return an empty subtitle list. If SESSDATA is not configured, calling `get_subtitles` returns a notice in the result telling you to configure SESSDATA and retry.

### 2. How to find SESSDATA?

1. Log in to the Bilibili website
2. Open browser developer tools (F12)
3. Go to Application/Storage -> Cookies
4. Find the value corresponding to SESSDATA

Once you have it, set it via the `env.SESSDATA` field in the stdio config above, or as an environment variable:

```bash
export SESSDATA="your SESSDATA value"
```

### 3. What video link formats are supported?

Standard Bilibili video links are supported, such as:
- https://www.bilibili.com/video/BV1x341177NN
- https://b23.tv/xxxxx (short links)
- Any link containing a BV number
