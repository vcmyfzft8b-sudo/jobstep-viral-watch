#!/bin/zsh
# Saves a Discord #announcements webhook (copied in Discord) as GitHub secret.
# usage: save_discord_webhook.sh [de|fr|es]   (default de)
M="${1:-de}"
case "$M" in de) NAME=DISCORD_WEBHOOK_URL;; fr) NAME=DISCORD_WEBHOOK_URL_FR;; es) NAME=DISCORD_WEBHOOK_URL_ES;; *) echo "de | fr | es"; exit 1;; esac
URL="$(pbpaste | tr -d '[:space:]')"
if [[ "$URL" != https://discord.com/api/webhooks/* && "$URL" != https://discordapp.com/api/webhooks/* ]]; then
  echo "❌ Kein Discord-Webhook-Link im Zwischenspeicher. In Discord 'Copy Webhook URL' klicken und nochmal starten."; exit 1
fi
printf '%s' "$URL" | gh secret set "$NAME" -R vcmyfzft8b-sudo/jobstep-viral-watch && echo "✅ Discord ($M) verbunden – sag Claude: done"
