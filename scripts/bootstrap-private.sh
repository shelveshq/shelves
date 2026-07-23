#!/usr/bin/env bash
#
# Bootstrap the private companion repo (shelveshq/shelves-internal) for local
# development. Clones it to ./.private (gitignored) and symlinks its contents
# back to the paths the tooling and docs expect.
#
# Idempotent: safe to re-run. Pulls latest if the clone already exists.
#
# Requires read access to shelveshq/shelves-internal (private).
#
#   ./scripts/bootstrap-private.sh
#
set -euo pipefail

PRIVATE_REMOTE="${SHELVES_PRIVATE_REMOTE:-git@github.com:shelveshq/shelves-internal.git}"

# repo root = parent of this script's dir
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PRIV="$ROOT/.private"
cd "$ROOT"

# 1. clone or update the private repo
if [ -d "$PRIV/.git" ]; then
  echo "== .private already cloned; pulling latest =="
  git -C "$PRIV" pull --ff-only
else
  echo "== cloning $PRIVATE_REMOTE -> .private =="
  git clone "$PRIVATE_REMOTE" "$PRIV"
fi

# 2. (re)create the symlinks.  "linkpath" -> "target" (relative to linkpath's dir)
link() {
  local linkpath="$1" target="$2"
  # remove a stale link/file, but never blow away a real directory of content
  if [ -L "$linkpath" ]; then
    rm -f "$linkpath"
  elif [ -e "$linkpath" ]; then
    echo "!! refusing to replace non-symlink $linkpath — resolve manually" >&2
    exit 1
  fi
  mkdir -p "$(dirname "$linkpath")"
  ln -s "$target" "$linkpath"
  if [ -e "$linkpath" ]; then
    echo "OK  $linkpath -> $target"
  else
    echo "!! broken link: $linkpath -> $target" >&2
    exit 1
  fi
}

echo "== wiring symlinks =="
link "docs/foundational"                 "../.private/foundational"
link "docs/design-system"                "../.private/design-system"
link "docs/plans"                        "../.private/plans"
link "PLAN.md"                            ".private/PLAN.md"
link "assets/Shelves Design System.zip"  "../.private/assets/Shelves Design System.zip"

echo "== done. private content is available locally and gitignored. =="
