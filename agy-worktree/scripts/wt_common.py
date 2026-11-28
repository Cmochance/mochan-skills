"""Shared pure-stdlib helpers for agy-worktree CLI and PreToolUse guard hook."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "strict_main_repos": [],
    "path_template": "../{repo}-worktree/{repo}-{branch_slug}",
    "branch_slug_separator": "-",
    "default_base_branch": "auto",
    "protected_paths": [],
    "guard": {
        "enabled": True,
        "mode": "active-and-strict",
        "block_install_in_worktree": True,
        "install_command_patterns": [
            r"\bmake\s+(?:.*\s)?install\b",
        ],
        "allow_main_paths": [
            ".git/info/exclude",
        ],
    },
    "enter": {
        "auto_pull_main": True,
        "post_create_commands": [],
    },
    "exit": {
        "default_action": "keep",
        "ignored_safe_dirs": [
            "build",
            "dist",
            ".build",
            "target",
            "node_modules",
            ".pytest_cache",
            "__pycache__",
            ".venv",
        ],
        "cleanup_macos_app_bundles": "auto",
        "delete_remote_branch": True,
        "post_merge_commands": [],
    },
    "repos": {},
}

VALID_GUARD_MODES = frozenset({"active-and-strict", "active-only", "off"})
SESSION_ID_SAFE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
TEMPLATE_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")
ALLOWED_TEMPLATE_KEYS = frozenset({"repo", "branch_slug", "repo_parent"})
_DARWIN_F_GETPATH = 50


def safe_expanduser(raw: str | Path) -> Path:
    """Expand leading ~ safely without raising RuntimeError on unknown ~user / ~- / ~notes literals."""
    return Path(os.path.expanduser(str(raw)))


def clone_json(val: Any) -> Any:
    """Deep-clone JSON-compatible nested structures without copy module overhead."""
    if isinstance(val, dict):
        return {k: clone_json(v) for k, v in val.items()}
    if isinstance(val, list):
        return [clone_json(v) for v in val]
    return val


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override onto a cloned base dict, preserving defaults against null/type mismatch."""
    out: dict[str, Any] = {k: clone_json(v) for k, v in base.items()}
    for k, v in override.items():
        existing = out.get(k)
        if existing is not None and v is None:
            continue
        if isinstance(existing, dict):
            if isinstance(v, dict):
                out[k] = deep_merge(existing, v)
        elif isinstance(existing, list):
            if isinstance(v, list):
                out[k] = clone_json(v)
        elif isinstance(existing, bool):
            if isinstance(v, bool):
                out[k] = v
        else:
            out[k] = clone_json(v)
    return out


def default_data_dir() -> Path:
    """Return Antigravity CLI data directory honoring AGY_DATA_DIR."""
    env = os.environ.get("AGY_DATA_DIR", "").strip()
    return safe_expanduser(env) if env else Path.home() / ".gemini" / "antigravity-cli"


def default_config_path() -> Path:
    """Return agy-worktree config file path honoring AGY_WORKTREE_CONFIG."""
    env = os.environ.get("AGY_WORKTREE_CONFIG", "").strip()
    if env:
        return safe_expanduser(env)
    return Path.home() / ".gemini" / "config" / "agy-worktree.json"


def plugin_root() -> Path:
    """Return the root directory of the agy-worktree plugin."""
    return Path(__file__).resolve().parent.parent


def load_raw_config_strict(config_path: Path | None = None) -> tuple[dict[str, Any], bool]:
    """Load raw user config strictly. Returns (dict, existed). Raises ValueError/OSError on error."""
    target = config_path if config_path is not None else default_config_path()
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, False
    if not raw.strip():
        raise ValueError(f"Config file is empty: {target}")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"Config root must be a JSON object: {target}")
    return parsed, True


def load_config_checked(config_path: Path | None = None) -> tuple[dict[str, Any], str | None]:
    """Load merged agy-worktree config, returning (config, error_message_or_None)."""
    target = config_path if config_path is not None else default_config_path()
    try:
        raw_cfg, existed = load_raw_config_strict(target)
        if not existed:
            return deep_merge(DEFAULT_CONFIG, {}), None
        return deep_merge(DEFAULT_CONFIG, raw_cfg), None
    except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return deep_merge(DEFAULT_CONFIG, {}), f"Invalid or unreadable config {target}: {exc}"


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load merged agy-worktree config (convenience wrapper; logs warning on error)."""
    cfg, err = load_config_checked(config_path=config_path)
    if err:
        print(f"Warning: {err}", file=sys.stderr)
    return cfg


def _canonical_darwin_path(path: Path) -> Path:
    """Canonicalize on-disk casing on macOS APFS/HFS+ via non-blocking F_GETPATH without hanging on FIFOs."""
    if sys.platform != "darwin":
        return path
    import fcntl

    cur = path
    tail: list[str] = []
    open_flags = getattr(os, "O_EVTONLY", os.O_RDONLY) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)

    while True:
        try:
            st = os.lstat(str(cur))
        except OSError:
            st = None

        if st is not None and (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
            fd = -1
            try:
                fd = os.open(str(cur), open_flags)
                buf = fcntl.fcntl(fd, _DARWIN_F_GETPATH, bytes(1024))
                real = buf.split(b"\x00", 1)[0].decode("utf-8", errors="surrogateescape")
                if real:
                    out = Path(real)
                    for part in reversed(tail):
                        out = out / part
                    return out
            except OSError:
                pass
            finally:
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass

        if cur == cur.parent:
            return path
        tail.append(cur.name)
        cur = cur.parent


def _resolve_existing_ancestor(p: Path) -> tuple[Path, list[str]]:
    tail: list[str] = []
    cur = p
    while True:
        try:
            exists = cur.exists() or cur.is_symlink()
        except (OSError, ValueError):
            exists = False
        if exists:
            try:
                base = cur.resolve()
            except OSError:
                base = cur
            base = _canonical_darwin_path(base)
            return base, tail
        if cur == cur.parent:
            return Path(os.path.normpath(str(p))), []
        tail.append(cur.name)
        cur = cur.parent


def resolve_path_safe(raw_path: str | Path, base_dir: Path | None = None) -> Path:
    """Resolve a path safely, normalizing '..' even over nonexistent segments and APFS casing."""
    raw_str = str(raw_path)
    if "\x00" in raw_str:
        raise ValueError("Path contains embedded NUL byte")
    p = safe_expanduser(raw_str)
    if not p.is_absolute() and base_dir is not None:
        p = base_dir / p

    base, tail = _resolve_existing_ancestor(p)
    for part in reversed(tail):
        base = base / part

    # Collapse lexical '..' or '.' segments that occurred under nonexistent subpaths and re-canonicalize
    if ".." in tail or "." in tail:
        norm = Path(os.path.normpath(str(base)))
        base2, tail2 = _resolve_existing_ancestor(norm)
        for part in reversed(tail2):
            base2 = base2 / part
        return base2

    return base


def _case_key(path: Path) -> str:
    s = str(path)
    return s.lower() if sys.platform == "darwin" else s


def rel_posix_within(child: Path, parent: Path) -> str | None:
    """Return child's POSIX path relative to parent (case-insensitive safe on macOS), or None if outside."""
    try:
        c = resolve_path_safe(child)
        p = resolve_path_safe(parent)
    except (OSError, ValueError):
        return None
    if not is_path_within(c, p):
        return None
    try:
        return c.relative_to(p).as_posix()
    except ValueError:
        c_parts = c.parts
        p_parts = p.parts
        if len(c_parts) < len(p_parts):
            return None
        if sys.platform == "darwin":
            if [x.lower() for x in c_parts[: len(p_parts)]] != [x.lower() for x in p_parts]:
                return None
        elif c_parts[: len(p_parts)] != p_parts:
            return None
        rem = c_parts[len(p_parts) :]
        return "/".join(rem) if rem else "."


def normalize_home_display(path: Path) -> str:
    """Format a path with leading ~ when inside the user's home directory."""
    try:
        resolved = resolve_path_safe(path)
    except (OSError, ValueError):
        resolved = path
    home = resolve_path_safe(Path.home())
    if _case_key(resolved) == _case_key(home):
        return "~"
    rel = rel_posix_within(resolved, home)
    if rel is not None and rel != ".":
        return f"~/{rel}"
    return str(resolved)


def is_path_within(child: Path, parent: Path) -> bool:
    """Return True if resolved child is equal to or nested under resolved parent."""
    try:
        c = _case_key(resolve_path_safe(child))
        p = _case_key(resolve_path_safe(parent))
        return os.path.commonpath([c, p]) == p
    except (ValueError, OSError):
        return False


def same_resolved_path(a: str | Path, b: str | Path) -> bool:
    """Compare two filesystem paths after resolution (APFS case-insensitive safe)."""
    if not a or not b:
        return False
    try:
        pa = resolve_path_safe(a)
        pb = resolve_path_safe(b)
    except (OSError, ValueError):
        return False
    try:
        if os.path.samefile(str(pa), str(pb)):
            return True
    except OSError:
        pass
    return _case_key(pa) == _case_key(pb)


def repo_hash(main_root: Path) -> str:
    """Stable short hash for a resolved main repository path."""
    import hashlib

    norm = _case_key(resolve_path_safe(main_root))
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def read_git_head(git_dir: Path) -> str:
    """Read active branch name or 7-char detached SHA from <git_dir>/HEAD."""
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8")
    except Exception:
        return ""
    lines = head.splitlines()
    if not lines:
        return ""
    first = lines[0].strip()
    if first.startswith("ref:"):
        ref = first[4:].strip()
        prefix = "refs/heads/"
        return ref[len(prefix) :] if ref.startswith(prefix) else ref
    return first[:7] if len(first) >= 7 else first


def inspect_git_dir_directly(git_dir: Path) -> dict[str, Any] | None:
    """Inspect an explicit GIT_DIR path (e.g., from --git-dir or GIT_DIR env)."""
    try:
        resolved_gd = resolve_path_safe(git_dir)
    except (OSError, ValueError):
        return None
    if not resolved_gd.is_dir():
        return None

    parts = resolved_gd.parts
    common_dir = resolved_gd
    try:
        cd_raw = (resolved_gd / "commondir").read_text(encoding="utf-8").strip()
        if cd_raw and "\x00" not in cd_raw:
            cd_path = safe_expanduser(cd_raw)
            common_dir = resolve_path_safe(resolved_gd / cd_path) if not cd_path.is_absolute() else resolve_path_safe(cd_path)
    except OSError:
        if len(parts) >= 3 and parts[-2] == "worktrees" and parts[-3] == ".git":
            common_dir = resolve_path_safe(resolved_gd.parent.parent)

    is_linked = len(parts) >= 2 and parts[-2] == "worktrees"
    if is_linked:
        main_root = common_dir.parent if common_dir.name == ".git" else common_dir
        wt_root = resolved_gd
        try:
            gd_ref = (resolved_gd / "gitdir").read_text(encoding="utf-8").strip()
            if gd_ref and "\x00" not in gd_ref:
                wt_dot_git = resolve_path_safe(gd_ref)
                wt_root = wt_dot_git.parent if wt_dot_git.name == ".git" else wt_dot_git
        except OSError:
            pass
        return {
            "root": wt_root,
            "git_dir": resolved_gd,
            "common_dir": common_dir,
            "main_root": resolve_path_safe(main_root),
            "is_linked": True,
            "wt_name": parts[-1],
            "branch": read_git_head(resolved_gd),
        }

    main_root = resolved_gd.parent if resolved_gd.name == ".git" else resolved_gd
    return {
        "root": resolve_path_safe(main_root),
        "git_dir": resolved_gd,
        "common_dir": common_dir,
        "main_root": resolve_path_safe(main_root),
        "is_linked": False,
        "wt_name": "",
        "branch": read_git_head(resolved_gd),
    }


def find_git_repo_info(path: str | Path) -> dict[str, Any] | None:
    """Inspect git topology (main repo vs linked worktree) without spawning git."""
    if not path:
        return None
    raw_str = str(path)
    if "\x00" in raw_str:
        return None
    try:
        start = resolve_path_safe(raw_str)
    except (OSError, ValueError):
        return None

    try:
        if start.is_file() or not start.exists():
            start_candidates = (*start.parents,)
        else:
            start_candidates = (start, *start.parents)
    except (OSError, ValueError):
        start_candidates = (*start.parents,)

    for parent in start_candidates:
        dot_git = parent / ".git"
        try:
            st = os.lstat(str(dot_git))
        except (OSError, ValueError):
            continue

        if stat.S_ISDIR(st.st_mode):
            resolved_git = resolve_path_safe(dot_git)
            resolved_parent = resolve_path_safe(parent)
            return {
                "root": resolved_parent,
                "git_dir": resolved_git,
                "common_dir": resolved_git,
                "main_root": resolved_parent,
                "is_linked": False,
                "wt_name": "",
                "branch": read_git_head(resolved_git),
            }

        if stat.S_ISREG(st.st_mode):
            try:
                content = dot_git.read_text(encoding="utf-8")
            except OSError:
                return None
            gitdir_raw = ""
            for line in content.splitlines():
                if line.lower().startswith("gitdir:"):
                    gitdir_raw = line.split(":", 1)[1].strip()
                    break
            if not gitdir_raw or "\x00" in gitdir_raw:
                return None

            try:
                gitdir_path = safe_expanduser(gitdir_raw)
                if not gitdir_path.is_absolute():
                    gitdir_path = resolve_path_safe(parent / gitdir_path)
                else:
                    gitdir_path = resolve_path_safe(gitdir_path)
            except (OSError, ValueError):
                return None

            parts = gitdir_path.parts
            common_dir = gitdir_path
            commondir_file = gitdir_path / "commondir"
            try:
                cd_raw = commondir_file.read_text(encoding="utf-8").strip()
                if cd_raw and "\x00" not in cd_raw:
                    cd_path = safe_expanduser(cd_raw)
                    if not cd_path.is_absolute():
                        common_dir = resolve_path_safe(gitdir_path / cd_path)
                    else:
                        common_dir = resolve_path_safe(cd_path)
            except (OSError, ValueError):
                if len(parts) >= 3 and parts[-2] == "worktrees" and parts[-3] == ".git":
                    common_dir = resolve_path_safe(gitdir_path.parent.parent)

            is_linked = len(parts) >= 2 and parts[-2] == "worktrees"
            resolved_parent = resolve_path_safe(parent)
            if is_linked:
                if common_dir.name == ".git":
                    main_root = common_dir.parent
                elif len(parts) >= 3 and parts[-3] == ".git":
                    main_root = gitdir_path.parent.parent.parent
                else:
                    main_root = common_dir
                return {
                    "root": resolved_parent,
                    "git_dir": gitdir_path,
                    "common_dir": common_dir,
                    "main_root": resolve_path_safe(main_root),
                    "is_linked": True,
                    "wt_name": parts[-1],
                    "branch": read_git_head(gitdir_path),
                }

            return {
                "root": resolved_parent,
                "git_dir": gitdir_path,
                "common_dir": common_dir,
                "main_root": resolved_parent,
                "is_linked": False,
                "wt_name": "",
                "branch": read_git_head(gitdir_path),
            }

    return None


def entry_matches_repo(entry: str, main_root: Path) -> bool:
    """Match a configured repo selector (path or bare repo basename) against main_root."""
    s = entry.strip()
    if not s:
        return False
    norm_main = resolve_path_safe(main_root)
    if "/" not in s and not s.startswith("~"):
        if sys.platform == "darwin":
            return norm_main.name.lower() == s.lower()
        return norm_main.name == s
    return same_resolved_path(s, norm_main)


def is_strict_main_repo(cfg: dict[str, Any], main_root: Path) -> bool:
    """Return True if main_root matches any entry in cfg['strict_main_repos']."""
    strict_list = cfg.get("strict_main_repos")
    if not isinstance(strict_list, list):
        return False
    for entry in strict_list:
        if isinstance(entry, str) and entry_matches_repo(entry, main_root):
            return True
    return False


def effective_guard_for_override(global_guard: dict[str, Any], repo_override: dict[str, Any]) -> dict[str, Any]:
    """Compute effective guard dict merging global_guard with shorthand & nested repo overrides."""
    eff = deep_merge(DEFAULT_CONFIG["guard"], global_guard if isinstance(global_guard, dict) else {})
    for k in ("enabled", "mode", "allow_main_paths", "block_install_in_worktree", "install_command_patterns"):
        if k in repo_override and repo_override[k] is not None:
            if k in ("enabled", "block_install_in_worktree") and not isinstance(repo_override[k], bool):
                continue
            if k in ("allow_main_paths", "install_command_patterns") and not isinstance(repo_override[k], list):
                continue
            eff[k] = clone_json(repo_override[k])
    if isinstance(repo_override.get("guard"), dict):
        eff = deep_merge(eff, repo_override["guard"])
    return eff


def resolve_repo_config(cfg: dict[str, Any], main_root: Path) -> dict[str, Any]:
    """Resolve effective config for a specific repo by merging matching `repos` overrides."""
    eff = deep_merge(DEFAULT_CONFIG, cfg if isinstance(cfg, dict) else {})
    repos = eff.get("repos")
    if not isinstance(repos, dict):
        return eff

    matched_override: dict[str, Any] | None = None
    for key, val in repos.items():
        if not isinstance(key, str) or not isinstance(val, dict):
            continue
        if ("/" in key or key.startswith("~")) and entry_matches_repo(key, main_root):
            matched_override = val
            break
    if matched_override is None:
        for key, val in repos.items():
            if not isinstance(key, str) or not isinstance(val, dict):
                continue
            if entry_matches_repo(key, main_root):
                matched_override = val
                break

    if matched_override is None:
        return eff

    for top_key in ("path_template", "branch_slug_separator", "default_base_branch", "protected_paths"):
        if top_key in matched_override and matched_override[top_key] is not None:
            if top_key == "protected_paths" and not isinstance(matched_override[top_key], list):
                continue
            eff[top_key] = clone_json(matched_override[top_key])

    eff["guard"] = effective_guard_for_override(eff["guard"], matched_override)

    enter_shorthand = ("auto_pull_main", "post_create_commands")
    for k in enter_shorthand:
        if k in matched_override and matched_override[k] is not None:
            eff["enter"][k] = clone_json(matched_override[k])

    exit_shorthand = (
        "default_action",
        "ignored_safe_dirs",
        "cleanup_macos_app_bundles",
        "delete_remote_branch",
        "post_merge_commands",
    )
    for k in exit_shorthand:
        if k in matched_override and matched_override[k] is not None:
            eff["exit"][k] = clone_json(matched_override[k])

    for nested in ("enter", "exit"):
        if isinstance(matched_override.get(nested), dict):
            eff[nested] = deep_merge(eff[nested], matched_override[nested])

    return eff


def strip_rel_prefix(path_str: str) -> str:
    """Strip any combination of leading '/' and './' prefixes without stripping leading dots from dotfiles."""
    s = path_str.strip()
    while True:
        if s.startswith("/"):
            s = s[1:]
        elif s.startswith("./"):
            s = s[2:]
        else:
            break
    return s


def match_allow_path(rel_posix: str, patterns: list[str]) -> bool:
    """Return True if a repo-relative POSIX path matches any allowlist glob/exact path."""
    import fnmatch

    norm_rel = strip_rel_prefix(rel_posix)
    cmp_rel = norm_rel.lower() if sys.platform == "darwin" else norm_rel
    for pat in patterns:
        if not isinstance(pat, str) or not pat.strip():
            continue
        clean_pat = strip_rel_prefix(pat)
        cmp_pat = clean_pat.lower() if sys.platform == "darwin" else clean_pat
        if cmp_pat.endswith("/"):
            if cmp_rel == cmp_pat.rstrip("/") or cmp_rel.startswith(cmp_pat):
                return True
        elif cmp_rel == cmp_pat or fnmatch.fnmatch(cmp_rel, cmp_pat):
            return True
    return False


def slugify_branch(branch: str, sep: str = "-") -> str:
    """Convert a git branch name to a safe single-segment worktree slug."""
    if not sep or any(bad in sep for bad in ("/", "\\", "\x00")) or ".." in sep:
        raise ValueError(f"Invalid branch_slug_separator: {sep!r}")
    s = branch.strip().strip("/")
    s = s.replace("/", sep)
    s = re.sub(r"[^A-Za-z0-9._-]+", sep, s)
    s = re.sub(rf"(?:{re.escape(sep)})+", sep, s).strip(sep)
    if not s or s in (".", ".."):
        return "worktree"
    return s


def render_worktree_path(main_root: Path, branch: str, repo_cfg: dict[str, Any]) -> Path:
    """Compute default worktree path from path_template using strict allowlisted placeholders."""
    sep = str(repo_cfg.get("branch_slug_separator") or "-")
    template = str(repo_cfg.get("path_template") or DEFAULT_CONFIG["path_template"])
    # Validate braces on the template itself BEFORE substituting repo/repo_parent (which may contain '{'/'}')
    leftover = TEMPLATE_PLACEHOLDER_RE.sub("", template)
    if "{" in leftover or "}" in leftover:
        raise ValueError(f"Malformed braces in path_template: {template!r}")

    norm_main = resolve_path_safe(main_root)
    slug = slugify_branch(branch, sep=sep)
    values = {
        "repo": norm_main.name,
        "branch_slug": slug,
        "repo_parent": str(norm_main.parent),
    }

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in ALLOWED_TEMPLATE_KEYS:
            raise ValueError(
                f"Unknown placeholder '{{{key}}}' in path_template {template!r}. "
                f"Allowed placeholders: {', '.join(sorted(ALLOWED_TEMPLATE_KEYS))}."
            )
        return values[key]

    rendered = TEMPLATE_PLACEHOLDER_RE.sub(_replace, template)
    cand = safe_expanduser(rendered)
    if not cand.is_absolute():
        cand = norm_main / cand
    return resolve_path_safe(cand)


def atomic_write_private(dest: Path, content: str, *, mode: int = 0o600) -> None:
    """Atomically write text to dest with private permissions, refusing symlinks."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        st = os.lstat(str(dest))
    except FileNotFoundError:
        st = None
    if st is not None:
        if not stat.S_ISREG(st.st_mode):
            raise OSError(f"Refusing to overwrite non-regular file: {dest}")
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            raise PermissionError(f"Refusing to overwrite foreign-owned file: {dest}")

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    tmp_path: Path | None = None
    fd = -1
    for _ in range(12):
        cand = dest.parent / f".{dest.name}.{os.getpid()}.{os.urandom(4).hex()}.tmp"
        try:
            fd = os.open(str(cand), flags, mode)
            tmp_path = cand
            break
        except FileExistsError:
            continue
    if fd < 0 or tmp_path is None:
        raise OSError(f"Failed to allocate temp file next to {dest}")

    try:
        os.fchmod(fd, mode)
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


def is_safe_session_id(cid: str) -> bool:
    """Validate conversation/session ID is a safe single path segment."""
    return bool(cid and SESSION_ID_SAFE_RE.fullmatch(cid))


def normalize_brain_dir(path: Path) -> Path:
    """Normalize <appDataDir>/brain/<cid>/artifacts -> <appDataDir>/brain/<cid>."""
    if path.name == "artifacts" and path.parent.parent.name == "brain":
        return path.parent
    return path


def brain_dir_from_hook_payload(payload: dict[str, Any], data_dir: Path | None = None) -> Path | None:
    """Resolve <appDataDir>/brain/<cid> from a hook payload (supports camelCase & snake_case)."""
    for k in ("artifactDirectoryPath", "artifact_directory_path"):
        art = payload.get(k)
        if isinstance(art, str) and art.strip() and "\x00" not in art:
            art_p = safe_expanduser(art.strip())
            if art_p.parent.name == "brain":
                return art_p
            if art_p.name == "artifacts" and art_p.parent.parent.name == "brain":
                return art_p.parent

    for k in ("transcriptPath", "transcript_path"):
        tp = payload.get(k)
        if isinstance(tp, str) and tp.strip() and "\x00" not in tp:
            tp_p = safe_expanduser(tp.strip())
            if tp_p.parent.name == "logs" and tp_p.parent.parent.name == ".system_generated":
                return tp_p.parent.parent.parent

    cid = str(
        payload.get("conversationId")
        or payload.get("session_id")
        or payload.get("conversation_id")
        or ""
    ).strip()
    if is_safe_session_id(cid):
        d = data_dir if data_dir is not None else default_data_dir()
        return d / "brain" / cid
    return None


def state_file_for_brain_dir(brain_dir: Path) -> Path:
    return brain_dir / "scratch" / "worktree.json"


def read_transcript_offsets(brain_dir: Path | None, extra_tp: Path | None = None) -> tuple[int, dict[str, int]]:
    """Measure byte sizes of transcript.jsonl and transcript_full.jsonl for exact watermarks."""
    offsets: dict[str, int] = {}
    candidates: list[Path] = []
    if extra_tp is not None:
        candidates.append(extra_tp)
    if brain_dir is not None:
        logs_dir = brain_dir / ".system_generated" / "logs"
        candidates.append(logs_dir / "transcript.jsonl")
        candidates.append(logs_dir / "transcript_full.jsonl")

    for p in candidates:
        name = p.name
        if not name or name in offsets:
            continue
        try:
            offsets[name] = p.stat().st_size
        except OSError:
            pass

    compat_offset = offsets.get("transcript.jsonl", 0)
    if compat_offset == 0 and extra_tp is not None and extra_tp.name in offsets:
        compat_offset = offsets[extra_tp.name]
    return compat_offset, offsets


def read_worktree_state_strict(state_file: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Read scratch/worktree.json distinguishing FileNotFoundError from corruption/permission errors."""
    try:
        raw = state_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        return None, f"Unreadable state file {state_file}: {exc}"
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        return None, f"Corrupt state file {state_file}: {exc}"
    if not isinstance(parsed, dict):
        return None, f"State file root is not a JSON object: {state_file}"
    return parsed, None


def read_worktree_state(state_file: Path) -> dict[str, Any] | None:
    """Safely read scratch/worktree.json (logs warning to stderr on corruption/unreadable)."""
    state, err = read_worktree_state_strict(state_file)
    if err:
        print(f"Warning: {err}", file=sys.stderr)
    return state


def hint_dir_path() -> Path:
    uid = os.getuid() if hasattr(os, "getuid") else 0
    return Path(f"/tmp/agy-wt-ctx-{uid}")


def _ensure_private_hint_dir() -> Path | None:
    d = hint_dir_path()
    try:
        os.makedirs(str(d), mode=0o700, exist_ok=True)
        st = os.lstat(str(d))
        if not stat.S_ISDIR(st.st_mode):
            print(f"Warning: agy-wt hint path is not a directory: {d}", file=sys.stderr)
            return None
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            print(f"Warning: agy-wt hint dir owned by another user: {d}", file=sys.stderr)
            return None
        if stat.S_IMODE(st.st_mode) != 0o700:
            os.chmod(str(d), 0o700)
        return d
    except OSError as exc:
        print(f"Warning: failed to prepare agy-wt hint dir {d}: {exc}", file=sys.stderr)
        return None


def write_session_hint(main_root: Path, hint: dict[str, Any]) -> None:
    """Write a short-lived private session hint in /tmp so sandboxed agy-wt knows current conversationId."""
    import time

    d = _ensure_private_hint_dir()
    if d is None:
        return
    dest = d / f"{repo_hash(main_root)}.json"
    payload = dict(hint)
    payload["ts"] = time.time()
    try:
        atomic_write_private(dest, json.dumps(payload, ensure_ascii=False))
    except OSError as exc:
        print(f"Warning: failed to write agy-wt session hint {dest}: {exc}", file=sys.stderr)


def read_session_hint(
    main_root: Path,
    max_age_sec: float = 60.0,
    *,
    consume: bool = False,
) -> dict[str, Any] | None:
    """Read a fresh private session hint for main_root using O_NOFOLLOW + O_NONBLOCK + atomic claim."""
    import time

    d = hint_dir_path()
    try:
        st_d = os.lstat(str(d))
        if not stat.S_ISDIR(st_d.st_mode):
            return None
        if hasattr(os, "getuid") and st_d.st_uid != os.getuid():
            return None
        if stat.S_IMODE(st_d.st_mode) & 0o077 != 0:
            return None
    except OSError:
        return None

    src = d / f"{repo_hash(main_root)}.json"
    read_target = src
    claimed_tmp: Path | None = None
    if consume:
        cand = d / f".claim.{src.name}.{os.getpid()}.{os.urandom(4).hex()}"
        try:
            os.rename(str(src), str(cand))
            read_target = cand
            claimed_tmp = cand
        except OSError:
            return None

    fd = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(str(read_target), flags)
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            return None
        with os.fdopen(fd, "r", encoding="utf-8") as fp:
            fd = -1
            parsed = json.loads(fp.read())
    except Exception:
        return None
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if claimed_tmp is not None:
            try:
                claimed_tmp.unlink(missing_ok=True)
            except OSError:
                pass

    if not isinstance(parsed, dict):
        return None
    ts = parsed.get("ts")
    if not isinstance(ts, (int, float)):
        return None
    if time.time() - float(ts) > max_age_sec:
        return None
    return parsed
