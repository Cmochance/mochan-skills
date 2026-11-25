"""Bitrate preset resolution."""

from bilibili2mp3.convert import BITRATE_PRESETS, resolve_bitrate


def test_presets_map():
    assert resolve_bitrate("speech") == "96k"
    assert resolve_bitrate("podcast") == "128k"
    assert resolve_bitrate("standard") == "192k"
    assert resolve_bitrate("high") == "320k"


def test_case_insensitive_preset():
    assert resolve_bitrate("HIGH") == "320k"
    assert resolve_bitrate(" Podcast ") == "128k"


def test_raw_passthrough():
    assert resolve_bitrate("256k") == "256k"
    assert resolve_bitrate("256") == "256k"
    assert resolve_bitrate(None) == "192k"
    assert resolve_bitrate("") == "192k"


def test_invalid_bitrate_raises():
    import pytest

    with pytest.raises(ValueError):
        resolve_bitrate("abc")
    with pytest.raises(ValueError):
        resolve_bitrate("192kbps")


def test_presets_table_complete():
    assert set(BITRATE_PRESETS) == {"speech", "podcast", "standard", "high"}
