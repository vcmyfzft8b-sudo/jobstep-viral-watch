#!/bin/zsh
# Saves the DACH Discord #announcements webhook (copied from Discord) as GitHub secret DISCORD_WEBHOOK_URL.
URL="$(pbpaste | tr -d '[:space:]')"
if [[ "$URL" != https://discord.com/api/webhooks/* && "$URL" != https://discordapp.com/api/webhooks/* ]]; then
  echo "❌ Im Zwischenspeicher ist kein Discord-Webhook-Link. In Discord 'Webhook-URL kopieren' klicken und nochmal starten."
  exit 1
fi
printf '%s' "$URL" | gh secret set DISCORD_WEBHOOK_URL -R vcmyfzft8b-sudo/jobstep-viral-watch && echo "✅ Discord verbunden – sag Claude: done"
