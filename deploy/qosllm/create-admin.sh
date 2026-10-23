#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ $# -ne 1 ]]; then
  printf '用法：%s 管理员邮箱\n' "$0" >&2
  exit 2
fi

docker compose exec -T -e ADMIN_EMAIL="$1" litellm python3 - <<'PY'
import json
import os
import secrets
import string
import sys
import urllib.error
import urllib.request

BASE_URL = "http://localhost:4000"
HEADERS = {"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}", "Content-Type": "application/json"}


def post(path, body):
    request = urllib.request.Request(BASE_URL + path, data=json.dumps(body).encode(), headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(request) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        sys.exit(f"{path} 失败（HTTP {error.code}）：{error.read().decode()}")


def strong_password(length=20):
    classes = (string.ascii_uppercase, string.ascii_lowercase, string.digits, "!@#$%^&*-_=+")
    alphabet = "".join(classes)
    chars = [secrets.choice(group) for group in classes] + [secrets.choice(alphabet) for _ in range(length - len(classes))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


email = os.environ["ADMIN_EMAIL"]
password = strong_password()
user = post("/user/new", {"user_email": email, "user_role": "proxy_admin", "auto_create_key": False})
post("/user/update", {"user_id": user["user_id"], "password": password})
print(f"已创建管理员：{email}")
print(f"初始密码：{password}")
print("首次登录后系统会要求修改密码。该密码只显示这一次，请立即保存。")
PY
