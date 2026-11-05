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

"$stage/source/localization/zh-CN/build.sh" "$stage/source" linux/amd64 "$image"
env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy docker buildx build --load --platform linux/amd64 \
  --file "$stage/source/qos/media-probe.Dockerfile" --tag "$image-media-probe" "$stage/source/qos"
docker image push --platform linux/amd64 "$image"
docker image push --platform linux/amd64 "$image-media-probe"
printf '已发布：%s 和 %s-media-probe\n服务器 .env 设置 LITELLM_IMAGE=%s，再运行 docker compose pull --policy always litellm media-probe 和 ./start.sh\n' \
  "$image" "$image" "$image"
