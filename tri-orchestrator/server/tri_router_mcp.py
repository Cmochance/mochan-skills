#!/usr/bin/env python3
"""Stdlib-only concurrent MCP stdio server routing Antigravity across Hydrogen, Neon, and Carbon."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable
import uuid

SERVER_INFO = {"name": "tri-router", "version": "1.1.0"}
EMPTY_TREE_OID = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

MODELS = {
    "neon_analyze": os.environ.get("TRI_MODEL_NEON_ANALYZE", "gemini-4-neon-medium"),
    "neon_coder": os.environ.get("TRI_MODEL_NEON_CODER", "gemini-4-neon-xhigh"),
    "carbon_planner": os.environ.get("TRI_MODEL_CARBON_PLANNER", "gemini-4-carbon-high"),
    "carbon_reviewer": os.environ.get("TRI_MODEL_CARBON_REVIEWER", "gemini-4-carbon-high"),
}

PIPELINE_BUDGET_SEC = max(120, int(os.environ.get("TRI_PIPELINE_TIMEOUT_SEC", "1200")))

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "NEEDS_FIX"]},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["BLOCKER", "HIGH", "MEDIUM", "LOW"],
                    },
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "issue": {"type": "string"},
                    "fix": {"type": "string"},
                },
                "required": ["severity", "file", "issue", "fix"],
            },
        },
    },
    "required": ["verdict", "summary", "findings"],
}

SEVERITY_MAP = {
    "BLOCKER": "BLOCKER",
    "CRITICAL": "BLOCKER",
    "FATAL": "BLOCKER",
    "P0": "BLOCKER",
    "HIGH": "HIGH",
    "MAJOR": "HIGH",
    "P1": "HIGH",
    "MEDIUM": "MEDIUM",
    "MODERATE": "MEDIUM",
    "WARN": "MEDIUM",
    "WARNING": "MEDIUM",
    "P2": "MEDIUM",
    "LOW": "LOW",
    "MINOR": "LOW",
    "NIT": "LOW",
    "INFO": "LOW",
    "P3": "LOW",
}

ACTIONABLE_SEVERITIES = ("BLOCKER", "HIGH", "MEDIUM")
MAX_DIFF_CHARS = 55_000
MAX_SNAPSHOT_FILE_BYTES = 1_048_576
MAX_FS_TEXT_BYTES = 262_144
MAX_FS_FILES = 2_000

IGNORED_UNTRACKED_PARTS = frozenset(
    {
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".DS_Store",
        "node_modules",
        "target",
        ".build",
        "dist",
        "build",
        ".venv",
        "venv",
        ".next",
        ".nuxt",
        ".turbo",
        ".cache",
        "coverage",
        ".git",
    }
)
IGNORED_EXTENSIONS = (".pyc", ".pyo", ".o", ".so", ".dylib", ".a", ".class", ".wasm")

SESSION_ERR_RE = re.compile(r"conversation|session|resume|not found|invalid.*id|locked", re.IGNORECASE)
QUOTA_ERR_RE = re.compile(r"quota|rate.?limit|unauth|credit|permission|429|403", re.IGNORECASE)
MODEL_ERR_RE = re.compile(r"model|unknown.*flag|not found|unavailable", re.IGNORECASE)
UNPARSED_SEVERITY_RE = re.compile(
    r"(?:\[\s*(BLOCKER|CRITICAL|HIGH|MEDIUM)\s*\]"
    r"|\bseverity\s*[:=]\s*[\"']?(BLOCKER|CRITICAL|HIGH|MEDIUM)\b"
    r"|\bNEEDS_FIX\b)",
    re.IGNORECASE,
)

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "neon_analyze",
        "description": (
            "Delegate multi-file codebase summarization, log diagnosis, or root-cause analysis "
            "to Gemini 4 Neon (Medium, read-only)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Analysis question and scope."},
                "cwd": {"type": "string", "description": "Absolute path to the target workspace or repo."},
                "resume_session_id": {
                    "type": "string",
                    "description": "Optional previous Neon session ID to continue.",
                },
            },
            "required": ["prompt", "cwd"],
        },
    },
    {
        "name": "carbon_planner",
        "description": (
            "Delegate project planning, architecture design, and multi-file refactoring breakdown "
            "to Gemini 4 Carbon (High, read-only). Returns plan text plus plan_session_id for review continuity."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Goal, constraints, and context to plan."},
                "cwd": {"type": "string", "description": "Absolute path to the target workspace or repo."},
                "resume_session_id": {
                    "type": "string",
                    "description": "Optional previous Carbon session ID to refine.",
                },
            },
            "required": ["task", "cwd"],
        },
    },
    {
        "name": "execute_with_review",
        "description": (
            "Closed-loop coding pipeline: Gemini 4 Neon (XHigh) implements and tests -> "
            "Gemini 4 Carbon (High) performs mandatory Round-1 review -> Neon auto-fixes actionable issues -> "
            "if diff is large or R1 had BLOCKER/HIGH issues, Carbon runs mandatory Round-2 review "
            "and Neon auto-fixes before returning a full status report."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Detailed coding task or approved plan plus build/test commands.",
                },
                "cwd": {"type": "string", "description": "Absolute path to the target workspace or repo."},
                "plan_session_id": {
                    "type": "string",
                    "description": "Optional plan_session_id from carbon_planner for Round-1 review continuity.",
                },
                "large_diff_lines": {
                    "type": "integer",
                    "default": 120,
                    "description": "Changed-line threshold triggering mandatory Round-2 Carbon review.",
                },
                "large_diff_files": {
                    "type": "integer",
                    "default": 4,
                    "description": "Changed-file count threshold triggering mandatory Round-2 Carbon review.",
                },
            },
            "required": ["task", "cwd"],
        },
    },
    {
        "name": "carbon_reviewer",
        "description": "Standalone read-only code review by Gemini 4 Carbon (High) against focused git diffs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Absolute path to the target git repo."},
                "focus": {
                    "type": "string",
                    "description": "Optional extra review focus (e.g., security, concurrency, specific PR).",
                },
                "base_ref": {
                    "type": "string",
                    "default": "HEAD",
                    "description": "Git ref to diff against (defaults to HEAD).",
                },
                "resume_session_id": {
                    "type": "string",
                    "description": "Optional Carbon session ID to resume.",
                },
            },
            "required": ["cwd"],
        },
    },
    {
        "name": "neon_coder",
        "description": (
            "Single-pass coding by Gemini 4 Neon (XHigh) without Carbon review. Use ONLY when the user "
            "explicitly asks to skip code review or make a tiny follow-up tweak to a known neon_session_id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Implementation task and test command."},
                "cwd": {"type": "string", "description": "Absolute path to the target workspace or repo."},
                "resume_session_id": {
                    "type": "string",
                    "description": "Optional Neon session ID to resume.",
                },
            },
            "required": ["task", "cwd"],
        },
    },
]


def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False)
    return str(val)


def is_child_session() -> bool:
    return os.environ.get("TRI_ORCHESTRATOR_CHILD") == "1"


def resolve_agy_binary() -> str:
    extra_paths = [
        os.environ.get("PATH", ""),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        str(Path.home() / ".local" / "bin"),
    ]
    found = shutil.which("agy", path=os.pathsep.join(p for p in extra_paths if p))
    if not found:
        raise FileNotFoundError("Could not find 'agy' binary in PATH or standard Homebrew/local paths.")
    return found


def validate_cwd(cwd: Any) -> Path:
    if not isinstance(cwd, str) or not cwd.strip():
        raise ValueError("cwd must be a non-empty directory path string.")
    path = Path(cwd).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"cwd does not exist or is not a directory: {cwd}")
    return path


def _ensure_private_tmp_dir() -> Path:
    uid = os.getuid() if hasattr(os, "getuid") else 0
    tmp_dir = Path(f"/tmp/tri-orch-{uid}")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(tmp_dir, 0o700)
    st = tmp_dir.stat()
    if hasattr(os, "getuid") and st.st_uid != uid:
        raise PermissionError(f"Unsafe ownership on temp dir {tmp_dir}")
    return tmp_dir


def _stage_prompt_file(prompt_text: str) -> tuple[Path, Path]:
    tmp_dir = _ensure_private_tmp_dir()
    prompt_path = tmp_dir / f"prompt-{uuid.uuid4().hex}.md"
    clean = _safe_str(prompt_text).replace("\x00", "")
    fd = os.open(str(prompt_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(clean)
    except Exception:
        try:
            prompt_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return tmp_dir, prompt_path


def _kill_pgid(pgid: int) -> None:
    if pgid <= 0:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except (ProcessLookupError, PermissionError, OSError):
            return
        time.sleep(0.1)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


class CancelContext:
    """Tracks active child process groups and reports progress/cancellation."""

    def __init__(
        self,
        req_id: Any = None,
        progress_token: Any = None,
        send_fn: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.req_id = req_id
        self.progress_token = progress_token
        self.send_fn = send_fn
        self.cancelled = threading.Event()
        self._lock = threading.Lock()
        self._pgids: set[int] = set()

    def register_pgid(self, pgid: int) -> None:
        with self._lock:
            self._pgids.add(pgid)
        if self.cancelled.is_set():
            _kill_pgid(pgid)

    def unregister_pgid(self, pgid: int) -> None:
        with self._lock:
            self._pgids.discard(pgid)

    def cancel(self) -> None:
        self.cancelled.set()
        with self._lock:
            pgids = list(self._pgids)
        for pgid in pgids:
            _kill_pgid(pgid)

    def emit_progress(self, progress: int, total: int, message: str) -> None:
        sys.stderr.write(f"[tri-router] ({progress}/{total}) {message}\n")
        sys.stderr.flush()
        if self.progress_token is not None and self.send_fn is not None:
            try:
                self.send_fn(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/progress",
                        "params": {
                            "progressToken": self.progress_token,
                            "progress": progress,
                            "total": total,
                            "message": message,
                        },
                    }
                )
            except Exception:
                pass


def parse_agy_stdout(stdout: str) -> dict[str, Any] | None:
    """Extract the JSON summary object emitted by `agy --output-format json`."""
    text = _safe_str(stdout).strip()
    if text.startswith("{"):
        try:
            obj = json.loads(text)
            if isinstance(obj, dict) and (
                ("status" in obj and ("response" in obj or "error" in obj))
                or "conversation_id" in obj
                or "response" in obj
            ):
                return obj
        except json.JSONDecodeError:
            pass

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and (
            ("status" in obj and ("response" in obj or "error" in obj))
            or "conversation_id" in obj
        ):
            return obj
    return None


def _drain_stream(stream: Any, bucket: list[str]) -> None:
    try:
        for chunk in iter(lambda: stream.read(4096), ""):
            bucket.append(chunk)
    except Exception:
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


INLINE_PROMPT_MAX_BYTES = 32_768
CHILD_SETTINGS_JSON = '{"orchestrator":{"planner":""}}'


def run_agy(
    model_slug: str,
    prompt: str,
    cwd: Path,
    access_mode: str,
    timeout_sec: int,
    resume_id: str | None = None,
    fallback_prompt: str | None = None,
    json_schema: dict[str, Any] | None = None,
    cancel_ctx: CancelContext | None = None,
    inline_prefix: str | None = None,
) -> dict[str, Any]:
    """Invoke `agy` in non-interactive print mode with tiered prompt delivery & pgid cleanup."""
    agy_bin = resolve_agy_binary()
    ctx = cancel_ctx or CancelContext()

    def _exec(active_prompt: str, active_resume: str | None) -> dict[str, Any]:
        if ctx.cancelled.is_set():
            return {"ok": False, "model": model_slug, "cancelled": True, "error": "Cancelled before start."}

        clean_prompt = _safe_str(active_prompt).replace("\x00", "")
        prompt_file: Path | None = None
        extra_add_dirs: list[str] = []

        if len(clean_prompt.encode("utf-8")) <= INLINE_PROMPT_MAX_BYTES:
            prompt_arg = clean_prompt
        else:
            try:
                tmp_dir, prompt_file = _stage_prompt_file(clean_prompt)
            except OSError as exc:
                return {"ok": False, "model": model_slug, "error": f"Failed to stage prompt file: {exc}"}
            extra_add_dirs.extend(["--add-dir", str(tmp_dir)])
            prefix = _safe_str(inline_prefix).replace("\x00", "")[:8000]
            prompt_arg = (
                (f"{prefix}\n\n" if prefix else "")
                + f"Full diff/context is saved at {prompt_file}. Inspect it with `read_file` "
                "(use StartLine/EndLine if large) or read changed source files directly, then execute without mentioning the temporary file."
            )
            if json_schema is not None:
                prompt_arg += " Your final response MUST be raw valid JSON matching the required schema."

        cmd = [
            agy_bin,
            "--model",
            model_slug,
            "--mode",
            "auto",
            "--disable-slash-commands",
            "--settings",
            CHILD_SETTINGS_JSON,
            "--add-dir",
            str(cwd),
            *extra_add_dirs,
            "--output-format",
            "json",
            "--print-timeout",
            f"{timeout_sec}s",
        ]
        if json_schema is not None:
            cmd.extend(["--json-schema", json.dumps(json_schema, ensure_ascii=False)])
        if active_resume:
            cmd.extend(["-r", active_resume])
        cmd.extend(["-p", prompt_arg])

        env = os.environ.copy()
        env["TRI_ORCHESTRATOR_CHILD"] = "1"
        env["TRI_ORCHESTRATOR_ACCESS"] = access_mode
        env["GIT_OPTIONAL_LOCKS"] = "0"

        proc: subprocess.Popen[str] | None = None
        pgid = 0
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        timed_out = False
        was_cancelled = False
        started = time.monotonic()

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            pgid = proc.pid
            ctx.register_pgid(pgid)

            t_out = threading.Thread(target=_drain_stream, args=(proc.stdout, stdout_chunks), daemon=True)
            t_err = threading.Thread(target=_drain_stream, args=(proc.stderr, stderr_chunks), daemon=True)
            t_out.start()
            t_err.start()

            deadline = started + timeout_sec + 30
            last_beat = started
            while proc.poll() is None:
                if ctx.cancelled.is_set():
                    was_cancelled = True
                    _kill_pgid(pgid)
                    break
                now = time.monotonic()
                if now >= deadline:
                    timed_out = True
                    _kill_pgid(pgid)
                    break
                if now - last_beat >= 25.0:
                    last_beat = now
                    sys.stderr.write(f"[tri-router] {model_slug} running ({int(now - started)}s)...\n")
                    sys.stderr.flush()
                time.sleep(0.25)

            t_out.join(timeout=2.0)
            t_err.join(timeout=2.0)
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                _kill_pgid(pgid)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return {
                "ok": False,
                "model": model_slug,
                "duration_seconds": round(time.monotonic() - started, 2),
                "error": f"Failed to launch agy: {exc}",
            }
        finally:
            if pgid:
                ctx.unregister_pgid(pgid)
            if prompt_file is not None:
                try:
                    prompt_file.unlink(missing_ok=True)
                except OSError:
                    pass

        elapsed = round(time.monotonic() - started, 2)
        stdout_text = "".join(stdout_chunks)
        stderr_text = "".join(stderr_chunks)

        if was_cancelled:
            return {
                "ok": False,
                "model": model_slug,
                "cancelled": True,
                "duration_seconds": elapsed,
                "error": "Cancelled by client request.",
            }
        if timed_out:
            return {
                "ok": False,
                "model": model_slug,
                "timed_out": True,
                "duration_seconds": elapsed,
                "error": f"Timed out after {timeout_sec + 30}s.",
            }

        parsed = parse_agy_stdout(stdout_text)
        is_success = (
            proc is not None
            and proc.returncode == 0
            and parsed is not None
            and (
                parsed.get("status") == "SUCCESS"
                or ("status" not in parsed and "response" in parsed and not parsed.get("error"))
            )
        )
        if is_success and parsed is not None:
            return {
                "ok": True,
                "model": model_slug,
                "conversation_id": _safe_str(parsed.get("conversation_id")),
                "response": _safe_str(parsed.get("response")),
                "duration_seconds": parsed.get("duration_seconds") if isinstance(parsed.get("duration_seconds"), (int, float)) else elapsed,
                "usage": parsed.get("usage") if isinstance(parsed.get("usage"), dict) else {},
            }

        err_msg = ""
        if parsed and parsed.get("error"):
            err_msg = _safe_str(parsed["error"])
        elif stderr_text.strip():
            err_msg = stderr_text.strip()
        elif stdout_text.strip():
            err_msg = stdout_text.strip()[-1500:]
        else:
            rc = proc.returncode if proc is not None else -1
            err_msg = f"agy exited with status {rc}"

        if MODEL_ERR_RE.search(err_msg):
            err_msg += " (Hint: run 'agy models' or override via TRI_MODEL_* env vars.)"

        return {
            "ok": False,
            "model": model_slug,
            "error": err_msg,
            "conversation_id": _safe_str((parsed or {}).get("conversation_id")),
            "duration_seconds": (parsed or {}).get("duration_seconds") if isinstance((parsed or {}).get("duration_seconds"), (int, float)) else elapsed,
            "usage": (parsed or {}).get("usage") if isinstance((parsed or {}).get("usage"), dict) else {},
        }

    result = _exec(prompt, resume_id)
    err_text = _safe_str(result.get("error"))
    if (
        not result["ok"]
        and resume_id
        and not result.get("cancelled")
        and not result.get("timed_out")
        and not QUOTA_ERR_RE.search(err_text)
        and not MODEL_ERR_RE.search(err_text)
        and (
            (result.get("duration_seconds") or 0) < 15
            and bool(SESSION_ERR_RE.search(err_text))
        )
    ):
        prior_dur = result.get("duration_seconds") or 0
        prior_tok = (result.get("usage") or {}).get("total_tokens") or 0
        retried = _exec(fallback_prompt or prompt, None)
        retried["resume_fallback"] = True
        if isinstance(retried.get("duration_seconds"), (int, float)):
            retried["duration_seconds"] = round(float(retried["duration_seconds"]) + float(prior_dur), 2)
        if prior_tok:
            usage = dict(retried.get("usage") or {})
            usage["total_tokens"] = int(usage.get("total_tokens") or 0) + int(prior_tok)
            retried["usage"] = usage
        return retried
    return result


def _run_git(
    cwd: Path,
    args: list[str],
    extra_env: dict[str, str] | None = None,
    timeout: int = 20,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    if extra_env:
        env.update(extra_env)
    try:
        return subprocess.run(
            ["git", "-C", str(cwd), "-c", "core.quotePath=false", "--no-pager", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return subprocess.CompletedProcess(args, 128, "", _safe_str(exc))


def _is_ignored_untracked(rel: str) -> bool:
    parts = Path(rel).parts
    if any(part in IGNORED_UNTRACKED_PARTS for part in parts):
        return True
    return rel.endswith(IGNORED_EXTENSIONS)


def _probe_file(path: Path) -> tuple[int, bool, bool, str]:
    """Return (size_bytes, is_binary, large_omitted, preview_or_full_text) safely."""
    try:
        st = path.stat()
    except OSError:
        return 0, False, False, ""

    size = int(st.st_size)
    if size > MAX_SNAPSHOT_FILE_BYTES:
        try:
            with path.open("rb") as fh:
                head = fh.read(8192)
            return size, (b"\x00" in head), True, ""
        except OSError:
            return size, False, True, ""

    try:
        raw = path.read_bytes()
    except OSError:
        return size, False, False, ""

    if b"\x00" in raw[:8192]:
        return size, True, False, ""
    if size <= MAX_FS_TEXT_BYTES:
        return size, False, False, raw.decode("utf-8", errors="replace").replace("\x00", "")
    return size, False, True, ""


def _resolve_git_context(cwd: Path) -> tuple[Path | None, str]:
    top = _run_git(cwd, ["rev-parse", "--show-toplevel"])
    if top.returncode != 0 or not top.stdout.strip():
        return None, "."
    git_root = Path(top.stdout.strip()).resolve()
    try:
        rel = cwd.resolve().relative_to(git_root).as_posix()
        rel_scope = "." if not rel or rel == "." else rel
    except ValueError:
        rel_scope = "."
    return git_root, rel_scope


def _capture_git_tree(
    git_root: Path,
    rel_scope: str,
    obj_dir: Path | None = None,
) -> tuple[str | None, list[str]]:
    """Capture an immutable tree OID without mutating repo index or .git/objects."""
    idx_proc = _run_git(git_root, ["rev-parse", "--git-path", "index"])
    obj_proc = _run_git(git_root, ["rev-parse", "--git-path", "objects"])
    if idx_proc.returncode != 0 or not idx_proc.stdout.strip():
        return None, []
    real_idx = Path(idx_proc.stdout.strip())
    if not real_idx.is_absolute():
        real_idx = (git_root / real_idx).resolve()

    real_obj: Path | None = None
    if obj_proc.returncode == 0 and obj_proc.stdout.strip():
        real_obj = Path(obj_proc.stdout.strip())
        if not real_obj.is_absolute():
            real_obj = (git_root / real_obj).resolve()

    tmp_dir = _ensure_private_tmp_dir()
    tmp_idx = tmp_dir / f"idx-{uuid.uuid4().hex}"
    omitted_large: list[str] = []

    try:
        if real_idx.is_file():
            shutil.copyfile(real_idx, tmp_idx)
        idx_env: dict[str, str] = {"GIT_INDEX_FILE": str(tmp_idx)}
        if obj_dir is not None and real_obj is not None:
            obj_dir.mkdir(parents=True, exist_ok=True)
            idx_env["GIT_OBJECT_DIRECTORY"] = str(obj_dir)
            idx_env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = str(real_obj)

        # Update tracked modifications/deletions in the scope.
        _run_git(git_root, ["add", "-u", "--", rel_scope], extra_env=idx_env)

        # Stage untracked non-ignored files within rel_scope (NUL-delimited for safety).
        ls_proc = _run_git(
            git_root,
            ["ls-files", "-z", "--others", "--exclude-standard", "--", rel_scope],
        )
        to_stage: list[str] = []
        if ls_proc.returncode == 0 and ls_proc.stdout:
            for rel in ls_proc.stdout.split("\x00"):
                if not rel or _is_ignored_untracked(rel):
                    continue
                full_p = git_root / rel
                if full_p.is_symlink() or not full_p.is_file():
                    continue
                try:
                    if full_p.stat().st_size > MAX_SNAPSHOT_FILE_BYTES:
                        disp_rel = (
                            Path(rel).relative_to(rel_scope).as_posix()
                            if rel_scope != "."
                            else rel
                        )
                        omitted_large.append(disp_rel)
                        continue
                except OSError:
                    continue
                to_stage.append(rel)

        for i in range(0, len(to_stage), 200):
            batch = to_stage[i : i + 200]
            _run_git(git_root, ["add", "-f", "--", *batch], extra_env=idx_env)

        wt = _run_git(git_root, ["write-tree"], extra_env=idx_env)
        if wt.returncode != 0 or not wt.stdout.strip():
            return None, omitted_large
        return wt.stdout.strip(), omitted_large
    finally:
        try:
            tmp_idx.unlink(missing_ok=True)
        except OSError:
            pass


def _snapshot_fs_files(
    cwd: Path,
    prev_files: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    count = 0
    for root, dirs, filenames in os.walk(cwd, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_UNTRACKED_PARTS and not (Path(root) / d).is_symlink())
        for fname in sorted(filenames):
            if fname.endswith(IGNORED_EXTENSIONS) or fname in IGNORED_UNTRACKED_PARTS:
                continue
            full_p = Path(root) / fname
            if full_p.is_symlink() or not full_p.is_file():
                continue
            rel = full_p.relative_to(cwd).as_posix()
            if _is_ignored_untracked(rel):
                continue

            try:
                st = full_p.stat()
            except OSError:
                continue
            size = int(st.st_size)
            mtime_ns = int(st.st_mtime_ns)

            # Fast O(1) metadata hit: skip reading/hashing unchanged files.
            if prev_files is not None:
                prev = prev_files.get(rel)
                if prev and prev.get("size") == size and prev.get("mtime_ns") == mtime_ns:
                    files[rel] = prev
                    count += 1
                    if count >= MAX_FS_FILES:
                        return files
                    continue

            if size > MAX_SNAPSHOT_FILE_BYTES:
                try:
                    with full_p.open("rb") as fh:
                        is_bin = b"\x00" in fh.read(8192)
                except OSError:
                    is_bin = False
                files[rel] = {
                    "size": size,
                    "mtime_ns": mtime_ns,
                    "sha256": f"stat:{size}:{mtime_ns}",
                    "is_bin": is_bin,
                    "large_omitted": True,
                    "text": "",
                }
            else:
                try:
                    raw = full_p.read_bytes()
                except OSError:
                    continue
                is_bin = b"\x00" in raw[:8192]
                large_omitted = (not is_bin) and (size > MAX_FS_TEXT_BYTES)
                text = "" if (is_bin or large_omitted) else raw.decode("utf-8", errors="replace").replace("\x00", "")
                files[rel] = {
                    "size": size,
                    "mtime_ns": mtime_ns,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "is_bin": is_bin,
                    "large_omitted": large_omitted,
                    "text": text,
                }

            count += 1
            if count >= MAX_FS_FILES:
                return files
    return files


def snapshot_baseline(cwd: Path, obj_dir: Path | None = None) -> dict[str, Any]:
    git_root, rel_scope = _resolve_git_context(cwd)
    if git_root is not None:
        tree_oid, omitted = _capture_git_tree(git_root, rel_scope, obj_dir=obj_dir)
        if tree_oid:
            return {
                "mode": "git",
                "git_root": str(git_root),
                "rel_scope": rel_scope,
                "tree_oid": tree_oid,
                "omitted_large": omitted,
            }
    return {"mode": "fs", "files": _snapshot_fs_files(cwd)}


def _sanitize_base_ref(base_ref: str) -> str:
    ref = _safe_str(base_ref).strip()
    if not ref or ref.startswith("-") or any(ch.isspace() or ord(ch) < 32 for ch in ref):
        raise ValueError(f"Invalid git base_ref: {base_ref!r}")
    return ref


def collect_diff_context(
    cwd: Path,
    base_ref: str = "HEAD",
    baseline: dict[str, Any] | None = None,
    obj_dir: Path | None = None,
) -> dict[str, Any]:
    """Collect baseline-isolated or ref-based focused diff slice and accurate magnitude."""
    git_root, rel_scope = _resolve_git_context(cwd)

    if git_root is not None and (baseline is None or baseline.get("mode") == "git"):
        if baseline and baseline.get("tree_oid"):
            base_tree = str(baseline["tree_oid"])
            base_omitted = set(baseline.get("omitted_large") or [])
        else:
            ref = _sanitize_base_ref(base_ref)
            ver = _run_git(
                git_root,
                ["rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}"],
            )
            if ver.returncode == 0 and ver.stdout.strip():
                base_tree = ver.stdout.strip()
            elif ref == "HEAD":
                base_tree = EMPTY_TREE_OID
            else:
                raise ValueError(f"Unknown or invalid git base_ref: {ref!r}")
            base_omitted = set()

        cur_tree, cur_omitted = _capture_git_tree(git_root, rel_scope, obj_dir=obj_dir)
        if not cur_tree:
            return {
                "in_git": True,
                "changed_files": 0,
                "changed_lines": 0,
                "file_list": [],
                "status_text": "(Failed to capture git tree)",
                "diff_text": "",
                "diff_truncated": False,
            }

        rel_flag = [f"--relative={rel_scope}"] if rel_scope != "." else ["--relative"]
        diff_env: dict[str, str] | None = None
        if obj_dir is not None:
            diff_env = {"GIT_ALTERNATE_OBJECT_DIRECTORIES": str(obj_dir)}

        ns_proc = _run_git(cwd, ["diff", *rel_flag, "--name-status", base_tree, cur_tree, "--", "."], extra_env=diff_env)
        num_proc = _run_git(cwd, ["diff", *rel_flag, "--numstat", base_tree, cur_tree, "--", "."], extra_env=diff_env)
        diff_proc = _run_git(cwd, ["diff", *rel_flag, base_tree, cur_tree, "--", "."], extra_env=diff_env)

        changed_files_set: set[str] = set()
        status_lines: list[str] = []
        for line in ns_proc.stdout.splitlines():
            if not line.strip():
                continue
            status_lines.append(line)
            parts = line.split("\t")
            if parts:
                changed_files_set.add(parts[-1])

        new_large = [p for p in cur_omitted if p not in base_omitted]
        for p in new_large:
            changed_files_set.add(p)
            status_lines.append(f"A\t{p} (>1MB omitted)")

        changed_lines = 0
        for line in num_proc.stdout.splitlines():
            parts = line.split("\t", 2)
            if len(parts) != 3:
                continue
            ins_raw, del_raw, _ = parts
            if ins_raw.isdigit():
                changed_lines += int(ins_raw)
            if del_raw.isdigit():
                changed_lines += int(del_raw)

        diff_raw = diff_proc.stdout
        diff_truncated = False
        if len(diff_raw) > MAX_DIFF_CHARS:
            diff_raw = diff_raw[:MAX_DIFF_CHARS] + (
                "\n\n... [diff truncated at 55,000 chars; use read_file on specific changed files if needed] ..."
            )
            diff_truncated = True

        return {
            "in_git": True,
            "changed_files": len(changed_files_set),
            "changed_lines": changed_lines,
            "file_list": sorted(changed_files_set),
            "status_text": "\n".join(status_lines) if status_lines else "(no changes)",
            "diff_text": diff_raw.strip(),
            "diff_truncated": diff_truncated,
        }

    # Non-git workspace snapshot diff
    prev_files = baseline.get("files") if (baseline and baseline.get("mode") == "fs") else None
    cur_files = _snapshot_fs_files(cwd, prev_files=prev_files)
    if baseline and baseline.get("mode") == "fs":
        pre_files: dict[str, dict[str, Any]] = baseline.get("files") or {}
        all_paths = sorted(set(pre_files.keys()) | set(cur_files.keys()))
        changed_files_list: list[str] = []
        status_lines_fs: list[str] = []
        diff_chunks: list[str] = []
        changed_lines = 0

        for rel in all_paths:
            old = pre_files.get(rel)
            new = cur_files.get(rel)
            if old and new and old.get("sha256") == new.get("sha256"):
                continue
            changed_files_list.append(rel)
            if old is None:
                status_lines_fs.append(f"A\t{rel}")
            elif new is None:
                status_lines_fs.append(f"D\t{rel}")
            else:
                status_lines_fs.append(f"M\t{rel}")

            if (old and (old.get("is_bin") or old.get("large_omitted"))) or (
                new and (new.get("is_bin") or new.get("large_omitted"))
            ):
                diff_chunks.append(f"--- {rel} (binary or >256KB file modified)")
                continue

            old_lines = (old.get("text") if old else "").splitlines(keepends=True)
            new_lines = (new.get("text") if new else "").splitlines(keepends=True)
            udiff = list(
                difflib.unified_diff(
                    old_lines,
                    new_lines,
                    fromfile=f"a/{rel}",
                    tofile=f"b/{rel}",
                )
            )
            for dl in udiff:
                if dl.startswith(("+", "-")) and not dl.startswith(("+++", "---")):
                    changed_lines += 1
            diff_chunks.append("".join(udiff))

        diff_raw = "\n".join(c for c in diff_chunks if c).strip()
        diff_truncated = False
        if len(diff_raw) > MAX_DIFF_CHARS:
            diff_raw = diff_raw[:MAX_DIFF_CHARS] + "\n\n... [diff truncated at 55,000 chars] ..."
            diff_truncated = True

        return {
            "in_git": False,
            "changed_files": len(changed_files_list),
            "changed_lines": changed_lines,
            "file_list": changed_files_list,
            "status_text": "\n".join(status_lines_fs) if status_lines_fs else "(no changes in non-git workspace)",
            "diff_text": diff_raw,
            "diff_truncated": diff_truncated,
        }

    file_list = sorted(cur_files.keys())[:50]
    return {
        "in_git": False,
        "changed_files": len(cur_files),
        "changed_lines": 0,
        "file_list": file_list,
        "status_text": "Non-git workspace files:\n" + "\n".join(file_list),
        "diff_text": "",
        "diff_truncated": False,
    }


def _normalize_finding(raw: dict[str, Any]) -> dict[str, Any]:
    raw_sev = _safe_str(raw.get("severity") or "MEDIUM").strip().upper()
    sev = SEVERITY_MAP.get(raw_sev, "MEDIUM")
    line_val = raw.get("line")
    try:
        line_num = int(line_val) if line_val is not None else 0
    except (TypeError, ValueError):
        line_num = 0
    return {
        "severity": sev,
        "file": _safe_str(raw.get("file") or "?").strip() or "?",
        "line": line_num,
        "issue": _safe_str(raw.get("issue")).strip(),
        "fix": _safe_str(raw.get("fix")).strip(),
    }


def extract_review_json(raw_text: str) -> dict[str, Any]:
    """Parse structured review JSON from Carbon's response without silent NEEDS_FIX drops."""
    cleaned = _safe_str(raw_text).strip()
    decoder = json.JSONDecoder()
    best_obj: dict[str, Any] | None = None

    for idx, ch in enumerate(cleaned):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(cleaned, idx)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if isinstance(obj.get("findings"), list) and "verdict" in obj:
            best_obj = obj
            break
        if isinstance(obj.get("findings"), list) or isinstance(obj.get("verdict"), str):
            best_obj = obj

    if best_obj is not None:
        raw_findings = best_obj.get("findings") if isinstance(best_obj.get("findings"), list) else []
        findings = [_normalize_finding(item) for item in raw_findings if isinstance(item, dict)]
        summary = _safe_str(best_obj.get("summary")).strip()
        raw_verdict = _safe_str(best_obj.get("verdict")).strip().upper()
        actionable = [f for f in findings if f["severity"] in ACTIONABLE_SEVERITIES]

        if actionable:
            verdict = "NEEDS_FIX"
        elif raw_verdict == "NEEDS_FIX":
            verdict = "NEEDS_FIX"
            if not findings:
                findings.append(
                    {
                        "severity": "HIGH",
                        "file": "(review-summary)",
                        "line": 0,
                        "issue": summary or "Reviewer returned NEEDS_FIX without itemized findings.",
                        "fix": "Resolve the issue described in the review summary and re-run verification.",
                    }
                )
        else:
            verdict = "PASS"

        return {
            "verdict": verdict,
            "summary": summary,
            "findings": findings,
            "parsed": True,
        }

    # Unparsed free-text fallback: never silently pass if structured defect markers appear.
    has_defect_marker = bool(UNPARSED_SEVERITY_RE.search(cleaned))
    if has_defect_marker:
        return {
            "verdict": "NEEDS_FIX",
            "summary": cleaned,
            "findings": [
                {
                    "severity": "HIGH",
                    "file": "(unparsed-review)",
                    "line": 0,
                    "issue": "Carbon review returned non-JSON defect report:\n" + cleaned[:2000],
                    "fix": "Address every issue described in the review output above and verify tests.",
                }
            ],
            "parsed": False,
        }

    return {
        "verdict": "PASS",
        "summary": cleaned,
        "findings": [],
        "parsed": False,
    }


def get_actionable_findings(review: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in review.get("findings", [])
        if isinstance(item, dict) and _safe_str(item.get("severity")).upper() in ACTIONABLE_SEVERITIES
    ]


def format_findings_markdown(review: dict[str, Any]) -> str:
    lines: list[str] = []
    summary = _safe_str(review.get("summary")).strip()
    if summary:
        lines.append(summary)
    findings = review.get("findings") or []
    if not findings:
        if not review.get("parsed"):
            return summary or "(Empty review)"
        lines.append("- No issues found.")
        return "\n".join(lines)

    for idx, f in enumerate(findings, 1):
        sev = _safe_str(f.get("severity") or "MEDIUM").upper()
        fpath = _safe_str(f.get("file") or "?")
        line = f.get("line")
        loc = f"{fpath}:{line}" if line else fpath
        issue = _safe_str(f.get("issue")).strip()
        fix = _safe_str(f.get("fix")).strip()
        lines.append(f"{idx}. **[{sev}] `{loc}`** — {issue}\n   - **Fix:** {fix}")
    return "\n".join(lines)


def fmt_telemetry_row(label: str, res: dict[str, Any]) -> str:
    dur = res.get("duration_seconds")
    dur_s = f"{dur:.1f}s" if isinstance(dur, (int, float)) else "-"
    usage = res.get("usage") or {}
    tok = usage.get("total_tokens")
    tok_s = f"{tok:,}" if isinstance(tok, int) else "-"
    cid = _safe_str(res.get("conversation_id")) or "-"
    status = "OK" if res.get("ok") else "ERR"
    if res.get("resume_fallback"):
        status += " (fresh)"
    return f"| {label} | `{res.get('model', '-')}` | {status} | {dur_s} | {tok_s} | `{cid}` |"


def build_review_prompt(diff_ctx: dict[str, Any], header_note: str) -> str:
    parts = [
        header_note,
        "CRITICAL: You are in READ-ONLY review mode. Do NOT edit or create files. If you need surrounding context, issue all `read_file` calls in parallel in a single turn.",
        "Focus on real bugs, logic regressions, contract mismatches, concurrency/state invariants, silent error swallowing, missing edge cases, and security flaws. Label minor style nits as LOW.",
        "Return ONLY valid JSON matching the required schema: {verdict: 'PASS'|'NEEDS_FIX', summary: string, findings: [{severity: 'BLOCKER'|'HIGH'|'MEDIUM'|'LOW', file: string, line: int, issue: string, fix: string}]}. Set verdict='NEEDS_FIX' whenever any BLOCKER/HIGH/MEDIUM finding exists.",
        f"## Changed Files Summary\n```\n{diff_ctx['status_text']}\n```",
    ]
    if diff_ctx.get("diff_text"):
        parts.append(f"## Unified Diff\n```diff\n{diff_ctx['diff_text']}\n```")
    else:
        parts.append("No code diff was detected; inspect the target workspace files mentioned in context.")
    return "\n\n".join(parts)


def run_carbon_review_with_retry(
    prompt: str,
    cwd: Path,
    timeout_sec: int,
    resume_id: str | None = None,
    fallback_prompt: str | None = None,
    cancel_ctx: CancelContext | None = None,
    inline_prefix: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    res = run_agy(
        model_slug=MODELS["carbon_reviewer"],
        prompt=prompt,
        cwd=cwd,
        access_mode="readonly",
        timeout_sec=timeout_sec,
        resume_id=resume_id,
        fallback_prompt=fallback_prompt,
        json_schema=REVIEW_SCHEMA,
        cancel_ctx=cancel_ctx,
        inline_prefix=inline_prefix,
    )
    if not res["ok"]:
        return res, {"verdict": "NEEDS_FIX", "summary": "", "findings": [], "parsed": False}

    review = extract_review_json(res["response"])
    if not review["parsed"] and not (cancel_ctx and cancel_ctx.cancelled.is_set()):
        reformat_prompt = (
            "Your previous review output was not valid JSON. Convert your exact review findings into raw JSON ONLY "
            "(no markdown commentary outside JSON) matching: "
            "{verdict: 'PASS'|'NEEDS_FIX', summary: string, findings: [{severity: 'BLOCKER'|'HIGH'|'MEDIUM'|'LOW', file: string, line: int, issue: string, fix: string}]}.\n\n"
            f"Previous review output:\n{res['response'][:8000]}"
        )
        r_retry = run_agy(
            model_slug=MODELS["carbon_reviewer"],
            prompt=reformat_prompt,
            cwd=cwd,
            access_mode="readonly",
            timeout_sec=min(120, timeout_sec),
            resume_id=res.get("conversation_id") or None,
            fallback_prompt=reformat_prompt,
            json_schema=REVIEW_SCHEMA,
            cancel_ctx=cancel_ctx,
        )
        if r_retry["ok"]:
            parsed_retry = extract_review_json(r_retry["response"])
            if parsed_retry["parsed"]:
                res["response"] = r_retry["response"]
                if isinstance(res.get("duration_seconds"), (int, float)) and isinstance(r_retry.get("duration_seconds"), (int, float)):
                    res["duration_seconds"] = round(res["duration_seconds"] + r_retry["duration_seconds"], 2)
                retry_tok = (r_retry.get("usage") or {}).get("total_tokens")
                if isinstance(retry_tok, int) and retry_tok > 0:
                    usage = dict(res.get("usage") or {})
                    usage["total_tokens"] = int(usage.get("total_tokens") or 0) + retry_tok
                    res["usage"] = usage
                return res, parsed_retry

    return res, review


def _build_failure_report(
    stage_title: str,
    error_msg: str,
    telemetry_rows: list[str],
    plan_session_id: str | None = None,
    neon_session_id: str = "",
    extra_sections: list[str] | None = None,
) -> tuple[str, bool]:
    lines = [
        f"### {stage_title}",
        f"- **Error:** {error_msg}",
    ]
    if plan_session_id:
        lines.append(f"- **plan_session_id:** `{plan_session_id}`")
    if neon_session_id:
        lines.append(f"- **neon_session_id:** `{neon_session_id}`")
    if telemetry_rows:
        lines.extend(
            [
                "",
                "### Execution & Review Telemetry",
                "| Phase | Model | Status | Duration | Tokens | Session ID |",
                "| :--- | :--- | :---: | :---: | :---: | :--- |",
                *telemetry_rows,
            ]
        )
    if extra_sections:
        lines.extend(["", *extra_sections])
    return "\n".join(lines), True


def handle_neon_analyze(args: dict[str, Any], cancel_ctx: CancelContext) -> tuple[str, bool]:
    cwd = validate_cwd(args["cwd"])
    cancel_ctx.emit_progress(1, 1, "Running Gemini 4 Neon (Medium) analysis...")
    prompt = (
        "You are Gemini 4 Neon (Medium) acting as the dedicated READ-ONLY analysis specialist.\n"
        "Investigate the workspace using read-only tools (`read_file` or read-only `rg`/`git` commands) "
        "and produce a concise, evidence-backed analysis citing exact file paths and line numbers.\n"
        "Do NOT modify files.\n\n"
        f"Task:\n{_safe_str(args.get('prompt'))}"
    )
    res = run_agy(
        model_slug=MODELS["neon_analyze"],
        prompt=prompt,
        cwd=cwd,
        access_mode="readonly",
        timeout_sec=240,
        resume_id=args.get("resume_session_id"),
        cancel_ctx=cancel_ctx,
    )
    if not res["ok"]:
        return f"neon_analyze failed: {res['error']}", True
    fallback_note = " *(started fresh session)*" if res.get("resume_fallback") else ""
    body = (
        f"**Model:** `{res['model']}` | **session_id:** `{res['conversation_id']}`{fallback_note}\n\n"
        f"{_safe_str(res['response']).strip()}"
    )
    return body, False


def handle_carbon_planner(args: dict[str, Any], cancel_ctx: CancelContext) -> tuple[str, bool]:
    cwd = validate_cwd(args["cwd"])
    cancel_ctx.emit_progress(1, 1, "Running Gemini 4 Carbon (High) planner...")
    prompt = (
        "You are Gemini 4 Carbon (High) acting as the Chief Software Architect in READ-ONLY mode.\n"
        "Do NOT edit or write any files. Explore only the relevant modules in the workspace and produce a concrete, "
        "actionable implementation plan covering:\n"
        "1. Architectural approach & key trade-offs\n"
        "2. Exact files & symbols to add/modify and interface contracts\n"
        "3. Edge cases, failure modes, and security/concurrency invariants\n"
        "4. Exact build/test verification commands\n\n"
        f"Planning Request:\n{_safe_str(args.get('task'))}"
    )
    res = run_agy(
        model_slug=MODELS["carbon_planner"],
        prompt=prompt,
        cwd=cwd,
        access_mode="readonly",
        timeout_sec=360,
        resume_id=args.get("resume_session_id"),
        cancel_ctx=cancel_ctx,
    )
    if not res["ok"]:
        return f"carbon_planner failed: {res['error']}", True
    fallback_note = " *(started fresh session)*" if res.get("resume_fallback") else ""
    body = (
        f"**plan_session_id:** `{res['conversation_id']}` *(pass this to `execute_with_review` for design-aligned review)*{fallback_note}\n"
        f"**Model:** `{res['model']}`\n\n"
        f"{_safe_str(res['response']).strip()}"
    )
    return body, False


def handle_carbon_reviewer(args: dict[str, Any], cancel_ctx: CancelContext) -> tuple[str, bool]:
    cwd = validate_cwd(args["cwd"])
    raw_ref = args.get("base_ref")
    base_ref = _safe_str(raw_ref) if raw_ref is not None else "HEAD"
    cancel_ctx.emit_progress(1, 2, f"Collecting focused diff against {base_ref}...")
    tmp_obj = _ensure_private_tmp_dir() / f"obj-{uuid.uuid4().hex}"
    try:
        diff_ctx = collect_diff_context(cwd, base_ref=base_ref, obj_dir=tmp_obj)
    finally:
        shutil.rmtree(tmp_obj, ignore_errors=True)
    focus = _safe_str(args.get("focus")).strip()
    header = (
        "You are Gemini 4 Carbon (High) performing an independent READ-ONLY code review."
        + (f"\nUser focus instructions: {focus}" if focus else "")
    )
    prompt = build_review_prompt(diff_ctx, header)
    inline_prefix = f"{header}\n\n## Changed Files Summary\n```\n{diff_ctx['status_text']}\n```"
    cancel_ctx.emit_progress(2, 2, "Running Gemini 4 Carbon (High) review...")
    res, review = run_carbon_review_with_retry(
        prompt=prompt,
        cwd=cwd,
        timeout_sec=360,
        resume_id=args.get("resume_session_id"),
        cancel_ctx=cancel_ctx,
        inline_prefix=inline_prefix,
    )
    if not res["ok"]:
        return f"carbon_reviewer failed: {res['error']}", True

    fallback_note = " *(started fresh session)*" if res.get("resume_fallback") else ""
    body = (
        f"**Model:** `{res['model']}` | **session_id:** `{res['conversation_id']}`{fallback_note} | "
        f"**Diff:** {diff_ctx['changed_files']} file(s), {diff_ctx['changed_lines']} line(s)\n"
        f"**Verdict:** `{review['verdict']}`\n\n"
        f"{format_findings_markdown(review)}"
    )
    return body, False


def handle_neon_coder(args: dict[str, Any], cancel_ctx: CancelContext) -> tuple[str, bool]:
    cwd = validate_cwd(args["cwd"])
    cancel_ctx.emit_progress(1, 1, "Running Gemini 4 Neon (XHigh) coder...")
    prompt = (
        "You are Gemini 4 Neon (XHigh) acting as the Senior Implementation Engineer.\n"
        "Implement the requested changes cleanly, avoid duplicating logic, run relevant build/tests to verify, "
        "and report exact changed files and command results.\n\n"
        f"Task:\n{_safe_str(args.get('task'))}"
    )
    res = run_agy(
        model_slug=MODELS["neon_coder"],
        prompt=prompt,
        cwd=cwd,
        access_mode="readwrite",
        timeout_sec=600,
        resume_id=args.get("resume_session_id"),
        cancel_ctx=cancel_ctx,
    )
    if not res["ok"]:
        return f"neon_coder failed: {res['error']}", True
    fallback_note = " *(started fresh session)*" if res.get("resume_fallback") else ""
    body = (
        f"**Model:** `{res['model']}` | **neon_session_id:** `{res['conversation_id']}`{fallback_note}\n\n"
        f"{_safe_str(res['response']).strip()}"
    )
    return body, False


def _remaining_timeout(deadline: float, requested: int) -> int | None:
    rem = int(deadline - time.monotonic())
    if rem < 60:
        return None
    return min(requested, rem)


def handle_execute_with_review(args: dict[str, Any], cancel_ctx: CancelContext) -> tuple[str, bool]:
    cwd = validate_cwd(args["cwd"])
    task = _safe_str(args.get("task"))
    if not task.strip():
        raise ValueError("task must be a non-empty string.")
    plan_session_id = _safe_str(args.get("plan_session_id")).strip() or None

    raw_lines = args.get("large_diff_lines")
    raw_files = args.get("large_diff_files")
    large_lines = max(0, int(raw_lines)) if raw_lines is not None else 120
    large_files = max(0, int(raw_files)) if raw_files is not None else 4

    pipeline_deadline = time.monotonic() + PIPELINE_BUDGET_SEC
    telemetry_rows: list[str] = []
    tmp_obj = _ensure_private_tmp_dir() / f"obj-{uuid.uuid4().hex}"
    try:
        return _execute_with_review_inner(
            cwd=cwd,
            task=task,
            plan_session_id=plan_session_id,
            large_lines=large_lines,
            large_files=large_files,
            pipeline_deadline=pipeline_deadline,
            telemetry_rows=telemetry_rows,
            tmp_obj=tmp_obj,
            cancel_ctx=cancel_ctx,
        )
    finally:
        shutil.rmtree(tmp_obj, ignore_errors=True)


def _execute_with_review_inner(
    cwd: Path,
    task: str,
    plan_session_id: str | None,
    large_lines: int,
    large_files: int,
    pipeline_deadline: float,
    telemetry_rows: list[str],
    tmp_obj: Path,
    cancel_ctx: CancelContext,
) -> tuple[str, bool]:
    baseline = snapshot_baseline(cwd, obj_dir=tmp_obj)

    # Phase 1: Neon XHigh implementation + local build/tests.
    cancel_ctx.emit_progress(1, 5, "Phase 1: Gemini 4 Neon (XHigh) implementing changes...")
    t1 = _remaining_timeout(pipeline_deadline, 600) or 600
    impl_prompt = (
        "You are Gemini 4 Neon (XHigh) implementing a software engineering task.\n"
        "1. Implement the task cleanly following existing codebase patterns.\n"
        "2. Run the project's build/lint/test commands to verify your changes.\n"
        "3. Keep your final summary concise (<= 250 words): list modified file paths, 1-line rationale per file, "
        "and exact build/test exit codes. Do NOT paste full code blocks.\n\n"
        f"Task / Plan:\n{task}"
    )
    p1 = run_agy(
        model_slug=MODELS["neon_coder"],
        prompt=impl_prompt,
        cwd=cwd,
        access_mode="readwrite",
        timeout_sec=t1,
        cancel_ctx=cancel_ctx,
    )
    telemetry_rows.append(fmt_telemetry_row("1. Implement", p1))
    if not p1["ok"]:
        return _build_failure_report("Execution Failed in Phase 1 (Neon XHigh)", p1["error"], telemetry_rows, plan_session_id)

    neon_session_id = p1["conversation_id"]
    latest_impl_report = _safe_str(p1["response"]).strip()

    diff_1 = collect_diff_context(cwd, base_ref="HEAD", baseline=baseline, obj_dir=tmp_obj)
    if diff_1["changed_files"] == 0 and diff_1["changed_lines"] == 0:
        sections = [
            "## Tri-Orchestrator Closed-Loop Report",
            "- **Final Gate Status:** `NO_CODE_CHANGES (Verified by Neon; Carbon review skipped on empty diff)`",
            f"- **Workspace:** `{cwd}`",
            "- **Final Diff Magnitude:** 0 file(s), 0 line(s)",
            f"- **neon_session_id:** `{neon_session_id}`",
            "",
            "### Execution & Review Telemetry",
            "| Phase | Model | Status | Duration | Tokens | Session ID |",
            "| :--- | :--- | :---: | :---: | :---: | :--- |",
            *telemetry_rows,
            "",
            "### Phase 1 — Neon Implementation Summary",
            latest_impl_report,
        ]
        return "\n".join(sections), False

    is_large_1 = (diff_1["changed_lines"] >= large_lines) or (diff_1["changed_files"] >= large_files)

    # Phase 2: Mandatory Carbon Round-1 Review.
    t2 = _remaining_timeout(pipeline_deadline, 360)
    if t2 is None:
        return _build_failure_report(
            "Pipeline Budget Exhausted Before Phase 2 (Carbon Round-1 Review)",
            f"Total pipeline budget ({PIPELINE_BUDGET_SEC}s) exhausted.",
            telemetry_rows,
            plan_session_id,
            neon_session_id,
        )

    cancel_ctx.emit_progress(2, 5, "Phase 2: Gemini 4 Carbon (High) Round-1 review...")
    r1_header = (
        "You are Gemini 4 Carbon (High) performing MANDATORY ROUND-1 FINAL CODE REVIEW.\n"
        f"Original Task / Plan Context:\n{task}\n\n"
        f"Implementation Report from Neon:\n{latest_impl_report[:2000]}"
    )
    r1_prompt = build_review_prompt(diff_1, r1_header)
    r1_fallback_prompt = build_review_prompt(
        diff_1,
        r1_header + "\n(Note: Verify all architectural requirements from the task context above.)",
    )
    r1_inline_prefix = f"{r1_header}\n\n## Changed Files Summary\n```\n{diff_1['status_text']}\n```"
    p2, r1_review = run_carbon_review_with_retry(
        prompt=r1_prompt,
        cwd=cwd,
        timeout_sec=t2,
        resume_id=plan_session_id,
        fallback_prompt=r1_fallback_prompt,
        cancel_ctx=cancel_ctx,
        inline_prefix=r1_inline_prefix,
    )
    telemetry_rows.append(fmt_telemetry_row("2. Review R1", p2))
    if not p2["ok"]:
        return _build_failure_report(
            "Phase 2 (Carbon Round-1 Review) Failed",
            p2["error"],
            telemetry_rows,
            plan_session_id,
            neon_session_id,
            [f"#### Neon Phase 1 Output\n{latest_impl_report}"],
        )

    r1_actionable = get_actionable_findings(r1_review)
    r1_has_high_or_blocker = any(f["severity"] in ("BLOCKER", "HIGH") for f in r1_actionable)
    r1_fix_report = ""

    # Phase 2b: Auto-fix Round 1 findings if any BLOCKER/HIGH/MEDIUM exist.
    if r1_actionable:
        t2b = _remaining_timeout(pipeline_deadline, 480)
        if t2b is None:
            return _build_failure_report(
                "Pipeline Budget Exhausted Before Phase 2b (Neon Fix R1)",
                f"Total pipeline budget ({PIPELINE_BUDGET_SEC}s) exhausted with unfixed Round-1 issues.",
                telemetry_rows,
                plan_session_id,
                neon_session_id,
                [f"#### Round-1 Findings\n{format_findings_markdown(r1_review)}"],
            )
        cancel_ctx.emit_progress(3, 5, f"Phase 2b: Neon fixing {len(r1_actionable)} Round-1 finding(s)...")
        fix1_prompt = (
            "Carbon High Round-1 code review found actionable issues that MUST be fixed:\n\n"
            f"{format_findings_markdown({'summary': r1_review.get('summary', ''), 'findings': r1_actionable, 'parsed': True})}\n\n"
            "Instructions:\n"
            "1. Fix every BLOCKER, HIGH, and MEDIUM issue listed above cleanly.\n"
            "2. Re-run all relevant build and test checks after your final edit.\n"
            "3. Keep summary concise (<= 200 words): exact fixes made and exact verification output."
        )
        p2b = run_agy(
            model_slug=MODELS["neon_coder"],
            prompt=fix1_prompt,
            cwd=cwd,
            access_mode="readwrite",
            timeout_sec=t2b,
            resume_id=neon_session_id,
            fallback_prompt=f"Original task:\n{task}\n\n{fix1_prompt}",
            cancel_ctx=cancel_ctx,
        )
        telemetry_rows.append(fmt_telemetry_row("2b. Fix R1", p2b))
        if not p2b["ok"]:
            return _build_failure_report(
                "Phase 2b (Neon Fix Round 1) Failed",
                p2b["error"],
                telemetry_rows,
                plan_session_id,
                neon_session_id,
                [f"#### Round-1 Findings\n{format_findings_markdown(r1_review)}"],
            )
        neon_session_id = p2b["conversation_id"] or neon_session_id
        r1_fix_report = _safe_str(p2b["response"]).strip()
        latest_impl_report = r1_fix_report
        diff_after_fix1 = collect_diff_context(cwd, base_ref="HEAD", baseline=baseline, obj_dir=tmp_obj)
    else:
        diff_after_fix1 = diff_1

    is_large_after = (diff_after_fix1["changed_lines"] >= large_lines) or (diff_after_fix1["changed_files"] >= large_files)
    trigger_r2 = is_large_1 or is_large_after or r1_has_high_or_blocker

    if is_large_1 or is_large_after:
        trig_diff = diff_after_fix1 if is_large_after else diff_1
        r2_trigger_label = (
            f"TRIGGERED — Large Diff (`{trig_diff['changed_files']}` files / `{trig_diff['changed_lines']}` lines; "
            f"thresholds: `{large_files}` files or `{large_lines}` lines)"
        )
    elif r1_has_high_or_blocker:
        r2_trigger_label = "TRIGGERED — Mandatory Verification of Round-1 BLOCKER/HIGH Fixes"
    else:
        r2_trigger_label = (
            f"SKIPPED (`{diff_after_fix1['changed_files']}` files, `{diff_after_fix1['changed_lines']}` lines "
            "— below thresholds & zero BLOCKER/HIGH in R1)"
        )

    # Phase 3: Round-2 Review when diff is large OR R1 fixed BLOCKER/HIGH findings.
    r2_review: dict[str, Any] | None = None
    r2_actionable: list[dict[str, Any]] = []
    r2_fix_report = ""
    r4_review: dict[str, Any] | None = None
    final_diff = diff_after_fix1

    if trigger_r2:
        t3 = _remaining_timeout(pipeline_deadline, 360)
        if t3 is None:
            return _build_failure_report(
                "Pipeline Budget Exhausted Before Phase 3 (Carbon Round-2 Review)",
                f"Total pipeline budget ({PIPELINE_BUDGET_SEC}s) exhausted.",
                telemetry_rows,
                plan_session_id,
                neon_session_id,
                [f"#### Latest Implementation\n{latest_impl_report}"],
            )
        cancel_ctx.emit_progress(4, 5, "Phase 3: Gemini 4 Carbon (High) Round-2 verification & deep audit...")
        if r1_actionable:
            r2_note = (
                "You are Gemini 4 Carbon (High) performing MANDATORY ROUND-2 ADVERSARIAL REVIEW "
                f"({diff_after_fix1['changed_files']} files, {diff_after_fix1['changed_lines']} lines).\n"
                "Verify that ALL Round-1 findings below are genuinely resolved without regressions, AND deeply audit "
                "cross-file interface boundaries, concurrency/state invariants, silent failure paths, and security.\n\n"
                f"Round-1 Actionable Findings:\n{format_findings_markdown({'summary': '', 'findings': r1_actionable, 'parsed': True})}\n\n"
                f"Neon Fix Report:\n{r1_fix_report[:2000]}"
            )
            r2_resume = _safe_str(p2.get("conversation_id")).strip() or None
        else:
            r2_note = (
                "You are Gemini 4 Carbon (High) performing MANDATORY ROUND-2 ADVERSARIAL REVIEW for a large change "
                f"({diff_after_fix1['changed_files']} files, {diff_after_fix1['changed_lines']} lines).\n"
                "Round-1 passed, so treat this as a fresh second-pair-of-eyes deep audit focusing on cross-file "
                "regressions, missed edge cases, error propagation, concurrency/race conditions, and security.\n\n"
                f"Original Task:\n{task}"
            )
            r2_resume = None
        r2_prompt = build_review_prompt(diff_after_fix1, r2_note)
        r2_inline_prefix = f"{r2_note}\n\n## Changed Files Summary\n```\n{diff_after_fix1['status_text']}\n```"
        p3, r2_review = run_carbon_review_with_retry(
            prompt=r2_prompt,
            cwd=cwd,
            timeout_sec=t3,
            resume_id=r2_resume,
            fallback_prompt=r2_prompt,
            cancel_ctx=cancel_ctx,
            inline_prefix=r2_inline_prefix,
        )
        telemetry_rows.append(fmt_telemetry_row("3. Review R2", p3))
        if not p3["ok"]:
            return _build_failure_report(
                "Phase 3 (Carbon Round-2 Review) Failed",
                p3["error"],
                telemetry_rows,
                plan_session_id,
                neon_session_id,
                [f"#### Latest Implementation\n{latest_impl_report}"],
            )

        r2_actionable = get_actionable_findings(r2_review)
        if r2_actionable:
            t3b = _remaining_timeout(pipeline_deadline, 480)
            if t3b is None:
                return _build_failure_report(
                    "Pipeline Budget Exhausted Before Phase 3b (Neon Fix R2)",
                    f"Total pipeline budget ({PIPELINE_BUDGET_SEC}s) exhausted with unfixed Round-2 issues.",
                    telemetry_rows,
                    plan_session_id,
                    neon_session_id,
                    [f"#### Round-2 Findings\n{format_findings_markdown(r2_review)}"],
                )
            cancel_ctx.emit_progress(5, 5, f"Phase 3b: Neon fixing {len(r2_actionable)} Round-2 finding(s)...")
            fix2_prompt = (
                "Carbon High Round-2 audit found remaining actionable issues that MUST be fixed:\n\n"
                f"{format_findings_markdown({'summary': r2_review.get('summary', ''), 'findings': r2_actionable, 'parsed': True})}\n\n"
                "Instructions:\n"
                "1. Fix every BLOCKER, HIGH, and MEDIUM issue listed above cleanly.\n"
                "2. Re-run all relevant build and test checks after your final edit.\n"
                "3. Keep summary concise (<= 200 words): exact fixes made and exact verification output."
            )
            p3b = run_agy(
                model_slug=MODELS["neon_coder"],
                prompt=fix2_prompt,
                cwd=cwd,
                access_mode="readwrite",
                timeout_sec=t3b,
                resume_id=neon_session_id,
                fallback_prompt=f"Original task:\n{task}\n\n{fix2_prompt}",
                cancel_ctx=cancel_ctx,
            )
            telemetry_rows.append(fmt_telemetry_row("3b. Fix R2", p3b))
            if not p3b["ok"]:
                return _build_failure_report(
                    "Phase 3b (Neon Fix Round 2) Failed",
                    p3b["error"],
                    telemetry_rows,
                    plan_session_id,
                    neon_session_id,
                    [f"#### Round-2 Findings\n{format_findings_markdown(r2_review)}"],
                )
            neon_session_id = p3b["conversation_id"] or neon_session_id
            r2_fix_report = _safe_str(p3b["response"]).strip()
            latest_impl_report = r2_fix_report
            final_diff = collect_diff_context(cwd, base_ref="HEAD", baseline=baseline, obj_dir=tmp_obj)

            # Optional fast Blocker-Closure Gate if Round 2 raised BLOCKER(s) and budget remains.
            if any(f["severity"] == "BLOCKER" for f in r2_actionable):
                t4 = _remaining_timeout(pipeline_deadline, 180)
                if t4 is not None and t4 >= 120:
                    gate_note = (
                        "You are Gemini 4 Carbon (High) running a targeted FINAL BLOCKER-CLOSURE GATE.\n"
                        "Confirm whether the Round-2 BLOCKER issue(s) below are fully fixed with zero regressions:\n"
                        f"{format_findings_markdown({'summary': '', 'findings': r2_actionable, 'parsed': True})}"
                    )
                    gate_prompt = build_review_prompt(final_diff, gate_note)
                    p4, r4_review = run_carbon_review_with_retry(
                        prompt=gate_prompt,
                        cwd=cwd,
                        timeout_sec=t4,
                        resume_id=_safe_str(p3.get("conversation_id")).strip() or None,
                        fallback_prompt=gate_prompt,
                        cancel_ctx=cancel_ctx,
                        inline_prefix=f"{gate_note}\n\n## Changed Files Summary\n```\n{final_diff['status_text']}\n```",
                    )
                    telemetry_rows.append(fmt_telemetry_row("4. Blocker Gate", p4))
                    if not p4["ok"]:
                        r4_review = None

    if r4_review is not None:
        r4_act = get_actionable_findings(r4_review)
        if not r4_act:
            gate_status = "VERIFIED_PASS (Confirmed by Carbon Post-R2 Blocker Gate)"
        else:
            gate_status = "NEEDS_HUMAN_ATTENTION (Residual Issues After Post-R2 Gate)"
    elif r2_review is not None:
        if not r2_actionable:
            gate_status = "VERIFIED_PASS (Confirmed by Carbon Round-2)"
        else:
            gate_status = (
                f"FIXED_POST_R2_UNVERIFIED (Modified in Phase 3b after Round-2; "
                f"resume `neon_session_id={neon_session_id}` or run `carbon_reviewer` to spot-check)"
            )
    elif not r1_actionable:
        gate_status = "VERIFIED_PASS (Confirmed by Carbon Round-1)"
    else:
        gate_status = "FIXED_AFTER_R1_MEDIUM (Tests Re-run by Neon)"

    sections = [
        "## Tri-Orchestrator Closed-Loop Report",
        f"- **Final Gate Status:** `{gate_status}`",
        f"- **Workspace:** `{cwd}`",
        f"- **Final Diff Magnitude:** {final_diff['changed_files']} file(s), {final_diff['changed_lines']} line(s)",
        f"- **Round-2 Audit:** {r2_trigger_label}",
        f"- **neon_session_id:** `{neon_session_id}`",
        "",
        "### Execution & Review Telemetry",
        "| Phase | Model | Status | Duration | Tokens | Session ID |",
        "| :--- | :--- | :---: | :---: | :---: | :--- |",
        *telemetry_rows,
        "",
        "### Phase 1 — Neon Implementation Summary",
        _safe_str(p1["response"]).strip(),
        "",
        f"### Phase 2 — Carbon Round-1 Review (`{r1_review['verdict']}`)",
        format_findings_markdown(r1_review),
    ]
    if r1_fix_report:
        sections.extend(["", "### Phase 2b — Neon Round-1 Fixes & Verification", r1_fix_report])
    if r2_review is not None:
        sections.extend(
            [
                "",
                f"### Phase 3 — Carbon Round-2 Review (`{r2_review['verdict']}`)",
                format_findings_markdown(r2_review),
            ]
        )
    if r2_fix_report:
        sections.extend(["", "### Phase 3b — Neon Round-2 Fixes & Verification", r2_fix_report])
    if r4_review is not None:
        sections.extend(
            [
                "",
                f"### Phase 4 — Carbon Blocker-Closure Gate (`{r4_review['verdict']}`)",
                format_findings_markdown(r4_review),
            ]
        )

    return "\n".join(sections), False


DISPATCH = {
    "neon_analyze": handle_neon_analyze,
    "carbon_planner": handle_carbon_planner,
    "execute_with_review": handle_execute_with_review,
    "carbon_reviewer": handle_carbon_reviewer,
    "neon_coder": handle_neon_coder,
}


def read_next_message(stream: Any) -> tuple[dict[str, Any] | None, str, str | None]:
    """Read newline-delimited or Content-Length MCP JSON-RPC message safely."""
    while True:
        raw_line = stream.readline()
        if not raw_line:
            return None, "newline", None
        stripped = raw_line.strip()
        if not stripped:
            continue

        if stripped.startswith((b"{", b"[")):
            try:
                parsed = json.loads(stripped.decode("utf-8"))
                return parsed, "newline", None
            except Exception as exc:
                return None, "newline", f"Invalid JSON payload: {exc}"

        # Content-Length framing (LSP-style)
        headers: dict[str, str] = {}
        line_str = raw_line.decode("ascii", errors="replace").strip()
        while line_str:
            if ":" in line_str:
                k, v = line_str.split(":", 1)
                headers[k.strip().lower()] = v.strip()
            next_line = stream.readline()
            if not next_line:
                return None, "content-length", None
            line_str = next_line.decode("ascii", errors="replace").strip()

        raw_len = headers.get("content-length", "")
        if not raw_len.isdigit():
            return None, "content-length", "Invalid or missing Content-Length header."
        length = int(raw_len)
        if length <= 0:
            continue

        chunks: list[bytes] = []
        remaining = length
        while remaining > 0:
            chunk = stream.read(remaining)
            if not chunk:
                return None, "content-length", None
            chunks.append(chunk)
            remaining -= len(chunk)
        body = b"".join(chunks)
        try:
            parsed = json.loads(body.decode("utf-8"))
            return parsed, "content-length", None
        except Exception as exc:
            return None, "content-length", f"Invalid JSON body: {exc}"


def main() -> int:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    write_lock = threading.Lock()
    active_lock = threading.Lock()
    active_contexts: dict[Any, CancelContext] = {}
    initial_ppid = os.getppid()

    def cancel_all_active() -> None:
        with active_lock:
            remaining = list(active_contexts.values())
        for ctx in remaining:
            ctx.cancel()

    def _on_term_signal(_signum: int, _frame: Any) -> None:
        cancel_all_active()
        raise SystemExit(128 + _signum)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _on_term_signal)
        except (ValueError, OSError):
            pass

    def send_json(payload: dict[str, Any], framing: str) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        with write_lock:
            try:
                if framing == "content-length":
                    header = f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii")
                    stdout.write(header + encoded)
                else:
                    stdout.write(encoded + b"\n")
                stdout.flush()
            except BrokenPipeError:
                pass

    def make_sender(framing: str) -> Callable[[dict[str, Any]], None]:
        return lambda payload: send_json(payload, framing)

    def run_tool_async(
        req_id: Any,
        tool_name: str,
        tool_args: dict[str, Any],
        ctx: CancelContext,
        framing: str,
    ) -> None:
        try:
            handler = DISPATCH[tool_name]
            text, is_error = handler(tool_args, ctx)
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": text}], "isError": is_error},
            }
        except Exception as exc:
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Tool `{tool_name}` failed: {exc}"}],
                    "isError": True,
                },
            }
        finally:
            with active_lock:
                active_contexts.pop(req_id, None)
        send_json(resp, framing)

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="tri-worker") as executor:
        while True:
            msg, framing, parse_err = read_next_message(stdin)
            if msg is None and parse_err is None:
                break
            if parse_err is not None:
                send_json(
                    {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": parse_err}},
                    framing,
                )
                continue
            if not isinstance(msg, dict):
                send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32600, "message": "Invalid Request: expected JSON object."},
                    },
                    framing,
                )
                continue

            req_id = msg.get("id")
            method = msg.get("method")
            params = msg.get("params")

            if "id" not in msg:
                if method == "notifications/cancelled" and isinstance(params, dict):
                    target_id = params.get("requestId")
                    with active_lock:
                        ctx = active_contexts.get(target_id)
                    if ctx is not None:
                        ctx.cancel()
                continue

            if params is None:
                params = {}
            elif not isinstance(params, dict):
                send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32602, "message": "Invalid params: expected JSON object."},
                    },
                    framing,
                )
                continue

            if method == "initialize":
                proto = params.get("protocolVersion") or "2024-11-05"
                send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "protocolVersion": proto,
                            "capabilities": {"tools": {}},
                            "serverInfo": SERVER_INFO,
                        },
                    },
                    framing,
                )
            elif method == "ping":
                send_json({"jsonrpc": "2.0", "id": req_id, "result": {}}, framing)
            elif method == "resources/list":
                send_json({"jsonrpc": "2.0", "id": req_id, "result": {"resources": []}}, framing)
            elif method == "prompts/list":
                send_json({"jsonrpc": "2.0", "id": req_id, "result": {"prompts": []}}, framing)
            elif method == "tools/list":
                tools = [] if is_child_session() else TOOL_DEFINITIONS
                send_json({"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}, framing)
            elif method == "tools/call":
                if is_child_session():
                    send_json(
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Error: Specialist child session must execute directly without calling tri-router.",
                                    }
                                ],
                                "isError": True,
                            },
                        },
                        framing,
                    )
                    continue

                tool_name = params.get("name")
                tool_args = params.get("arguments")
                if not isinstance(tool_name, str) or tool_name not in DISPATCH:
                    send_json(
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                        },
                        framing,
                    )
                    continue
                if tool_args is None:
                    tool_args = {}
                elif not isinstance(tool_args, dict):
                    send_json(
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {"code": -32602, "message": "Invalid arguments: expected JSON object."},
                        },
                        framing,
                    )
                    continue

                meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
                prog_token = meta.get("progressToken")
                ctx = CancelContext(req_id=req_id, progress_token=prog_token, send_fn=make_sender(framing))
                with active_lock:
                    active_contexts[req_id] = ctx
                executor.submit(run_tool_async, req_id, tool_name, tool_args, ctx, framing)
            else:
                send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32601, "message": f"Method not found: {method}"},
                    },
                    framing,
                )

        # Wait for queued tool calls after stdin EOF (piped batch callers close stdin early);
        # cancel immediately if parent process died (ppid changed).
        while True:
            with active_lock:
                has_active = bool(active_contexts)
            if not has_active:
                break
            if os.getppid() != initial_ppid:
                cancel_all_active()
                break
            time.sleep(0.25)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
