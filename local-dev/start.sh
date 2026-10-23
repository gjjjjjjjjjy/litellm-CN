#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec docker compose --project-name litellm-local --env-file .env -f local-dev/compose.yaml up -d
