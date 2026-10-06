#!/bin/zsh
# Saves the Discord bot token (Developer Portal -> Bot -> Reset Token -> Copy) as GitHub secret DISCORD_BOT_TOKEN.
TOKEN="$(pbpaste | tr -d '[:space:]')"
if [[ ${#TOKEN} -lt 50 || "$TOKEN" != *.*.* ]]; then
  echo "❌ Kein Bot-Token im Zwischenspeicher. Im Developer Portal unter 'Bot' auf 'Reset Token' -> 'Copy' klicken und nochmal starten."; exit 1
fi
printf '%s' "$TOKEN" | gh secret set DISCORD_BOT_TOKEN -R vcmyfzft8b-sudo/jobstep-viral-watch && echo "✅ Discord-Bot verbunden – sag Claude: done"
printf '' | pbcopy
