"""ASR whisper json parsing (no real model)."""

import json
from pathlib import Path

from bilibili2mp3.asr import parse_whisper_json


def test_parse_segments_with_end(tmp_path: Path):
    p = tmp_path / "out.json"
    p.write_text(
        json.dumps(
            {
                "text": "你好世界",
                "segments": [
                    {"start": 0.0, "end": 1.2, "text": " 你好 "},
                    {"start": 1.2, "end": 2.5, "text": "世界"},
                ],
            }
        ),
        encoding="utf-8",
    )
    lines = parse_whisper_json(str(p))
    assert lines == [
        {"t": 0.0, "to": 1.2, "text": "你好"},
        {"t": 1.2, "to": 2.5, "text": "世界"},
    ]


def test_parse_text_only_fallback(tmp_path: Path):
    p = tmp_path / "out.json"
    p.write_text(json.dumps({"text": "整段文本", "segments": []}), encoding="utf-8")
    lines = parse_whisper_json(str(p))
    assert lines == [{"t": 0.0, "to": None, "text": "整段文本"}]
