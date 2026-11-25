---
name: bilibili2mp3
description: >-
  将 B 站视频音频提取为 MP3，并以内嵌歌词（ID3 USLT/SYLT）+ 旁路 LRC 的形式附带字幕，
  可选封面 APIC 与本地 ASR 兜底。用户提到 bilibili/B站 转 mp3、提取音频、内嵌字幕/歌词、
  bilibili2mp3 时使用。
---

# bilibili2mp3

B 站视频 → MP3（内嵌 CC/ASR 歌词）+ 可选 `.lrc` / `.srt` + 封面。

## When to use

- 用户要「把 B 站视频下成 mp3 / 提取音频」
- 需要「带字幕/歌词」的音频文件（听播客、听课）
- 明确提到 `bilibili2mp3`

不要用它做：视频下载、弹幕、评论、长文总结（总结走 `bilibili-compact-mcp`）。

## Requirements

| 依赖 | 说明 |
| --- | --- |
| `ffmpeg` | 硬依赖，转码 m4a→mp3 |
| `SESSDATA` | **可选**但推荐：列/下 CC 字幕需要登录 cookie |
| ASR（可选） | 默认 `uvx` + mlx-whisper（Apple Silicon）；其他平台设 `BILIBILI_ASR_CMD` |
| Python 包 | 本目录 `uv sync` |

获取 SESSDATA：浏览器登录 bilibili.com → DevTools → Application → Cookies → `SESSDATA`。

## CLI

```bash
cd bilibili2mp3
uv run bilibili2mp3 "https://www.bilibili.com/video/BVxxxx" -o ~/Downloads/bilibili2mp3
uv run bilibili2mp3 BVxxxx --probe --json
uv run bilibili2mp3 BVxxxx --list-langs --json
uv run bilibili2mp3 BVxxxx --page 2 --lang zh-CN --bitrate podcast --srt
uv run bilibili2mp3 BVxxxx --allow-asr          # 无 CC 时 ASR 兜底（慢）
uv run bilibili2mp3 BVxxxx --force-asr          # 跳过 CC 强制 ASR
uv run bilibili2mp3 BVxxxx --no-cover
```

默认输出：`~/Downloads/bilibili2mp3/`（环境变量 `BILIBILI2MP3_OUT` 可覆盖）。

### 码率预设

| 预设 | 码率 | 场景 |
| --- | --- | --- |
| `speech` | 96k | 口播省空间 |
| `podcast` | 128k | 播客 |
| `standard` | 192k | 默认 |
| `high` | 320k | 高码率 |

也可直接传 `192k` / `256k` 等。

## MCP

```json
{
  "mcpServers": {
    "bilibili2mp3": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mochan-skills/bilibili2mp3", "bilibili2mp3", "--mcp"],
      "env": {
        "SESSDATA": "your_sessdata_optional"
      }
    }
  }
}
```

### Tools

| Tool | 作用 |
| --- | --- |
| `probe_video` | 元信息 + 分 P + 封面 URL + 字幕语言 + 码率预设表 |
| `list_subtitle_langs` | 仅列 CC 字幕语言（需 SESSDATA） |
| `convert_to_mp3` | 下载音轨 → MP3 + USLT/SYLT + LRC + APIC；可选 ASR |

### convert_to_mp3 关键参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `allow_asr` | false | 无 CC 时本地 ASR（可能数分钟） |
| `force_asr` | false | 跳过 CC 强制 ASR |
| `embed_cover` | true | 写入封面 APIC |
| `bitrate` | `192k` | 预设名或原始码率 |
| `write_lrc` / `write_srt` | true / false | 旁路字幕文件 |

## Workflow for agents

1. `probe_video` 确认标题/分 P/是否有字幕。
2. 需要指定字幕轨时 `list_subtitle_langs`（先确保 `SESSDATA`）。
3. `convert_to_mp3`；用户明确要无 CC 也能出歌词时再 `allow_asr=true`。
4. 把 `mp3_path` / `lrc_path` 交给用户。
5. ASR 路径：提示耗时长、准确度低于官方 CC、专有名词可能错。

## Output contract

```json
{
  "ok": true,
  "mp3_path": "/abs/...mp3",
  "lrc_path": "/abs/...lrc",
  "subtitle_source": "cc|asr|none",
  "lyrics_embedded": true,
  "embed_cover": true,
  "bitrate": "192k",
  "warnings": []
}
```

- `subtitle_source`：歌词文本来源（cc/asr/none）
- `lyrics_embedded`：是否成功写入 ID3 USLT/SYLT（写失败时仍可为 false）
- `embed_cover`：是否成功写入 APIC

MP3「内嵌字幕」= ID3 **USLT** + **SYLT**；另写 **LRC**；封面为 **APIC**。

## ASR 环境变量

| 变量 | 说明 |
| --- | --- |
| `BILIBILI_ASR_CMD` | 自定义命令模板（`{audio}` `{output_dir}` `{model}` `{lang}`） |
| `BILIBILI_ASR_MODEL` | 默认 `mlx-community/whisper-large-v3-mlx` |
| `BILIBILI_ASR_LANG` | 默认 `zh` |

## Troubleshooting

| 现象 | 处理 |
| --- | --- |
| 未找到 ffmpeg | `brew install ffmpeg` |
| 字幕为空 | 配置 `SESSDATA`；或 `--allow-asr` |
| ASR 失败 | 装 `uv`/`uvx`，或设 `BILIBILI_ASR_CMD` |
| playurl 失败 | 检查网络/地区/大会员 cookie |
| 封面未嵌入 | 看 warnings；可用 `--no-cover` 跳过 |
