# bilibili2mp3

将 B 站视频**音频提取为 MP3**，字幕写成**内嵌歌词**（ID3 USLT/SYLT）+ 旁路 **LRC/SRT**，并可选**封面 APIC**。无 CC 时可开**本地 ASR** 兜底。

## 依赖

- Python ≥ 3.10
- PATH 中的 [ffmpeg](https://ffmpeg.org/)
- 可选：`SESSDATA`（列/下 CC 字幕）
- 可选 ASR：`uv`/`uvx` + mlx-whisper（Apple Silicon），或 `BILIBILI_ASR_CMD`

## 安装

```bash
cd bilibili2mp3
uv sync
```

## CLI

```bash
uv run bilibili2mp3 "https://www.bilibili.com/video/BV1x341177NN"
uv run bilibili2mp3 BV1x341177NN --probe --json
uv run bilibili2mp3 BV1x341177NN --list-langs --json
uv run bilibili2mp3 BV1x341177NN -o ~/Music/bili --bitrate podcast --srt
uv run bilibili2mp3 BV1x341177NN --allow-asr
uv run bilibili2mp3 BV1x341177NN --force-asr
uv run bilibili2mp3 BV1x341177NN --no-cover
```

默认输出：`~/Downloads/bilibili2mp3`。

### 码率预设

| 预设 | 码率 |
| --- | --- |
| `speech` | 96k |
| `podcast` | 128k |
| `standard` | 192k |
| `high` | 320k |

## MCP

```bash
uv run bilibili2mp3 --mcp
```

工具：`probe_video`、`list_subtitle_langs`、`convert_to_mp3`。

## 「内嵌字幕」说明

- **USLT** / **SYLT**：全文与同步歌词  
- **APIC**：封面  
- **`.lrc` / `.srt`**：旁路文件  

字幕源优先级：**CC** → **ASR**（`allow_asr`/`force_asr`）→ none。

## 与 bilibili-compact-mcp

compact 负责读信息/转写；本工具负责**落盘可听的 MP3**（歌词+封面）。ASR 环境变量与 compact 对齐（`BILIBILI_ASR_*`）。

## 测试

```bash
uv run pytest
```

## 许可

MIT。仅供个人学习；请遵守平台规则与版权。
