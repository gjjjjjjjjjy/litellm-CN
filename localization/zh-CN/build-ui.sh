#!/bin/bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  printf '用法：%s /绝对路径/litellm 输出目录（不能已存在）\n' "$0" >&2
  exit 2
fi

patch_root="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$1" && pwd)"
mkdir "$2"
output="$(cd "$2" && pwd)"
work="$(mktemp -d -t litellm-zh-cn-ui.XXXXXXXX)"
trap 'rm -rf "$work"' EXIT

mkdir "$work/ui"
tar -C "$repo_root/ui/litellm-dashboard" --exclude=node_modules --exclude=.next --exclude=out -cf - . | tar -C "$work/ui" -xf -

printf '正在编译中文前端，Node 在本机 Docker 架构上运行\n'
docker run --rm \
  --platform "$(docker version --format '{{.Server.Os}}/{{.Server.Arch}}')" \
  --mount "type=bind,source=$work,target=/work" \
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

cp -R "$work/ui/out/." "$output/"
cp "$work/translation-report.json" "$patch_root/translation-report.json"
printf '中文前端已编译到 %s，翻译报告位于 %s/translation-report.json\n' "$output" "$patch_root"
