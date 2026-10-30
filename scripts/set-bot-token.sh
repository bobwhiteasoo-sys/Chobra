#!/usr/bin/env bash
# Run on the server. Reads the bot token without echoing it, checks it with Telegram,
# stores it in .env.deploy and restarts the services that use it.
set -euo pipefail
cd /opt/chobra
read -rsp "Токен бота: " token
echo
username="$(curl -fsS "https://api.telegram.org/bot${token}/getMe" | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["username"])')" || { echo "Telegram не принял токен" >&2; exit 1; }
sed -i '/^CHOBRA_TELEGRAM_BOT_TOKEN=/d;/^CHOBRA_TELEGRAM_BOT_USERNAME=/d' .env.deploy
{ echo "CHOBRA_TELEGRAM_BOT_TOKEN='${token}'"; echo "CHOBRA_TELEGRAM_BOT_USERNAME='${username}'"; } >> .env.deploy
docker compose --env-file .env.deploy -f infra/compose.production.yml -f infra/compose.public.yml up -d --wait api worker bot web caddy
echo "Готово: бот @${username} подключён"
