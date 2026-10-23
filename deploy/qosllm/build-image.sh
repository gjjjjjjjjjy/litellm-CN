#!/bin/bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  printf '用法：%s /输出目录/qosllm-linux-amd64.tar.gz\n请在本机运行，生成供服务器导入的镜像包\n' "$0" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
archive_dir="$(cd "$(dirname "$1")" && pwd)"
archive="$archive_dir/$(basename "$1")"
version="$(sed -n 's/^version = "\(.*\)"$/\1/p' "$repo_root/pyproject.toml" | head -n 1)"
image_tag=litellm-local:zh-cn-amd64

"$repo_root/localization/zh-CN/build.sh" "$repo_root" "ghcr.io/berriai/litellm:v$version" linux/amd64 "$image_tag"

archive_temp="$(mktemp "$archive.XXXXXXXX")"
trap 'rm -f "$archive_temp"' EXIT
printf '正在导出服务器镜像包\n'
docker image save --platform linux/amd64 "$image_tag" | gzip -1 > "$archive_temp"
mv "$archive_temp" "$archive"
printf '镜像包已生成：%s\n上传后在服务器执行 docker load -i 镜像包路径，再运行 ./start.sh\n' "$archive"
