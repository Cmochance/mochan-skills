"""CLI and MCP entrypoint for bilibili2mp3."""

from __future__ import annotations

import argparse
import json
import sys

from .convert import BITRATE_PRESETS, DEFAULT_BITRATE


def _build_parser() -> argparse.ArgumentParser:
    preset_help = ", ".join(f"{k}={v}" for k, v in BITRATE_PRESETS.items())
    parser = argparse.ArgumentParser(
        prog="bilibili2mp3",
        description=(
            "Extract Bilibili video audio to MP3 with embedded lyrics "
            "(ID3 USLT/SYLT + LRC + cover). Use --mcp to run as an MCP server."
        ),
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="Bilibili URL / BV id / b23.tv short link",
    )
    parser.add_argument(
        "--mcp",
        nargs="?",
        const="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="Run MCP server (default transport: stdio)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--probe",
        action="store_true",
        help="Only probe metadata and subtitle availability",
    )
    mode.add_argument(
        "--list-langs",
        action="store_true",
        help="List available CC subtitle languages (needs SESSDATA)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=None,
        help="Output directory (default: ~/Downloads/bilibili2mp3)",
    )
    parser.add_argument(
        "--page",
        type=int,
        default=1,
        help="1-based part number (default: 1)",
    )
    parser.add_argument(
        "--lang",
        default=None,
        help="Subtitle language code (e.g. zh-CN, ai-zh)",
    )
    parser.add_argument(
        "--bitrate",
        default=DEFAULT_BITRATE,
        help=f"MP3 bitrate or preset ({preset_help}); default: {DEFAULT_BITRATE}",
    )
    parser.add_argument(
        "--no-lrc",
        action="store_true",
        help="Do not write companion .lrc",
    )
    parser.add_argument(
        "--srt",
        action="store_true",
        help="Also write companion .srt",
    )
    parser.add_argument(
        "--no-cover",
        action="store_true",
        help="Do not embed cover art (APIC)",
    )
    parser.add_argument(
        "--allow-asr",
        action="store_true",
        help="If no CC subtitles, run local ASR (slow; needs mlx-whisper or BILIBILI_ASR_CMD)",
    )
    parser.add_argument(
        "--force-asr",
        action="store_true",
        help="Skip CC and always run ASR",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print result as JSON",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.mcp is not None:
        if args.url or args.probe or args.list_langs:
            parser.error("--mcp 不能与 url / --probe / --list-langs 同时使用")
        from .server import mcp

        mcp.run(transport=args.mcp)
        return

    if not args.url:
        parser.error("需要提供 url，或使用 --mcp 启动 MCP server")

    from . import pipeline

    if args.probe:
        result = pipeline.probe_video(args.url, page=args.page)
    elif args.list_langs:
        result = pipeline.list_subtitle_langs(args.url, page=args.page)
    else:
        result = pipeline.convert_to_mp3(
            args.url,
            page=args.page,
            lang=args.lang,
            output_dir=args.output_dir,
            bitrate=args.bitrate,
            write_lrc=not args.no_lrc,
            write_srt=args.srt,
            embed_cover=not args.no_cover,
            allow_asr=args.allow_asr,
            force_asr=args.force_asr,
        )

    if args.json or args.probe or args.list_langs:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result.get("ok"):
            sys.exit(1)
    else:
        if not result.get("ok"):
            print(f"error: {result.get('error')}", file=sys.stderr)
            for w in result.get("warnings") or []:
                print(f"warning: {w}", file=sys.stderr)
            sys.exit(1)
        print(result.get("mp3_path") or "")
        if result.get("lrc_path"):
            print(result["lrc_path"])
        if result.get("srt_path"):
            print(result["srt_path"])
        for w in result.get("warnings") or []:
            print(f"warning: {w}", file=sys.stderr)
        extra = (
            f"# subtitle_source={result.get('subtitle_source')}"
            f" lang={result.get('subtitle_lang')}"
            f" lyrics_embedded={result.get('lyrics_embedded')}"
            f" bitrate={result.get('bitrate')}"
            f" cover={result.get('embed_cover')}"
        )
        print(extra, file=sys.stderr)


if __name__ == "__main__":
    main()
