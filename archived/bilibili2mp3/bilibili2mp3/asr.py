"""On-demand ASR for videos without CC subtitles.

与 bilibili-compact-mcp 同策略:whisper 类 ASR 是重依赖,以子进程外挂,
不进本包 dependencies。

- 默认 mlx-whisper(Apple Silicon,经 uvx 按需拉起)
- 其他平台:环境变量 BILIBILI_ASR_CMD 覆盖整条命令

环境变量:
- BILIBILI_ASR_CMD   模板,占位 {audio} {output_dir} {model} {lang};
                     须在 {output_dir} 产出含 segments 的 whisper json
- BILIBILI_ASR_MODEL 默认 mlx-community/whisper-large-v3-mlx
- BILIBILI_ASR_LANG  默认 zh
"""

from __future__ import annotations

import glob
import json
import logging
import os
import shlex
import shutil
import subprocess
import tempfile

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "mlx-community/whisper-large-v3-mlx"
DEFAULT_LANG = "zh"

_DEFAULT_ASR_ARGV = [
    "uvx",
    "--python",
    "3.12",
    "--from",
    "mlx-whisper",
    "mlx_whisper",
    "{audio}",
    "--model",
    "{model}",
    "--language",
    "{lang}",
    "--task",
    "transcribe",
    "--output-dir",
    "{output_dir}",
    "--output-format",
    "json",
    "--verbose",
    "False",
]


def _build_command(fields: dict[str, str]):
    """Returns (command, use_shell). Custom template → shell; default → argv list.

    Raises ValueError/KeyError/IndexError on bad custom templates.
    """
    override = os.getenv("BILIBILI_ASR_CMD")
    if override:
        quoted = {k: shlex.quote(v) for k, v in fields.items()}
        return override.format(**quoted), True
    return [part.format(**fields) for part in _DEFAULT_ASR_ARGV], False


def parse_whisper_json(path: str) -> list[dict]:
    """Parse whisper-format json into lines [{t, to, text}]. Public for tests."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    lines: list[dict] = []
    for seg in data.get("segments") or []:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = round(float(seg.get("start") or 0), 2)
        end_raw = seg.get("end")
        end = round(float(end_raw), 2) if end_raw is not None else None
        lines.append({"t": start, "to": end, "text": text})
    if not lines and (data.get("text") or "").strip():
        lines.append({"t": 0.0, "to": None, "text": data["text"].strip()})
    return lines


def transcribe(
    audio_path: str,
    language: str | None = None,
    timeout: int = 1800,
) -> tuple[list[dict] | None, dict | None]:
    """Transcribe audio to timestamped lines [{t, to, text}] via subprocess ASR.

    Returns (lines, error). First run may download models and take minutes.
    """
    output_dir = tempfile.mkdtemp(prefix="bilibili2mp3_asr_")
    fields = {
        "audio": audio_path,
        "output_dir": output_dir,
        "model": os.getenv("BILIBILI_ASR_MODEL", DEFAULT_MODEL),
        "lang": language or os.getenv("BILIBILI_ASR_LANG", DEFAULT_LANG),
    }
    try:
        try:
            command, use_shell = _build_command(fields)
        except (KeyError, IndexError, ValueError) as e:
            return None, {
                "error": (
                    f"BILIBILI_ASR_CMD 模板无效: {e}; "
                    "可用占位符: {{audio}} {{output_dir}} {{model}} {{lang}}"
                )
            }

        if use_shell:
            logger.info("running ASR: custom BILIBILI_ASR_CMD (shell)")
        else:
            logger.info("running ASR: %s", " ".join(command))

        proc = subprocess.run(
            command,
            shell=use_shell,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or "")[-500:]
            return None, {"error": f"ASR failed (exit {proc.returncode}): {tail}"}
        outputs = glob.glob(os.path.join(fields["output_dir"], "*.json"))
        if not outputs:
            return None, {
                "error": "ASR produced no json output (check BILIBILI_ASR_CMD)"
            }
        lines = parse_whisper_json(outputs[0])
        if not lines:
            return None, {"error": "ASR output had no transcribable text"}
        return lines, None
    except subprocess.TimeoutExpired:
        return None, {"error": f"ASR timed out after {timeout}s"}
    except FileNotFoundError as e:
        return None, {
            "error": (
                f"ASR command not found ({e}); install uv/uvx "
                "or set BILIBILI_ASR_CMD to your own transcriber"
            )
        }
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)
