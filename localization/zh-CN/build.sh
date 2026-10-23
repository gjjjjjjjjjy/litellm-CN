#!/bin/bash
set -euo pipefail

case $# in
  2)
    target_platform="$(docker version --format '{{.Server.Os}}/{{.Server.Arch}}')"
    image_tag=litellm-local:zh-cn
    ;;
  4)
    target_platform="$3"
    image_tag="$4"
    ;;
  *)
    printf '用法：%s /绝对路径/litellm 后端基础镜像 [目标平台 镜像名称]\n' "$0" >&2
    exit 2
    ;;
esac

patch_root="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$1" && pwd)"
base_image="$2"
build_root="$(mktemp -d -t litellm-zh-cn.XXXXXXXX)"
trap 'rm -rf "$build_root"' EXIT

"$patch_root/build-ui.sh" "$repo_root" "$build_root/ui"
"$patch_root/stage-backend.sh" "$repo_root" "$build_root/backend"
source_version="$(sed -n 's/^version = "\(.*\)"$/\1/p' "$repo_root/pyproject.toml" | head -n 1)"
cp "$patch_root/Dockerfile.runtime" "$build_root/Dockerfile"
printf '正在打包 %s 镜像：%s\n' "$target_platform" "$image_tag"
env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy docker buildx build --load \
  --platform "$target_platform" \
  --build-arg "LITELLM_BASE_IMAGE=$base_image" --build-arg "LITELLM_SOURCE_VERSION=$source_version" \
  --tag "$image_tag" "$build_root"
printf '中文镜像已构建为 %s\n' "$image_tag"
