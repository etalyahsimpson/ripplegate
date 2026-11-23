#!/usr/bin/env bash
# Verify docs and asset references resolve.
set -euo pipefail
cd "$(dirname "$0")/.."
FAIL=0
for f in README.md docs/*.md; do
  for link in $(grep -oE '\]\(([^)#]+)(#[^)]*)?\)' "$f" | sed -E 's/\]\(([^)#]+).*/\1/' | grep -v '^http' | sort -u || true); do
    [ -e "$link" ] || { echo "broken link in $f: $link"; FAIL=1; }
  done
done
[ "$FAIL" = "0" ] && echo "links: OK" || exit 1
