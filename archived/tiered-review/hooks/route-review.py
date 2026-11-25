#!/usr/bin/env python3
"""tiered-review PreToolUse hook — 成本守门。

把「多 agent 审查」的两个明显信号在 Claude 真调用时拦下、deny + 引导改走 grok:
  信号 A  Task 工具 + subagent_type ∈ pr-review-toolkit:*   (adaptive-review Fan-out / /review-pr / 手动)
  信号 B  Workflow 工具 + review 脚本                         (/code-review workflow)

deny 后 Claude 应改跑 tiered-review.sh(grok 出 findings)+ 自己做高档验收(见 adaptive-review /
tiered-review SKILL.md 的确定性改道,option A)。

只对这两个信号 deny;其它 Task/Workflow(Explore/Plan/general-purpose/验证/非 review workflow)
**静默放行**(不输出 → 走正常权限流,不自动批准)。任何异常也静默放行,绝不因 hook 报错卡住工具。
"""
import json
import sys

SKILL = "~/.claude/skills/tiered-review"
REVIEW_PREFIX = "pr-review-toolkit:"

# pr-review-toolkit agent 名 → tiered-review 的 lens 名(config.lens_prompts / adaptive-review 单一命名空间)。
AGENT_TO_LENS = {
    "code-reviewer": "correctness-linescan",
    "silent-failure-hunter": "silent-failure",
    "pr-test-analyzer": "test-coverage",
    "comment-analyzer": "comment-accuracy",
    "type-design-analyzer": "type-design",
    "code-simplifier": "simplification",
}


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # 读不到/坏 JSON → 放行,不卡工具

    tool = data.get("tool_name", "") or ""
    ti = data.get("tool_input", {}) or {}

    # 信号 A:多 agent 审查
    if tool == "Task":
        sub = str(ti.get("subagent_type", "") or "")
        if sub.startswith(REVIEW_PREFIX):
            agent = sub[len(REVIEW_PREFIX):]
            lens = AGENT_TO_LENS.get(agent, agent)  # 映射到 lens 名;未知则原样(走 config.default)
            deny(
                f"[tiered-review 成本策略] pr-review-toolkit 审查 agent 不走 Claude 子 agent。"
                f"改跑:bash {SKILL}/tiered-review.sh --dims {lens} "
                f"(多维度就把 --dims 逗号拼成一次调用;默认审工作区 git diff,或加 --base main)。"
                f"grok 用你的订阅出结构化 findings;回来后**你(Claude,高档)**逐条对抗验证(refute)、"
                f"去重、按 severity 报告 —— 验证用主循环或 general-purpose,别再 spawn pr-review-toolkit。"
            )
        sys.exit(0)  # 非审查 Task(Explore/Plan/general-purpose/验证)放行

    # 信号 B:code-review workflow
    if tool == "Workflow":
        blob = (str(ti.get("script", "") or "") + " " +
                str(ti.get("name", "") or "") + " " +
                str(ti.get("title", "") or "")).lower()
        if any(k in blob for k in ("review", "审查", "code-review", "code review")):
            deny(
                f"[tiered-review 成本策略] code-review Workflow 的 finder 层改走 grok:"
                f"bash {SKILL}/tiered-review.sh --dims <各维度> --base <目标 ref>。"
                f"Workflow 仅在真需要「高档对抗验证/综合」时保留;云端 /code-review ultra 不受此限。"
            )
        sys.exit(0)  # 非 review workflow 放行

    sys.exit(0)  # 其它工具不管


if __name__ == "__main__":
    main()
