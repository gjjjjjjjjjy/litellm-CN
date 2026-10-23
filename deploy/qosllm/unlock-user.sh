#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ $# -ne 1 ]]; then
  printf '用法：%s 用户邮箱\n' "$0" >&2
  exit 2
fi

set -a
. ./.env
set +a

result="$(docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -v email="$1" -At <<'SQL'
UPDATE "LiteLLM_UserTable"
SET metadata = metadata - 'login_failed_attempts' - 'login_locked_until' - 'login_locked_at'
WHERE lower(user_email) = lower(:'email');
SQL
)"
if [[ "$result" == "UPDATE 0" ]]; then
  echo "没有找到邮箱为 $1 的用户" >&2
  exit 1
fi
echo "已解锁 $1"
