# Antigravity CLI Statusline Payload Schema & Contracts

This reference documents the stdin JSON contract consumed by `scripts/statusline.py` and the downstream snapshot contract consumed by `agy-stats`.

## 1. Stdin JSON Payload Fields

`agy` invokes `statusLine.command` with a JSON object on `stdin` and displays the first line printed to `stdout`. All fields are optional and defensive fallbacks are applied.

### Workspace & Path
Checked in priority order:
1. `workspace.current_dir`
2. `workspace.project_dir`
3. `cwd`
4. `folder`
5. Fallback: `os.getcwd()`

- `file://` and `file://localhost/` URIs are stripped and percent-decoded (`urllib.parse.unquote`).

### Git Branch & Linked Worktree
Checked without spawning `git` subprocesses:
1. Explicit worktree: `worktree` or `workspace.worktree` (string or dict with `name` / `branch` / `display_name`) → marked as linked worktree.
2. Walk ancestors of resolved project dir looking for `.git`:
   - `.git` **file**: reads `gitdir: <path>`; if the resolved gitdir ends with `.../worktrees/<name>`, returns `(<name>, linked=True)`; otherwise (e.g., submodule or `--separate-git-dir`) reads `<gitdir>/HEAD` and marks as non-linked (`linked=False`).
   - `.git` **directory** (main repo): reads `.git/HEAD` (`ref: refs/heads/<branch>` or 7-char detached SHA), falls back to `vcs.branch` → marked as main repo.
3. Fallback: `vcs.branch`.
- Dirty indicator: `vcs.dirty` truthy appends `*` when `worktree.show_dirty` is enabled.

### Permission / Execution Mode
Checked in priority order across `PERMISSION_KEYS`:
`cycle_mode`, `mode`, `agent_mode`, `agentMode`, `permission_mode`, `permissionMode`, `approval_mode`, `approvalMode`, `execution_mode`, `executionMode`, `tool_permission`, `toolPermission`, `permissions` (string or dict with `display_name`/`name`/`mode`/`level`/`preset`/`id`).
- Official `agy` sends `cycle_mode` (`accept-edits`, `auto`, `plan`, `best-of-n`) and omits it in default confirmation mode.
- Fallback 1: `settings.json` → `agentMode` / `toolPermission`.
- Fallback 2: `sandbox === true` or `sandbox.enabled === true` → `"sandbox"`.
- Fallback 3: `config.permission.default_fallback` (default `"default"`).

### Model Name
1. `model` (string or dict with `display_name` / `name` / `id`; appends `(<effort>)` when `model.effort` is present and not already part of the name).
2. Fallback: `settings.json` → `model`.
3. Fallback: `"--"`.

### Context Window
Reads `context_window` dict:
- **Total capacity** (first positive finite number): `context_window_size`, `max_tokens`, `limit`, `window_size`.
- **Used tokens** (first match):
  1. `used_tokens`, `current_tokens`
  2. `current_usage.total_tokens` or sum of `current_usage.{input_tokens, cache_creation_input_tokens|cache_creation_tokens, cache_read_input_tokens|cache_read_tokens}` (defers to non-zero `used_percentage` if all `current_usage` fields are `0`)
  3. `used_percentage` × total / 100
  4. `(100 - remaining_percentage)` × total / 100
- Cumulative `total_input_tokens` is intentionally **not** used as current window occupancy; degrades to `--` when no current occupancy metric is present.
- Formatted as `<used>/<total>` (e.g., `109k/1M`).

### Prompt Cache Hit Rate (`cache` segment)
Reads `context_window.current_usage` (latest model step):
- `cache_read_input_tokens` (fallback `cache_read_tokens`)
- `cache_creation_input_tokens` (fallback `cache_creation_tokens`, default `0`)
- `input_tokens` (uncached input tokens; mutually exclusive with `cache_read_input_tokens`)
- Hit rate formula: `cache_read / (input_tokens + cache_creation + cache_read) * 100`.
- Direct fallback: `context_window.cache_hit_percentage` if provided.
- Displays `⚡<pct>%` by default (configurable via `cache.icon`, `cache.style` = `percent` | `tokens` | `both`, `cache.hide_when_empty`), degrading to `⚡--` when `current_usage` is `null` (before first model response).
- Color thresholds: `>= cache_ok_pct` (70%) green, `>= cache_warn_pct` (30%) amber, `< cache_warn_pct` muted.

### Quota Buckets & Credits Fallback
1. `quota` can be:
   - A single bucket dict containing `remaining_fraction` (`0.0..1.0`), `remaining_percentage` (`0..100`), or `remaining_amount` (finite number), plus optional `reset_in_seconds` and `disabled` (`true` buckets are skipped).
   - A dict mapping bucket name → bucket dict (e.g. `{"gemini-5h": {...}, "gemini-weekly": {...}, "3p-5h": {...}}`).
   - A list of bucket dicts with `name` / `id` / `bucket`.
2. When `quota.filter_by_model` is `true`, multiple buckets exist, and `model_name` is resolved (not `"--"`):
   - Active model matching `claude|opus|sonnet|gpt|3p` selects buckets containing `3p`; otherwise selects buckets containing `gemini` (falls back to all buckets if none match).
3. Bucket ordering: `5h` → `7d`/`weekly` → `argon` → others.
4. Countdown `(<dur>)` appends when remaining percentage `<= thresholds.quota_countdown_below_pct` (default `20`), or when `remaining_amount <= 0`.
5. Fallback when `quota` has no usable buckets: `credits`, `ai_credits`, `g1_credits` (scalar or dict with `remaining`/`available`/`balance`/`amount`/`value`) → `AI: <N>` or `AI: Out of credits`.

### Terminal Width
- Resolution order: `terminal_width` (positive finite int) → `COLUMNS` env var (positive int) → `os.get_terminal_size().columns` (when `> 0`) → `100`.

---

## 2. Downstream `agy-stats` Snapshot Contract

When `data["quota"]` contains at least one usable (enabled) bucket, `config.quota.write_snapshot` is not `false`, and `AGY_STATUSLINE_NO_SNAPSHOT` is not `1`/`true`/`yes`, `statusline.py` atomically writes `<AGY_DATA_DIR>/cache/quota_snapshot.json` (mode `0600`):

```json
{
  "updated_at": "2026-11-28T00:59:47.841438+00:00",
  "quota": { "...raw payload data.quota..." }
}
```

`agy-stats` reads this exact file (`load_quota_snapshot`) to display the Quota Snapshot section. Do not change the top-level keys (`updated_at`, `quota`) or default filename without updating `agy-stats`.

---

## 3. Environment Variables & Config Precedence

Config lookup order: `AGY_STATUSLINE_CONFIG` → `<skill_root>/config.local.json` → `<AGY_DATA_DIR>/statusline.json` → built-in `tokyo-night` defaults.

| Variable | Purpose |
| :--- | :--- |
| `AGY_DATA_DIR` | Override Antigravity CLI data directory (default `~/.gemini/antigravity-cli`). |
| `AGY_STATUSLINE_CONFIG` | Explicit path to a statusline config JSON file (highest precedence). |
| `AGY_STATUSLINE_DEBUG` | Set to `1`/`true`/`yes` to atomically dump raw stdin JSON to `/tmp/agy-statusline-debug.json` (mode `0600`), `0`/`false`/`no` to disable, or another non-empty value for a custom file path. |
| `AGY_STATUSLINE_NO_SNAPSHOT` | Set to `1`/`true`/`yes` to skip writing `cache/quota_snapshot.json` (used by `agy-statusline doctor` and benchmarks). |
| `COLUMNS` | Fallback terminal column width when `terminal_width` is absent from stdin JSON. |
| `NO_COLOR` | Any non-empty value disables ANSI escape sequences. |
