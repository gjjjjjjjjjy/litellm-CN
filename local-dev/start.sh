#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
interface="$(route -n get default | awk '/interface:/ {print $2}')"
LITELLM_LAN_IP="$(ipconfig getifaddr "$interface")"
export LITELLM_LAN_IP
exec docker compose --project-name litellm-local --env-file .env -f local-dev/compose.yaml up -d
