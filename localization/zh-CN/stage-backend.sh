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

tar -C "$repo_root" --exclude=__pycache__ -cf - litellm | tar -C "$output" -xf -
cp "$patch_root"/branding/logo.png "$patch_root"/branding/logo_dark.png \
  "$patch_root"/branding/logo_monogram.png "$patch_root"/branding/logo_monogram_dark.png "$output/litellm/proxy/"
cp "$repo_root/ui/litellm-dashboard/src/app/favicon.ico" "$output/litellm/proxy/_experimental/out/favicon.ico"
