#!/usr/bin/env bash
# tiered-review.sh — 把多维度代码审查的「广度发现」层 offload 到 grok CLI(用 grok 订阅,
# 不烧 Claude 额度)。每维度并发调 grok,--json-schema 约束结构化 findings,回给 Claude 做
# 高档对抗验证 + 综合(见 SKILL.md)。
#
# 用法(务必用 bash 跑,勿用 zsh):
#   bash tiered-review.sh --dims code-reviewer,silent-failure-hunter,... [--diff <file>] [--base <ref>]
#     --dims  逗号分隔的 lens(= pr-review-toolkit agent 名去前缀 / config.lens_prompts 的 key)
#     --diff  diff 文件路径;缺省则 `git diff`(工作区未提交改动)
#     --base  与某 ref 比(如 main);等价 git diff <base>...HEAD;与 --diff 二选一
#
# 输出:stdout 每行一个 lens 的 JSON:{"lens":..,"backend":"grok","findings":[...]} 或 {..,"error":..}
# 前提:grok CLI 已登录(`grok login`);未登录时该 lens 输出 error(不中断其它 lens)。
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
SCHEMA="$DIR/schemas/findings.json"
CFG="$DIR/config.local.json"; [ -f "$CFG" ] || CFG="$DIR/config.example.json"

DIFF=""; DIMS=""; BASE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dims) DIMS="${2:-}"; shift 2 ;;
    --diff) DIFF="${2:-}"; shift 2 ;;
    --base) BASE="${2:-}"; shift 2 ;;
    *) shift ;;
  esac
done

command -v grok >/dev/null 2>&1 || { echo '{"error":"grok CLI 未安装"}'; exit 1; }
command -v jq   >/dev/null 2>&1 || { echo '{"error":"jq 未安装"}'; exit 1; }
[ -n "$DIMS" ] || { echo '{"error":"缺 --dims"}'; exit 1; }

if [ -z "$DIFF" ]; then
  DIFF="$(mktemp -t tr-diff.XXXXXX)"
  if [ -n "$BASE" ]; then git diff "$BASE"...HEAD > "$DIFF" 2>/dev/null; else git diff > "$DIFF" 2>/dev/null; fi
fi
[ -s "$DIFF" ] || { echo '{"error":"diff 为空,无改动可审"}'; exit 0; }

MODEL="$(jq -r '.backends.grok.model // "grok-4.5"' "$CFG")"
PREAMBLE="$(jq -r '.common_preamble // ""' "$CFG")"
SCHEMA_STR="$(cat "$SCHEMA")"

# 审一个 lens,结果(单行 JSON)写到 $2。grok 失败/未登录 → error 对象,不中断整体。
run_lens() {
  local lens="$1" outfile="$2"
  local focus pf err out rc hint=""
  focus="$(jq -r --arg l "$lens" '.lens_prompts[$l] // .lens_prompts.default' "$CFG")"
  pf="$(mktemp -t tr-p.XXXXXX)"; err="$(mktemp -t tr-e.XXXXXX)"
  { printf '%s\n\n%s\n\n=== DIFF ===\n' "$PREAMBLE" "$focus"; cat "$DIFF"; } > "$pf"

  out="$(grok --prompt-file "$pf" --model "$MODEL" --json-schema "$SCHEMA_STR" \
              --output-format json --disable-web-search --always-approve 2>"$err")"
  rc=$?
  if [ $rc -ne 0 ] || [ -z "$out" ]; then
    grep -qiE 'auth|login|not authenticated' "$err" 2>/dev/null && hint=";疑未登录 → 先跑 grok login"
    jq -nc --arg l "$lens" --arg e "grok 调用失败(rc=$rc)$hint" \
       '{lens:$l,backend:"grok",error:$e}' > "$outfile"
  else
    # grok --output-format json 返回包装对象 {text, structuredOutput:[...schema 匹配的 findings...], ...};
    # 用 --json-schema 时干净的 findings 在 .structuredOutput。兜底:裸数组直接用 / 解析 .text / []。
    printf '%s' "$out" | jq -c --arg l "$lens" \
      '{lens:$l, backend:"grok",
        findings:(if type=="array" then . else (.structuredOutput // (.text|fromjson?) // []) end)}' \
      > "$outfile" 2>/dev/null \
      || jq -nc --arg l "$lens" --arg raw "${out:0:400}" '{lens:$l,backend:"grok",error:"输出非合法 JSON",raw:$raw}' > "$outfile"
  fi
  rm -f "$pf" "$err"
}

# Fan-out:每 lens 一个后台 job(≤6 个,免 xargs/mapfile,兼容 macOS bash 3.2),结果各写临时文件,wait 后汇总。
outs=""
old_ifs="$IFS"; IFS=','
for lens in $DIMS; do
  [ -n "$lens" ] || continue
  of="$(mktemp -t tr-o.XXXXXX)"
  outs="$outs $of"
  run_lens "$lens" "$of" &
done
IFS="$old_ifs"
wait
for of in $outs; do cat "$of"; echo; rm -f "$of"; done
