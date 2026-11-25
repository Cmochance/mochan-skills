"""Unit tests for ID3 embed (needs ffmpeg for a tiny silent mp3)."""

import shutil
import subprocess
from pathlib import Path

import pytest
from mutagen.id3 import ID3

from bilibili2mp3.embed import _guess_image_mime, embed_metadata

ffmpeg = shutil.which("ffmpeg")


def _make_silent_mp3(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            "0.5",
            "-q:a",
            "9",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def test_guess_image_mime():
    assert _guess_image_mime(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert _guess_image_mime(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert _guess_image_mime(b"xxxx", hint="image/webp") == "image/webp"


@pytest.mark.skipif(not ffmpeg, reason="ffmpeg not installed")
def test_embed_uslt_and_sylt(tmp_path: Path):
    mp3 = tmp_path / "t.mp3"
    _make_silent_mp3(mp3)
    assert mp3.is_file()

    lines = [
        {"t": 0.0, "to": 1.0, "text": "hello"},
        {"t": 1.0, "to": 2.0, "text": "world"},
    ]
    err = embed_metadata(
        mp3,
        title="Test Title",
        artist="UP",
        album="Bilibili BVtest",
        year="2024",
        comment="BVtest P1",
        lines=lines,
    )
    assert err is None

    tags = ID3(mp3)
    assert tags.get("TIT2").text[0] == "Test Title"
    assert tags.get("TPE1").text[0] == "UP"
    uslt = tags.getall("USLT")
    assert uslt
    assert "hello" in str(uslt[0].text)
    sylt = tags.getall("SYLT")
    assert sylt
    texts = [t[0] for t in sylt[0].text]
    assert "hello" in texts
    assert "world" in texts


@pytest.mark.skipif(not ffmpeg, reason="ffmpeg not installed")
def test_embed_cover_apic(tmp_path: Path):
    mp3 = tmp_path / "c.mp3"
    _make_silent_mp3(mp3)
    # minimal JPEG SOI + EOI (invalid image but enough for APIC bytes)
    jpeg = b"\xff\xd8\xff\xd9"
    err = embed_metadata(
        mp3,
        title="Covered",
        cover_data=jpeg,
        cover_mime="image/jpeg",
    )
    assert err is None
    tags = ID3(mp3)
    apics = tags.getall("APIC")
    assert apics
    assert apics[0].mime == "image/jpeg"
    assert apics[0].data == jpeg
