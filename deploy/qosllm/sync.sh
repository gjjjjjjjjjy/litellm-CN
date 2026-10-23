#!/bin/bash
set -euo pipefail

if [[ "${1:-}" == "--backend-only" ]]; then
  build_ui=false
  shift
else
  build_ui=true
fi
if [[ $# -ne 2 ]]; then
  printf '用法：%s [--backend-only] SSH目标 服务器部署目录\n例如：%s qosllm /root/service/litellm-CN/deploy/qosllm\n' "$0" "$0" >&2
  exit 2
fi

target="$1"
remote_dir="$2"
remote_dir_q="$(printf '%q' "$remote_dir")"
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
version="$(sed -n 's/^version = "\(.*\)"$/\1/p' "$repo_root/pyproject.toml" | head -n 1)"

remote_version="$(ssh "$target" "docker run --rm --entrypoint python3 litellm-local:zh-cn-amd64 -c 'import importlib.metadata; print(importlib.metadata.version(\"litellm\"))'")"
if [[ "$remote_version" != "$version" ]]; then
  echo "服务器镜像中的 litellm $remote_version 与源码版本 $version 不一致，请先用 build-image.sh 更新服务器镜像" >&2
  exit 1
fi

stage="$(mktemp -d -t qosllm-sync.XXXXXXXX)"
trap 'rm -rf "$stage"' EXIT
"$repo_root/localization/zh-CN/stage-backend.sh" "$repo_root" "$stage/backend"
components=(backend)
if [[ "$build_ui" == true ]]; then
  "$repo_root/localization/zh-CN/build-ui.sh" "$repo_root" "$stage/ui"
  components+=(ui)
fi

for component in "${components[@]}"; do
  printf '正在同步 %s ...\n' "$component"
  ssh "$target" "mkdir -p $remote_dir_q/runtime/$component"
  rsync -rlz --checksum --delete --delay-updates --stats -e ssh "$stage/$component/" "$target:$remote_dir/runtime/$component/"
done

ssh "$target" "cd $remote_dir_q && docker compose up -d --force-recreate litellm && ./start.sh"
