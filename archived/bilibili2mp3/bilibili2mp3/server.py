"""FastMCP server for bilibili2mp3."""

from __future__ import annotations

import functools
from typing import Any

import anyio
from mcp.server.fastmcp import FastMCP

from . import pipeline
from .convert import DEFAULT_BITRATE

mcp = FastMCP("bilibili2mp3", dependencies=["requests", "mutagen"])


async def _run_sync(fn, /, *args, **kwargs) -> Any:
    """Run blocking pipeline work off the event loop."""
    call = functools.partial(fn, *args, **kwargs)
    return await anyio.to_thread.run_sync(call)


@mcp.tool(
    annotations={
        "title": "Probe Bilibili video (metadata + subtitle availability)",
        "readOnlyHint": True,
        "openWorldHint": True,
    }
)
async def probe_video(url: str, page: int = 1) -> dict:
    """Resolve a Bilibili video without downloading audio.

    Returns title, owner, duration, part list, cover URL, available subtitle
    languages, bitrate presets, SESSDATA/ffmpeg readiness, and notices.

    Args:
        url: Bilibili video URL, BV id, or b23.tv short link
        page: 1-based part number for multi-part videos (default 1)
    """
    return await _run_sync(pipeline.probe_video, url, page)


@mcp.tool(
    annotations={
        "title": "List Bilibili CC subtitle languages",
        "readOnlyHint": True,
        "openWorldHint": True,
    }
)
async def list_subtitle_langs(url: str, page: int = 1) -> dict:
    """List available CC subtitle tracks (language codes) for a video part.

    Requires SESSDATA env for a non-empty list; anonymous calls return empty.

    Args:
        url: Bilibili video URL, BV id, or b23.tv short link
        page: 1-based part number (default 1)
    """
    return await _run_sync(pipeline.list_subtitle_langs, url, page)


@mcp.tool(
    annotations={
        "title": "Convert Bilibili video audio to MP3 with embedded lyrics",
        "readOnlyHint": False,
        "openWorldHint": True,
    }
)
async def convert_to_mp3(
    url: str,
    page: int = 1,
    lang: str | None = None,
    output_dir: str | None = None,
    bitrate: str = DEFAULT_BITRATE,
    write_lrc: bool = True,
    write_srt: bool = False,
    embed_cover: bool = True,
    allow_asr: bool = False,
    force_asr: bool = False,
) -> dict:
    """Download Bilibili audio, convert to MP3, embed lyrics as ID3 USLT/SYLT.

    Prefers official/AI CC subtitles. With allow_asr=True and no CC, runs local
    ASR on the audio (slow; default mlx-whisper via uvx, or BILIBILI_ASR_CMD).
    force_asr skips CC. Also embeds cover (APIC) when embed_cover is true,
    and writes a sibling .lrc when write_lrc and lines exist.

    Requires ffmpeg on PATH. CC listing needs SESSDATA.

    Args:
        url: Bilibili video URL, BV id, or b23.tv short link
        page: 1-based part number (default 1)
        lang: CC language code (e.g. zh-CN, ai-zh); also hints ASR language
        output_dir: output directory (default ~/Downloads/bilibili2mp3 or BILIBILI2MP3_OUT)
        bitrate: preset speech(=96k)/podcast(=128k)/standard(=192k)/high(=320k)
                 or raw like 192k
        write_lrc: write companion .lrc (default True)
        write_srt: write companion .srt (default False)
        embed_cover: embed video cover as APIC (default True)
        allow_asr: ASR fallback when no CC (default False; can take minutes)
        force_asr: skip CC and always ASR (default False)
    """
    return await _run_sync(
        pipeline.convert_to_mp3,
        url,
        page=page,
        lang=lang,
        output_dir=output_dir,
        bitrate=bitrate,
        write_lrc=write_lrc,
        write_srt=write_srt,
        embed_cover=embed_cover,
        allow_asr=allow_asr,
        force_asr=force_asr,
    )
