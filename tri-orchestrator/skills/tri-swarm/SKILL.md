---
name: tri-swarm
description: >-
  Orchestrate ultra-large multi-module engineering tasks using the native Swarm board with
  Gemini 4 Carbon (architect/reviewer), Gemini 4 Neon (parallel coders), and Gemini 4 Hydrogen (scouts).
  Use ONLY when the user explicitly invokes /swarm or tri-swarm for large parallel tasks.
---

# Tri-Tier Native Swarm Workflow

When the user explicitly asks to run a large multi-module task with `tri-swarm` or `/swarm`, coordinate workers on the native Swarm board with explicit model bindings:

1. **Initialize Overview & Verify Live Models**:
   - Read the `swarm_pane` skill (`~/.gemini/antigravity-cli/builtin/skills/swarm_pane/SKILL.md`) before adding workers so the Swarm UI overview renders cleanly.
   - Call `swarm(action="title", title=...)` and **ALWAYS call `swarm(action="models")` first** to verify exact available model slugs (`gemini-4-carbon-high`, `gemini-4-neon-xhigh`, `gemini-4-hydrogen-medium`, or available fallback tiers).
2. **Spawn Architect & Final Reviewer (`gemini-4-carbon-high`)**:
   - Include in the brief:
     `"CRITICAL: You are an active Swarm worker pinned to Carbon. NEVER call tri-router MCP tools (carbon_planner, carbon_reviewer, execute_with_review, etc.). Use native read_file/run_command (read-only) directly."`
   - Own the architecture plan, interface contracts, and multi-round code review before final sign-off. Do not edit code directly.
3. **Spawn Parallel Coders (`gemini-4-neon-xhigh`, isolated `share` workspaces)**:
   - Shard disjoint file/module ownership across `coder-1`, `coder-2`, etc. using `workspace="share"` and `model="gemini-4-neon-xhigh"`.
   - Include in every coder brief:
     `"CRITICAL: You are an active Swarm worker pinned to Neon XHigh. NEVER call tri-router MCP tools (execute_with_review, neon_coder, etc.). Edit files and run local build/tests directly with native tools in your shared worktree, commit cleanly, and report your branch/commit."`
4. **Spawn Fast Scouts (`gemini-4-hydrogen-medium`)** (optional, for wide read-only exploration):
   - Use `model="gemini-4-hydrogen-medium"` with `workspace="inherit"` and explicit anti-`tri-router` brief.
5. **Integration, Conflict Resolution & Closed-Loop Review Gate**:
   - Once all `coder-*` workers report passing local tests, the **coordinator** sequentially merges each worker's branch/changes into the primary working copy:
     - If a merge conflict occurs, the coordinator resolves trivial adjacent/import conflicts directly or assigns **one** `coder` to rebase and resolve before merging the remaining branches, then runs the full integration build/test suite.
   - Wake `architect` (`gemini-4-carbon-high`) to review the combined primary diff:
     - Any `BLOCKER` / `HIGH` / `MEDIUM` findings must go back to a `coder` to fix and re-test, followed by a Round-2 verification pass from `architect` before final sign-off.
6. **Cleanup**: Only after integration tests and Carbon review pass, `swarm(action="kill", name=...)` finished workers and deliver the final report.
