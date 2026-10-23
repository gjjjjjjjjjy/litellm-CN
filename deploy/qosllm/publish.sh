#!/bin/bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  printf '用法：%s 镜像仓库地址/命名空间/仓库名\n请先使用 docker login 登录该仓库\n' "$0" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
revision="$(git -C "$repo_root" rev-parse --short=12 HEAD)"
image="$1:$revision"
stage="$(mktemp -d -t qosllm-publish.XXXXXXXX)"
trap 'rm -rf "$stage"' EXIT
mkdir "$stage/source"
git -C "$repo_root" archive HEAD | tar -C "$stage/source" -xf -
version="$(sed -n 's/^version = "\(.*\)"$/\1/p' "$stage/source/pyproject.toml" | head -n 1)"

"$stage/source/localization/zh-CN/build.sh" "$stage/source" "ghcr.io/berriai/litellm:v$version" linux/amd64 "$image"
docker image push --platform linux/amd64 "$image"
printf '已发布：%s\n服务器 .env 设置 LITELLM_IMAGE=%s，再运行 docker compose pull --policy always litellm 和 ./start.sh\n' "$image" "$image"
