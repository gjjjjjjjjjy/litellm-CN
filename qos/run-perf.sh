#!/bin/bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  printf '用法：%s <模型名> <并发数...>\n例如：%s qwen3-max 1 4 16 32\n' "$0" "$0" >&2
  exit 2
fi
: "${LITELLM_API_KEY:?请设置 LITELLM_API_KEY 为网关的虚拟密钥}"

qos_root="$(cd "$(dirname "$0")" && pwd)"
model="$1"
shift
concurrency=("$@")
base_url="${LITELLM_BASE_URL:-http://host.docker.internal:4000}"
requests_per_worker="${QOS_REQUESTS_PER_WORKER:-8}"
max_tokens="${QOS_MAX_TOKENS:-512}"
tag="qos-$(date +%Y%m%d-%H%M%S)-$(printf '%s' "$model" | tr -c 'A-Za-z0-9.-' '-')"
numbers=()
for parallel in "${concurrency[@]}"; do
  numbers+=("$((parallel * requests_per_worker))")
done
mkdir -p "$qos_root/results"

docker run --rm --add-host=host.docker.internal:host-gateway \
  --mount "type=bind,source=$qos_root,target=/qos" \
  litellm-qos-bench:evalscope-1.14.0 perf \
  --url "$base_url/v1/chat/completions" --api openai --api-key "$LITELLM_API_KEY" \
  --model "$model" --stream --max-tokens "$max_tokens" \
  --parallel "${concurrency[@]}" --number "${numbers[@]}" \
  --dataset line_by_line --dataset-path /qos/prompts.txt \
  --headers "x-litellm-tags=$tag" \
  --name "$tag" --outputs-dir "/qos/results/$tag"

printf '\n压测完成，请求标签：%s\n结果目录：%s\n在管理界面「服务质量」页面填入该标签，可查看网关记录的各节点指标\n' \
  "$tag" "$qos_root/results/$tag"
