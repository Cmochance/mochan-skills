"""Unit tests for LRC / SRT / SYLT pure functions."""

from bilibili2mp3.subtitle_fmt import (
    normalize_lines,
    resolve_end,
    safe_filename,
    to_lrc,
    to_plain,
    to_srt,
    to_sylt_tuples,
)


SAMPLE = [
    {"t": 1.5, "to": 3.0, "text": "第一句"},
    {"t": 3.0, "to": 5.5, "text": "第二句"},
    {"t": 5.5, "to": None, "text": "第三句"},
]


def test_normalize_skips_empty_and_sorts():
    lines = [
        {"t": 2, "text": "b"},
        {"t": 1, "text": "  "},
        {"t": 0.5, "text": "a"},
    ]
    norm = normalize_lines(lines)
    assert [x["text"] for x in norm] == ["a", "b"]
    assert norm[0]["t"] == 0.5


def test_resolve_end_prefers_to():
    line = {"t": 1.0, "to": 2.5, "text": "x"}
    nxt = {"t": 9.0, "to": None, "text": "y"}
    assert resolve_end(line, nxt) == 2.5


def test_resolve_end_uses_next_start():
    line = {"t": 1.0, "to": None, "text": "x"}
    nxt = {"t": 4.0, "to": None, "text": "y"}
    assert resolve_end(line, nxt) == 4.0


def test_resolve_end_default_gap():
    line = {"t": 10.0, "to": None, "text": "x"}
    assert resolve_end(line, None, default_gap=3.0) == 13.0


def test_to_lrc():
    lrc = to_lrc(SAMPLE)
    assert "[00:01.50]第一句" in lrc
    assert "[00:03.00]第二句" in lrc
    assert "[00:05.50]第三句" in lrc
    assert lrc.endswith("\n")


def test_to_srt_uses_to_and_gap():
    srt = to_srt(SAMPLE)
    assert "1\n" in srt
    assert "00:00:01,500 --> 00:00:03,000" in srt
    assert "第一句" in srt
    # last line without to → +3s default
    assert "00:00:05,500 --> 00:00:08,500" in srt


def test_to_plain():
    assert to_plain(SAMPLE) == "第一句\n第二句\n第三句"


def test_to_sylt_tuples_ms():
    tuples = to_sylt_tuples(SAMPLE)
    assert tuples[0] == ("第一句", 1500)
    assert tuples[1] == ("第二句", 3000)
    assert tuples[2] == ("第三句", 5500)


def test_safe_filename():
    assert "/" not in safe_filename("a/b:c*")
    assert safe_filename("   ") == "untitled"
    assert "\x00" not in safe_filename("a\x00b")
    # byte-aware: many CJK chars must stay under FS filename limit headroom
    long_zh = safe_filename("中" * 200)
    assert len(long_zh.encode("utf-8")) <= 200
    assert len(safe_filename("x" * 500).encode("utf-8")) <= 200
