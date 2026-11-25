"""Pipeline unit tests with heavy mocking (no network)."""

from pathlib import Path
from unittest.mock import patch

from bilibili2mp3.pipeline import _cc_lang_to_asr_lang, _id3_title, convert_to_mp3


def test_cc_lang_to_asr_lang():
    assert _cc_lang_to_asr_lang(None) is None
    assert _cc_lang_to_asr_lang("zh-CN") == "zh"
    assert _cc_lang_to_asr_lang("ai-zh") == "zh"
    assert _cc_lang_to_asr_lang("en") == "en"


def test_id3_title():
    assert _id3_title("T", "T") == "T"
    assert _id3_title("T", "P2") == "T - P2"
    assert _id3_title("T", "") == "T"


def test_convert_preflight_no_ffmpeg(tmp_path):
    with patch("bilibili2mp3.pipeline.convert.preflight", return_value={"error": "no ffmpeg"}):
        r = convert_to_mp3("BV1x341177NN", output_dir=tmp_path)
    assert r["ok"] is False
    assert "ffmpeg" in r["error"]


def test_convert_lang_not_found_hard_error(tmp_path):
    video = {
        "bvid": "BV1x341177NN",
        "aid": 1,
        "title": "t",
        "owner": {"name": "up"},
        "pubdate": 0,
        "duration": 10,
        "pages": [{"page": 1, "part": "t", "duration": 10, "cid": 9}],
        "cid": 9,
        "pic": None,
    }
    with (
        patch("bilibili2mp3.pipeline.convert.preflight", return_value=None),
        patch(
            "bilibili2mp3.pipeline.bilibili.resolve_video",
            return_value=(video, 9, None),
        ),
        patch(
            "bilibili2mp3.pipeline.bilibili.get_subtitles",
            return_value=(
                None,
                ["zh-CN"],
                {
                    "error": "没有语言为 en 的字幕，可用: ['zh-CN']",
                    "lang_not_found": True,
                },
            ),
        ),
    ):
        r = convert_to_mp3(
            "BV1x341177NN",
            lang="en",
            output_dir=tmp_path,
            allow_asr=False,
        )
    assert r["ok"] is False
    assert "en" in r["error"]


def test_convert_happy_path_no_cc(tmp_path):
    video = {
        "bvid": "BV1x341177NN",
        "aid": 1,
        "title": "t",
        "owner": {"name": "up"},
        "pubdate": 1700000000,
        "duration": 10,
        "pages": [{"page": 1, "part": "t", "duration": 10, "cid": 9}],
        "cid": 9,
        "pic": None,
    }

    def fake_to_mp3(src, dest, bitrate="192k"):
        Path(dest).write_bytes(b"ID3fake")
        return None

    with (
        patch("bilibili2mp3.pipeline.convert.preflight", return_value=None),
        patch(
            "bilibili2mp3.pipeline.bilibili.resolve_video",
            return_value=(video, 9, None),
        ),
        patch(
            "bilibili2mp3.pipeline.bilibili.get_subtitles",
            return_value=(None, [], None),
        ),
        patch(
            "bilibili2mp3.pipeline.bilibili.has_sessdata",
            return_value=False,
        ),
        patch(
            "bilibili2mp3.pipeline.bilibili.get_audio_url",
            return_value=("https://cdn.example/a.m4a", None),
        ),
        patch(
            "bilibili2mp3.pipeline.bilibili.download_audio",
            return_value=None,
        ),
        patch(
            "bilibili2mp3.pipeline.convert.to_mp3",
            side_effect=fake_to_mp3,
        ),
        patch(
            "bilibili2mp3.pipeline.embed.embed_metadata",
            return_value=None,
        ),
    ):
        r = convert_to_mp3("BV1x341177NN", output_dir=tmp_path, embed_cover=False)
    assert r["ok"] is True
    assert Path(r["mp3_path"]).is_file()
    assert r["subtitle_source"] == "none"
    assert r["lyrics_embedded"] is False
    assert r["embed_cover"] is False
