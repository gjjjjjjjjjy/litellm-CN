#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

command -v docker >/dev/null || { echo "未找到 docker，请先安装 Docker 和 Docker Compose 插件" >&2; exit 1; }
docker compose version >/dev/null

random_hex() {
  head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'
}

if [[ ! -f .env ]]; then
  sed -e "s|^LITELLM_MASTER_KEY=.*|LITELLM_MASTER_KEY=sk-$(random_hex 24)|" \
    -e "s|^LITELLM_SALT_KEY=.*|LITELLM_SALT_KEY=$(random_hex 32)|" \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(random_hex 24)|" \
    .env.example > .env
  chmod 600 .env
  echo "已生成 .env，其中的密钥为随机生成，请妥善备份（LITELLM_SALT_KEY 丢失后已保存的服务商密钥将无法解密）"
  echo "请编辑 .env 填写 SITE_ADDRESS（解析到本服务器的域名），然后重新运行 ./start.sh"
  exit 1
fi

set -a
. ./.env
set +a

[[ -n "${SITE_ADDRESS:-}" ]] || { echo "请在 .env 中设置 SITE_ADDRESS" >&2; exit 1; }
for name in LITELLM_MASTER_KEY LITELLM_SALT_KEY POSTGRES_PASSWORD; do
  value="${!name:-}"
  (( ${#value} >= 32 )) || { echo "$name 至少需要 32 个字符" >&2; exit 1; }
done
if [[ "$SITE_ADDRESS" == :* ]]; then
  echo "警告：SITE_ADDRESS 未使用域名，登录密码将通过未加密的 HTTP 传输，仅适合临时测试" >&2
fi

if [[ "${1:-}" == "--build" ]] || ! docker image inspect litellm-local:zh-cn >/dev/null 2>&1; then
  repo_root="$(cd ../.. && pwd)"
  version="$(sed -n 's/^version = "\(.*\)"$/\1/p' "$repo_root/pyproject.toml" | head -n 1)"
  echo "正在构建镜像 litellm-local:zh-cn（首次约 10~20 分钟）..."
  "$repo_root/localization/zh-CN/build.sh" "$repo_root" "ghcr.io/berriai/litellm:v$version"
fi

docker compose up -d

echo "等待网关就绪（首次启动需要初始化数据库，约 1~3 分钟）..."
health="starting"
for _ in $(seq 1 60); do
  health="$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q litellm)")"
  [[ "$health" == "healthy" ]] && break
  sleep 5
done
[[ "$health" == "healthy" ]] || { echo "网关 5 分钟内未就绪，请查看日志：docker compose logs litellm" >&2; exit 1; }

admins="$(docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At \
  -c "SELECT count(*) FROM \"LiteLLM_UserTable\" WHERE user_role = 'proxy_admin' AND password IS NOT NULL")"

if [[ "$SITE_ADDRESS" == :* ]]; then
  echo "已启动：http://<服务器 IP>${SITE_ADDRESS#:80}/ui/"
else
  echo "已启动：https://$SITE_ADDRESS/ui/"
fi
if [[ "$admins" == "0" ]]; then
  echo "还没有管理员账号，请运行：./create-admin.sh 管理员邮箱"
fi
