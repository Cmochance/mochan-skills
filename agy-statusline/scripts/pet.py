"""Pure-stdlib animated Gemini pixel mascot renderer for agy-statusline.

Renders the blocky lavender-purple Gemini pixel cat (and its diagonal rainbow
prism variant) in 10x16 half-block TrueColor (5 terminal rows), 5-row ASCII,
or 1-line inline mode, aligned right (default) or left, reacting to Antigravity
CLI's live statusLine JSON state (`agent_state`, `tool_confirmation_pending`,
`subagents`, `context_window`, `quota`).
"""

from __future__ import annotations

import math
import os
import re
import time
from typing import Any
import unicodedata

RESET = "\033[0m"
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
ESCAPE_SEQ_RE = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b[PX^_][^\x1b]*\x1b\\"
    r"|\x1b\[[0-9;?]*[ -/]*[@-~]"
    r"|\x1b[@-Z\\-_]"
    r"|\x9d[^\x07\x9c]*(?:\x07|\x9c)"
    r"|\x9b[0-9;?]*[ -/]*[@-~]"
)
WS_BREAK_RE = re.compile(r"[\r\n\t\u2028\u2029]+")

# 24-bit TrueColor palette for the Gemini lavender-purple pixel cat.
# '.' / ' ' = transparent (inherits terminal background cleanly).
PIXEL_COLORS: dict[str, tuple[int, int, int]] = {
    "V": (148, 127, 214),  # #947FD6 Gemini lavender-purple body
    "S": (115, 94, 181),   # #735EB5 deeper purple shading / tail tip
    "L": (182, 167, 230),  # #B6A7E6 soft lavender highlight
    "K": (20, 20, 19),     # #141413 iconic dark 1x2 pixel eyes
    "E": (125, 207, 255),  # glowing cyan code spark
    "Y": (250, 204, 85),   # warm golden star spark
    "R": (247, 118, 142),  # coral-red alert / error
    "Z": (148, 163, 184),  # floating sleep zzz
    "X": (65, 72, 104),    # subtle ground shadow while airborne
}

# Diagonal spectrum stops for the "prism" rainbow aurora variant
PRISM_STOPS: tuple[tuple[int, int, int], ...] = (
    (139, 92, 246),   # violet
    (244, 63, 94),    # rose-red
    (251, 146, 60),   # orange
    (250, 204, 21),   # yellow
    (56, 189, 248),   # sky-cyan
    (59, 130, 246),   # cobalt-blue
    (168, 85, 247),   # iris-purple
)

# Monochrome fallback characters for NO_COLOR / plain themes
MONO_CHARS: dict[str, str] = {
    "K": "@",
    "E": "*",
    "Y": "*",
    "R": "!",
    "X": "_",
    "Z": "z",
}

SPECIES_LIST: tuple[str, ...] = ("gemini", "prism")
STYLES_LIST: tuple[str, ...] = ("pixel", "inline", "ascii")
POSITIONS_LIST: tuple[str, ...] = ("above", "below")
ALIGNS_LIST: tuple[str, ...] = ("right", "left")

GEMINI_ACCENT_ANSI = "\033[38;2;148;127;214m"

# Strictly 10 pixel rows x 16 columns -> compresses to 5 terminal rows x 16 cols.
# Wide chunky rectangular body, pointy corner ears, wide-set 1x2 dark eyes,
# 4 little pixel legs, and curled right tail — with squash-and-stretch bounce.
GEMINI_PIXEL_FRAMES: dict[str, list[list[str]]] = {
    "idle": [
        [
            "................",
            "..V..........V..",
            "..VV........VV..",
            "..VVVVVVVVVVVV..",
            "..VVKVVVVVVKVV.S",
            "..VVKVVVVVVKVV.V",
            "..VVVVVVVVVVVVVV",
            "..VVVVVVVVVVVV..",
            "...V.V....V.V...",
            "...V.V....V.V...",
        ],
        [
            "................",
            "..V..........V..",
            "..VV........VV..",
            "..VVVVVVVVVVVV..",
            "..VVVVVVVVVVVV..",  # gentle blink
            "..VVKVVVVVVKVV.S",
            "..VVVVVVVVVVVVSV",  # tail swish
            "..VVVVVVVVVVVV..",
            "...V.V....V.V...",
            "...V.V....V.V...",
        ],
    ],
    "working": [
        [
            "..V....Y.....V..",  # hop UP 1px + star spark
            "..VV........VV..",
            "..VVVVVVVVVVVV..",
            "..VVKVVVVVVKVV.V",  # happy ^ ^ eyes top
            "..VKVKVVVVKVKV.V",  # happy ^ ^ eyes arch
            "..VVVVVVVVVVVVVV",
            "..VVVVVVVVVVVV..",
            "...V.V....V.V...",  # airborne legs
            "................",  # air gap
            "...XXXXXXXXXX...",  # ground shadow
        ],
        [
            "................",  # squash landing!
            "................",
            "..V..........V..",
            "..VV........VV..",
            ".SVVVVVVVVVVVVS.",
            ".VVVKVVVVVVKVVVV",
            ".VVVKVVVVVVKVVV.",
            ".VVVVVVVVVVVVV..",
            ".VVVVVVVVVVVVV..",
            "...V.V....V.V...",
        ],
    ],
    "tool_use": [
        [
            "..V..........V.E",  # hop + cyan code spark right
            "..VV........VV..",
            "..VVVVVVVVVVVV..",
            "..VVEVVVVVVEVV.V",  # bright cyan focus eyes
            "..VVKVVVVVVKVV.V",
            "..VVVVVVVVVVVVVV",
            "..VVVVVVVVVVVV..",
            "...V.V....V.V...",
            "................",
            "...XXXXXXXXXX...",
        ],
        [
            "E...............",  # grounded + alternating spark left
            "..V..........V..",
            "..VV........VV..",
            "..VVVVVVVVVVVV..",
            "..VVKVVVVVVKVV.S",
            "..VVKVVVVVVKVV.V",
            "..VVVVVVVVVVVVVV",
            "..VVVVVVVVVVVV..",
            "...V.V....V.V...",
            "...V.V....V.V...",
        ],
    ],
    "confirm": [
        [
            "..V....R.....V..",  # hop + alert ping
            "..VV...R....VV..",
            "..VVVVVVVVVVVV..",
            "..VKKVVVVVVKKV.V",  # wide 2x2 startled eyes
            "..VKKVVVVVVKKV.V",
            "..VVVVVVVVVVVVVV",
            "..VVVVVVVVVVVV..",
            "...V.V....V.V...",
            "................",
            "...XXXXXXXXXX...",
        ],
        [
            ".......R........",
            "..V..........V..",
            "..VV........VV..",
            "..VVVVVVVVVVVV..",
            "..VKKVVVVVVKKV.S",
            "..VKKVVVVVVKKV.V",
            "..VVVVVVVVVVVVVV",
            "..VVVVVVVVVVVV..",
            "...V.V....V.V...",
            "...V.V....V.V...",
        ],
    ],
    "error": [
        [
            ".......R........",
            ".......R........",
            "VV............VV",  # airplane ears flattened
            "VVVVVVVVVVVVVVVV",
            "..VVRVVVVVVRVV..",
            "..VVRVVVVVVRVV.S",
            "..VVVVVVVVVVVVVV",
            "..VVVVVVVVVVVV..",
            "...V.V....V.V...",
            "...V.V....V.V...",
        ],
        [
            "................",
            ".......R........",
            "VV............VV",
            "VVVVVVVVVVVVVVVV",
            "..VVRVVVVVVRVV.S",
            "..VVKVVVVVVKVV.V",
            "..VVVVVVVVVVVVVV",
            "..VVVVVVVVVVVV..",
            "..V..V....V..V..",
            "..V..V....V..V..",
        ],
    ],
    "sleep": [
        [
            "...........ZZ...",  # cozy tucked cat loaf + zzz
            "............Z...",
            ".........Z......",
            "..V..........V..",
            "..VV........VV..",
            ".SVVVVVVVVVVVVS.",
            ".VVVVVVVVVVVVVV.",
            ".VVKKVVVVVVKKVV.",
            ".VVVVVVVVVVVVVV.",
            ".VVVVVVVVVVVVVV.",
        ],
        [
            "............ZZ..",  # gentle breathing loaf
            ".............Z..",
            "..........Z.....",
            "................",
            "..V..........V..",
            "..VV........VV..",
            ".SVVVVVVVVVVVVS.",
            ".VVKKVVVVVVKKVV.",
            ".VVVVVVVVVVVVVV.",
            ".VVVVVVVVVVVVVV.",
        ],
    ],
}

# Classic 5-row monospace ASCII sprites (strictly 16 display columns per row)
GEMINI_ASCII_FRAMES: dict[str, list[list[str]]] = {
    "idle": [
        [
            "  /\\        /\\  ",
            " |  o      o  | ",
            " |            |~",
            " |____________| ",
            "   | |    | |   ",
        ],
        [
            "  /\\        /\\  ",
            " |  -      -  | ",
            " |            | ",
            " |____________|~",
            "   | |    | |   ",
        ],
    ],
    "working": [
        [
            "  /\\   *    /\\  ",
            " |  ^      ^  |~",
            " |____________| ",
            "   | |    | |   ",
            "   ..........   ",
        ],
        [
            "                ",
            "  /\\        /\\  ",
            "|   o      o   |",
            "|______________|",
            "   | |    | |   ",
        ],
    ],
    "tool_use": [
        [
            "  /\\        /\\* ",
            " |  o      o  |~",
            " |____________| ",
            "   | |    | |   ",
            "   ..........   ",
        ],
        [
            "* /\\        /\\  ",
            " |  ^      ^  | ",
            " |            |~",
            " |____________| ",
            "   | |    | |   ",
        ],
    ],
    "confirm": [
        [
            "  /\\   !    /\\  ",
            " |  O      O  |~",
            " |____________| ",
            "   | |    | |   ",
            "   ..........   ",
        ],
        [
            "  /\\   ?    /\\  ",
            " |  O      O  | ",
            " |            |~",
            " |____________| ",
            "   | |    | |   ",
        ],
    ],
    "error": [
        [
            "       !        ",
            "__            __",
            " |  x      x  | ",
            " |____________| ",
            "   | |    | |   ",
        ],
        [
            "       !        ",
            "__            __",
            " |  >      <  | ",
            " |____________| ",
            "  |  |    |  |  ",
        ],
    ],
    "sleep": [
        [
            "          zz    ",
            "        z       ",
            "  /\\        /\\  ",
            " |  -      -  | ",
            " (____________) ",
        ],
        [
            "           zz   ",
            "         z      ",
            "                ",
            "  /\\  -  -  /\\  ",
            " (____________) ",
        ],
    ],
}

# Compact 1-line inline companion frames (zero extra vertical rows)
GEMINI_INLINE_FRAMES: dict[str, list[str]] = {
    "idle": ["/\\o.o/\\", "/\\-.-/\\"],
    "working": ["/\\^.^/\\*", "*/\\o.o/\\"],
    "tool_use": ["/\\o.o/\\*", "*/\\^.^/\\"],
    "confirm": ["/\\O.O/\\!", "/\\O.O/\\?"],
    "error": ["/\\x.x/\\!", "/\\>.>/\\!"],
    "sleep": ["/\\-.-/\\z", "/\\-.-/\\Z"],
}

MOOD_META: dict[str, tuple[str, str, str]] = {
    # mood -> (palette_slot, status_tag, bubble_text)
    "error": ("red", "oops!", "hit a snag — let's debug"),
    "confirm": ("yellow", "waiting", "need your ok to proceed!"),
    "tool_use": ("sky", "coding", "running tools..."),
    "working": ("green", "thinking", "working on it..."),
    "reviewing": ("sky", "reviewing", "inspecting changes..."),
    "hungry": ("amber", "low fuel", "quota running low..."),
    "tired": ("amber", "crowded", "context almost full!"),
    "sleep": ("muted", "zzz", "chilling, ready when you are"),
    "idle": ("wt_linked", "ready", "ready to ship!"),
}

MOOD_TO_SPRITE_STATE: dict[str, str] = {
    "error": "error",
    "confirm": "confirm",
    "tool_use": "tool_use",
    "working": "working",
    "reviewing": "working",
    "hungry": "confirm",
    "tired": "error",
    "sleep": "sleep",
    "idle": "idle",
}


def _sanitize_text(text: str) -> str:
    """Strip ANSI/OSC escapes and control chars so user-supplied pet names stay single-line safe."""
    if not text:
        return ""
    cleaned = ESCAPE_SEQ_RE.sub("", text)
    cleaned = WS_BREAK_RE.sub(" ", cleaned)
    if any(unicodedata.category(ch) == "Cc" for ch in cleaned):
        cleaned = "".join(ch for ch in cleaned if unicodedata.category(ch) != "Cc")
    return cleaned.strip()


def _char_width(ch: str) -> int:
    cat = unicodedata.category(ch)
    if cat in ("Mn", "Me", "Cf") or ch == "\u200d":
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    cp = ord(ch)
    if (0x1F300 <= cp <= 0x1FAFF) or (0x2600 <= cp <= 0x27BF):
        return 2
    return 1


def _display_width(text: str) -> int:
    clean = ANSI_RE.sub("", text)
    total = 0
    in_zwj = False
    for ch in clean:
        if ch == "\u200d":
            in_zwj = True
            continue
        if ch in ("\ufe0e", "\ufe0f"):
            continue
        w = _char_width(ch)
        if in_zwj:
            if w > 0:
                in_zwj = False
            continue
        total += w
    return total


def _truncate_right_ellipsis(text: str, max_w: int) -> str:
    """Truncate text on the right to fit strictly within max_w display columns."""
    if max_w <= 0:
        return ""
    if _display_width(text) <= max_w:
        return text
    if max_w == 1:
        return "…"
    out: list[str] = []
    acc = 0
    limit = max_w - 1
    in_zwj = False
    for ch in text:
        if ch == "\u200d":
            in_zwj = True
            if out:
                out.append(ch)
            continue
        if ch in ("\ufe0e", "\ufe0f"):
            if out:
                out.append(ch)
            continue
        w = _char_width(ch)
        if in_zwj:
            if out:
                out.append(ch)
            if w > 0:
                in_zwj = False
            continue
        if w == 0:
            if out:
                out.append(ch)
            continue
        if acc + w > limit:
            break
        out.append(ch)
        acc += w
    return "".join(out).rstrip() + "…"


def _finite_num(val: object) -> float | None:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return None
    f = float(val)
    return f if math.isfinite(f) else None


def _prism_rgb(x: int, y: int, phase: int, shade: bool = False) -> tuple[int, int, int]:
    """Sample smooth diagonal rainbow-prism RGB for the aurora easter-egg variant."""
    n = len(PRISM_STOPS)
    t = ((x * 0.42 + y * 0.65 + phase * 1.3) % n)
    idx = int(t) % n
    nxt = (idx + 1) % n
    frac = t - math.floor(t)
    c0 = PRISM_STOPS[idx]
    c1 = PRISM_STOPS[nxt]
    r = int(c0[0] + (c1[0] - c0[0]) * frac)
    g = int(c0[1] + (c1[1] - c0[1]) * frac)
    b = int(c0[2] + (c1[2] - c0[2]) * frac)
    if shade:
        return (int(r * 0.78), int(g * 0.78), int(b * 0.78))
    return (r, g, b)


def _resolve_pixel_rgb(ch: str, x: int, y: int, species: str, phase: int) -> tuple[int, int, int] | None:
    if ch in (".", " "):
        return None
    if species == "prism" and ch in ("V", "S", "L"):
        return _prism_rgb(x, y, phase, shade=(ch == "S"))
    return PIXEL_COLORS.get(ch)


def is_pet_enabled(cfg: dict[str, Any]) -> bool:
    """Resolve pet enabled state: AGY_STATUSLINE_PET env overrides config.pet.enabled."""
    env_flag = os.environ.get("AGY_STATUSLINE_PET", "").strip().lower()
    if env_flag in ("0", "false", "no", "off"):
        return False
    if env_flag in ("1", "true", "yes", "on"):
        return True
    pet_cfg = cfg.get("pet")
    if isinstance(pet_cfg, dict) and isinstance(pet_cfg.get("enabled"), bool):
        return pet_cfg["enabled"]
    return True


def _extract_context_pct(data: dict[str, Any]) -> float | None:
    cw = data.get("context_window")
    if not isinstance(cw, dict):
        return None
    up = _finite_num(cw.get("used_percentage"))
    if up is not None:
        return up
    total = _finite_num(cw.get("context_window_size")) or _finite_num(cw.get("max_tokens"))
    cu = cw.get("current_usage")
    if total is not None and total > 0 and isinstance(cu, dict):
        parts = [
            v
            for k in (
                "input_tokens",
                "cache_creation_input_tokens",
                "cache_creation_tokens",
                "cache_read_input_tokens",
                "cache_read_tokens",
            )
            if (v := _finite_num(cu.get(k))) is not None and v >= 0
        ]
        if parts:
            return (sum(parts) / total) * 100.0
    return None


def _extract_min_quota_pct(data: dict[str, Any]) -> float | None:
    quota = data.get("quota")
    pcts: list[float] = []
    items = list(quota.values()) if isinstance(quota, dict) else (quota if isinstance(quota, list) else [])
    if isinstance(quota, dict) and ("remaining_fraction" in quota or "remaining_percentage" in quota):
        items = [quota]
    for b in items:
        if not isinstance(b, dict) or b.get("disabled") is True:
            continue
        rf = _finite_num(b.get("remaining_fraction"))
        if rf is not None:
            pcts.append(rf * 100.0)
            continue
        rp = _finite_num(b.get("remaining_percentage"))
        if rp is not None:
            pcts.append(rp)
    return min(pcts) if pcts else None


def resolve_pet_mood(data: dict[str, Any], cfg: dict[str, Any]) -> tuple[str, str]:
    """Determine (mood_key, extra_badge) from live Antigravity CLI state payload."""
    agent_state = str(data.get("agent_state") or "").strip().lower()
    confirm_pending = bool(data.get("tool_confirmation_pending"))

    subagents = data.get("subagents")
    running_subs = 0
    if isinstance(subagents, list):
        running_subs = sum(
            1 for s in subagents if isinstance(s, dict) and str(s.get("status") or "").lower() == "running"
        )
    sub_badge = f"+{running_subs} sub" if running_subs > 0 else ""

    if agent_state == "error":
        return "error", sub_badge
    if confirm_pending:
        return "confirm", sub_badge
    if agent_state == "tool_use":
        return "tool_use", sub_badge
    if agent_state in ("working", "initializing", "authenticating"):
        return "working", sub_badge
    if agent_state == "reviewing":
        return "reviewing", sub_badge

    thresholds = cfg.get("thresholds") if isinstance(cfg.get("thresholds"), dict) else {}
    ctx_crit = _finite_num(thresholds.get("context_critical_pct"))
    if ctx_crit is None:
        ctx_crit = 85.0
    quota_warn = _finite_num(thresholds.get("quota_warn_pct"))
    if quota_warn is None:
        quota_warn = 20.0

    ctx_pct = _extract_context_pct(data)
    if ctx_pct is not None and ctx_pct >= ctx_crit:
        return "tired", sub_badge
    min_q = _extract_min_quota_pct(data)
    if min_q is not None and min_q <= quota_warn:
        return "hungry", sub_badge

    cw = data.get("context_window")
    has_usage = isinstance(cw, dict) and cw.get("current_usage") is not None
    if agent_state == "idle" and not has_usage:
        return "sleep", sub_badge
    return "idle", sub_badge


def _frame_index(mood: str, num_frames: int, animate: bool, now: float | None = None) -> int:
    if num_frames <= 1 or not animate:
        return 0
    env_override = os.environ.get("AGY_STATUSLINE_PET_FRAME", "").strip()
    if env_override.isdigit():
        return int(env_override) % num_frames
    t = time.time() if now is None else now
    hz = 2.5 if mood in ("working", "tool_use", "confirm", "error", "reviewing") else 0.5
    return int(t * hz) % num_frames


def render_halfblock_frame(
    grid: list[str],
    *,
    species: str = "gemini",
    phase: int = 0,
    use_color: bool = True,
) -> list[str]:
    """Compress an even-height pixel grid into half-height Unicode `▀`/`▄` ANSI lines."""
    rows = list(grid)
    if not rows:
        return []
    if len(rows) % 2 == 1:
        rows.append("." * len(rows[0]))
    width = max((len(r) for r in rows), default=0)
    padded = [r.ljust(width, ".") for r in rows]

    out_lines: list[str] = []
    for y in range(0, len(padded), 2):
        top_row = padded[y]
        bot_row = padded[y + 1]
        parts: list[str] = []
        for x in range(width):
            tc = top_row[x]
            bc = bot_row[x]
            t_rgb = _resolve_pixel_rgb(tc, x, y, species, phase)
            b_rgb = _resolve_pixel_rgb(bc, x, y + 1, species, phase)
            if not use_color:
                if t_rgb and b_rgb:
                    ch = MONO_CHARS.get(tc, MONO_CHARS.get(bc, "#"))
                    parts.append(ch)
                elif t_rgb:
                    parts.append(MONO_CHARS.get(tc, "^"))
                elif b_rgb:
                    parts.append(MONO_CHARS.get(bc, "_"))
                else:
                    parts.append(" ")
                continue

            if t_rgb is None and b_rgb is None:
                parts.append(" ")
            elif t_rgb is not None and b_rgb is None:
                parts.append(f"\033[38;2;{t_rgb[0]};{t_rgb[1]};{t_rgb[2]}m▀{RESET}")
            elif t_rgb is None and b_rgb is not None:
                parts.append(f"\033[38;2;{b_rgb[0]};{b_rgb[1]};{b_rgb[2]}m▄{RESET}")
            else:
                parts.append(
                    f"\033[38;2;{t_rgb[0]};{t_rgb[1]};{t_rgb[2]}m"
                    f"\033[48;2;{b_rgb[0]};{b_rgb[1]};{b_rgb[2]}m▀{RESET}"
                )
        out_lines.append("".join(parts))
    return out_lines


def _colorize_prism_text(text: str, phase: int = 0) -> str:
    out: list[str] = []
    for idx, ch in enumerate(text):
        if ch == " ":
            out.append(" ")
        else:
            r, g, b = _prism_rgb(idx * 2, 1, phase)
            out.append(f"\033[38;2;{r};{g};{b}m{ch}")
    out.append(RESET)
    return "".join(out)


def render_inline_pet(
    data: dict[str, Any],
    cfg: dict[str, Any],
    pal: dict[str, str],
    *,
    now: float | None = None,
) -> str:
    """Render a compact 1-line inline Gemini cat companion (zero extra rows)."""
    pet_cfg = cfg.get("pet") if isinstance(cfg.get("pet"), dict) else {}
    species = str(pet_cfg.get("species") or "gemini").strip().lower()
    if species not in SPECIES_LIST:
        species = "gemini"
    animate = bool(pet_cfg.get("animate", True))
    mood, _ = resolve_pet_mood(data, cfg)
    sprite_state = MOOD_TO_SPRITE_STATE.get(mood, "idle")
    frames = GEMINI_INLINE_FRAMES.get(sprite_state) or GEMINI_INLINE_FRAMES["idle"]
    f_idx = _frame_index(mood, len(frames), animate, now=now)
    face = frames[f_idx]
    use_color = bool(pal.get("reset"))
    if not use_color:
        return face
    if species == "prism":
        return _colorize_prism_text(face, phase=f_idx)
    if mood in ("error", "confirm"):
        slot = MOOD_META[mood][0]
        return f"{pal.get(slot, GEMINI_ACCENT_ANSI)}{face}{pal['reset']}"
    return f"{GEMINI_ACCENT_ANSI}{face}{pal['reset']}"


def render_pet_lines(
    data: dict[str, Any],
    cfg: dict[str, Any],
    pal: dict[str, str],
    term_width: int,
    *,
    target_width: int | None = None,
    now: float | None = None,
) -> list[str]:
    """Render multi-line Gemini pixel or ASCII mascot strictly fitting within term_width."""
    if term_width < 20:
        return []

    pet_cfg = cfg.get("pet") if isinstance(cfg.get("pet"), dict) else {}
    species = str(pet_cfg.get("species") or "gemini").strip().lower()
    if species not in SPECIES_LIST:
        species = "gemini"
    style = str(pet_cfg.get("style") or "pixel").strip().lower()
    if style == "inline":
        return []
    align = str(pet_cfg.get("align") or "right").strip().lower()
    if align not in ALIGNS_LIST:
        align = "right"
    animate = bool(pet_cfg.get("animate", True))
    show_bubble = bool(pet_cfg.get("show_bubble", True))
    raw_name = pet_cfg.get("name")
    pet_name = _sanitize_text(raw_name) if isinstance(raw_name, str) else ""

    eff_target = min(term_width, target_width) if target_width is not None and target_width > 0 else term_width

    mood, sub_badge = resolve_pet_mood(data, cfg)
    sprite_state = MOOD_TO_SPRITE_STATE.get(mood, "idle")
    slot, tag, bubble = MOOD_META.get(mood, ("wt_linked", "ready", "ready!"))
    use_color = bool(pal.get("reset"))
    accent = (GEMINI_ACCENT_ANSI if mood == "idle" else pal.get(slot, GEMINI_ACCENT_ANSI)) if use_color else ""
    muted = pal.get("muted", "") if use_color else ""
    sep_col = pal.get("sep", "") if use_color else ""
    reset = pal.get("reset", "") if use_color else ""

    if style == "ascii":
        frames_ascii = GEMINI_ASCII_FRAMES.get(sprite_state) or GEMINI_ASCII_FRAMES["idle"]
        f_idx = _frame_index(mood, len(frames_ascii), animate, now=now)
        frame_ascii = frames_ascii[f_idx]
        if not use_color:
            sprite_lines = list(frame_ascii)
        elif species == "prism":
            sprite_lines = [_colorize_prism_text(line, phase=f_idx + idx) for idx, line in enumerate(frame_ascii)]
        else:
            sprite_col = pal.get(slot, GEMINI_ACCENT_ANSI) if mood in ("error", "confirm") else GEMINI_ACCENT_ANSI
            sprite_lines = [f"{sprite_col}{line}{reset}" for line in frame_ascii]
        sprite_w = max((_display_width(ln) for ln in frame_ascii), default=16)
    else:
        frames_px = GEMINI_PIXEL_FRAMES.get(sprite_state) or GEMINI_PIXEL_FRAMES["idle"]
        f_idx = _frame_index(mood, len(frames_px), animate, now=now)
        frame_px = frames_px[f_idx]
        sprite_lines = render_halfblock_frame(frame_px, species=species, phase=f_idx, use_color=use_color)
        sprite_w = max((len(r) for r in frame_px), default=16)

    if sprite_w > eff_target:
        return []

    header_parts = [pet_name] if pet_name else [species]
    header_parts.append(tag)
    if sub_badge:
        header_parts.append(sub_badge)
    raw_header = " · ".join(header_parts)

    if align == "right":
        sprite_pad = max(0, eff_target - sprite_w)
        # Bubble sits cleanly to the LEFT of the right-aligned Gemini cat:
        # Row 1: "<pad><header> ─╮  <sprite>"  (connector " ─╮  " = 5 cols)
        # Row 2: "<pad><msg>  ╰─ <sprite>"     (connector "  ╰─ " = 5 cols)
        connector_w = 5
        max_text_w = sprite_pad - connector_w - 1
        if not show_bubble or max_text_w < 10:
            pad_str = " " * sprite_pad
            return [f"{pad_str}{sl}" for sl in sprite_lines]

        header_plain = _truncate_right_ellipsis(raw_header, max_text_w)
        msg_plain = _truncate_right_ellipsis(bubble, max_text_w)
        header_w = _display_width(header_plain)
        msg_w = _display_width(msg_plain)

        pad_sprite = " " * sprite_pad
        pad_r1 = " " * max(0, sprite_pad - connector_w - header_w)
        pad_r2 = " " * max(0, sprite_pad - connector_w - msg_w)

        result: list[str] = []
        for idx, sl in enumerate(sprite_lines):
            if idx == 1:
                result.append(f"{pad_r1}{accent}{header_plain}{reset} {sep_col}─╮{reset}  {sl}")
            elif idx == 2:
                result.append(f"{pad_r2}{muted}{msg_plain}{reset}  {sep_col}╰─{reset} {sl}")
            else:
                result.append(f"{pad_sprite}{sl}")
        return result

    # Left-aligned layout: 1-space left padding when space allows, bubble to the RIGHT
    left_pad = " " if eff_target >= sprite_w + 1 else ""
    connector_w = 5
    max_text_w = eff_target - (len(left_pad) + sprite_w + connector_w)
    if not show_bubble or max_text_w < 10:
        return [f"{left_pad}{sl}" for sl in sprite_lines]

    header_plain = _truncate_right_ellipsis(raw_header, max_text_w)
    msg_plain = _truncate_right_ellipsis(bubble, max_text_w)

    result = []
    for idx, sl in enumerate(sprite_lines):
        if idx == 1:
            tail = f"  {sep_col}╭─{reset} {accent}{header_plain}{reset}"
        elif idx == 2:
            tail = f" {sep_col}─╯{reset}  {muted}{msg_plain}{reset}"
        else:
            tail = ""
        result.append(f"{left_pad}{sl}{tail}")
    return result
