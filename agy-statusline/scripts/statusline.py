#!/usr/bin/env python3
"""Custom statusline renderer for Antigravity CLI (agy).

Pure-stdlib hot-path renderer invoked directly by `agy` via settings.json.
Zero subprocesses, zero network calls, single-line ANSI output.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import unicodedata

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
SGR_RE = re.compile(r"^(?:\x1b\[[0-9;]*m)*$")
ESCAPE_SEQ_RE = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC
    r"|\x1b[PX^_][^\x1b]*\x1b\\"  # DCS / SOS / PM / APC
    r"|\x1b\[[0-9;?]*[ -/]*[@-~]"  # CSI
    r"|\x1b[@-Z\\-_]"  # 2-byte ESC
    r"|\x9d[^\x07\x9c]*(?:\x07|\x9c)"  # C1 OSC
    r"|\x9b[0-9;?]*[ -/]*[@-~]"  # C1 CSI
)
WS_BREAK_RE = re.compile(r"[\r\n\t\u2028\u2029]+")
RESET = "\033[0m"

THEMES: dict[str, dict[str, str]] = {
    "tokyo-night": {
        "reset": RESET,
        "path": "\033[38;5;111m",
        "wt_linked": "\033[38;5;79m",
        "wt_main": "\033[38;5;114m",
        "sep": "\033[38;5;242m",
        "model": "\033[38;5;250m",
        "muted": "\033[38;5;244m",
        "green": "\033[38;5;114m",
        "amber": "\033[38;5;215m",
        "red": "\033[38;5;203m",
        "sky": "\033[38;5;117m",
        "teal": "\033[38;5;116m",
        "yellow": "\033[38;5;221m",
    },
    "minimal": {
        "reset": RESET,
        "path": "\033[38;5;250m",
        "wt_linked": "\033[38;5;110m",
        "wt_main": "\033[38;5;246m",
        "sep": "\033[38;5;239m",
        "model": "\033[38;5;248m",
        "muted": "\033[38;5;242m",
        "green": "\033[38;5;248m",
        "amber": "\033[38;5;215m",
        "red": "\033[38;5;203m",
        "sky": "\033[38;5;110m",
        "teal": "\033[38;5;248m",
        "yellow": "\033[38;5;221m",
    },
    "plain": {
        "reset": "",
        "path": "",
        "wt_linked": "",
        "wt_main": "",
        "sep": "",
        "model": "",
        "muted": "",
        "green": "",
        "amber": "",
        "red": "",
        "sky": "",
        "teal": "",
        "yellow": "",
    },
}

DEFAULT_CONFIG: dict = {
    "theme": "tokyo-night",
    "no_color": False,
    "separator": " · ",
    "left_segments": ["path", "worktree"],
    "right_segments": ["permission", "model", "context", "cache", "quota"],
    "path": {
        "home_tilde": True,
        "abbreviate_parents": True,
    },
    "worktree": {
        "icon": "⎇",
        "show_dirty": True,
        "label": "branch",
        "auto_detect_from_transcript": True,
        "auto_prefix": "~",
    },
    "cache": {
        "icon": "⚡",
        "style": "percent",
        "hide_when_empty": False,
    },
    "permission": {
        "default_fallback": "default",
    },
    "thresholds": {
        "context_warn_pct": 60,
        "context_critical_pct": 85,
        "cache_ok_pct": 70,
        "cache_warn_pct": 30,
        "quota_ok_pct": 50,
        "quota_warn_pct": 20,
        "quota_countdown_below_pct": 20,
    },
    "quota": {
        "filter_by_model": True,
        "write_snapshot": True,
    },
    "layout": {
        "right_margin": 2,
        "min_gap": 2,
    },
    "colors": {},
}

DEFAULT_DEBUG_DUMP_PATH = Path("/tmp/agy-statusline-debug.json")

PERMISSION_KEYS = (
    "cycle_mode",
    "mode",
    "agent_mode",
    "agentMode",
    "permission_mode",
    "permissionMode",
    "approval_mode",
    "approvalMode",
    "execution_mode",
    "executionMode",
    "tool_permission",
    "toolPermission",
    "permissions",
)


def skill_root() -> Path:
    """Resolve the skill root directory even when invoked through symlinks."""
    return Path(__file__).resolve().parent.parent


def default_data_dir() -> Path:
    """Resolve the Antigravity CLI data directory (honoring AGY_DATA_DIR)."""
    env = os.environ.get("AGY_DATA_DIR", "").strip()
    return Path(env).expanduser() if env else Path.home() / ".gemini" / "antigravity-cli"


def _clone(val: object) -> object:
    """Deep-clone nested JSON-compatible dicts and lists without copy module overhead."""
    if isinstance(val, dict):
        return {k: _clone(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_clone(v) for v in val]
    return val


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override onto a freshly cloned base dict."""
    out = {k: _clone(v) for k, v in base.items()}
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = _clone(v)
    return out


def resolve_config_path(data_dir: Path | None = None) -> Path | None:
    """Find the highest-priority existing config file path, or None for defaults."""
    env_cfg = os.environ.get("AGY_STATUSLINE_CONFIG", "").strip()
    if env_cfg:
        p = Path(env_cfg).expanduser()
        if p.is_file():
            return p
    local_cfg = skill_root() / "config.local.json"
    if local_cfg.is_file():
        return local_cfg
    d_dir = data_dir if data_dir is not None else default_data_dir()
    global_cfg = d_dir / "statusline.json"
    if global_cfg.is_file():
        return global_cfg
    return None


def load_config(data_dir: Path | None = None, config_path: Path | None = None) -> dict:
    """Load merged runtime configuration safely, falling back to built-in defaults."""
    target = config_path if config_path is not None else resolve_config_path(data_dir)
    if target is None:
        return _deep_merge(DEFAULT_CONFIG, {})
    try:
        parsed = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            return _deep_merge(DEFAULT_CONFIG, parsed)
    except Exception:
        pass
    return _deep_merge(DEFAULT_CONFIG, {})


def _sanitize_single_line(text: str, strip: bool = True) -> str:
    """Strip ANSI/OSC escapes and control characters to guarantee clean single-line output."""
    if not text:
        return ""
    cleaned = ESCAPE_SEQ_RE.sub("", text)
    cleaned = WS_BREAK_RE.sub(" ", cleaned)
    if any(unicodedata.category(ch) == "Cc" for ch in cleaned):
        cleaned = "".join(ch for ch in cleaned if unicodedata.category(ch) != "Cc")
    return cleaned.strip() if strip else cleaned


def _normalize_color(val: object) -> str | None:
    """Convert an int 256-color index or validated SGR escape string into a color code."""
    if isinstance(val, bool):
        return None
    if isinstance(val, int) and 0 <= val <= 255:
        return f"\033[38;5;{val}m"
    if isinstance(val, str) and SGR_RE.fullmatch(val):
        return val
    return None


def build_palette(cfg: dict, no_color: bool = False) -> dict[str, str]:
    """Build the active color palette from theme, overrides, and NO_COLOR."""
    env_no_color = bool(os.environ.get("NO_COLOR", ""))
    raw_theme = cfg.get("theme")
    theme_name = raw_theme.strip().lower() if isinstance(raw_theme, str) and raw_theme.strip() else "tokyo-night"
    if no_color or env_no_color or cfg.get("no_color") or theme_name == "plain":
        return dict(THEMES["plain"])

    base = THEMES.get(theme_name, THEMES["tokyo-night"])
    pal = dict(base)
    overrides = cfg.get("colors")
    if isinstance(overrides, dict):
        for k, v in overrides.items():
            if k in pal and k != "reset":
                norm = _normalize_color(v)
                if norm is not None:
                    pal[k] = norm
    return pal


def _char_width(ch: str) -> int:
    """Return terminal cell width of a single Unicode character."""
    cat = unicodedata.category(ch)
    if cat in ("Mn", "Me", "Cf", "Cc"):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def display_width(text: str) -> int:
    """Calculate terminal column width after stripping ANSI CSI sequences."""
    plain = ANSI_RE.sub("", text)
    width = 0
    after_zwj = False
    for ch in plain:
        if ch == "\u200d":
            after_zwj = True
            continue
        cw = _char_width(ch)
        if cw == 0:
            continue
        if after_zwj:
            after_zwj = False
            continue
        width += cw
    return width


def truncate_left_ellipsis(text: str, max_w: int) -> str:
    """Truncate text from the left with a leading ellipsis to fit max_w."""
    if max_w <= 0:
        return ""
    if display_width(text) <= max_w:
        return text
    if max_w == 1:
        return "…"
    kept: list[str] = []
    acc = 1  # reserve 1 column for "…"
    idx = len(text) - 1
    while idx >= 0:
        # Collect a base character along with any trailing zero-width marks / ZWJ extenders
        cluster_end = idx + 1
        while idx > 0 and _char_width(text[idx]) == 0:
            idx -= 1
        cluster_start = idx
        while cluster_start >= 2 and text[cluster_start - 1] == "\u200d":
            cluster_start -= 2
            while cluster_start > 0 and _char_width(text[cluster_start]) == 0:
                cluster_start -= 1
        cluster = text[cluster_start:cluster_end]
        cw = display_width(cluster)
        if acc + cw > max_w:
            break
        kept.append(cluster)
        acc += cw
        idx = cluster_start - 1

    # Ensure no orphaned leading combining mark attaches onto "…"
    result_tail = "".join(reversed(kept))
    while result_tail and _char_width(result_tail[0]) == 0:
        result_tail = result_tail[1:]
    return "…" + result_tail


def load_settings(data_dir: Path | None = None) -> dict:
    """Safely read <data_dir>/settings.json."""
    d_dir = data_dir if data_dir is not None else default_data_dir()
    settings_path = d_dir / "settings.json"
    try:
        parsed = json.loads(settings_path.read_text(encoding="utf-8"))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def extract_str(
    val: object,
    keys: tuple[str, ...] = ("display_name", "name", "mode", "level", "preset", "id"),
) -> str:
    """Extract a sanitized non-empty single-line string from a scalar or dict value."""
    if isinstance(val, str):
        return _sanitize_single_line(val)
    if isinstance(val, dict):
        for k in keys:
            inner = val.get(k)
            if isinstance(inner, str):
                cleaned = _sanitize_single_line(inner)
                if cleaned:
                    return cleaned
    return ""


def normalize_home(path_str: str, enabled: bool = True) -> str:
    """Replace the user's home directory prefix with ~ when enabled."""
    if not enabled:
        return path_str
    home = str(Path.home())
    if path_str == home:
        return "~"
    if path_str.startswith(home + os.sep):
        return "~" + path_str[len(home):]
    return path_str


def resolve_project_dir(data: dict) -> str:
    """Determine the active project/workspace directory path."""
    ws = data.get("workspace")
    candidates: list[object] = []
    if isinstance(ws, dict):
        candidates.extend([ws.get("current_dir"), ws.get("project_dir")])
    candidates.extend([data.get("cwd"), data.get("folder")])
    for cand in candidates:
        if isinstance(cand, str) and cand.strip():
            raw = cand.strip()
            if raw.startswith("file://"):
                from urllib.parse import unquote

                stripped = raw[7:]
                if stripped.startswith("localhost/"):
                    stripped = stripped[9:]
                raw = unquote(stripped)
            return raw
    try:
        return os.getcwd()
    except OSError:
        return ""


def read_git_head(git_dir: Path) -> str:
    """Read branch name or short commit SHA from a git directory's HEAD file."""
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8")
    except Exception:
        return ""
    first_line = head.splitlines()[0].strip() if head.splitlines() else ""
    if not first_line:
        return ""
    if first_line.startswith("ref:"):
        ref = first_line[4:].strip()
        prefix = "refs/heads/"
        raw = ref[len(prefix):] if ref.startswith(prefix) else ref
        return _sanitize_single_line(raw)
    clean_sha = _sanitize_single_line(first_line)
    if len(clean_sha) >= 7:
        return clean_sha[:7]
    return clean_sha


SESSION_ID_SAFE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
UNQUOTED_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_.\-/])((?:/|~/)(?:\\.|[^\s'\"`\\;|<>()&:,\{\}\[\]])+)"
    r"|(?<=-[A-Za-z])((?:/|~/)(?:\\.|[^\s'\"`\\;|<>()&:,\{\}\[\]])+)"
)
ABS_PATH_TOKEN_RE = re.compile(
    r'"((?:/|~/)(?:\\.|[^"\\\r\n])+)"'
    r"|'((?:/|~/)(?:[^'\r\n]+))'"
    r"|(?<![A-Za-z0-9_.\-/])((?:/|~/)(?:\\.|[^\s'\"`\\;|<>()&:,\{\}\[\]])+)"
    r"|(?<=-[A-Za-z])((?:/|~/)(?:\\.|[^\s'\"`\\;|<>()&:,\{\}\[\]])+)"
)
UNESCAPE_SHELL_RE = re.compile(r"\\(.)")
TRANSCRIPT_TAIL_SCAN_BYTES = 65536
FILE_TOOL_NAMES = frozenset(
    {
        "write_file",
        "edit_file",
        "write_to_file",
        "replace_file_content",
        "multi_replace_file_content",
        "read_file",
        "view_file",
    }
)
FILE_TOOL_PATH_KEYS = ("Path", "TargetFile", "path", "file_path", "target_file")


def _safe_expanduser(raw: str | Path) -> Path:
    return Path(os.path.expanduser(str(raw)))


def _same_git_path(a: Path | None, b: Path | None) -> bool:
    if a is None or b is None:
        return False
    try:
        if os.path.samefile(str(a), str(b)):
            return True
    except (OSError, ValueError):
        pass
    sa, sb = str(a), str(b)
    return sa.lower() == sb.lower() if sys.platform == "darwin" else sa == sb


def _inspect_git_path(path: Path) -> tuple[str, str, Path | None, bool, Path | None] | None:
    """Walk ancestors of path to inspect .git without spawning git.

    Returns (branch, wt_name, common_dir, is_linked, worktree_root) or None.
    """
    raw_str = str(path)
    if not raw_str or "\x00" in raw_str:
        return None
    try:
        start = _safe_expanduser(raw_str).resolve()
    except (OSError, ValueError):
        start = _safe_expanduser(raw_str)

    try:
        candidates = (*start.parents,) if (start.is_file() or not start.exists()) else (start, *start.parents)
    except (OSError, ValueError):
        candidates = (*start.parents,)

    for parent in candidates:
        dot_git = parent / ".git"
        try:
            st = os.lstat(str(dot_git))
        except (OSError, ValueError):
            continue

        if stat.S_ISDIR(st.st_mode):
            try:
                common = dot_git.resolve()
                root = parent.resolve()
            except (OSError, ValueError):
                common = dot_git
                root = parent
            return read_git_head(common), "", common, False, root

        if stat.S_ISREG(st.st_mode):
            try:
                content = dot_git.read_text(encoding="utf-8").strip()
            except Exception:
                return "", "", None, False, parent
            gitdir_raw = ""
            for line in content.splitlines():
                if line.lower().startswith("gitdir:"):
                    gitdir_raw = line.split(":", 1)[1].strip()
                    break
            if not gitdir_raw or "\x00" in gitdir_raw:
                return "", "", None, False, parent
            try:
                gitdir_path = _safe_expanduser(gitdir_raw)
                if not gitdir_path.is_absolute():
                    gitdir_path = (parent / gitdir_path).resolve()
                else:
                    gitdir_path = gitdir_path.resolve()
            except Exception:
                return "", "", None, False, parent

            parts = gitdir_path.parts
            common_dir = gitdir_path
            try:
                cd_raw = (gitdir_path / "commondir").read_text(encoding="utf-8").strip()
                if cd_raw and "\x00" not in cd_raw:
                    cd_path = _safe_expanduser(cd_raw)
                    common_dir = (gitdir_path / cd_path).resolve() if not cd_path.is_absolute() else cd_path.resolve()
            except Exception:
                if len(parts) >= 3 and parts[-2] == "worktrees" and parts[-3] == ".git":
                    try:
                        common_dir = gitdir_path.parent.parent.resolve()
                    except (OSError, ValueError):
                        common_dir = gitdir_path.parent.parent

            branch = read_git_head(gitdir_path)
            try:
                root = parent.resolve()
            except (OSError, ValueError):
                root = parent
            if len(parts) >= 2 and parts[-2] == "worktrees":
                return branch, _sanitize_single_line(parts[-1]), common_dir, True, root
            return branch, "", common_dir, False, root

    return None


def _format_linked_label(branch: str, wt_name: str, label_mode: str) -> str:
    if label_mode == "name":
        return _sanitize_single_line(wt_name or branch)
    return _sanitize_single_line(branch or wt_name)


def _select_preferred_transcript(logs_dir: Path, fallback: Path | None = None) -> Path:
    """Prefer compact transcript.jsonl only when non-empty and fresh relative to transcript_full.jsonl."""
    compact = logs_dir / "transcript.jsonl"
    full = logs_dir / "transcript_full.jsonl"
    try:
        st_c = compact.stat()
    except (OSError, ValueError):
        st_c = None
    try:
        st_f = full.stat()
    except (OSError, ValueError):
        st_f = None

    if st_c is not None and st_c.st_size > 0:
        if st_f is None or st_c.st_mtime >= st_f.st_mtime - 5.0:
            return compact
    if st_f is not None and st_f.st_size > 0:
        return full
    if fallback is not None:
        return fallback
    return compact


def _extract_session_paths(data: dict, data_dir: Path | None) -> tuple[Path | None, Path | None]:
    """Resolve (scratch_dir, transcript_path) for the active agy conversation."""
    scratch_dir: Path | None = None
    transcript_path: Path | None = None

    for k in ("artifactDirectoryPath", "artifact_directory_path"):
        raw_art = data.get(k)
        if isinstance(raw_art, str) and raw_art.strip() and "\x00" not in raw_art:
            art_p = _safe_expanduser(raw_art.strip())
            if art_p.parent.name == "brain":
                scratch_dir = art_p / "scratch"
                transcript_path = _select_preferred_transcript(art_p / ".system_generated" / "logs")
                break
            if art_p.name == "artifacts" and art_p.parent.parent.name == "brain":
                scratch_dir = art_p.parent / "scratch"
                transcript_path = _select_preferred_transcript(art_p.parent / ".system_generated" / "logs")
                break

    raw_tp = data.get("transcript_path") or data.get("transcriptPath")
    if isinstance(raw_tp, str) and raw_tp.strip() and "\x00" not in raw_tp:
        tp = _safe_expanduser(raw_tp.strip())
        if tp.name in ("transcript_full.jsonl", "transcript.jsonl"):
            tp = _select_preferred_transcript(tp.parent, fallback=tp)
        transcript_path = tp
        if scratch_dir is None and tp.parent.name == "logs" and tp.parent.parent.name == ".system_generated":
            scratch_dir = tp.parent.parent.parent / "scratch"

    cid = ""
    for k in ("session_id", "conversation_id", "conversationId"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            cid = v.strip()
            break
    if cid and SESSION_ID_SAFE_RE.fullmatch(cid):
        d = data_dir if data_dir is not None else default_data_dir()
        brain_conv = d / "brain" / cid
        if scratch_dir is None:
            scratch_dir = brain_conv / "scratch"
        if transcript_path is None:
            transcript_path = _select_preferred_transcript(brain_conv / ".system_generated" / "logs")

    return scratch_dir, transcript_path


def _resolve_exit_watermark(parsed: dict, transcript_path: Path | None) -> int:
    """Resolve the byte-offset watermark matching the exact transcript filename being scanned."""
    offsets_map = parsed.get("exit_transcript_offsets")
    tp_name = transcript_path.name if transcript_path is not None else ""
    if isinstance(offsets_map, dict) and offsets_map:
        if tp_name and tp_name in offsets_map:
            val = offsets_map.get(tp_name)
            if is_num(val) and float(val) >= 0:
                return int(val)
        return 0
    raw_offset = parsed.get("exit_transcript_offset")
    if is_num(raw_offset) and float(raw_offset) >= 0:
        return int(raw_offset)
    return 0


def _load_session_worktree(
    scratch_dir: Path | None,
    main_common: Path,
    label_mode: str,
    transcript_path: Path | None = None,
) -> tuple[str | None, int]:
    """Read Layer 1 scratch/worktree.json. Returns (active_label_or_None, exit_transcript_offset)."""
    if scratch_dir is None:
        return None, 0
    state_path = scratch_dir / "worktree.json"
    try:
        parsed = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return None, 0
    if not isinstance(parsed, dict):
        return None, 0

    state = str(parsed.get("state") or "").strip().lower()
    if state != "active":
        raw_cd = parsed.get("common_dir")
        if isinstance(raw_cd, str) and raw_cd.strip() and "\x00" not in raw_cd:
            try:
                st_common = _safe_expanduser(raw_cd).resolve()
            except (OSError, ValueError):
                st_common = _safe_expanduser(raw_cd)
            if not _same_git_path(st_common, main_common):
                return None, 0
        return None, _resolve_exit_watermark(parsed, transcript_path)

    wt_path_raw = parsed.get("worktree_path")
    if not isinstance(wt_path_raw, str) or not wt_path_raw.strip() or "\x00" in wt_path_raw:
        return None, 0
    wt_path = _safe_expanduser(wt_path_raw)
    try:
        if not wt_path.is_dir():
            return None, 0
    except (OSError, ValueError):
        return None, 0

    info = _inspect_git_path(wt_path)
    if info is None:
        return None, 0
    branch, wt_name, wt_common, is_linked, _ = info
    if not is_linked or not _same_git_path(wt_common, main_common):
        return None, 0

    label = _format_linked_label(
        branch or _sanitize_single_line(str(parsed.get("branch") or "")),
        wt_name or _sanitize_single_line(str(parsed.get("worktree_name") or "")),
        label_mode,
    )
    return (label or None), 0


def _unwrap_transcript_arg(val: object) -> str:
    """Unwrap plain or double-JSON-encoded string arguments from transcript.jsonl."""
    if not isinstance(val, str):
        return ""
    s = val.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        try:
            decoded = json.loads(s)
            if isinstance(decoded, str):
                return decoded.strip()
        except Exception:
            pass
    return s


def _extract_candidate_paths_from_tool_call(tc: object) -> list[str]:
    """Extract filesystem path candidates from a single transcript tool_call object."""
    if not isinstance(tc, dict):
        return []
    name = str(tc.get("name") or "").strip().lower()
    args = tc.get("args")
    if not isinstance(args, dict):
        return []

    paths: list[str] = []
    if name in FILE_TOOL_NAMES:
        for k in FILE_TOOL_PATH_KEYS:
            p = _unwrap_transcript_arg(args.get(k))
            if p and "\x00" not in p and (p.startswith("/") or p.startswith("~/")):
                paths.append(p)
                break
        return paths

    if name == "run_command":
        raw_cmd = args.get("CommandLine") or args.get("command")
        cmd = _unwrap_transcript_arg(raw_cmd)
        if cmd and "\x00" not in cmd:
            if (cmd.startswith("/") or cmd.startswith("~/")) and " " in cmd:
                paths.append(cmd)
            for m in ABS_PATH_TOKEN_RE.finditer(cmd):
                if m.group(1) is not None:
                    cand = m.group(1).replace('\\"', '"').replace("\\\\", "\\").rstrip("\\").strip()
                    if cand and len(cand) > 1:
                        paths.append(cand)
                        # If a double-quoted compound command starts with '/', also scan its interior for paths
                        if " " in cand and ("/" in cand[1:] or "~/" in cand):
                            for inner in UNQUOTED_PATH_RE.finditer(cand):
                                ic = UNESCAPE_SHELL_RE.sub(r"\1", inner.group(1) or inner.group(2) or "").strip()
                                if ic and len(ic) > 1:
                                    paths.append(ic)
                elif m.group(2) is not None:
                    cand = m.group(2).strip()
                    if cand and len(cand) > 1:
                        paths.append(cand)
                        if " " in cand and ("/" in cand[1:] or "~/" in cand):
                            for inner in UNQUOTED_PATH_RE.finditer(cand):
                                ic = UNESCAPE_SHELL_RE.sub(r"\1", inner.group(1) or inner.group(2) or "").strip()
                                if ic and len(ic) > 1:
                                    paths.append(ic)
                else:
                    cand = UNESCAPE_SHELL_RE.sub(r"\1", m.group(3) or m.group(4) or "").strip()
                    if cand and len(cand) > 1:
                        paths.append(cand)
        return paths

    return paths


def _match_same_repo_linked_worktree(cand_raw: str, main_common: Path) -> tuple[str, str, Path] | None:
    """If cand_raw points inside a linked worktree sharing main_common, return (branch, wt_name, wt_root)."""
    if not cand_raw or "\x00" in cand_raw:
        return None
    try:
        cand = _safe_expanduser(cand_raw)
        if not cand.is_absolute():
            return None
        info = _inspect_git_path(cand)
        if info is None:
            return None
        branch, wt_name, wt_common, is_linked, wt_root = info
        if is_linked and _same_git_path(wt_common, main_common) and wt_root is not None and wt_root.is_dir():
            return branch, wt_name, wt_root
    except Exception:
        return None
    return None


def _probe_worktree_from_transcript(
    scratch_dir: Path | None,
    transcript_path: Path | None,
    main_common: Path,
    exit_watermark: int,
    label_mode: str,
) -> str | None:
    """Layer 2: incrementally scan complete JSONL lines in transcript tail for same-repo linked worktrees."""
    if transcript_path is None or "\x00" in str(transcript_path):
        return None
    try:
        st = transcript_path.stat()
    except (OSError, ValueError):
        return None

    size = st.st_size
    inode = st.st_ino
    if size <= exit_watermark:
        return None

    cache_path = scratch_dir / "wt_probe_cache.json" if scratch_dir is not None else None
    cached: dict | None = None
    if cache_path is not None:
        try:
            raw_c = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(raw_c, dict):
                cached = raw_c
        except Exception:
            cached = None

    main_common_str = str(main_common)
    same_stream = (
        cached is not None
        and cached.get("inode") == inode
        and cached.get("main_common") == main_common_str
        and cached.get("exit_watermark") == exit_watermark
        and isinstance(cached.get("offset"), int)
        and 0 <= cached["offset"] <= size
    )

    if same_stream and cached is not None and cached["offset"] == size:
        cached_wt = str(cached.get("worktree_path") or "")
        if not cached_wt:
            return None
        matched = _match_same_repo_linked_worktree(cached_wt, main_common)
        if matched is None:
            try:
                if cache_path is not None:
                    _atomic_write_private(
                        cache_path,
                        json.dumps(
                            {
                                "inode": inode,
                                "offset": size,
                                "main_common": main_common_str,
                                "exit_watermark": exit_watermark,
                                "worktree_path": "",
                            }
                        ),
                    )
            except Exception:
                pass
            return None
        branch, wt_name, _ = matched
        return _format_linked_label(branch, wt_name, label_mode) or None

    prev_offset = cached["offset"] if (same_stream and cached is not None) else exit_watermark
    seek_start = max(exit_watermark, prev_offset, size - TRANSCRIPT_TAIL_SCAN_BYTES)
    mid_line = False
    try:
        with open(transcript_path, "rb") as fp:
            if seek_start > 0:
                fp.seek(seek_start - 1)
                mid_line = fp.read(1) != b"\n"
            raw_chunk = fp.read(size - seek_start)
    except (OSError, ValueError):
        return None

    # Only advance cached offset through the last complete newline so partial mid-write JSONL lines are never skipped
    last_nl = raw_chunk.rfind(b"\n")
    if last_nl >= 0:
        next_offset = seek_start + last_nl + 1
        chunk = raw_chunk[:last_nl]
    else:
        # No complete line yet in delta: hold prev_offset unless a single unterminated line exceeds the scan window
        next_offset = prev_offset if (size - prev_offset) <= TRANSCRIPT_TAIL_SCAN_BYTES else size
        chunk = b""

    if mid_line and chunk:
        first_nl = chunk.find(b"\n")
        chunk = chunk[first_nl + 1 :] if first_nl >= 0 else b""

    detected: tuple[str, str, Path] | None = None
    if chunk:
        for raw_line in reversed(chunk.splitlines()):
            if b"tool_calls" not in raw_line:
                continue
            try:
                entry = json.loads(raw_line.decode("utf-8", errors="replace"))
            except Exception:
                continue
            if not isinstance(entry, dict):
                continue
            tool_calls = entry.get("tool_calls")
            if not isinstance(tool_calls, list):
                continue
            for tc in reversed(tool_calls):
                for cand in reversed(_extract_candidate_paths_from_tool_call(tc)):
                    matched = _match_same_repo_linked_worktree(cand, main_common)
                    if matched is not None:
                        detected = matched
                        break
                if detected is not None:
                    break
            if detected is not None:
                break

    if detected is None and same_stream and cached is not None:
        prev_wt = str(cached.get("worktree_path") or "")
        if prev_wt:
            detected = _match_same_repo_linked_worktree(prev_wt, main_common)

    if cache_path is not None:
        try:
            _atomic_write_private(
                cache_path,
                json.dumps(
                    {
                        "inode": inode,
                        "offset": next_offset,
                        "main_common": main_common_str,
                        "exit_watermark": exit_watermark,
                        "worktree_path": str(detected[2]) if detected is not None else "",
                    }
                ),
            )
        except Exception:
            pass

    if detected is None:
        return None
    branch, wt_name, _ = detected
    return _format_linked_label(branch, wt_name, label_mode) or None


def detect_worktree_detail(
    data: dict,
    current_dir: str,
    *,
    cfg: dict | None = None,
    data_dir: Path | None = None,
) -> tuple[str, bool, bool, bool]:
    """Return (label, is_linked, is_auto_detected, is_session_override) without spawning git."""
    wt_cfg = cfg.get("worktree") if isinstance(cfg, dict) and isinstance(cfg.get("worktree"), dict) else {}
    label_mode = str(wt_cfg.get("label") or "branch").strip().lower()
    auto_detect = bool(wt_cfg.get("auto_detect_from_transcript", True))

    ws = data.get("workspace")
    explicit = extract_str(data.get("worktree"), ("branch", "name", "display_name") if label_mode != "name" else ("name", "branch", "display_name"))
    if not explicit and isinstance(ws, dict):
        explicit = extract_str(ws.get("worktree"), ("branch", "name", "display_name") if label_mode != "name" else ("name", "branch", "display_name"))
    if explicit:
        return explicit, True, False, False

    vcs = data.get("vcs") if isinstance(data.get("vcs"), dict) else {}
    vcs_branch = extract_str(vcs.get("branch"))

    if current_dir and "\x00" not in current_dir:
        info = _inspect_git_path(Path(current_dir))
        if info is not None:
            branch, wt_name, common_dir, is_linked, root = info
            if is_linked:
                return _format_linked_label(branch, wt_name, label_mode), True, False, False

            # Current directory is a main repository: check Layer 1 (worktree.json) then Layer 2 (transcript)
            if common_dir is not None:
                scratch_dir, transcript_path = _extract_session_paths(data, data_dir)
                layer1_label, exit_watermark = _load_session_worktree(
                    scratch_dir, common_dir, label_mode, transcript_path
                )
                if layer1_label:
                    return layer1_label, True, False, True
                if auto_detect:
                    layer2_label = _probe_worktree_from_transcript(
                        scratch_dir,
                        transcript_path,
                        common_dir,
                        exit_watermark,
                        label_mode,
                    )
                    if layer2_label:
                        return layer2_label, True, True, True

            if branch:
                return branch, False, False, False
            if vcs_branch:
                return vcs_branch, False, False, False
            if root is not None and common_dir is None:
                return _sanitize_single_line(root.name), False, False, False

    if vcs_branch:
        return vcs_branch, False, False, False
    return "", False, False, False


def detect_worktree(
    data: dict,
    current_dir: str,
    *,
    cfg: dict | None = None,
    data_dir: Path | None = None,
) -> tuple[str, bool]:
    """Return (worktree_or_branch_name, is_linked_worktree) without spawning git."""
    label, is_linked, _, _ = detect_worktree_detail(data, current_dir, cfg=cfg, data_dir=data_dir)
    return label, is_linked


def shorten_path(path_text: str, max_w: int, abbreviate_parents: bool = True) -> str:
    """Progressively shorten a display path while keeping the final segment recognizable."""
    if max_w <= 0:
        return ""
    if display_width(path_text) <= max_w:
        return path_text

    is_tilde = path_text.startswith("~/") or path_text == "~"
    is_abs = path_text.startswith("/")
    stripped = path_text[2:] if path_text.startswith("~/") else path_text.lstrip("/")
    parts = [p for p in stripped.split("/") if p]
    if not parts:
        return truncate_left_ellipsis(path_text, max_w)

    prefix = "~/" if is_tilde else ("/" if is_abs else "")
    if len(parts) > 1:
        if abbreviate_parents:
            abbrev_parts = [p[0] for p in parts[:-1]] + [parts[-1]]
            candidate = prefix + "/".join(abbrev_parts)
            if display_width(candidate) <= max_w:
                return candidate

        for idx in range(1, len(parts)):
            tail = "/".join(parts[idx:])
            cand = "…/" + tail
            if display_width(cand) <= max_w:
                return cand

    base = parts[-1]
    if display_width(base) <= max_w:
        return base
    return truncate_left_ellipsis(base, max_w)


def is_num(val: object) -> bool:
    """Return True if val is a finite int or float (excluding booleans)."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return False
    try:
        return math.isfinite(float(val))
    except OverflowError:
        return False


def _num_cfg(mapping: object, key: str, default: float) -> float:
    if isinstance(mapping, dict):
        val = mapping.get(key)
        if is_num(val):
            return float(val)
    return float(default)


def format_permission(data: dict, settings: dict, cfg: dict, pal: dict[str, str]) -> str:
    """Format the active permission / execution mode segment."""
    perm = ""
    for key in PERMISSION_KEYS:
        if key in data and data[key] is not None:
            perm = extract_str(data[key])
            if perm:
                break

    if not perm:
        perm = extract_str(settings.get("agentMode")) or extract_str(settings.get("toolPermission"))
    if not perm:
        sandbox = data.get("sandbox")
        if (isinstance(sandbox, dict) and sandbox.get("enabled")) or sandbox is True:
            perm = "sandbox"
        else:
            perm_cfg = cfg.get("permission") if isinstance(cfg.get("permission"), dict) else {}
            raw_fallback = perm_cfg.get("default_fallback")
            perm = _sanitize_single_line(raw_fallback) if isinstance(raw_fallback, str) and raw_fallback.strip() else "default"

    lower = perm.lower()
    if any(tok in lower for tok in ("auto", "always-proceed", "bypass")):
        color = pal["amber"]
    elif "plan" in lower or "best-of-n" in lower:
        color = pal["sky"]
    elif "accept-edits" in lower:
        color = pal["yellow"]
    else:
        color = pal["green"]
    return f"{color}{perm}{pal['reset']}"


def resolve_model_name(data: dict, settings: dict) -> str:
    """Resolve the active model display name (including effort when reported separately)."""
    raw_model = data.get("model")
    name = extract_str(raw_model, ("display_name", "name", "id"))
    if name:
        if isinstance(raw_model, dict):
            effort = extract_str(raw_model.get("effort"))
            if effort and effort.lower() not in name.lower():
                name = f"{name} ({effort})"
        return name
    fallback = extract_str(settings.get("model"))
    return fallback or "--"


def format_countdown(seconds: object) -> str:
    """Format remaining seconds into compact countdown string like 1h20m."""
    if not is_num(seconds):
        return ""
    secs = int(float(seconds))
    if secs <= 0:
        return ""
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days > 0:
        return f"{days}d{hours}h" if hours else f"{days}d"
    if hours > 0:
        return f"{hours}h{mins}m" if mins else f"{hours}h"
    return f"{max(1, mins)}m"


def format_tokens(n: int | float) -> str:
    """Format token count concisely (e.g. 109k, 45.2k, 1M)."""
    if not is_num(n):
        return "0"
    val = float(n)
    if val <= 0:
        return "0"
    if val >= 1_000_000:
        if val.is_integer():
            n_int = int(val)
            if n_int % 1_048_576 == 0:
                return f"{n_int // 1_048_576}M"
            if n_int % 1_000_000 == 0:
                return f"{n_int // 1_000_000}M"
        return f"{val / 1_000_000:.1f}M".replace(".0M", "M")
    if val >= 999_500:
        return "1M"
    if val >= 100_000:
        return f"{round(val / 1_000)}k"
    if val >= 1_000:
        return f"{val / 1_000:.1f}k".replace(".0k", "k")
    return str(int(round(val)))


def format_context_window(data: dict, cfg: dict, pal: dict[str, str]) -> str:
    """Format context window usage as used/total tokens."""
    cw = data.get("context_window")
    if not isinstance(cw, dict):
        return f"{pal['muted']}--{pal['reset']}"

    total = 0.0
    for key in ("context_window_size", "max_tokens", "limit", "window_size"):
        val = cw.get(key)
        if is_num(val) and float(val) > 0:
            total = float(val)
            break
    if total <= 0:
        return f"{pal['muted']}--{pal['reset']}"

    used: float | None = None
    for key in ("used_tokens", "current_tokens"):
        val = cw.get(key)
        if is_num(val):
            used = max(0.0, float(val))
            break

    has_used_pct = is_num(cw.get("used_percentage"))
    if used is None and isinstance(cw.get("current_usage"), dict):
        cu = cw["current_usage"]
        if is_num(cu.get("total_tokens")):
            used = max(0.0, float(cu["total_tokens"]))
        else:
            raw_in = cu.get("input_tokens")
            raw_create = cu.get("cache_creation_input_tokens")
            if not is_num(raw_create):
                raw_create = cu.get("cache_creation_tokens")
            raw_read = cu.get("cache_read_input_tokens")
            if not is_num(raw_read):
                raw_read = cu.get("cache_read_tokens")
            token_parts = [max(0.0, float(v)) for v in (raw_in, raw_create, raw_read) if is_num(v)]
            if token_parts:
                part_sum = sum(token_parts)
                # Prefer non-zero used_percentage when current_usage is zeroed out
                if part_sum > 0 or not has_used_pct or float(cw["used_percentage"]) <= 0:
                    used = part_sum

    if used is None and has_used_pct:
        used = round(total * max(0.0, float(cw["used_percentage"])) / 100.0)
    if used is None and is_num(cw.get("remaining_percentage")):
        used = round(total * max(0.0, 100.0 - float(cw["remaining_percentage"])) / 100.0)

    if used is None:
        return f"{pal['muted']}--{pal['reset']}"
    used = max(0.0, used)

    thresholds = cfg.get("thresholds")
    warn_pct = _num_cfg(thresholds, "context_warn_pct", 60.0)
    crit_pct = _num_cfg(thresholds, "context_critical_pct", 85.0)
    pct = float(cw["used_percentage"]) if has_used_pct else (used / total) * 100.0
    if pct >= crit_pct:
        color = pal["red"]
    elif pct >= warn_pct:
        color = pal["amber"]
    else:
        color = pal["teal"]
    return f"{color}{format_tokens(used)}/{format_tokens(total)}{pal['reset']}"


def extract_cache_usage(data: dict) -> tuple[int, float | None, float | None] | None:
    """Extract (hit_pct, cache_read_tokens, total_input_tokens) from latest step usage."""
    cw = data.get("context_window")
    if not isinstance(cw, dict):
        return None

    cu = cw.get("current_usage")
    if isinstance(cu, dict):
        raw_read = cu.get("cache_read_input_tokens")
        if not is_num(raw_read):
            raw_read = cu.get("cache_read_tokens")
        raw_create = cu.get("cache_creation_input_tokens")
        if not is_num(raw_create):
            raw_create = cu.get("cache_creation_tokens")
        raw_in = cu.get("input_tokens")

        if is_num(raw_read) or is_num(raw_in) or is_num(raw_create):
            read_val = max(0.0, float(raw_read)) if is_num(raw_read) else 0.0
            create_val = max(0.0, float(raw_create)) if is_num(raw_create) else 0.0
            in_val = max(0.0, float(raw_in)) if is_num(raw_in) else 0.0
            total_in = in_val + create_val + read_val
            if total_in > 0:
                pct = int(round(max(0.0, min(100.0, (read_val / total_in) * 100.0))))
                return pct, read_val, total_in

    direct_pct = cw.get("cache_hit_percentage")
    if is_num(direct_pct):
        pct = int(round(max(0.0, min(100.0, float(direct_pct)))))
        return pct, None, None

    return None


def format_cache_hit(data: dict, cfg: dict, pal: dict[str, str]) -> str:
    """Format prompt-cache hit rate for the latest model turn."""
    cache_cfg = cfg.get("cache") if isinstance(cfg.get("cache"), dict) else {}
    raw_icon = cache_cfg.get("icon", "⚡")
    icon = _sanitize_single_line(raw_icon, strip=False) if isinstance(raw_icon, str) else "⚡"
    style = str(cache_cfg.get("style") or "percent").strip().lower()
    hide_empty = bool(cache_cfg.get("hide_when_empty", False))

    usage = extract_cache_usage(data)
    if usage is None:
        if hide_empty:
            return ""
        return f"{pal['muted']}{icon}--{pal['reset']}"

    pct, read_val, _ = usage
    thresholds = cfg.get("thresholds")
    ok_pct = _num_cfg(thresholds, "cache_ok_pct", 70.0)
    warn_pct = _num_cfg(thresholds, "cache_warn_pct", 30.0)
    if pct >= ok_pct:
        color = pal["green"]
    elif pct >= warn_pct:
        color = pal["amber"]
    else:
        color = pal["muted"]

    if style == "tokens" and read_val is not None:
        body = f"{icon}{format_tokens(read_val)}"
    elif style == "both" and read_val is not None:
        body = f"{icon}{pct}%({format_tokens(read_val)})"
    else:
        body = f"{icon}{pct}%"
    return f"{color}{body}{pal['reset']}"


def extract_pct(bucket: dict) -> int | None:
    """Extract remaining percentage [0..100] from a quota bucket dict."""
    frac = bucket.get("remaining_fraction")
    if is_num(frac):
        return int(round(max(0.0, min(1.0, float(frac))) * 100))
    pct = bucket.get("remaining_percentage")
    if is_num(pct):
        return int(round(max(0.0, min(100.0, float(pct)))))
    return None


def extract_amount(bucket: dict) -> float | None:
    """Extract numeric remaining_amount from a quota bucket dict when present."""
    amt = bucket.get("remaining_amount")
    if is_num(amt):
        return float(amt)
    return None


def _is_usable_bucket(bucket: object) -> bool:
    if not isinstance(bucket, dict):
        return False
    if bucket.get("disabled") is True:
        return False
    return extract_pct(bucket) is not None or extract_amount(bucket) is not None


def bucket_label(name: str) -> str:
    """Map raw quota bucket names into concise labels."""
    clean = _sanitize_single_line(name)
    lower = clean.lower()
    if "argon" in lower:
        return "argon"
    if "5h" in lower:
        return "5h"
    if "weekly" in lower or "7d" in lower:
        return "7d"
    return clean


def bucket_sort_key(item: tuple[str, dict]) -> tuple[int, str]:
    """Sort quota buckets as 5h -> 7d -> argon -> others."""
    lower = item[0].lower()
    if "argon" in lower:
        return (2, lower)
    if "5h" in lower:
        return (0, lower)
    if "weekly" in lower or "7d" in lower:
        return (1, lower)
    return (3, lower)


def color_for_pct(pct: int, cfg: dict, pal: dict[str, str]) -> str:
    """Select status color based on remaining quota percentage."""
    thresholds = cfg.get("thresholds")
    ok_pct = _num_cfg(thresholds, "quota_ok_pct", 50.0)
    warn_pct = _num_cfg(thresholds, "quota_warn_pct", 20.0)
    if pct >= ok_pct:
        return pal["green"]
    if pct >= warn_pct:
        return pal["amber"]
    return pal["red"]


def parse_quota_buckets(quota: object) -> list[tuple[str, dict]]:
    """Normalize quota payload into a list of enabled (name, bucket_dict)."""
    buckets: list[tuple[str, dict]] = []
    if isinstance(quota, dict):
        if _is_usable_bucket(quota):
            return [("", quota)]
        for k, v in quota.items():
            if _is_usable_bucket(v):
                buckets.append((_sanitize_single_line(str(k)), v))
    elif isinstance(quota, list):
        for item in quota:
            if _is_usable_bucket(item):
                name = extract_str(item, ("name", "id", "bucket"))
                buckets.append((name, item))
    return buckets


def _format_amount_value(val: float) -> str:
    return str(int(val)) if val.is_integer() else f"{val:.2f}".rstrip("0").rstrip(".")


def format_quota_or_credits(
    data: dict,
    model_name: str,
    cfg: dict,
    pal: dict[str, str],
) -> str:
    """Format remaining quota buckets or fallback credits display."""
    quota_cfg = cfg.get("quota") if isinstance(cfg.get("quota"), dict) else {}
    filter_by_model = bool(quota_cfg.get("filter_by_model", True))
    countdown_below = _num_cfg(cfg.get("thresholds"), "quota_countdown_below_pct", 20.0)
    raw_sep = cfg.get("separator")
    sep_text = _sanitize_single_line(raw_sep, strip=False) if isinstance(raw_sep, str) else " · "

    buckets = parse_quota_buckets(data.get("quota"))
    if buckets:
        if filter_by_model and len(buckets) > 1 and model_name and model_name != "--":
            m_lower = model_name.lower()
            is_3p = any(tok in m_lower for tok in ("claude", "opus", "sonnet", "gpt", "3p"))
            target = "3p" if is_3p else "gemini"
            filtered = [(n, b) for n, b in buckets if target in n.lower()]
            if filtered:
                buckets = filtered
        buckets.sort(key=bucket_sort_key)

        pcts: list[int] = []
        amount_exhausted = False
        parts: list[str] = []
        single = len(buckets) == 1
        for name, bucket in buckets:
            pct = extract_pct(bucket)
            if pct is not None:
                pcts.append(pct)
                countdown = format_countdown(bucket.get("reset_in_seconds")) if pct <= countdown_below else ""
                cd_suffix = f"({countdown})" if countdown else ""
                if single:
                    parts.append(f"{pct}%{cd_suffix}")
                else:
                    lbl = bucket_label(name)
                    prefix = f"{lbl} " if lbl else ""
                    parts.append(f"{prefix}{pct}%{cd_suffix}")
                continue

            amt = extract_amount(bucket)
            if amt is not None:
                if amt <= 0:
                    amount_exhausted = True
                amt_str = _format_amount_value(max(0.0, amt))
                countdown = format_countdown(bucket.get("reset_in_seconds")) if amt <= 0 else ""
                cd_suffix = f"({countdown})" if countdown else ""
                lbl = bucket_label(name)
                if single and not lbl:
                    parts.append(f"{amt_str}{cd_suffix}")
                else:
                    prefix = f"{lbl} " if lbl else ""
                    parts.append(f"{prefix}{amt_str}{cd_suffix}")

        if parts:
            if amount_exhausted:
                color = pal["red"]
            elif pcts:
                color = color_for_pct(min(pcts), cfg, pal)
            else:
                color = pal["green"]
            inner_sep = f"{pal['sep']}{sep_text}{color}"
            return f"{color}{inner_sep.join(parts)}{pal['reset']}"

    for key in ("credits", "ai_credits", "g1_credits"):
        if key not in data or data[key] is None:
            continue
        val = data[key]
        if isinstance(val, dict):
            for inner_k in ("remaining", "available", "balance", "amount", "value"):
                if inner_k in val and val[inner_k] is not None:
                    val = val[inner_k]
                    break
        if is_num(val):
            num_val = float(val)
            if num_val <= 0:
                return f"{pal['red']}AI: Out of credits{pal['reset']}"
            return f"{pal['green']}AI: {_format_amount_value(num_val)}{pal['reset']}"
        if isinstance(val, str):
            s = _sanitize_single_line(val)
            if s:
                if s == "0" or "out of credits" in s.lower():
                    return f"{pal['red']}AI: Out of credits{pal['reset']}"
                return f"{pal['green']}AI: {s}{pal['reset']}"

    return f"{pal['muted']}--{pal['reset']}"


def _style_separator(raw_sep: object, pal: dict[str, str]) -> str:
    """Style a separator while keeping surrounding spaces outside ANSI escapes."""
    text = _sanitize_single_line(raw_sep, strip=False) if isinstance(raw_sep, str) else " · "
    core = text.strip(" ")
    if not core:
        return text
    lead_len = len(text) - len(text.lstrip(" "))
    trail_len = len(text) - len(text.rstrip(" "))
    lead = text[:lead_len]
    trail = text[len(text) - trail_len:] if trail_len else ""
    return f"{lead}{pal['sep']}{core}{pal['reset']}{trail}"


def _build_left(
    data: dict,
    cfg: dict,
    pal: dict[str, str],
    avail_left: int,
    data_dir: Path | None = None,
) -> str:
    """Build the responsive left-hand segment string strictly within avail_left."""
    if avail_left <= 0:
        return ""
    raw_order = cfg.get("left_segments")
    order = [str(s).strip().lower() for s in raw_order] if isinstance(raw_order, list) else ["path", "worktree"]
    show_path = "path" in order
    show_wt = "worktree" in order
    if not show_path and not show_wt:
        return ""

    raw_dir = resolve_project_dir(data)
    path_cfg = cfg.get("path") if isinstance(cfg.get("path"), dict) else {}
    wt_cfg = cfg.get("worktree") if isinstance(cfg.get("worktree"), dict) else {}

    path_display = _sanitize_single_line(
        normalize_home(raw_dir, enabled=bool(path_cfg.get("home_tilde", True)))
    )
    abbreviate_parents = bool(path_cfg.get("abbreviate_parents", True))

    wt_name = ""
    is_linked = False
    dirty_suffix = ""
    raw_icon = wt_cfg.get("icon", "⎇")
    wt_icon = _sanitize_single_line(raw_icon, strip=False) if isinstance(raw_icon, str) else "⎇"
    wt_color = pal["wt_main"]
    wt_prefix = f"{wt_icon} " if wt_icon else ""
    wt_prefix_w = display_width(wt_prefix)

    if show_wt:
        wt_name, is_linked, is_auto, is_override = detect_worktree_detail(
            data, raw_dir, cfg=cfg, data_dir=data_dir
        )
        if wt_name and is_auto:
            raw_auto_pfx = wt_cfg.get("auto_prefix", "~")
            auto_pfx = _sanitize_single_line(raw_auto_pfx, strip=False) if isinstance(raw_auto_pfx, str) else "~"
            wt_name = f"{auto_pfx}{wt_name}"
        vcs = data.get("vcs") if isinstance(data.get("vcs"), dict) else {}
        if bool(wt_cfg.get("show_dirty", True)) and not is_override and vcs.get("dirty"):
            dirty_suffix = "*"
        wt_color = pal["wt_linked"] if is_linked else pal["wt_main"]

    if show_path and not show_wt:
        if not path_display:
            return ""
        short_path = shorten_path(path_display, avail_left, abbreviate_parents=abbreviate_parents)
        return f"{pal['path']}{short_path}{pal['reset']}"

    if show_wt and not show_path:
        if not wt_name:
            return ""
        wt_full = f"{wt_prefix}{wt_name}{dirty_suffix}"
        if display_width(wt_full) <= avail_left:
            return f"{wt_color}{wt_full}{pal['reset']}"
        max_wt_w = avail_left - wt_prefix_w - len(dirty_suffix)
        if max_wt_w >= 1:
            wt_short = truncate_left_ellipsis(wt_name, max_wt_w)
            return f"{wt_color}{wt_prefix}{wt_short}{dirty_suffix}{pal['reset']}"
        return f"{wt_color}{truncate_left_ellipsis(wt_full, avail_left)}{pal['reset']}"

    # Both path and worktree enabled
    wt_segment = f" {wt_color}{wt_prefix}{wt_name}{dirty_suffix}{pal['reset']}" if wt_name else ""
    wt_w = display_width(wt_segment)

    if wt_name and avail_left - wt_w < 3:
        overhead = 1 + wt_prefix_w + len(dirty_suffix)
        if avail_left >= overhead + 3:
            max_path_w = min(max(2, avail_left // 2), avail_left - overhead - 1)
            short_path = shorten_path(path_display, max_path_w, abbreviate_parents=abbreviate_parents)
            max_wt_name_w = avail_left - display_width(short_path) - overhead
            if max_wt_name_w >= 1:
                wt_short = truncate_left_ellipsis(wt_name, max_wt_name_w)
                wt_segment = f" {wt_color}{wt_prefix}{wt_short}{dirty_suffix}{pal['reset']}"
            else:
                short_path = shorten_path(path_display, avail_left, abbreviate_parents=abbreviate_parents)
                wt_segment = ""
        else:
            short_path = shorten_path(path_display, avail_left, abbreviate_parents=abbreviate_parents)
            wt_segment = ""
    else:
        max_path_w = max(1, avail_left - wt_w)
        short_path = shorten_path(path_display, max_path_w, abbreviate_parents=abbreviate_parents)

    path_segment = f"{pal['path']}{short_path}{pal['reset']}" if short_path else ""
    if not path_segment:
        return wt_segment.lstrip()
    if order.index("worktree") < order.index("path") and wt_segment:
        return f"{wt_segment.lstrip()} {path_segment}"
    return f"{path_segment}{wt_segment}"


def _build_right(
    data: dict,
    settings: dict,
    cfg: dict,
    pal: dict[str, str],
) -> str:
    """Build the configured right-hand metadata segments."""
    raw_order = cfg.get("right_segments")
    order = (
        [str(s).strip().lower() for s in raw_order]
        if isinstance(raw_order, list)
        else ["permission", "model", "context", "cache", "quota"]
    )
    if not order:
        return ""

    model_name = resolve_model_name(data, settings)
    parts: list[str] = []
    for seg in order:
        if seg == "permission":
            parts.append(format_permission(data, settings, cfg, pal))
        elif seg == "model":
            parts.append(f"{pal['model']}{model_name}{pal['reset']}")
        elif seg == "context":
            parts.append(format_context_window(data, cfg, pal))
        elif seg == "cache":
            seg_str = format_cache_hit(data, cfg, pal)
            if seg_str:
                parts.append(seg_str)
        elif seg == "quota":
            parts.append(format_quota_or_credits(data, model_name, cfg, pal))
    if not parts:
        return ""
    sep = _style_separator(cfg.get("separator", " · "), pal)
    return sep.join(parts)


def resolve_terminal_width(data: dict) -> int:
    """Resolve positive terminal width: terminal_width -> COLUMNS -> TTY -> 100."""
    raw_width = data.get("terminal_width")
    term_width = 0
    if not isinstance(raw_width, bool) and raw_width is not None:
        if is_num(raw_width):
            term_width = int(float(raw_width))
        elif isinstance(raw_width, str) and raw_width.strip():
            try:
                term_width = int(raw_width.strip())
            except ValueError:
                term_width = 0
    if term_width <= 0:
        cols_env = os.environ.get("COLUMNS", "").strip()
        try:
            term_width = int(cols_env) if cols_env else 0
        except ValueError:
            term_width = 0
    if term_width <= 0:
        try:
            term_width = os.get_terminal_size().columns
        except OSError:
            term_width = 0
    return term_width if term_width > 0 else 100


def render(
    data: dict,
    *,
    config: dict | None = None,
    settings: dict | None = None,
    data_dir: Path | None = None,
    no_color: bool = False,
) -> str:
    """Render the full single-line status bar."""
    cfg = config if config is not None else load_config(data_dir=data_dir)
    active_settings = settings if settings is not None else load_settings(data_dir=data_dir)
    pal = build_palette(cfg, no_color=no_color)

    right = _build_right(data, active_settings, cfg, pal)
    term_width = resolve_terminal_width(data)

    layout_cfg = cfg.get("layout") if isinstance(cfg.get("layout"), dict) else {}
    right_margin = max(0, int(_num_cfg(layout_cfg, "right_margin", 2)))
    min_gap = max(1, int(_num_cfg(layout_cfg, "min_gap", 2)))
    target_width = min(term_width, max(term_width - right_margin, 20)) if term_width >= 20 else max(1, term_width)

    right_w = display_width(right)
    if right:
        # Reserve at least 1 col for left when term_width allows both sides; otherwise let left adapt cleanly
        avail_left = target_width - min_gap - right_w
        if avail_left <= 0 and term_width >= 3:
            avail_left = 1
    else:
        avail_left = target_width
    left = _build_left(data, cfg, pal, avail_left, data_dir=data_dir)

    if not left and not right:
        return ""
    if not right:
        left_w = display_width(left)
        if left_w > term_width:
            plain_left = truncate_left_ellipsis(ANSI_RE.sub("", left), term_width)
            return f"{pal['path']}{plain_left}{pal['reset']}"
        return f"{left}{pal['reset']}"
    if not left:
        if right_w > term_width:
            plain_right = truncate_left_ellipsis(ANSI_RE.sub("", right), term_width)
            return f"{pal['model']}{plain_right}{pal['reset']}"
        pad = " " * max(0, target_width - right_w)
        return f"{pad}{right}{pal['reset']}"

    left_w = display_width(left)
    if left_w + 2 > term_width:
        # Terminal too narrow to display both left + gap + right without overflowing
        plain_left = truncate_left_ellipsis(ANSI_RE.sub("", left), term_width)
        return f"{pal['path']}{plain_left}{pal['reset']}"

    if left_w + min_gap + right_w > term_width:
        eff_gap = min_gap if (term_width - left_w - min_gap) >= 1 else 1
        max_right = term_width - left_w - eff_gap
        right = truncate_left_ellipsis(ANSI_RE.sub("", right), max_right)
        right = f"{pal['model']}{right}{pal['reset']}"
        right_w = display_width(right)

    gap_len = max(min_gap, target_width - left_w - right_w)
    if left_w + gap_len + right_w > term_width:
        gap_len = max(1, term_width - left_w - right_w)
    return f"{left}{' ' * gap_len}{right}{pal['reset']}"


def _atomic_write_private(dest: Path, content: str) -> None:
    """Atomically write content to dest with mode 0600, refusing symlinks or foreign-owned targets."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        st = os.lstat(str(dest))
    except FileNotFoundError:
        st = None
    if st is not None:
        if not stat.S_ISREG(st.st_mode):
            return
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            return

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    tmp_path: Path | None = None
    fd = -1
    for _ in range(8):
        cand = dest.parent / f".{dest.name}.{os.getpid()}.{os.urandom(4).hex()}.tmp"
        try:
            fd = os.open(str(cand), flags, 0o600)
            tmp_path = cand
            break
        except FileExistsError:
            continue
    if fd < 0 or tmp_path is None:
        return

    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            fd = -1
            fp.write(content)
        os.replace(tmp_path, dest)
        tmp_path = None
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass


def write_debug_dump(raw: str) -> None:
    """Atomically write raw stdin JSON payload to a private (0600) file when enabled."""
    flag = os.environ.get("AGY_STATUSLINE_DEBUG", "").strip()
    if not flag or flag.lower() in ("0", "false", "no"):
        return
    if flag.lower() in ("1", "true", "yes"):
        dest = DEFAULT_DEBUG_DUMP_PATH
    else:
        dest = Path(flag).expanduser()
    try:
        _atomic_write_private(dest, raw)
    except Exception:
        pass


def write_quota_snapshot(data: dict, data_dir: Path | None = None, cfg: dict | None = None) -> None:
    """Atomically cache usable quota payload for downstream tools like agy-stats."""
    raw_quota = data.get("quota")
    if not parse_quota_buckets(raw_quota):
        return
    if os.environ.get("AGY_STATUSLINE_NO_SNAPSHOT", "").strip().lower() in ("1", "true", "yes"):
        return
    if cfg is not None:
        quota_cfg = cfg.get("quota")
        if isinstance(quota_cfg, dict) and quota_cfg.get("write_snapshot") is False:
            return
    d_dir = data_dir if data_dir is not None else default_data_dir()
    snap_path = d_dir / "cache" / "quota_snapshot.json"
    try:
        from datetime import datetime, timezone

        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "quota": raw_quota,
        }
        _atomic_write_private(snap_path, json.dumps(payload))
    except Exception:
        pass


def main() -> int:
    """Entry point reading JSON state from stdin and printing statusline."""
    raw = ""
    try:
        raw = sys.stdin.read()
    except Exception:
        pass

    write_debug_dump(raw)

    data: dict = {}
    if raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            data = {}

    d_dir = default_data_dir()
    cfg = load_config(data_dir=d_dir)
    write_quota_snapshot(data, data_dir=d_dir, cfg=cfg)
    print(render(data, config=cfg, data_dir=d_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
