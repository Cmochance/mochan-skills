# bilibili2mp3

Extract Bilibili video **audio to MP3** and attach subtitles as **embedded lyrics** (ID3 USLT/SYLT), companion **LRC/SRT**, and optional **cover art** (APIC). Optional **local ASR** when no CC track exists.

## Requirements

- Python ≥ 3.10
- [ffmpeg](https://ffmpeg.org/) on `PATH`
- Optional: `SESSDATA` cookie for CC subtitle listing
- Optional ASR: `uv`/`uvx` + mlx-whisper (Apple Silicon), or set `BILIBILI_ASR_CMD`

## Install

```bash
cd bilibili2mp3
uv sync
# or: pip install -e ".[dev]"
```

## CLI

```bash
uv run bilibili2mp3 "https://www.bilibili.com/video/BV1x341177NN"
uv run bilibili2mp3 BV1x341177NN --probe --json
uv run bilibili2mp3 BV1x341177NN --list-langs --json
uv run bilibili2mp3 BV1x341177NN -o ~/Music/bili --bitrate podcast --srt
uv run bilibili2mp3 BV1x341177NN --allow-asr    # ASR if no CC (slow)
uv run bilibili2mp3 BV1x341177NN --force-asr    # always ASR
uv run bilibili2mp3 BV1x341177NN --no-cover
```

Default output: `~/Downloads/bilibili2mp3` (`BILIBILI2MP3_OUT` or `-o`).

### Bitrate presets

| Preset | Bitrate |
| --- | --- |
| `speech` | 96k |
| `podcast` | 128k |
| `standard` | 192k (default alias) |
| `high` | 320k |

Raw values like `192k` / `256k` are also accepted.

## MCP

```bash
uv run bilibili2mp3 --mcp          # stdio
```

Tools: `probe_video`, `list_subtitle_langs`, `convert_to_mp3`.

```json
{
  "mcpServers": {
    "bilibili2mp3": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/bilibili2mp3", "bilibili2mp3", "--mcp"],
      "env": { "SESSDATA": "optional_for_cc" }
    }
  }
}
```

## What “embedded subtitles” means on MP3

| Layer | Tag / file | Role |
| --- | --- | --- |
| Unsynced lyrics | ID3 **USLT** | Full text |
| Synced lyrics | ID3 **SYLT** | Timed lines (ms) |
| Cover | ID3 **APIC** | Video cover |
| Sidecar | **`.lrc`** / **`.srt`** | Player-friendly |

Subtitle source priority: **CC** → **ASR** (if `allow_asr` / `force_asr`) → none (plain MP3 + warning).

## Relation to bilibili-compact-mcp

| Package | Job |
| --- | --- |
| `bilibili-compact-mcp` | Read metadata / CC / ASR transcript / danmaku / comments |
| `bilibili2mp3` | Download audio → listen-ready MP3 with lyrics + cover |

WBI playurl and subtitle APIs are adapted from the compact MCP. ASR uses the same subprocess-external pattern (`BILIBILI_ASR_*` env vars).

## Tests

```bash
uv run pytest
```

## License

MIT (personal / educational use; respect Bilibili ToS and copyright).
