"""bilibili2mp3: Bilibili audio → MP3 with embedded lyrics/subtitles."""

from .pipeline import convert_to_mp3, list_subtitle_langs, probe_video

__all__ = ["convert_to_mp3", "list_subtitle_langs", "probe_video", "main"]
__version__ = "0.2.0"


def main() -> None:
    from .__main__ import main as _main

    _main()
