#!/usr/bin/env bash
# tiered-review 安装脚本(install-and-use,幂等)。把 skill 放好后跑一次:
#   bash <此 skill 目录>/install.sh
# 做三件事:① config.example.json → config.local.json(缺则建);② 把 PreToolUse hook 注册进
# ~/.claude/settings.json(Task|Workflow matcher,已注册则跳过,改动前备份 .bak);③ 检查 grok CLI 前提。
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
HOOK="$DIR/hooks/route-review.py"

echo "== tiered-review install =="

# ① config
if [ ! -f "$DIR/config.local.json" ]; then
  cp "$DIR/config.example.json" "$DIR/config.local.json"
  echo "  ✓ 建 config.local.json(从 example 复制;可改模型/lens prompt)"
else
  echo "  · config.local.json 已存在,不覆盖"
fi

# ② 注册 hook(幂等,合并进现有 PreToolUse,不破坏其它 hook)
python3 - "$HOOK" <<'PY'
import json, os, sys, shutil
hook_path = sys.argv[1]
home = os.path.expanduser("~")
disp = "~" + hook_path[len(home):] if hook_path.startswith(home + "/") else hook_path
cmd = f"python3 {disp}"
p = os.path.expanduser("~/.claude/settings.json")
s = json.load(open(p)) if os.path.exists(p) else {}
pre = s.setdefault("hooks", {}).setdefault("PreToolUse", [])
if any(any(h.get("command") == cmd for h in it.get("hooks", [])) for it in pre):
    print("  · PreToolUse hook 已注册,跳过"); sys.exit(0)
if os.path.exists(p):
    shutil.copy(p, p + ".bak")
pre.append({"matcher": "Task|Workflow", "hooks": [{"type": "command", "command": cmd}]})
json.dump(s, open(p, "w"), ensure_ascii=False, indent=2)
print(f"  ✓ 注册 PreToolUse hook: {cmd}(改动前备份 settings.json.bak)")
PY

# ③ grok 前提(offload 后端)
if command -v grok >/dev/null 2>&1; then
  echo "  ✓ grok CLI: $(command -v grok)"
  echo "    (若未登录,发现层会对每 lens 回 error → 先跑: grok login)"
else
  echo "  ⚠ 未找到 grok CLI —— 装 Grok Build CLI 并 grok login,否则 tiered-review 发现层无后端"
fi
command -v jq >/dev/null 2>&1 || echo "  ⚠ 未装 jq(脚本需要)"

echo "== 完成。hook 生效可能需重开 Claude Code session。用法见 SKILL.md =="
