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

mkdir -p "$build_root/ui" "$build_root/runtime"
tar -C "$repo_root/ui/litellm-dashboard" --exclude=node_modules --exclude=.next --exclude=out -cf "$build_root/frontend.tar" .
tar -C "$build_root/ui" -xf "$build_root/frontend.tar"

printf '正在编译中文前端，Node 在本机 Docker 架构上运行\n'
docker run --rm \
  --platform "$(docker version --format '{{.Server.Os}}/{{.Server.Arch}}')" \
  --mount "type=bind,source=$build_root,target=/work" \
  --mount "type=bind,source=$patch_root,target=/patch,readonly" \
  --mount "type=volume,source=litellm-zh-cn-npm-cache,target=/root/.npm" \
  --env HTTPS_PROXY --env HTTP_PROXY --env NO_PROXY \
  --env NEXT_TELEMETRY_DISABLED=1 --env NODE_OPTIONS=--max-old-space-size=4096 \
  node:24.19-alpine3.24 sh -ec '
    cd /work/ui
    npm ci --no-audit --no-fund
    TYPESCRIPT_PATH=/work/ui/node_modules/typescript node --test /patch/tests/localize.test.mjs
    node /patch/localize.mjs apply --source /work/ui --catalog /patch/zh-CN.json --output /work/translation-report.json
    node /patch/prepare-ui.mjs /work/ui
    hidden_menu_keys="$(node /patch/hidden-menus.mjs /work/ui/src/components/leftnav.tsx /patch/hidden-menus.json)"
    NEXT_PUBLIC_HIDDEN_MENU_KEYS="$hidden_menu_keys" npx next build
  '

cp -R "$build_root/ui/out" "$build_root/runtime/ui"
mkdir -p "$build_root/runtime/backend"
tar -C "$repo_root" --exclude=__pycache__ -cf - litellm | tar -C "$build_root/runtime/backend" -xf -
source_version="$(sed -n 's/^version = "\(.*\)"$/\1/p' "$repo_root/pyproject.toml" | head -n 1)"
cp -R "$patch_root/branding" "$build_root/runtime/branding"
cp "$patch_root/Dockerfile.runtime" "$build_root/runtime/Dockerfile"
printf '正在打包 %s 镜像：%s\n' "$target_platform" "$image_tag"
env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy docker buildx build --load \
  --platform "$target_platform" \
  --build-arg "LITELLM_BASE_IMAGE=$base_image" --build-arg "LITELLM_SOURCE_VERSION=$source_version" \
  --tag "$image_tag" "$build_root/runtime"
cp "$build_root/translation-report.json" "$patch_root/translation-report.json"
printf '中文镜像已构建为 %s，翻译报告位于 %s/translation-report.json\n' "$image_tag" "$patch_root"
