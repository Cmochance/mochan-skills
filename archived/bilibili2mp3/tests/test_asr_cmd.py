"""ASR command building and error paths."""

import os
from unittest.mock import patch

from bilibili2mp3.asr import _build_command, transcribe


def test_default_command_is_argv_not_shell(monkeypatch):
    monkeypatch.delenv("BILIBILI_ASR_CMD", raising=False)
    fields = {
        "audio": "/tmp/a.m4a",
        "output_dir": "/tmp/out",
        "model": "m",
        "lang": "zh",
    }
    cmd, use_shell = _build_command(fields)
    assert use_shell is False
    assert isinstance(cmd, list)
    assert cmd[0] == "uvx"
    assert "/tmp/a.m4a" in cmd


def test_override_shell_quotes(monkeypatch):
    monkeypatch.setenv(
        "BILIBILI_ASR_CMD",
        "echo {audio} {lang}",
    )
    fields = {
        "audio": "/tmp/a file.m4a",
        "output_dir": "/tmp/out",
        "model": "m",
        "lang": "zh;rm -rf /",
    }
    cmd, use_shell = _build_command(fields)
    assert use_shell is True
    assert isinstance(cmd, str)
    # shlex.quote should neutralize metacharacters
    assert "zh;rm" not in cmd or "'zh;rm -rf /'" in cmd or '"zh;rm -rf /"' in cmd


def test_bad_template_returns_error_not_raise(monkeypatch, tmp_path):
    monkeypatch.setenv("BILIBILI_ASR_CMD", "echo {missing_placeholder}")
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"x")
    lines, err = transcribe(str(audio))
    assert lines is None
    assert err is not None
    assert "模板" in err["error"] or "placeholder" in err["error"].lower() or "{" in err["error"]


def test_build_command_bad_template_raises(monkeypatch):
    monkeypatch.setenv("BILIBILI_ASR_CMD", "echo {nope}")
    try:
        _build_command(
            {
                "audio": "a",
                "output_dir": "o",
                "model": "m",
                "lang": "zh",
            }
        )
        raised = False
    except KeyError:
        raised = True
    assert raised
