"""On-demand ASR transcription for videos without CC subtitles.

设计取舍:whisper 类 ASR 是重依赖(torch/mlx,且 mlx 仅 Apple Silicon),放进本
compact 包的 dependencies 会让它膨胀且不跨平台。因此转写器**以子进程方式外挂**,
不进本包依赖树:

- 默认走 mlx-whisper(Apple Silicon 原生,经 `uvx` 按需拉起,首次会下模型);
- 其他平台/后端(faster-whisper 等)通过环境变量 `BILIBILI_ASR_CMD` 覆盖整条命令。

环境变量:
- `BILIBILI_ASR_CMD`   自定义命令模板,含 `{audio}` `{output_dir}` `{model}` `{lang}`
                       占位;命令须在 `{output_dir}` 下产出一个 whisper json(含 segments)。
- `BILIBILI_ASR_MODEL` 模型(默认 mlx-community/whisper-large-v3-mlx)。
- `BILIBILI_ASR_LANG`  语言(默认 zh)。
"""

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

# 默认命令(argv 形式,免 shell 注入);占位符在运行时替换
_DEFAULT_ASR_ARGV = [
    "uvx", "--python", "3.12", "--from", "mlx-whisper", "mlx_whisper",
    "{audio}", "--model", "{model}", "--language", "{lang}",
    "--task", "transcribe", "--output-dir", "{output_dir}",
    "--output-format", "json", "--verbose", "False",
]


def _build_command(fields):
    """Returns (command, use_shell). Custom template → shell; default → argv list."""
    override = os.getenv("BILIBILI_ASR_CMD")
    if override:
        quoted = {k: shlex.quote(v) for k, v in fields.items()}
        return override.format(**quoted), True
    return [part.format(**fields) for part in _DEFAULT_ASR_ARGV], False


def _parse_whisper_json(path):
    with open(path) as f:
        data = json.load(f)
    lines = []
    for seg in data.get("segments") or []:
        text = (seg.get("text") or "").strip()
        if text:
            lines.append({"t": round(seg.get("start", 0), 2), "text": text})
    # 有些后端不产 segments,只给整段 text
    if not lines and (data.get("text") or "").strip():
        lines.append({"t": 0, "text": data["text"].strip()})
    return lines


def transcribe(audio_path, language=None, timeout=1800):
    """Transcribes an audio file to timestamped lines [{t, text}] via subprocess ASR.

    Returns (lines, error). 首次运行会下载模型,可能耗时数分钟。
    """
    fields = {
        "audio": audio_path,
        "output_dir": tempfile.mkdtemp(prefix="bili_asr_"),
        "model": os.getenv("BILIBILI_ASR_MODEL", DEFAULT_MODEL),
        "lang": language or os.getenv("BILIBILI_ASR_LANG", DEFAULT_LANG),
    }
    command, use_shell = _build_command(fields)
    logger.info("running ASR: %s", command if use_shell else " ".join(command))
    try:
        proc = subprocess.run(command, shell=use_shell, capture_output=True,
                              text=True, timeout=timeout)
        if proc.returncode != 0:
            tail = (proc.stderr or "")[-500:]
            return None, {"error": f"ASR failed (exit {proc.returncode}): {tail}"}
        outputs = glob.glob(os.path.join(fields["output_dir"], "*.json"))
        if not outputs:
            return None, {"error": "ASR produced no json output (check BILIBILI_ASR_CMD)"}
        lines = _parse_whisper_json(outputs[0])
        if not lines:
            return None, {"error": "ASR output had no transcribable text"}
        return lines, None
    except subprocess.TimeoutExpired:
        return None, {"error": f"ASR timed out after {timeout}s"}
    except FileNotFoundError as e:
        return None, {"error": f"ASR command not found ({e}); install uv/uvx "
                               f"or set BILIBILI_ASR_CMD to your own transcriber"}
    finally:
        shutil.rmtree(fields["output_dir"], ignore_errors=True)
