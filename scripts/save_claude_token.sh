#!/bin/zsh
# Saves the Claude subscription token (from `claude setup-token`) to GitHub, taking it from the clipboard.
# The token is never printed. Removes line breaks and checks it is complete before saving.
REPO="${1:-vcmyfzft8b-sudo/jobstep-viral-watch}"
echo "1) Markiere im Terminal den KOMPLETTEN Token (sk-ant-oat01-… inkl. der zweiten Zeile) und kopiere ihn (Cmd+C)."
echo "2) Drück dann hier Enter."
read -r _
TOKEN="$(pbpaste | tr -d '[:space:]')"
if [[ "$TOKEN" != sk-ant-oat01-* || ${#TOKEN} -lt 100 ]]; then
  echo "❌ Im Zwischenspeicher ist kein vollständiger Token (Länge ${#TOKEN}). Bitte beide Zeilen kopieren und nochmal starten."
  exit 1
fi
printf '%s' "$TOKEN" | gh secret set CLAUDE_CODE_OAUTH_TOKEN -R "$REPO" && echo "✅ Token gespeichert (Länge ${#TOKEN}) – sag Claude: done"
