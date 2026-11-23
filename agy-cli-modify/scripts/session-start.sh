#!/bin/sh
# Fast (<40ms) read-only SessionStart workspace snapshot for Antigravity CLI.
# Fails open with {} on any unexpected error so session startup never blocks.

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export GIT_OPTIONAL_LOCKS=0

command -v jq >/dev/null 2>&1 || { printf '{}\n'; exit 0; }

INPUT=$(cat 2>/dev/null || true)
TARGET=$(printf '%s' "$INPUT" | jq -r '(.cwd // .workspacePaths[0] // empty)' 2>/dev/null || true)

if [ -z "$TARGET" ] || [ ! -d "$TARGET" ]; then
  printf '{}\n'
  exit 0
fi

is_ignored_entry() {
  case "$1" in
    .|..|.git|.build|target|node_modules|dist|build|__pycache__|.venv|.DS_Store|.pnpm-store)
      return 0 ;;
    *)
      return 1 ;;
  esac
}

GIT_ROOT=$(git -C "$TARGET" rev-parse --show-toplevel 2>/dev/null || true)

if [ -n "$GIT_ROOT" ]; then
  BRANCH=$(git -C "$TARGET" symbolic-ref --quiet --short HEAD 2>/dev/null || git -C "$TARGET" rev-parse --short HEAD 2>/dev/null || printf 'HEAD')
  STATUS_RAW=$(git -C "$TARGET" status --porcelain 2>/dev/null || true)
  if [ -n "$STATUS_RAW" ]; then
    DIRTY_COUNT=$(printf '%s\n' "$STATUS_RAW" | wc -l | tr -d ' ')
    DIRTY_SAMPLE=$(printf '%s\n' "$STATUS_RAW" | head -n 8 | awk '{printf "%s%s", (NR>1?"; ":""), $0}')
  else
    DIRTY_COUNT=0
    DIRTY_SAMPLE="clean"
  fi
  RECENT=$(git -C "$TARGET" --no-pager log -n 3 --oneline 2>/dev/null | awk '{printf "%s%s", (NR>1?" | ":""), $0}')

  TOP_ITEMS=""
  COUNT=0
  for p in "$GIT_ROOT"/*; do
    [ -e "$p" ] || continue
    base=${p##*/}
    is_ignored_entry "$base" && continue
    if [ -d "$p" ]; then
      item="${base}/"
    else
      item="$base"
    fi
    TOP_ITEMS="${TOP_ITEMS}${TOP_ITEMS:+ }${item}"
    COUNT=$((COUNT + 1))
    [ "$COUNT" -ge 22 ] && break
  done

  SNAP="[workspace snapshot] mode=git-repo root=${GIT_ROOT} branch=${BRANCH} dirty=${DIRTY_COUNT} (${DIRTY_SAMPLE})
top: ${TOP_ITEMS:-empty}
recent: ${RECENT:-none}"
else
  DIRS=""
  DIR_COUNT=0
  FILES=""
  FILE_COUNT=0
  for p in "$TARGET"/*; do
    [ -e "$p" ] || continue
    base=${p##*/}
    is_ignored_entry "$base" && continue
    if [ -d "$p" ]; then
      tags=""
      [ -e "$p/.git" ] && tags="${tags}${tags:+,}git"
      [ -f "$p/Package.swift" ] && tags="${tags}${tags:+,}Swift"
      [ -f "$p/Cargo.toml" ] && tags="${tags}${tags:+,}Rust"
      [ -f "$p/package.json" ] && tags="${tags}${tags:+,}Node"
      [ -f "$p/pyproject.toml" ] && tags="${tags}${tags:+,}Py"
      [ -f "$p/go.mod" ] && tags="${tags}${tags:+,}Go"
      if [ -n "$tags" ]; then
        item="${base}/[${tags}]"
      else
        item="${base}/"
      fi
      DIRS="${DIRS}${DIRS:+ }${item}"
      DIR_COUNT=$((DIR_COUNT + 1))
      [ "$DIR_COUNT" -ge 25 ] && break
    elif [ "$FILE_COUNT" -lt 10 ]; then
      case "$base" in
        AGENTS.md|GEMINI.md|CLAUDE.md|README.md|Makefile|Cargo.toml|Package.swift|package.json|pyproject.toml)
          FILES="${FILES}${FILES:+ }${base}"
          FILE_COUNT=$((FILE_COUNT + 1))
          ;;
      esac
    fi
  done

  COMBINED="${DIRS}${FILES:+ }${FILES}"
  SNAP="[workspace snapshot] mode=multi-dir cwd=${TARGET}
projects: ${COMBINED:-empty}"
fi

jq -cn --arg msg "$SNAP" '{injectSteps:[{systemMessage:{systemMessage:($msg[0:800])}}]}' 2>/dev/null || printf '{}\n'
