# MCP Server for Bilibili Video Info

[![smithery badge](https://smithery.ai/badge/@lesir831/bilibili-video-info-mcp)](https://smithery.ai/server/@lesir831/bilibili-video-info-mcp)
[![English](https://img.shields.io/badge/language-English-blue.svg)](./README.md) [![中文](https://img.shields.io/badge/language-中文-red.svg)](./README.zh.md)

A Bilibili MCP Server that can retrieve metadata, subtitles, transcripts (with ASR fallback), danmaku (bullet comments), and comments information from videos using the video URL.

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

### 3. Get Video Transcript

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

`page` (default 1), `lang` (for CC: the subtitle track to fetch; for ASR: the recognition language, defaults to preferring Chinese/zh), and `force_asr` (boolean, default `False`, skips CC subtitles and goes straight to audio transcription) are all optional. Returns `{title, page, source, lines: [{t: seconds, text}]}`, where `source` is `'cc'` (official CC subtitle, same content as `get_subtitles`) or `'asr'` (machine transcription). This tool exists to solve the "no CC subtitles → no transcript available" problem: it tries CC subtitles first, and if the video has none (or `force_asr` is set), it downloads the audio and transcribes it locally.

> **Note on the ASR path:**
> - **Slow**: it downloads the audio track and runs transcription; the first run also downloads the ASR model, so the whole call can take several minutes. MCP clients calling this tool should tolerate a long-running response, or call `get_subtitles` first to check whether CC subtitles already exist.
> - **Lower accuracy**: `source='asr'` text is a speech-recognition result, less accurate than official subtitles — proper nouns and names may be misrecognized.
> - **External dependency, not bundled**: ASR is not part of this package's dependencies. It runs as an external subprocess so this package stays lightweight and cross-platform. By default it shells out to **mlx-whisper via `uvx`** (Apple Silicon only), downloading the model on first use.
> - **Environment variables** (to override the backend, e.g. on non-Apple-Silicon platforms):
>   - `BILIBILI_ASR_CMD` — custom transcription command template. Supports placeholders `{audio}`, `{output_dir}`, `{model}`, `{lang}`. The command must write a whisper-format JSON (containing `segments`) into `{output_dir}`.
>   - `BILIBILI_ASR_MODEL` — model name, default `mlx-community/whisper-large-v3-mlx`.
>   - `BILIBILI_ASR_LANG` — recognition language, default `zh`.

### 4. Get Video Danmaku (Bullet Comments)

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

### 5. Get Video Comments

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

No, it's optional. `get_video_info`, `get_danmaku`, and `get_comments` all work anonymously without SESSDATA. Only `get_subtitles` (listing subtitles) requires SESSDATA — Bilibili's subtitle endpoint needs a logged-in session; anonymous requests always return an empty subtitle list. If SESSDATA is not configured, calling `get_subtitles` returns a notice in the result telling you to configure SESSDATA and retry. `get_transcript` shares this limitation for its CC-subtitle path (it calls the same subtitle endpoint), but its ASR fallback path does not require SESSDATA — it only needs the video's audio stream, which is public.

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
