#!/bin/zsh
# Saves the Slack webhook (copied from api.slack.com → JobStep Radar → Incoming Webhooks) as SLACK_WEBHOOK_URL.
URL="$(pbpaste | grep -o 'https://hooks.slack.com/services/[A-Za-z0-9/]*' | head -1)"
if [[ -z "$URL" ]]; then echo "❌ Kein Slack-Webhook im Zwischenspeicher – bei #jobstep-radar auf 'Copy' klicken und nochmal starten."; exit 1; fi
printf '%s' "$URL" | gh secret set SLACK_WEBHOOK_URL -R vcmyfzft8b-sudo/jobstep-viral-watch && echo "✅ Slack-Kanal verbunden – sag Claude: done"
