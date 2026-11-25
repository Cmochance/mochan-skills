#!/usr/bin/env python3
"""PreToolUse hook enforcing strict read-only isolation when TRI_ORCHESTRATOR_ACCESS=readonly."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from typing import Any

READONLY_NATIVE_TOOLS = frozenset(
    {
        "read_file",
        "view_file",
        "view_file_outline",
        "view_code_item",
        "list_dir",
        "find_by_name",
        "grep_search",
        "search_web",
        "read_url_content",
        "list_resources",
        "read_resource",
        "update_steps",
    }
)

SAFE_INSPECT_BINS = frozenset(
    {
        "rg",
        "grep",
        "egrep",
        "fgrep",
        "fd",
        "ls",
        "stat",
        "wc",
        "head",
        "tail",
        "cat",
        "nl",
        "cut",
        "tr",
        "sort",
        "uniq",
        "jq",
        "diff",
        "file",
        "du",
        "pwd",
        "which",
        "basename",
        "dirname",
        "realpath",
        "tree",
        "true",
        "false",
        "echo",
        "printf",
    }
)

BLOCKED_ENV_ASSIGNMENTS = frozenset(
    {
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "PYTHONPATH",
        "GIT_INDEX_FILE",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_EXEC_PATH",
        "BASH_ENV",
        "ENV",
        "ZDOTDIR",
    }
)

FIND_FORBIDDEN_PREFIXES = (
    "-delete",
    "-exec",
    "-execdir",
    "-ok",
    "-okdir",
    "-fprint",
    "-fls",
    "-fprintf",
)

GIT_READONLY_SUBCMDS = frozenset(
    {
        "status",
        "diff",
        "log",
        "show",
        "rev-parse",
        "ls-files",
        "ls-tree",
        "cat-file",
        "blame",
        "grep",
        "describe",
        "shortlog",
        "symbolic-ref",
        "for-each-ref",
        "merge-base",
        "rev-list",
        "branch",
        "tag",
    }
)

SAFE_GIT_CONFIG_PREFIXES = (
    "core.quotepath=",
    "color.",
    "diff.algorithm=",
    "diff.context=",
    "safe.directory=",
)

GIT_LIST_FLAGS = frozenset(
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
    }
)

GIT_LIST_PREFIXES = ("--sort=", "--format=", "--color=", "--contains=", "--merged=", "--points-at=")

ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
REDIR_SAFE_RE = re.compile(r"(?:2>&1|1>&2|(?<![0-9A-Za-z_])[12]?>>?\s*/dev/null(?=$|[\s;&|]))")


def _deny(reason: str) -> int:
    sys.stdout.write(json.dumps({"decision": "deny", "reason": reason}, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


def _allow() -> int:
    sys.stdout.write('{"decision": "allow"}\n')
    sys.stdout.flush()
    return 0


def _split_shell_segments(cmd: str) -> tuple[bool, list[str], str]:
    """Quote-aware splitter that rejects expansions/redirections and splits on &&, ||, ;, |, newline."""
    segments: list[str] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    i = 0
    n = len(cmd)

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
            elif ch == "`" or (ch == "$" and i + 1 < n and cmd[i + 1] == "("):
                return False, [], "Command substitution (`...` or $(...)) is forbidden in read-only mode."
            buf.append(ch)
            i += 1
            continue

        # Outside quotes
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
        if ch == "`" or (ch in ("$", "<", ">") and i + 1 < n and cmd[i + 1] == "("):
            return False, [], "Subshell or process substitution is forbidden in read-only mode."
        if ch == ">":
            return False, [], "Output redirection ('>') is forbidden in read-only mode."

        # Segment delimiters outside quotes
        if cmd[i : i + 2] in ("&&", "||"):
            segments.append("".join(buf))
            buf.clear()
            i += 2
            continue
        if ch in (";", "|", "\n"):
            segments.append("".join(buf))
            buf.clear()
            i += 1
            continue

        buf.append(ch)
        i += 1

    if in_single or in_double:
        return False, [], "Unbalanced quotes in shell command."
    if buf:
        segments.append("".join(buf))
    return True, segments, ""


def _strip_safe_redirections(cmd: str) -> str:
    """Strip harmless `2>&1` and `>/dev/null` outside single quotes."""
    parts: list[str] = []
    in_single = False
    in_double = False
    i = 0
    n = len(cmd)
    while i < n:
        ch = cmd[i]
        if ch == "\\" and not in_single and i + 1 < n:
            parts.append(cmd[i : i + 2])
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            parts.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            parts.append(ch)
            i += 1
            continue
        if not in_single and not in_double:
            m = REDIR_SAFE_RE.match(cmd, i)
            if m:
                i = m.end()
                continue
        parts.append(ch)
        i += 1
    return "".join(parts)


def _validate_git_tokens(tokens: list[str]) -> tuple[bool, str]:
    idx = 1
    n = len(tokens)
    while idx < n:
        tok = tokens[idx]
        if tok in ("-C", "--namespace"):
            idx += 2
            continue
        if tok == "-c":
            if idx + 1 >= n:
                return False, "Missing value for `git -c`."
            kv = tokens[idx + 1].lower()
            if not kv.startswith(SAFE_GIT_CONFIG_PREFIXES):
                return False, f"Git config override `-c {tokens[idx + 1]}` is forbidden in read-only mode."
            idx += 2
            continue
        if tok.startswith("-c"):
            kv = tok[2:].lower()
            if not kv.startswith(SAFE_GIT_CONFIG_PREFIXES):
                return False, f"Git config override `{tok}` is forbidden in read-only mode."
            idx += 1
            continue
        if tok in ("--git-dir", "--work-tree", "-p", "--paginate") or tok.startswith(("--git-dir=", "--work-tree=")):
            return False, f"Git flag `{tok}` is forbidden in read-only mode."
        if tok in ("--no-pager", "--bare", "--no-replace-objects"):
            idx += 1
            continue
        if tok.startswith("-"):
            return False, f"Unsupported git global flag `{tok}` in read-only mode."
        break

    if idx >= n:
        return False, "Missing git subcommand."

    subcmd = tokens[idx]
    if subcmd not in GIT_READONLY_SUBCMDS:
        return False, f"Git subcommand `{subcmd}` is not in the read-only allowlist."

    rest = tokens[idx + 1 :]
    for arg in rest:
        if arg == "--output" or arg.startswith("--output="):
            return False, "Git `--output` file writing is forbidden in read-only mode."

    if subcmd in ("branch", "tag"):
        has_list_flag = False
        positionals: list[str] = []
        skip_next = False
        for arg in rest:
            if skip_next:
                skip_next = False
                continue
            if arg in ("-l", "--list", "-a", "--all", "-r", "--remotes", "--show-current"):
                has_list_flag = True
                continue
            if arg in GIT_LIST_FLAGS or arg.startswith(GIT_LIST_PREFIXES):
                if arg in ("--contains", "--no-contains", "--merged", "--no-merged", "--points-at"):
                    skip_next = True
                continue
            if arg.startswith("-"):
                return False, f"Mutating or unrecognized `git {subcmd}` flag `{arg}` is forbidden in read-only mode."
            positionals.append(arg)
        if positionals and not has_list_flag:
            return False, f"`git {subcmd}` creation/modification is forbidden in read-only mode."

    return True, ""


def is_safe_readonly_shell(cmd_str: str) -> tuple[bool, str]:
    if not isinstance(cmd_str, str) or not cmd_str.strip():
        return False, "Empty command is not allowed."
    if "\x00" in cmd_str:
        return False, "Null byte in command is forbidden."

    sanitized = _strip_safe_redirections(cmd_str)
    ok, segments, err = _split_shell_segments(sanitized)
    if not ok:
        return False, err

    for seg in segments:
        seg_stripped = seg.strip()
        if not seg_stripped:
            continue
        try:
            tokens = shlex.split(seg_stripped)
        except ValueError as exc:
            return False, f"Invalid shell quoting: {exc}"
        if not tokens:
            continue

        while tokens and ENV_ASSIGN_RE.match(tokens[0]):
            var_name = tokens[0].split("=", 1)[0]
            if var_name in BLOCKED_ENV_ASSIGNMENTS or var_name.startswith("DYLD_"):
                return False, f"Setting `{var_name}` is forbidden in read-only mode."
            tokens.pop(0)

        if not tokens:
            continue

        cmd0 = os.path.basename(tokens[0])

        if cmd0 == "find":
            for arg in tokens[1:]:
                if arg.startswith(FIND_FORBIDDEN_PREFIXES):
                    return False, f"`find {arg}` is forbidden in read-only mode."
            continue

        if cmd0 == "git":
            git_ok, git_err = _validate_git_tokens(tokens)
            if not git_ok:
                return False, git_err
            continue

        if cmd0 in SAFE_INSPECT_BINS:
            if cmd0 == "sort":
                for arg in tokens[1:]:
                    if arg == "-o" or arg.startswith("-o") or arg == "--output" or arg.startswith("--output="):
                        return False, f"`sort {arg}` file output is forbidden in read-only mode."
            continue

        return False, (
            f"Command `{cmd0}` is blocked in read-only specialist mode. "
            "Use `read_file` or read-only inspection commands (`rg`, `git diff/log/status/show`, `ls`, `find`)."
        )

    return True, ""


def _is_tri_router_tool(tool_name: str, args: dict[str, Any]) -> bool:
    low = tool_name.lower()
    if "tri-router" in low or "tri_router" in low:
        return True
    if low == "call_mcp_tool":
        srv = str(args.get("ServerName") or args.get("serverName") or "").strip().lower()
        return srv == "tri-router"
    return False


def main() -> int:
    raw = ""
    try:
        raw = sys.stdin.read()
    except Exception:
        pass

    is_readonly = os.environ.get("TRI_ORCHESTRATOR_ACCESS") == "readonly"
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        return _deny("Read-only guard could not parse PreToolUse payload.") if is_readonly else _allow()

    if not isinstance(payload, dict):
        return _deny("Read-only guard received malformed PreToolUse payload.") if is_readonly else _allow()

    tool_call: dict[str, Any] = payload.get("toolCall") if isinstance(payload.get("toolCall"), dict) else {}
    tool_name = str(tool_call.get("name") or "").strip()
    args: dict[str, Any] = tool_call.get("args") if isinstance(tool_call.get("args"), dict) else {}

    # Native Orchestrator bypass: avoid double-orchestration quota waste when session is already Orchestrator (...).
    model_name = str(payload.get("modelName") or "")
    if (
        "orchestrator" in model_name.lower()
        and os.environ.get("TRI_ORCHESTRATOR_CHILD") != "1"
        and _is_tri_router_tool(tool_name, args)
    ):
        return _deny(
            f"Native Orchestrator mode ({model_name}) is active; `tri-router` is disabled to avoid "
            "double-orchestration quota waste. Execute directly with native tools."
        )

    if not is_readonly:
        return _allow()

    if tool_name in READONLY_NATIVE_TOOLS:
        return _allow()

    if tool_name == "manage_task":
        action = str(args.get("Action") or "").strip().lower()
        if action in ("list", "status"):
            return _allow()
        return _deny(f"Read-only specialist mode blocks `manage_task` action `{action}`.")

    if tool_name == "run_command":
        cmd_line = args.get("CommandLine") or args.get("command") or ""
        safe, reason = is_safe_readonly_shell(cmd_line)
        if safe:
            return _allow()
        return _deny(reason)

    return _deny(
        f"Read-only specialist mode (analyze/plan/review): tool `{tool_name or 'unknown'}` is blocked. "
        "Inspect code read-only and return your complete analysis/plan/review directly in your text response."
    )


if __name__ == "__main__":
    raise SystemExit(main())
