#!/bin/zsh
# Run this yourself once (it copies your API keys from your local .env files into the repo's GitHub secrets).
# Nothing is printed except the ntfy topic you need to subscribe to on your phone.
set -e
REPO="${1:-vcmyfzft8b-sudo/jobstep-viral-watch}"

get() {  # get <file> <KEY>
  grep -E "^[[:space:]]*(export[[:space:]]+)?$2[[:space:]]*=" "$1" | tail -1 | sed -E "s/^[[:space:]]*(export[[:space:]]+)?$2[[:space:]]*=[[:space:]]*//; s/^[\"']//; s/[\"'][[:space:]]*$//"
}

get ~/Documents/auto-outreach-parakeetai/.env.local NOTION_API_KEY  | gh secret set NOTION_TOKEN       -R "$REPO"
get ~/Desktop/repost/.env                          OPENROUTER_API_KEY | gh secret set OPENROUTER_API_KEY -R "$REPO"
get ~/Documents/transcript/.env.local              SONIOX_API_KEY  | gh secret set SONIOX_API_KEY     -R "$REPO"
get ~/Documents/auto-outreach-parakeetai/.env.local LIGHTREEL_API_KEY | gh secret set LIGHTREEL_API_KEY -R "$REPO"

TOPIC="jobstep-radar-$(LC_ALL=C tr -dc 'a-z0-9' < /dev/urandom | head -c 20)"
echo -n "$TOPIC" | gh secret set NTFY_TOPIC -R "$REPO"

echo "Secrets set for $REPO."
echo "Push notifications: install the ntfy app (iOS/Android) and subscribe to this topic:"
echo "  $TOPIC"
echo "(keep it private – anyone with the topic name can read the alerts)"
