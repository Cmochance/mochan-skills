"""Unit tests for bilibili API helpers (mocked HTTP)."""

from unittest.mock import MagicMock, patch

import pytest

from bilibili2mp3 import bilibili
from bilibili2mp3.bilibili import extract_bvid, list_subtitle_tracks


def test_extract_bvid_bare():
    assert extract_bvid("BV1x341177NN") == "BV1x341177NN"


def test_extract_bvid_full_url():
    assert (
        extract_bvid("https://www.bilibili.com/video/BV1x341177NN?p=1")
        == "BV1x341177NN"
    )


def test_extract_bvid_attacker_substring_no_request():
    """'b23.tv' as query substring must not trigger HEAD with cookie."""
    evil = "https://attacker.example/collect?ref=b23.tv"
    with patch("bilibili2mp3.bilibili.requests.head") as head:
        # No BV in this URL → None; must not call head
        assert extract_bvid(evil) is None
        head.assert_not_called()


def test_extract_bvid_short_link_uses_anonymous_headers():
    final = MagicMock()
    final.url = "https://www.bilibili.com/video/BV1x341177NN"
    with patch("bilibili2mp3.bilibili.requests.head", return_value=final) as head:
        assert extract_bvid("https://b23.tv/abcdef") == "BV1x341177NN"
        head.assert_called_once()
        kwargs = head.call_args.kwargs
        headers = kwargs.get("headers") or head.call_args[1].get("headers")
        assert "Cookie" not in headers


def test_list_subtitle_tracks_data_null_no_crash():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"code": -352, "message": "风控", "data": None}
    with (
        patch("bilibili2mp3.bilibili.wbi.sign", return_value={"aid": 1, "cid": 2}),
        patch("bilibili2mp3.bilibili.requests.get", return_value=resp),
    ):
        tracks, err = list_subtitle_tracks(1, 2)
    assert tracks == []
    assert err is not None
    assert "code=-352" in err["error"] or "-352" in err["error"]


def test_list_subtitle_tracks_code_zero_empty():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "code": 0,
        "data": {"subtitle": {"subtitles": []}},
    }
    with (
        patch("bilibili2mp3.bilibili.wbi.sign", return_value={"aid": 1}),
        patch("bilibili2mp3.bilibili.requests.get", return_value=resp),
    ):
        tracks, err = list_subtitle_tracks(1, 2)
    assert err is None
    assert tracks == []


def test_list_subtitle_tracks_ok():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "code": 0,
        "data": {
            "subtitle": {
                "subtitles": [
                    {"lan": "zh-CN", "lan_doc": "中文", "subtitle_url": "//x/y.json"},
                ]
            }
        },
    }
    with (
        patch("bilibili2mp3.bilibili.wbi.sign", return_value={"aid": 1}),
        patch("bilibili2mp3.bilibili.requests.get", return_value=resp),
    ):
        tracks, err = list_subtitle_tracks(1, 2)
    assert err is None
    assert tracks[0]["lan"] == "zh-CN"


def test_get_audio_url_data_null():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"code": 0, "data": None}
    with (
        patch("bilibili2mp3.bilibili.wbi.sign", return_value={}),
        patch("bilibili2mp3.bilibili.requests.get", return_value=resp),
    ):
        url, err = bilibili.get_audio_url(1, 2)
    assert url is None
    assert err is not None


def test_anonymous_headers_no_cookie(monkeypatch):
    monkeypatch.setenv("SESSDATA", "secret")
    assert "Cookie" not in bilibili.anonymous_headers()
    assert "SESSDATA=secret" in bilibili.api_headers()["Cookie"]
