#!/bin/zsh
# Decrypts the latest script export (mode export) from the state branch with the private key on this Mac
# (the same key as the Memo AI watcher's export).
# Usage: scripts/read_export.sh [out.md]   (default: ~/Downloads/parakeet-scripts.md)
OUT="${1:-$HOME/Downloads/parakeet-scripts.md}"
cd "$(dirname "$0")/.." || exit 1
git fetch -q origin state || exit 1
git show origin/state:state/scripts_export.enc | openssl smime -decrypt -inform PEM -inkey ~/.config/memo-viral-watch/export_key.pem > "$OUT" && echo "✅ $OUT"
