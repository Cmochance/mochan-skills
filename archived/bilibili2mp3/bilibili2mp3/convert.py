"""Audio conversion via ffmpeg (DASH AAC/m4a → mp3)."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Named presets → ffmpeg -b:a values
BITRATE_PRESETS: dict[str, str] = {
    "speech": "96k",  # 口播 / 省空间
    "podcast": "128k",  # 播客平衡
    "standard": "192k",  # 默认
    "high": "320k",  # 高码率
}

DEFAULT_BITRATE = "192k"
_RAW_BITRATE_RE = re.compile(r"^\d+k?$", re.IGNORECASE)


def resolve_bitrate(value: str | None) -> str:
    """Map preset name or pass through raw bitrate (e.g. 192k).

    Raises ValueError for invalid non-preset values.
    """
    if not value:
        return DEFAULT_BITRATE
    key = value.strip().lower()
    if key in BITRATE_PRESETS:
        return BITRATE_PRESETS[key]
    raw = value.strip()
    if not _RAW_BITRATE_RE.match(raw):
        raise ValueError(
            f"无效 bitrate={value!r}；可用预设 {list(BITRATE_PRESETS)} "
            "或如 192k / 256"
        )
    # normalize bare digits → Nk for ffmpeg -b:a
    if raw.isdigit():
        return f"{raw}k"
    return raw.lower()


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def preflight() -> dict | None:
    """Return error dict if required tools are missing, else None."""
    if not ffmpeg_available():
        return {
            "error": (
                "未找到 ffmpeg。请安装后确保在 PATH 中: "
                "macOS `brew install ffmpeg` / 其他平台见 https://ffmpeg.org/download.html"
            )
        }
    return None


def to_mp3(
    src: str | Path,
    dest: str | Path,
    bitrate: str = DEFAULT_BITRATE,
) -> dict | None:
    """Convert audio file to mp3 with libmp3lame.

    bitrate: preset name (speech/podcast/standard/high) or raw (e.g. 192k).
    Returns None on success, error dict on failure.
    """
    src_path = Path(src)
    dest_path = Path(dest)
    if not src_path.is_file():
        return {"error": f"源音频不存在: {src_path}"}

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        resolved = resolve_bitrate(bitrate)
    except ValueError as e:
        return {"error": str(e)}

    cmd = [
        "ffmpeg",
        "-y",
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        str(src_path),
        "-vn",
        "-acodec",
        "libmp3lame",
        "-b:a",
        resolved,
        str(dest_path),
    ]
    logger.info("ffmpeg: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=3600,
        )
        if proc.returncode != 0:
            if dest_path.exists():
                dest_path.unlink(missing_ok=True)
            tail = (proc.stderr or proc.stdout or "")[-800:]
            return {"error": f"ffmpeg 转码失败 (exit {proc.returncode}): {tail}"}
        if not dest_path.is_file() or dest_path.stat().st_size == 0:
            if dest_path.exists():
                dest_path.unlink(missing_ok=True)
            return {"error": "ffmpeg 完成但输出文件为空或不存在"}
        return None
    except subprocess.TimeoutExpired:
        if dest_path.exists():
            dest_path.unlink(missing_ok=True)
        return {"error": "ffmpeg 转码超时"}
    except FileNotFoundError:
        return preflight() or {"error": "ffmpeg not found"}
