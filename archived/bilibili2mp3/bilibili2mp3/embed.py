"""Embed ID3 metadata, cover art, and lyrics (USLT + SYLT) into MP3."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from mutagen.id3 import (
    APIC,
    COMM,
    ID3,
    SYLT,
    TALB,
    TDRC,
    TIT2,
    TPE1,
    USLT,
    Encoding,
    ID3NoHeaderError,
    PictureType,
)
from mutagen import MutagenError

from .subtitle_fmt import to_plain, to_sylt_tuples

logger = logging.getLogger(__name__)


def _guess_image_mime(data: bytes, hint: str | None = None) -> str:
    if hint and hint.startswith("image/"):
        return hint
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    # Bilibili covers are almost always JPEG
    return "image/jpeg"


def embed_metadata(
    mp3_path: str | Path,
    *,
    title: str,
    artist: str | None = None,
    album: str | None = None,
    year: str | int | None = None,
    comment: str | None = None,
    lines: Iterable[dict] | None = None,
    lyrics_lang: str = "chi",
    cover_data: bytes | None = None,
    cover_mime: str | None = None,
) -> dict | None:
    """Write ID3 tags + optional USLT/SYLT lyrics + optional APIC cover.

    Returns None on success, error dict on failure.
    """
    path = Path(mp3_path)
    if not path.is_file():
        return {"error": f"MP3 不存在: {path}"}

    try:
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()

        tags.delall("TIT2")
        tags.add(TIT2(encoding=Encoding.UTF8, text=title or "untitled"))

        if artist:
            tags.delall("TPE1")
            tags.add(TPE1(encoding=Encoding.UTF8, text=artist))

        if album:
            tags.delall("TALB")
            tags.add(TALB(encoding=Encoding.UTF8, text=album))

        if year is not None and str(year):
            tags.delall("TDRC")
            tags.add(TDRC(encoding=Encoding.UTF8, text=str(year)))

        if comment:
            tags.delall("COMM")
            tags.add(
                COMM(
                    encoding=Encoding.UTF8,
                    lang="eng",
                    desc="bvid",
                    text=comment,
                )
            )

        if cover_data:
            mime = _guess_image_mime(cover_data, cover_mime)
            tags.delall("APIC")
            tags.add(
                APIC(
                    encoding=Encoding.UTF8,
                    mime=mime,
                    type=PictureType.COVER_FRONT,
                    desc="Cover",
                    data=cover_data,
                )
            )

        line_list = list(lines or [])
        if line_list:
            plain = to_plain(line_list)
            sylt = to_sylt_tuples(line_list)
            if plain:
                tags.delall("USLT")
                tags.add(
                    USLT(
                        encoding=Encoding.UTF8,
                        lang=lyrics_lang,
                        desc="",
                        text=plain,
                    )
                )
            if sylt:
                tags.delall("SYLT")
                tags.add(
                    SYLT(
                        encoding=Encoding.UTF8,
                        lang=lyrics_lang,
                        format=2,  # milliseconds
                        type=1,  # lyrics
                        desc="",
                        text=sylt,
                    )
                )

        tags.save(path, v2_version=3)
        return None
    except (MutagenError, OSError, ValueError, TypeError) as e:
        logger.exception("embed failed")
        return {"error": f"写入 ID3 失败: {e}"}
