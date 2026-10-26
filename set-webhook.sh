#!/usr/bin/env bash
# Daftarkan webhook Telegram memakai nilai dari file .env
set -euo pipefail

# baca .env yang berada satu folder dengan script ini
source "$(dirname "$0")/.env"

curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -d "url=${TELEGRAM_WEBHOOK_URL}" \
  -d "secret_token=${TELEGRAM_SECRET_TOKEN}"
