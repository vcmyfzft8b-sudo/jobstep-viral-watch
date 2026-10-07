#!/usr/bin/env bash
# Retry the same non-force push. Never merge or overwrite another writer's state.
set -euo pipefail

git config user.name "jobstep-viral-watch"
git config user.email "actions@users.noreply.github.com"
git add -A state
if ! git diff --cached --quiet; then
  git commit -q -m "state $(date -u +%Y-%m-%dT%H:%MZ)"
fi

for attempt in 1 2 3 4; do
  if git push -q; then
    exit 0
  fi
  if [ "$attempt" -lt 4 ]; then
    sleep "$((attempt * 5))"
  fi
done
echo "State push failed after 4 attempts; preserve the state recovery artifact." >&2
exit 1
