---
name: agy-statusline
description: >-
  Manage, customize, preview, and troubleshoot the custom Antigravity CLI (agy)
  statusline renderer. Use when the user asks to install, enable, disable,
  migrate, customize colors/themes/segments/thresholds, preview narrow-screen
  layout, debug missing fields, or extend the agy-cli status bar.
---

# agy-statusline — Custom Antigravity CLI Statusline

Pure-stdlib single-line statusline renderer for `agy` (`scripts/statusline.py`) paired with the management CLI (`scripts/agy-statusline`, symlinked to `~/.local/bin/agy-statusline`).

> **Config precedence**: `AGY_STATUSLINE_CONFIG` env var → `config.local.json` alongside this `SKILL.md` (template: [config.example.json](./config.example.json), gitignored) → `<AGY_DATA_DIR>/statusline.json` → built-in `tokyo-night` defaults.

## 1. CLI Quick Reference

Invoke `agy-statusline` directly as a standalone command (avoid chaining `&&`, pipes, or env prefixes on commands that require `BypassSandbox: true`, so prefix auto-approval stays intact):

```bash
# Pure sandbox (BypassSandbox: false)
agy-statusline preview
agy-statusline preview --scenario narrow --width 64
agy-statusline preview --from-debug

# Writes outside active workspace or touches ~/.gemini/antigravity-cli/ (BypassSandbox: true)
agy-statusline init-config
agy-statusline status
agy-statusline doctor
agy-statusline install
agy-statusline uninstall          # sets enabled=false; pass --remove to delete block
```

(Fallback if `~/.local/bin` is not on `PATH`: `python3 ~/.gemini/config/skills/agy-statusline/scripts/agy-statusline <subcmd>`)

## 2. Standard Workflows

### Install or Migrate
1. Run `agy-statusline install` (automatically backs up `settings.json` preserving mode `0600` and existing `statusLine` keys like `padding`/`stack_with_default`, writes `statusLine.command`, and archives any legacy standalone `~/.gemini/antigravity-cli/statusline.py` to `.legacy.bak`; pass `--link-legacy` to symlink `<data-dir>/statusline.py` instead).
2. Run `agy-statusline doctor` to verify JSON validity, shell command resolution (`sh -c`), cold-start latency, and `quota_snapshot.json` health.

### Customize Style, Segments, or Thresholds
1. If `config.local.json` does not exist yet, run `agy-statusline init-config`.
2. Edit `config.local.json`:
   - Supported top-level keys: `theme` (`tokyo-night` | `minimal` | `plain`), `no_color`, `separator`, `left_segments` (`path`, `worktree`), `right_segments` (`permission`, `model`, `context`, `cache`, `quota`), `path`, `worktree` (`icon`, `show_dirty`, `label` = `branch` | `name`, `auto_detect_from_transcript`, `auto_prefix`), `cache` (`icon`, `style` = `percent` | `tokens` | `both`, `hide_when_empty`), `permission`, `thresholds`, `quota`, `layout`, `colors`.
   - Valid `colors` slot keys (256-color int `0..255` or SGR ANSI string): `path`, `wt_linked`, `wt_main`, `sep`, `model`, `muted`, `green`, `amber`, `red`, `sky`, `teal`, `yellow`.
3. Verify visually with `agy-statusline preview --scenario all` (and test `--width 60` for narrow terminals).

### Troubleshoot Missing Fields (`--`) or Layout Overflow
1. Run `agy-statusline doctor` first to rule out broken paths, permissions, or malformed config.
2. If an `agy` payload field changed or shows `--`, ask the user to run `agy` briefly with `AGY_STATUSLINE_DEBUG=1` (dumps raw stdin JSON to `/tmp/agy-statusline-debug.json` with `0600` permissions), then run `agy-statusline preview --from-debug`.
3. Read [references/payload-schema.md](./references/payload-schema.md) to compare incoming JSON keys against current extractors before patching `scripts/statusline.py`.

### Extend with New Segments
1. Read [references/payload-schema.md](./references/payload-schema.md) and `scripts/statusline.py`.
2. Add the new segment builder, register it in `_build_left` / `_build_right` and `config.example.json`, and add unit tests in `tests/test_statusline.py`.
3. Run `python3 -m unittest discover -s agy-statusline/tests -q` and `agy-statusline doctor` to verify correctness and latency.

## 3. Hard Rules

1. **Hot-path performance**: `scripts/statusline.py` MUST stay pure Python stdlib with **zero subprocess calls** (never spawn `git`) and **zero network requests**; cold-start render time must stay well under 50–100ms.
2. **Clean single-line stdout**: Never print warnings or debug text to `stdout`; all failures degrade silently to `--` or empty segments.
3. **Safe `settings.json` writes**: Always mutate `~/.gemini/antigravity-cli/settings.json` through `agy-statusline install` / `uninstall` (strict JSON parse + `.bak` backup + atomic `os.replace`), never hand-overwrite.
4. **Preserve `agy-stats` contract**: Keep `<data_dir>/cache/quota_snapshot.json` format (`{"updated_at": ..., "quota": ...}`) backward-compatible unless explicitly updating `agy-stats` together.
