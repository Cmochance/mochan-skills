"""Convert timestamped subtitle lines to LRC / SRT / plain / SYLT tuples."""

from __future__ import annotations

from typing import Any, Iterable


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_lrc_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_cs = int(round(seconds * 100))
    minutes, cs = divmod(total_cs, 60 * 100)
    secs, cs = divmod(cs, 100)
    return f"[{minutes:02d}:{secs:02d}.{cs:02d}]"


def _format_srt_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3600 * 1000)
    minutes, rem = divmod(rem, 60 * 1000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def normalize_lines(lines: Iterable[dict]) -> list[dict]:
    """Normalize raw lines to [{t, to, text}] with float times."""
    result: list[dict] = []
    for item in lines or []:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        t = _as_float(item.get("t"), 0.0)
        to: float | None = None
        if item.get("to") is not None:
            try:
                to = float(item["to"])
            except (TypeError, ValueError):
                to = None
        result.append({"t": t, "to": to, "text": text})
    result.sort(key=lambda x: x["t"])
    return result


def resolve_end(line: dict, next_line: dict | None, default_gap: float = 3.0) -> float:
    """Resolve end time: explicit to → next start → t+default_gap."""
    if line.get("to") is not None:
        end = float(line["to"])
        if end > line["t"]:
            return end
    if next_line is not None:
        nxt = float(next_line["t"])
        if nxt > line["t"]:
            return nxt
    return float(line["t"]) + default_gap


def to_lrc(lines: Iterable[dict], default_gap: float = 3.0) -> str:
    """Build LRC content. Uses start times only (standard LRC)."""
    _ = default_gap  # LRC is start-timestamp only
    norm = normalize_lines(lines)
    out = [f"{_format_lrc_time(line['t'])}{line['text']}" for line in norm]
    return "\n".join(out) + ("\n" if out else "")


def to_srt(lines: Iterable[dict], default_gap: float = 3.0) -> str:
    """Build SRT content with resolved end times."""
    norm = normalize_lines(lines)
    blocks: list[str] = []
    for i, line in enumerate(norm):
        nxt = norm[i + 1] if i + 1 < len(norm) else None
        start = line["t"]
        end = resolve_end(line, nxt, default_gap=default_gap)
        if end <= start:
            end = start + 0.5
        blocks.append(
            f"{i + 1}\n"
            f"{_format_srt_time(start)} --> {_format_srt_time(end)}\n"
            f"{line['text']}\n"
        )
    return "\n".join(blocks)


def to_plain(lines: Iterable[dict]) -> str:
    """Join texts for USLT unsynced lyrics."""
    norm = normalize_lines(lines)
    return "\n".join(line["text"] for line in norm)


def to_sylt_tuples(lines: Iterable[dict]) -> list[tuple[str, int]]:
    """Build mutagen SYLT text list: [(lyric, start_ms), ...]."""
    norm = normalize_lines(lines)
    return [(line["text"], int(round(line["t"] * 1000))) for line in norm]


def safe_filename(name: str, max_bytes: int = 200) -> str:
    """Strip characters unsafe for common filesystems; truncate by UTF-8 bytes.

    max_bytes leaves headroom for extensions (`.mp3`) and `_N` disambiguators
    under the common 255-byte filename limit.
    """
    bad = set('\\/:*?"<>|\n\r\t\x00')
    cleaned = "".join("_" if c in bad else c for c in (name or "").strip())
    cleaned = cleaned.strip(" .")
    if not cleaned:
        cleaned = "untitled"
    encoded = cleaned.encode("utf-8")
    if len(encoded) <= max_bytes:
        return cleaned
    # Truncate without splitting a multi-byte char
    truncated = encoded[:max_bytes]
    while truncated:
        try:
            return truncated.decode("utf-8").rstrip(" .") or "untitled"
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return "untitled"
