---
name: stats
description: >-
  Render Claude Code-style Antigravity CLI usage statistics, GitHub-like
  activity heatmap, per-model token distribution, and quota snapshot. Use when
  the user invokes /stats or asks for detailed model usage breakdown and
  activity graphs.
---

# Antigravity Usage & Model Stats (`/stats`)

Render local Antigravity CLI (`agy`) usage telemetry from
`~/.gemini/antigravity-cli/brain/*/.system_generated/logs/transcript.jsonl`,
including an activity heatmap, per-model token distribution, streaks, and
latest quota snapshot.

## Instructions

1. Run the stats script (prints a static report once and exits by default):
   ```bash
   agy-stats
   ```
   (Fallback if not on `PATH`: `python3 ~/.gemini/config/skills/stats/scripts/agy-stats`)

2. Optional flags based on user request:
   - `--with-interactive` — launch single-key interactive TUI mode (requires a TTY)
   - `--by-model` — show per-model square distribution rows across weeks
   - `--exact-models` — show exact model variants (`-low`, `-medium`, `-high`, `-xhigh`) instead of model families
   - `--metric <tokens|all-tokens|messages|steps|tools>` — switch heatmap metric
   - `--days <N>` or `--weeks <N>` — adjust time window
   - `--width <N>` — override render width in columns (default: auto-detect)
   - `--exclude-subagents` — exclude child subagent conversations
   - `--project <substr>` — filter by workspace path substring
   - `--json` — output structured JSON

3. Present the rendered summary and distribution clearly to the user.
