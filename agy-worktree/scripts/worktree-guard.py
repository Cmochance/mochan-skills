#!/usr/bin/env python3
"""PreToolUse hook protecting main repositories, protected_paths, and worktree install hygiene."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import wt_common as wt  # noqa: E402

FILE_WRITE_TOOLS = frozenset(
    {
        "write_file",
        "edit_file",
        "write_to_file",
        "replace_file_content",
        "multi_replace_file_content",
    }
)

FILE_PATH_ARG_KEYS = ("Path", "TargetFile", "path", "file_path", "target_file")

GIT_ALWAYS_BLOCKED_SUBCMDS = frozenset(
    {
        "commit",
        "add",
        "rm",
        "mv",
        "checkout",
        "switch",
        "merge",
        "rebase",
        "cherry-pick",
        "reset",
        "revert",
        "stash",
        "am",
        "apply",
        "restore",
        "clean",
    }
)

GIT_BRANCH_LIST_FLAGS = frozenset(
    {
        "-a",
        "--all",
        "-r",
        "--remotes",
        "-l",
        "--list",
        "--show-current",
        "-v",
        "-vv",
        "--verbose",
        "--contains",
        "--no-contains",
        "--merged",
        "--no-merged",
        "--points-at",
        "--no-color",
        "--color",
        "--format",
        "--sort",
    }
)

GIT_BRANCH_LIST_VALUE_FLAGS = frozenset(
    {"--contains", "--no-contains", "--merged", "--no-merged", "--points-at", "--format", "--sort"}
)

GIT_BRANCH_LIST_PREFIXES = (
    "--sort=",
    "--format=",
    "--color=",
    "--contains=",
    "--merged=",
    "--no-merged=",
    "--points-at=",
)

GIT_PULL_FORBIDDEN_FLAGS = frozenset({"--no-ff", "--ff", "--rebase", "-r", "--squash", "--no-ff-only"})
GIT_PUSH_VALUE_FLAGS = frozenset({"-o", "--push-option", "--repo", "--receive-pack", "--exec"})

PROTECTED_BRANCH_NAMES = frozenset({"main", "master"})
MAKE_BINS = frozenset({"make", "gmake"})
SHELL_BINS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
SHELL_COMPOUND_KEYWORDS = frozenset({"if", "then", "elif", "else", "do", "while", "until", "!"})
DATA_ONLY_CMDS = frozenset(
    {"git", "gh", "rg", "grep", "egrep", "fgrep", "echo", "printf", "cat", "ls", "find", "head", "tail", "sed", "awk", "pbcopy"}
)
DELETE_CMDS = frozenset({"rm", "rmdir", "unlink"})
ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
COMBINED_BRANCH_LIST_SHORT_RE = re.compile(r"^-[arlv]+$")
NUM_ARG_RE = re.compile(r"^\d+(?:\.\d+)?$")


def _allow() -> int:
    sys.stdout.write('{"decision": "allow"}\n')
    sys.stdout.flush()
    return 0


def _deny(reason: str) -> int:
    sys.stdout.write(json.dumps({"decision": "deny", "reason": reason}, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


def _git_is_tracked(main_root: Path, rel_posix: str) -> bool:
    """Return True if rel_posix is tracked in main_root's git index (fail-closed on git errors)."""
    import subprocess

    pathspec = f":(icase){rel_posix}" if sys.platform == "darwin" else rel_posix
    try:
        proc = subprocess.run(
            ["git", "-C", str(main_root), "ls-files", "--error-unmatch", "--", pathspec],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2,
            check=False,
        )
        if proc.returncode == 0:
            return True
        if proc.returncode == 1:
            return False
        print(
            f"Warning: git ls-files failed (rc={proc.returncode}) in {main_root}: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return True
    except Exception as exc:
        print(f"Warning: git ls-files error in {main_root}: {exc}", file=sys.stderr)
        return True


def _git_is_ignored(main_root: Path, rel_posix: str) -> bool:
    """Return True if rel_posix matches .gitignore or .git/info/exclude."""
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "-C", str(main_root), "check-ignore", "-q", "--", rel_posix],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _read_shell_word(seg: str, start: int) -> tuple[str, int]:
    """Read and unquote a single shell word (handling mixed quotes & backslash escapes)."""
    n = len(seg)
    j = start
    word: list[str] = []
    in_single = False
    in_double = False

    while j < n:
        ch = seg[j]
        if in_single:
            if ch == "'":
                in_single = False
            else:
                word.append(ch)
            j += 1
            continue
        if in_double:
            if ch == '"':
                in_double = False
                j += 1
                continue
            if ch == "\\" and j + 1 < n and seg[j + 1] in ('"', "\\", "$", "`", "\n"):
                word.append(seg[j + 1])
                j += 2
                continue
            word.append(ch)
            j += 1
            continue

        if ch.isspace() or ch in (";", "|", "&", "<", ">", "(", ")"):
            break
        if ch == "'":
            in_single = True
            j += 1
            continue
        if ch == '"':
            in_double = True
            j += 1
            continue
        if ch == "\\" and j + 1 < n:
            word.append(seg[j + 1])
            j += 2
            continue
        word.append(ch)
        j += 1

    return "".join(word), j


def _parse_shell_segments(cmd: str) -> list[tuple[str, int, int, bool]]:
    """Split shell command into (segment_text, open_subshells, close_subshells, in_pipeline).

    Properly skips heredoc bodies (<<EOF / <<'EOF' / <<-EOF), handles # comments,
    [[ ... ]] / (( ... )) / $(( ... )) spans, subshell scopes ( ... ), pipelines, and zsh ops.
    """
    results: list[tuple[str, int, int, bool]] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    bracket_depth = 0  # [[ ... ]]
    arith_depth = 0  # (( ... )) or $(( ... ))
    seg_opens = 0
    seg_closes = 0
    seg_in_pipe = False
    next_in_pipe = False
    pending_heredocs: list[tuple[str, bool]] = []  # (delimiter, strip_tabs)

    i = 0
    n = len(cmd)

    def _flush(is_pipe_end: bool = False) -> None:
        nonlocal seg_opens, seg_closes, seg_in_pipe, next_in_pipe
        text = "".join(buf).strip()
        buf.clear()
        in_p = seg_in_pipe or is_pipe_end
        if text or seg_opens or seg_closes:
            results.append((text, seg_opens, seg_closes, in_p))
        seg_opens = 0
        seg_closes = 0
        seg_in_pipe = is_pipe_end
        next_in_pipe = is_pipe_end

    while i < n:
        ch = cmd[i]

        if in_single:
            if ch == "'":
                in_single = False
            buf.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            buf.append(ch)
            buf.append(cmd[i + 1])
            i += 2
            continue
        if in_double:
            if ch == '"':
                in_double = False
            buf.append(ch)
            i += 1
            continue

        # Comments outside quotes run to newline
        if ch == "#" and (not buf or buf[-1].isspace()):
            while i < n and cmd[i] != "\n":
                i += 1
            continue

        if ch == "'":
            in_single = True
            buf.append(ch)
            i += 1
            continue
        if ch == '"':
            in_double = True
            buf.append(ch)
            i += 1
            continue

        # Track [[ ... ]] and (( ... )) / $(( ... )) so internal >/< / ( / ) are not misparsed
        if cmd[i : i + 3] == "$((":
            arith_depth += 1
            buf.append("$((")
            i += 3
            continue
        if cmd[i : i + 2] == "((":
            arith_depth += 1
            buf.append("((")
            i += 2
            continue
        if arith_depth > 0 and cmd[i : i + 2] == "))":
            arith_depth -= 1
            buf.append("))")
            i += 2
            continue
        if cmd[i : i + 2] == "[[":
            bracket_depth += 1
            buf.append("[[")
            i += 2
            continue
        if bracket_depth > 0 and cmd[i : i + 2] == "]]":
            bracket_depth -= 1
            buf.append("]]")
            i += 2
            continue

        if bracket_depth > 0 or arith_depth > 0:
            buf.append(ch)
            i += 1
            continue

        # Detect heredoc operator << or <<- (not <<<)
        if cmd[i : i + 2] == "<<" and (i + 2 >= n or cmd[i + 2] != "<"):
            strip_tabs = i + 2 < n and cmd[i + 2] == "-"
            op_len = 3 if strip_tabs else 2
            j = i + op_len
            while j < n and cmd[j] in (" ", "\t"):
                j += 1
            delim, end_j = _read_shell_word(cmd, j)
            if delim:
                pending_heredocs.append((delim, strip_tabs))
            buf.append(cmd[i:end_j])
            i = end_j
            continue

        # Subshell / brace grouping boundaries outside quotes
        if ch == "(":
            # Do not treat $(...) or <(...) or >(...) as standalone subshell prefix
            prev_ch = cmd[i - 1] if i > 0 else ""
            if prev_ch in ("$", "<", ">"):
                buf.append(ch)
                i += 1
                continue
            if not "".join(buf).strip():
                seg_opens += 1
                i += 1
                continue
            buf.append(ch)
            i += 1
            continue

        if ch == ")":
            # Close subshell when balancing a tracked subshell open
            if seg_opens > 0 or any(o > c for _, o, c, _ in results):
                seg_closes += 1
                i += 1
                continue
            buf.append(ch)
            i += 1
            continue

        if ch == "{" and not "".join(buf).strip():
            # Strip leading brace group opener '{ '
            if i + 1 < n and cmd[i + 1].isspace():
                i += 1
                continue
        if ch == "}" and (not buf or buf[-1].isspace()) and (i + 1 >= n or cmd[i + 1] in (" ", "\t", ";", "\n", "&", "|")):
            i += 1
            continue

        # 3-char / 2-char redirection operators to keep intact
        three = cmd[i : i + 3]
        if three in ("<<<", ">>|", ">>!", "&>>", "&>|", "&>!"):
            buf.append(three)
            i += 3
            continue
        two = cmd[i : i + 2]
        if two in (">|", ">!", "&>", ">&", "<&", "<>"):
            buf.append(two)
            i += 2
            continue

        # Segment separators
        if two in ("&&", "||"):
            _flush(is_pipe_end=False)
            i += 2
            continue
        if two == "|&":
            _flush(is_pipe_end=True)
            i += 2
            continue
        if ch == "|":
            _flush(is_pipe_end=True)
            i += 1
            continue
        if ch in (";", "&"):
            _flush(is_pipe_end=False)
            i += 1
            continue
        if ch == "\n":
            _flush(is_pipe_end=False)
            i += 1
            # Consume pending heredoc body lines before resuming command parsing
            if pending_heredocs:
                for delim, strip_tabs in pending_heredocs:
                    while i < n:
                        nl = cmd.find("\n", i)
                        if nl < 0:
                            line = cmd[i:]
                            i = n
                        else:
                            line = cmd[i:nl]
                            i = nl + 1
                        check_line = line.lstrip("\t") if strip_tabs else line
                        if check_line.rstrip("\r") == delim:
                            break
                pending_heredocs.clear()
            continue

        buf.append(ch)
        i += 1

    if buf or seg_opens or seg_closes:
        _flush(is_pipe_end=False)
    return results


def _strip_redirections_for_tokens(seg: str) -> tuple[str, list[str]]:
    """Strip shell redirections (output, input, fd-dup, heredoc, here-string) and return output targets."""
    targets: list[str] = []
    out_chars: list[str] = []
    in_single = False
    in_double = False
    bracket_depth = 0
    arith_depth = 0
    i = 0
    n = len(seg)

    def _pop_leading_fd() -> None:
        k = len(out_chars) - 1
        while k >= 0 and out_chars[k].isdigit():
            k -= 1
        if k < len(out_chars) - 1 and (k < 0 or out_chars[k].isspace()):
            del out_chars[k + 1 :]

    while i < n:
        ch = seg[i]
        if ch == "\\" and not in_single and i + 1 < n:
            out_chars.append(seg[i : i + 2])
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            out_chars.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            out_chars.append(ch)
            i += 1
            continue

        if not in_single and not in_double:
            # Skip redirection scanning inside [[ ... ]], (( ... )), $(( ... ))
            if seg[i : i + 3] == "$((":
                arith_depth += 1
                out_chars.append("$((")
                i += 3
                continue
            if seg[i : i + 2] == "((":
                arith_depth += 1
                out_chars.append("((")
                i += 2
                continue
            if arith_depth > 0 and seg[i : i + 2] == "))":
                arith_depth -= 1
                out_chars.append("))")
                i += 2
                continue
            if seg[i : i + 2] == "[[":
                bracket_depth += 1
                out_chars.append("[[")
                i += 2
                continue
            if bracket_depth > 0 and seg[i : i + 2] == "]]":
                bracket_depth -= 1
                out_chars.append("]]")
                i += 2
                continue
            if bracket_depth > 0 or arith_depth > 0:
                out_chars.append(ch)
                i += 1
                continue

            # Combined stdout+stderr file redirect: &>, &>>, &>|, &>!, &>>|, &>>!
            if seg[i : i + 2] == "&>":
                j = i + 2
                if j < n and seg[j] == ">":
                    j += 1
                if j < n and seg[j] in ("|", "!"):
                    j += 1
                while j < n and seg[j].isspace():
                    j += 1
                word, j = _read_shell_word(seg, j)
                if word:
                    targets.append(word)
                out_chars.append(" ")
                i = j
                continue

            # Here-string <<< or heredoc << / <<- (strip completely so no stray '<' tokens remain)
            if seg[i : i + 3] == "<<<":
                _pop_leading_fd()
                j = i + 3
                while j < n and seg[j].isspace():
                    j += 1
                _, j = _read_shell_word(seg, j)
                out_chars.append(" ")
                i = j
                continue
            if seg[i : i + 2] == "<<":
                _pop_leading_fd()
                j = i + 2
                if j < n and seg[j] == "-":
                    j += 1
                while j < n and seg[j].isspace():
                    j += 1
                _, j = _read_shell_word(seg, j)
                out_chars.append(" ")
                i = j
                continue

            # POSIX read-write redirection <> (O_RDWR | O_CREAT) -> treat as output target!
            if seg[i : i + 2] == "<>":
                _pop_leading_fd()
                j = i + 2
                while j < n and seg[j].isspace():
                    j += 1
                word, j = _read_shell_word(seg, j)
                if word:
                    targets.append(word)
                out_chars.append(" ")
                i = j
                continue

            # Output redirect: >, >>, >|, >!, >>|, >>!, >& <fd-or-file>
            if ch == ">":
                _pop_leading_fd()
                is_amp = i + 1 < n and seg[i + 1] == "&"
                j = i + 1
                if is_amp:
                    j += 1
                else:
                    if j < n and seg[j] == ">":
                        j += 1
                    if j < n and seg[j] in ("|", "!"):
                        j += 1
                while j < n and seg[j].isspace():
                    j += 1
                word, j = _read_shell_word(seg, j)
                if word and not (is_amp and (word == "-" or word.isdigit())):
                    targets.append(word)
                out_chars.append(" ")
                i = j
                continue

            # Input redirect: < file or <& fd
            if ch == "<":
                _pop_leading_fd()
                j = i + 1
                if j < n and seg[j] == "&":
                    j += 1
                while j < n and seg[j].isspace():
                    j += 1
                _, j = _read_shell_word(seg, j)
                out_chars.append(" ")
                i = j
                continue

        out_chars.append(ch)
        i += 1

    return "".join(out_chars), targets


def _unwrap_tokens(tokens: list[str], seg_cwd: Path) -> tuple[list[str], dict[str, str], Path]:
    """Unwrap shell keywords, env assignments, and transparent wrappers. Returns (tokens, seg_env, eff_cwd)."""
    import shlex

    toks = list(tokens)
    seg_env: dict[str, str] = {}
    eff_cwd = seg_cwd

    changed = True
    while changed and toks:
        changed = False
        while toks and toks[0] in SHELL_COMPOUND_KEYWORDS:
            toks.pop(0)
            changed = True
        while toks and ENV_ASSIGN_RE.match(toks[0]):
            k, v = toks.pop(0).split("=", 1)
            seg_env[k] = v
            changed = True
        if not toks:
            break

        head = os.path.basename(toks[0])
        if head in ("nohup",):
            toks.pop(0)
            changed = True
        elif head == "env":
            toks.pop(0)
            while toks:
                t = toks[0]
                if t == "--":
                    toks.pop(0)
                    break
                if t in ("-C", "--chdir") and len(toks) >= 2:
                    toks.pop(0)
                    chdir_arg = toks.pop(0)
                    if chdir_arg and not chdir_arg.startswith("$"):
                        eff_cwd = wt.resolve_path_safe(chdir_arg, base_dir=eff_cwd)
                    continue
                if t.startswith("--chdir="):
                    chdir_arg = toks.pop(0).split("=", 1)[1]
                    if chdir_arg and not chdir_arg.startswith("$"):
                        eff_cwd = wt.resolve_path_safe(chdir_arg, base_dir=eff_cwd)
                    continue
                if t in ("-S", "--split-string") and len(toks) >= 2:
                    toks.pop(0)
                    split_val = toks.pop(0)
                    try:
                        spliced = shlex.split(split_val)
                    except ValueError:
                        spliced = split_val.split()
                    toks = spliced + toks
                    continue
                if t.startswith("--split-string="):
                    split_val = toks.pop(0).split("=", 1)[1]
                    try:
                        spliced = shlex.split(split_val)
                    except ValueError:
                        spliced = split_val.split()
                    toks = spliced + toks
                    continue
                if t in ("-u", "-P", "--unset") and len(toks) >= 2:
                    toks.pop(0)
                    toks.pop(0)
                    continue
                if t.startswith("-"):
                    toks.pop(0)
                    continue
                if ENV_ASSIGN_RE.match(t):
                    k, v = toks.pop(0).split("=", 1)
                    seg_env[k] = v
                    continue
                break
            changed = True
        elif head == "command":
            toks.pop(0)
            is_lookup = False
            while toks and toks[0].startswith("-"):
                t = toks.pop(0)
                if t == "--":
                    break
                if "v" in t or "V" in t:
                    is_lookup = True
            if is_lookup:
                return [], seg_env, eff_cwd
            changed = True
        elif head in ("builtin", "time"):
            toks.pop(0)
            while toks and toks[0].startswith("-"):
                t = toks.pop(0)
                if t == "--":
                    break
            changed = True
        elif head == "exec":
            toks.pop(0)
            while toks and toks[0].startswith("-"):
                t = toks.pop(0)
                if t == "--":
                    break
                if t == "-a" and toks:
                    toks.pop(0)
            changed = True
        elif head == "nice":
            toks.pop(0)
            if toks and toks[0] == "-n" and len(toks) >= 2:
                toks.pop(0)
                toks.pop(0)
            elif toks and toks[0].startswith("-"):
                toks.pop(0)
            changed = True
        elif head == "caffeinate":
            toks.pop(0)
            while toks and toks[0].startswith("-"):
                t = toks.pop(0)
                if t == "--":
                    break
                if t in ("-t", "-w") and toks:
                    toks.pop(0)
            changed = True
        elif head == "sudo":
            toks.pop(0)
            while toks and toks[0].startswith("-"):
                t = toks.pop(0)
                if t == "--":
                    break
                if t in ("-u", "-g", "-C", "-p", "-h", "-r", "-t", "-U") and toks:
                    toks.pop(0)
            changed = True

    return toks, seg_env, eff_cwd


def _active_worktree_for_session(payload: dict[str, Any]) -> dict[str, Any] | None:
    brain_dir = wt.brain_dir_from_hook_payload(payload)
    if brain_dir is None:
        return None
    state = wt.read_worktree_state(wt.state_file_for_brain_dir(brain_dir))
    if not state or state.get("state") != "active":
        return None
    wt_path_raw = state.get("worktree_path")
    main_dir_raw = state.get("main_dir")
    if not isinstance(wt_path_raw, str) or not wt_path_raw.strip() or "\x00" in wt_path_raw:
        return None
    if not isinstance(main_dir_raw, str) or not main_dir_raw.strip() or "\x00" in main_dir_raw:
        return None
    try:
        wt_path = wt.resolve_path_safe(wt_path_raw)
        if not wt_path.is_dir():
            return None
    except (OSError, ValueError):
        return None
    wt_info = wt.find_git_repo_info(wt_path)
    if wt_info is None or not wt_info["is_linked"] or not wt.same_resolved_path(wt_info["main_root"], main_dir_raw):
        return None
    return state


def _is_main_protected(
    main_root: Path,
    cfg: dict[str, Any],
    repo_cfg: dict[str, Any],
    active_wt: dict[str, Any] | None,
) -> tuple[bool, bool, bool]:
    guard_cfg = repo_cfg.get("guard") if isinstance(repo_cfg.get("guard"), dict) else {}
    if not guard_cfg.get("enabled", True):
        return False, False, False
    mode = str(guard_cfg.get("mode") or "active-and-strict").strip().lower()
    if mode not in wt.VALID_GUARD_MODES:
        print(f"Warning: invalid guard.mode {mode!r}; treating as 'active-and-strict'", file=sys.stderr)
        mode = "active-and-strict"
    if mode == "off":
        return False, False, False

    is_active_main = active_wt is not None and wt.same_resolved_path(active_wt["main_dir"], main_root)
    is_strict_main = mode == "active-and-strict" and wt.is_strict_main_repo(cfg, main_root)
    return (is_active_main or is_strict_main), is_active_main, is_strict_main


def _check_main_path_write(
    target: Path,
    main_root: Path,
    cfg: dict[str, Any],
    active_wt: dict[str, Any] | None,
    *,
    via_shell: bool = False,
) -> tuple[bool, str]:
    """Unified protection policy for file writes and shell redirections inside a main repo."""
    repo_cfg = wt.resolve_repo_config(cfg, main_root)
    protected, is_active_main, _ = _is_main_protected(main_root, cfg, repo_cfg, active_wt)
    if not protected:
        return True, ""

    rel_posix = wt.rel_posix_within(target, main_root)
    if rel_posix is None or rel_posix == ".":
        return True, ""

    allow_patterns = repo_cfg.get("guard", {}).get("allow_main_paths", [])
    if isinstance(allow_patterns, list) and wt.match_allow_path(rel_posix, allow_patterns):
        return True, ""

    is_dot_git = rel_posix == ".git" or rel_posix.startswith(".git/")
    if not is_dot_git:
        if not _git_is_tracked(main_root, rel_posix) and _git_is_ignored(main_root, rel_posix):
            return True, ""

    verb = "shell redirection to" if via_shell else "write to"
    if is_active_main and active_wt is not None:
        wt_target = Path(active_wt["worktree_path"]) / rel_posix
        branch = active_wt.get("branch") or active_wt.get("worktree_name") or "active worktree"
        return (
            False,
            f"Blocked {verb} main repo '{rel_posix}' while worktree '{branch}' is active. "
            f"Target '{wt_target}' instead (or run `agy-wt exit` if leaving this worktree).",
        )

    return (
        False,
        f"Blocked {verb} strict main repo '{main_root.name}' ('{rel_posix}'). "
        f"Run `agy-wt enter <branch>` and edit inside the linked worktree. "
        f"(If this is an untracked local-only file, add its path to '{main_root}/.git/info/exclude' first.)",
    )


def _check_file_write(
    target_raw: str,
    cwd: Path,
    cfg: dict[str, Any],
    active_wt: dict[str, Any] | None,
) -> tuple[bool, str]:
    if not target_raw:
        return True, ""
    if "\x00" in target_raw:
        return False, "Blocked file write with invalid NUL byte in path."
    target = wt.resolve_path_safe(target_raw, base_dir=cwd)
    repo = wt.find_git_repo_info(target)
    if repo is None or repo["is_linked"]:
        return True, ""
    return _check_main_path_write(target, repo["main_root"], cfg, active_wt, via_shell=False)


def _parse_git_invocation(
    tokens: list[str],
    seg_cwd: Path,
    seg_env: dict[str, str],
) -> tuple[Path, Path | None, str, list[str]]:
    eff_dir = seg_cwd
    explicit_gd: Path | None = None

    if seg_env.get("GIT_WORK_TREE"):
        eff_dir = wt.resolve_path_safe(seg_env["GIT_WORK_TREE"], base_dir=eff_dir)
    if seg_env.get("GIT_DIR"):
        explicit_gd = wt.resolve_path_safe(seg_env["GIT_DIR"], base_dir=seg_cwd)

    idx = 1
    n = len(tokens)
    while idx < n:
        tok = tokens[idx]
        if tok == "-C" and idx + 1 < n:
            eff_dir = wt.resolve_path_safe(tokens[idx + 1], base_dir=eff_dir)
            idx += 2
            continue
        if tok.startswith("-C") and len(tok) > 2:
            eff_dir = wt.resolve_path_safe(tok[2:], base_dir=eff_dir)
            idx += 1
            continue
        if tok == "--git-dir" and idx + 1 < n:
            explicit_gd = wt.resolve_path_safe(tokens[idx + 1], base_dir=eff_dir)
            idx += 2
            continue
        if tok.startswith("--git-dir="):
            explicit_gd = wt.resolve_path_safe(tok.split("=", 1)[1], base_dir=eff_dir)
            idx += 1
            continue
        if tok == "--work-tree" and idx + 1 < n:
            eff_dir = wt.resolve_path_safe(tokens[idx + 1], base_dir=eff_dir)
            idx += 2
            continue
        if tok.startswith("--work-tree="):
            eff_dir = wt.resolve_path_safe(tok.split("=", 1)[1], base_dir=eff_dir)
            idx += 1
            continue
        if tok in ("-c", "--namespace", "--super-prefix", "--config-env") and idx + 1 < n:
            idx += 2
            continue
        if tok.startswith("-"):
            idx += 1
            continue
        return eff_dir, explicit_gd, tok, tokens[idx + 1 :]
    return eff_dir, explicit_gd, "", []


def _normalize_branch_ref(ref: str) -> str:
    s = ref.strip()
    if s.startswith("refs/heads/"):
        s = s[len("refs/heads/") :]
    return s.lower() if sys.platform == "darwin" else s


def _check_git_main_mutation(subcmd: str, rest: list[str], main_branch: str) -> tuple[bool, str]:
    if not subcmd:
        return True, ""

    if subcmd in GIT_ALWAYS_BLOCKED_SUBCMDS:
        return False, f"`git {subcmd}` is blocked in protected main repository."

    if subcmd == "pull":
        has_ff_only = False
        for arg in rest:
            if arg == "--ff-only":
                has_ff_only = True
            elif arg in GIT_PULL_FORBIDDEN_FLAGS:
                return False, f"`git pull {arg}` is blocked in protected main repository; use `git pull --ff-only`."
            elif arg.startswith("--rebase=") and arg.lower() != "--rebase=false":
                return False, f"`git pull {arg}` is blocked in protected main repository; use `git pull --ff-only`."
        if has_ff_only:
            return True, ""
        return False, "Use `git pull --ff-only` in protected main repository (non-ff pull is blocked)."

    if subcmd == "branch":
        has_delete = False
        has_list = False
        positionals: list[str] = []
        skip_next = False
        end_opts = False
        for arg in rest:
            if skip_next:
                skip_next = False
                continue
            if end_opts:
                positionals.append(arg)
                continue
            if arg == "--":
                end_opts = True
                continue
            if arg in ("-d", "-D", "--delete"):
                has_delete = True
                continue
            if arg in ("-l", "--list", "-a", "--all", "-r", "--remotes", "--show-current"):
                has_list = True
                continue
            if COMBINED_BRANCH_LIST_SHORT_RE.fullmatch(arg):
                if any(c in arg for c in ("a", "r", "l")):
                    has_list = True
                continue
            if arg in GIT_BRANCH_LIST_FLAGS or arg.startswith(GIT_BRANCH_LIST_PREFIXES):
                if arg in GIT_BRANCH_LIST_VALUE_FLAGS:
                    skip_next = True
                continue
            if arg.startswith("-"):
                return False, f"`git branch {arg}` is blocked in protected main repository."
            positionals.append(arg)

        if has_delete:
            if not positionals:
                return False, "`git branch -d/-D` requires a branch name."
            protected_set = {_normalize_branch_ref(b) for b in PROTECTED_BRANCH_NAMES}
            if main_branch:
                protected_set.add(_normalize_branch_ref(main_branch))
            for b in positionals:
                if _normalize_branch_ref(b) in protected_set:
                    return False, f"Deleting protected branch `{b}` is blocked."
            return True, ""

        if positionals and not has_list:
            return False, "Creating a branch in protected main repository is blocked; use `agy-wt enter <branch>`."
        return True, ""

    if subcmd == "push":
        protected_set = {_normalize_branch_ref(b) for b in PROTECTED_BRANCH_NAMES}
        if main_branch:
            protected_set.add(_normalize_branch_ref(main_branch))

        has_delete = False
        positionals: list[str] = []
        skip_next = False
        end_opts = False
        for arg in rest:
            if skip_next:
                skip_next = False
                continue
            if end_opts:
                positionals.append(arg)
                continue
            if arg == "--":
                end_opts = True
                continue
            if arg in ("--delete", "-d"):
                has_delete = True
                continue
            if arg in GIT_PUSH_VALUE_FLAGS:
                skip_next = True
                continue
            if arg.startswith("-"):
                continue
            positionals.append(arg)

        if has_delete:
            branches = positionals[1:] if len(positionals) >= 2 else positionals
            if branches and all(_normalize_branch_ref(b) not in protected_set for b in branches):
                return True, ""
            return False, "Deleting a protected remote branch is blocked."

        if len(positionals) >= 2 and all(
            ref.startswith(":") and ref[1:] and _normalize_branch_ref(ref[1:]) not in protected_set
            for ref in positionals[1:]
        ):
            return True, ""
        return False, "`git push` from protected main repository is blocked; push from the linked worktree."

    return True, ""


def _effective_make_dir(tokens: list[str], seg_cwd: Path) -> Path:
    eff = seg_cwd
    idx = 1
    n = len(tokens)
    while idx < n:
        tok = tokens[idx]
        if tok in ("-C", "--directory") and idx + 1 < n:
            eff = wt.resolve_path_safe(tokens[idx + 1], base_dir=eff)
            idx += 2
            continue
        if tok.startswith("-C") and len(tok) > 2:
            eff = wt.resolve_path_safe(tok[2:], base_dir=eff)
            idx += 1
            continue
        if tok.startswith("--directory="):
            eff = wt.resolve_path_safe(tok.split("=", 1)[1], base_dir=eff)
            idx += 1
            continue
        idx += 1
    return eff


def _is_make_install_tokens(tokens: list[str]) -> bool:
    """Structurally check whether parsed `make`/`gmake` tokens invoke an `install` target."""
    idx = 1
    n = len(tokens)
    req_val_flags = frozenset({"-C", "--directory", "-f", "--file", "--makefile", "-I", "-o", "-W"})
    opt_num_flags = frozenset({"-j", "--jobs", "-l", "--load-average"})
    while idx < n:
        tok = tokens[idx]
        if tok == "--":
            idx += 1
            break
        if tok in req_val_flags:
            idx += 2
            continue
        if tok in opt_num_flags:
            if idx + 1 < n and NUM_ARG_RE.fullmatch(tokens[idx + 1]):
                idx += 2
            else:
                idx += 1
            continue
        if tok.startswith("-"):
            idx += 1
            continue
        if "=" in tok and not tok.startswith("="):
            idx += 1
            continue
        if tok == "install":
            return True
        idx += 1
    while idx < n:
        if tokens[idx] == "install":
            return True
        idx += 1
    return False


def _extract_shell_c_script(tokens: list[str]) -> str | None:
    """Extract inline script from `sh -c '...'` / `zsh -lc '...'` invocations."""
    idx = 1
    n = len(tokens)
    while idx < n:
        tok = tokens[idx]
        if tok == "--":
            return None
        if tok == "-c" or (tok.startswith("-") and not tok.startswith("--") and "c" in tok[1:]):
            return tokens[idx + 1] if idx + 1 < n else None
        if tok.startswith("-"):
            idx += 1
            continue
        return None
    return None


def _resolve_protected_paths(repo_cfg: dict[str, Any], main_root: Path) -> list[Path]:
    raw = repo_cfg.get("protected_paths")
    if not isinstance(raw, list):
        return []
    out: list[Path] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip() or "\x00" in item:
            continue
        try:
            out.append(wt.resolve_path_safe(item.strip(), base_dir=main_root))
        except (OSError, ValueError):
            continue
    return out


def _check_protected_path_deletion(
    cmd0: str,
    tokens: list[str],
    seg_cwd: Path,
    cfg: dict[str, Any],
) -> tuple[bool, str]:
    """Block `rm`/`rmdir`/`unlink` targeting any configured `protected_paths` entry."""
    if cmd0 not in DELETE_CMDS:
        return True, ""

    targets: list[Path] = []
    end_opts = False
    for arg in tokens[1:]:
        if not end_opts and arg == "--":
            end_opts = True
            continue
        if not end_opts and arg.startswith("-"):
            continue
        if not arg or "\x00" in arg or arg.startswith("$"):
            continue
        try:
            targets.append(wt.resolve_path_safe(arg, base_dir=seg_cwd))
        except (OSError, ValueError):
            continue

    if not targets:
        return True, ""

    candidate_mains: list[Path] = []
    seen_mains: set[str] = set()
    for p in (seg_cwd, *targets):
        info = wt.find_git_repo_info(p)
        if info is not None:
            m = info["main_root"]
            k = str(m).lower() if sys.platform == "darwin" else str(m)
            if k not in seen_mains:
                seen_mains.add(k)
                candidate_mains.append(m)

    protected_entries: list[tuple[Path, str]] = []
    for m in candidate_mains:
        rcfg = wt.resolve_repo_config(cfg, m)
        gcfg = rcfg.get("guard") if isinstance(rcfg.get("guard"), dict) else {}
        if not gcfg.get("enabled", True) or str(gcfg.get("mode") or "").lower() == "off":
            continue
        for pp in _resolve_protected_paths(rcfg, m):
            protected_entries.append((pp, m.name))

    g_guard = cfg.get("guard") if isinstance(cfg.get("guard"), dict) else {}
    if g_guard.get("enabled", True) and str(g_guard.get("mode") or "").lower() != "off":
        for item in cfg.get("protected_paths", []) if isinstance(cfg.get("protected_paths"), list) else []:
            if isinstance(item, str) and item.strip().startswith(("~", "/")):
                try:
                    protected_entries.append((wt.resolve_path_safe(item.strip()), "global"))
                except (OSError, ValueError):
                    pass

    repos_map = cfg.get("repos") if isinstance(cfg.get("repos"), dict) else {}
    for repo_key, rval in repos_map.items():
        if not isinstance(rval, dict):
            continue
        eff_g = wt.effective_guard_for_override(g_guard, rval)
        if not eff_g.get("enabled", True) or str(eff_g.get("mode") or "").lower() == "off":
            continue
        for item in rval.get("protected_paths", []) if isinstance(rval.get("protected_paths"), list) else []:
            if isinstance(item, str) and item.strip().startswith(("~", "/")):
                try:
                    protected_entries.append((wt.resolve_path_safe(item.strip()), str(repo_key)))
                except (OSError, ValueError):
                    pass

    for target in targets:
        for prot, scope in protected_entries:
            if wt.is_path_within(target, prot) or wt.is_path_within(prot, target):
                return (
                    False,
                    f"Blocked `{cmd0}` on protected path '{target}' (protected by '{prot}' in {scope} config).",
                )
    return True, ""


def _check_run_command(
    cmd_line: str,
    cwd: Path,
    cfg: dict[str, Any],
    active_wt: dict[str, Any] | None,
    *,
    _depth: int = 0,
) -> tuple[bool, str]:
    """Validate a shell command string against worktree, main-repo, and protected_paths guardrails."""
    import shlex

    if not cmd_line or not cmd_line.strip() or _depth > 3:
        return True, ""

    parsed_segments = _parse_shell_segments(cmd_line)
    seg_cwd = cwd
    prev_cwd = cwd
    cwd_stack: list[tuple[Path, Path]] = []

    for seg, opens, closes, in_pipe in parsed_segments:
        for _ in range(opens):
            cwd_stack.append((seg_cwd, prev_cwd))

        if seg:
            clean_seg, redir_targets = _strip_redirections_for_tokens(seg)

            try:
                raw_tokens = shlex.split(clean_seg, comments=True)
            except ValueError:
                raw_tokens = clean_seg.split()

            tokens, seg_env, eff_seg_cwd = _unwrap_tokens(raw_tokens, seg_cwd) if raw_tokens else ([], {}, seg_cwd)

            # 0. Check redirection targets against unified main-repo write policy
            for target_raw in redir_targets:
                if target_raw == "/dev/null" or target_raw.startswith("$"):
                    continue
                if "\x00" in target_raw:
                    return False, "Blocked shell redirection with NUL byte in path."
                target_path = wt.resolve_path_safe(target_raw, base_dir=eff_seg_cwd)
                repo = wt.find_git_repo_info(target_path)
                if repo is not None and not repo["is_linked"]:
                    ok_w, err_w = _check_main_path_write(
                        target_path, repo["main_root"], cfg, active_wt, via_shell=True
                    )
                    if not ok_w:
                        return False, err_w

            if tokens:
                cmd0 = os.path.basename(tokens[0])

                # Track cd within chained commands (isolated inside pipeline stages)
                if cmd0 == "cd":
                    if not in_pipe:
                        cd_args: list[str] = []
                        end_opts = False
                        for a in tokens[1:]:
                            if not end_opts and a == "--":
                                end_opts = True
                                continue
                            if not end_opts and a in ("-L", "-P", "-e"):
                                continue
                            cd_args.append(a)
                        if not cd_args:
                            prev_cwd, seg_cwd = seg_cwd, wt.resolve_path_safe(Path.home())
                        elif cd_args[0] == "-":
                            seg_cwd, prev_cwd = prev_cwd, seg_cwd
                        elif cd_args[0].startswith("$"):
                            prev_cwd, seg_cwd = seg_cwd, cwd
                        else:
                            prev_cwd = seg_cwd
                            seg_cwd = wt.resolve_path_safe(cd_args[0], base_dir=seg_cwd)
                elif cmd0 == "agy-wt":
                    pass
                else:
                    # Recursively inspect `sh -c '...'` / `zsh -c '...'`
                    if cmd0 in SHELL_BINS:
                        sub_script = _extract_shell_c_script(tokens)
                        if sub_script:
                            ok_sub, err_sub = _check_run_command(
                                sub_script, eff_seg_cwd, cfg, active_wt, _depth=_depth + 1
                            )
                            if not ok_sub:
                                return False, err_sub

                    # 1. Protect configured protected_paths from rm/rmdir/unlink
                    ok_del, err_del = _check_protected_path_deletion(cmd0, tokens, eff_seg_cwd, cfg)
                    if not ok_del:
                        return False, err_del

                    # 2. Block install commands inside linked worktrees
                    eff_dir = _effective_make_dir(tokens, eff_seg_cwd) if cmd0 in MAKE_BINS else eff_seg_cwd
                    eff_repo = wt.find_git_repo_info(eff_dir)
                    if eff_repo is not None and eff_repo["is_linked"]:
                        repo_cfg = wt.resolve_repo_config(cfg, eff_repo["main_root"])
                        guard_cfg = repo_cfg.get("guard") if isinstance(repo_cfg.get("guard"), dict) else {}
                        guard_active = (
                            guard_cfg.get("enabled", True)
                            and str(guard_cfg.get("mode") or "active-and-strict").lower() != "off"
                        )
                        if guard_active and guard_cfg.get("block_install_in_worktree", True):
                            if cmd0 in MAKE_BINS and _is_make_install_tokens(tokens):
                                return (
                                    False,
                                    f"Blocked `{cmd0} install` inside linked worktree '{eff_repo['root']}'. "
                                    f"Installing from a worktree leaves broken symlinks after worktree removal. "
                                    f"Run install in main repo '{eff_repo['main_root']}' after merge.",
                                )
                            if cmd0 not in DATA_ONLY_CMDS and cmd0 not in SHELL_BINS:
                                patterns = guard_cfg.get("install_command_patterns", [])
                                default_make_pat = wt.DEFAULT_CONFIG["guard"]["install_command_patterns"][0]
                                if isinstance(patterns, list):
                                    for pat in patterns:
                                        if not isinstance(pat, str) or not pat:
                                            continue
                                        # Default make pattern is fully covered structurally by make/gmake + recursive sh -c
                                        if pat == default_make_pat:
                                            continue
                                        try:
                                            if re.search(pat, clean_seg):
                                                return (
                                                    False,
                                                    f"Blocked install command inside linked worktree '{eff_repo['root']}'. "
                                                    f"Installing from a worktree leaves broken symlinks after worktree removal. "
                                                    f"Run install in main repo '{eff_repo['main_root']}' after merge.",
                                                )
                                        except re.error as exc:
                                            print(
                                                f"Warning: invalid guard.install_command_patterns regex {pat!r}: {exc}",
                                                file=sys.stderr,
                                            )

                    # 3. Block mutating git commands in protected main repositories
                    if cmd0 == "git":
                        git_dir_target, explicit_gd, subcmd, rest = _parse_git_invocation(tokens, eff_seg_cwd, seg_env)
                        git_repo = (
                            wt.inspect_git_dir_directly(explicit_gd)
                            if explicit_gd is not None
                            else wt.find_git_repo_info(git_dir_target)
                        )
                        if git_repo is not None and not git_repo["is_linked"]:
                            main_root = git_repo["main_root"]
                            repo_cfg = wt.resolve_repo_config(cfg, main_root)
                            protected, is_active_main, _ = _is_main_protected(main_root, cfg, repo_cfg, active_wt)
                            if protected:
                                ok, err = _check_git_main_mutation(subcmd, rest, git_repo.get("branch") or "")
                                if not ok:
                                    if is_active_main and active_wt is not None:
                                        wt_path = active_wt["worktree_path"]
                                        return False, f"{err} Run in active worktree instead: `git -C '{wt_path}' ...`"
                                    return False, f"{err} Run `agy-wt enter <branch>` and execute git changes in the worktree."

        for _ in range(closes):
            if cwd_stack:
                seg_cwd, prev_cwd = cwd_stack.pop()

    return True, ""


def _maybe_record_agy_wt_session_hint(payload: dict[str, Any], cmd_line: str, cwd: Path) -> None:
    """Record private session hint ONLY when a parsed shell segment actually executes `agy-wt`."""
    if "agy-wt" not in cmd_line:
        return
    import shlex

    brain_dir = wt.brain_dir_from_hook_payload(payload)
    cid = str(
        payload.get("conversationId")
        or payload.get("session_id")
        or payload.get("conversation_id")
        or ""
    ).strip()
    if brain_dir is None and not wt.is_safe_session_id(cid):
        return

    seg_cwd = cwd
    prev_cwd = cwd
    cwd_stack: list[tuple[Path, Path]] = []
    target_dirs: list[Path] = []

    for seg, opens, closes, in_pipe in _parse_shell_segments(cmd_line):
        for _ in range(opens):
            cwd_stack.append((seg_cwd, prev_cwd))
        if seg:
            clean_seg, _ = _strip_redirections_for_tokens(seg)
            try:
                raw_tokens = shlex.split(clean_seg, comments=True)
            except ValueError:
                raw_tokens = clean_seg.split()
            tokens, _, eff_seg_cwd = _unwrap_tokens(raw_tokens, seg_cwd) if raw_tokens else ([], {}, seg_cwd)
            if tokens:
                cmd0 = os.path.basename(tokens[0])
                if cmd0 == "cd" and not in_pipe:
                    cd_args = [a for a in tokens[1:] if a not in ("-L", "-P", "-e", "--")]
                    if not cd_args:
                        prev_cwd, seg_cwd = seg_cwd, wt.resolve_path_safe(Path.home())
                    elif cd_args[0] == "-":
                        seg_cwd, prev_cwd = prev_cwd, seg_cwd
                    elif not cd_args[0].startswith("$"):
                        prev_cwd = seg_cwd
                        seg_cwd = wt.resolve_path_safe(cd_args[0], base_dir=seg_cwd)
                else:
                    is_agy_wt = cmd0 == "agy-wt" or (
                        cmd0.startswith("python") and len(tokens) >= 2 and os.path.basename(tokens[1]) == "agy-wt"
                    )
                    if is_agy_wt:
                        target_dir = eff_seg_cwd
                        for idx, tok in enumerate(tokens):
                            if tok == "--repo" and idx + 1 < len(tokens):
                                target_dir = wt.resolve_path_safe(tokens[idx + 1], base_dir=eff_seg_cwd)
                                break
                            if tok.startswith("--repo="):
                                target_dir = wt.resolve_path_safe(tok.split("=", 1)[1], base_dir=eff_seg_cwd)
                                break
                        target_dirs.append(target_dir)
        for _ in range(closes):
            if cwd_stack:
                seg_cwd, prev_cwd = cwd_stack.pop()

    tp = str(payload.get("transcriptPath") or payload.get("transcript_path") or "")
    for tdir in target_dirs:
        repo = wt.find_git_repo_info(tdir)
        if repo is None:
            continue
        hint: dict[str, Any] = {
            "conversation_id": cid,
            "brain_dir": str(brain_dir) if brain_dir is not None else "",
            "transcript_path": tp,
            "cwd": str(tdir),
        }
        wt.write_session_hint(repo["main_root"], hint)


def evaluate_payload(payload: dict[str, Any], config_path: Path | None = None) -> tuple[bool, str]:
    """Core testable entrypoint returning (allowed, reason)."""
    tool_call = payload.get("toolCall") if isinstance(payload.get("toolCall"), dict) else {}
    tool_name = str(tool_call.get("name") or "").strip()
    args = tool_call.get("args") if isinstance(tool_call.get("args"), dict) else {}

    raw_cwd = payload.get("cwd")
    if not isinstance(raw_cwd, str) or not raw_cwd.strip():
        ws = payload.get("workspacePaths")
        if isinstance(ws, list) and ws and isinstance(ws[0], str):
            raw_cwd = ws[0]
        else:
            raw_cwd = os.getcwd()
    cwd = wt.resolve_path_safe(raw_cwd)

    if tool_name == "run_command":
        cmd_line = str(args.get("CommandLine") or args.get("command") or "")
        try:
            _maybe_record_agy_wt_session_hint(payload, cmd_line, cwd)
        except Exception as exc:
            print(f"Warning: failed recording agy-wt session hint: {exc}", file=sys.stderr)

    cfg, cfg_err = wt.load_config_checked(config_path=config_path)
    if cfg_err:
        print(f"Error: {cfg_err}", file=sys.stderr)
        if tool_name in FILE_WRITE_TOOLS or tool_name == "run_command":
            return False, f"agy-worktree config error: {cfg_err}. Fix config or disable guard before running mutating tools."

    guard_cfg = cfg.get("guard") if isinstance(cfg.get("guard"), dict) else {}
    has_repo_overrides = isinstance(cfg.get("repos"), dict) and len(cfg["repos"]) > 0
    if not has_repo_overrides and (
        not guard_cfg.get("enabled", True) or str(guard_cfg.get("mode") or "").lower() == "off"
    ):
        return True, ""

    active_wt = _active_worktree_for_session(payload)

    if tool_name in FILE_WRITE_TOOLS:
        target_raw = ""
        for k in FILE_PATH_ARG_KEYS:
            v = args.get(k)
            if isinstance(v, str) and v.strip():
                target_raw = v.strip()
                break
        return _check_file_write(target_raw, cwd, cfg, active_wt)

    if tool_name == "run_command":
        cmd_line = str(args.get("CommandLine") or args.get("command") or "")
        return _check_run_command(cmd_line, cwd, cfg, active_wt)

    return True, ""


def main() -> int:
    try:
        raw = sys.stdin.read()
    except Exception as exc:
        print(f"Warning: worktree-guard failed reading stdin: {exc}", file=sys.stderr)
        return _allow()

    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception as exc:
        print(f"Warning: worktree-guard failed parsing JSON payload: {exc}", file=sys.stderr)
        return _allow()

    if not isinstance(payload, dict):
        return _allow()

    tool_call = payload.get("toolCall") if isinstance(payload.get("toolCall"), dict) else {}
    tool_name = str(tool_call.get("name") or "").strip()

    try:
        allowed, reason = evaluate_payload(payload)
    except Exception as exc:
        print(f"Error: worktree-guard internal error on {tool_name or 'unknown'}: {exc}", file=sys.stderr)
        if tool_name in FILE_WRITE_TOOLS or tool_name == "run_command":
            return _deny(f"agy-worktree guard internal error ({exc}); blocking mutating tool for safety.")
        return _allow()

    return _allow() if allowed else _deny(reason)


if __name__ == "__main__":
    raise SystemExit(main())
