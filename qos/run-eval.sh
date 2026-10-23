#!/bin/bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  printf '用法：%s <模型名> <数据集...>\n例如：%s qwen3-max gsm8k ceval\n' "$0" "$0" >&2
  exit 2
fi
: "${LITELLM_API_KEY:?请设置 LITELLM_API_KEY 为网关的虚拟密钥}"

qos_root="$(cd "$(dirname "$0")" && pwd)"
model="$1"
shift
datasets=("$@")
base_url="${LITELLM_BASE_URL:-http://host.docker.internal:4000}"
limit="${QOS_EVAL_LIMIT:-50}"
run_name="eval-$(date +%Y%m%d-%H%M%S)-$(printf '%s' "$model" | tr -c 'A-Za-z0-9._-' '-')"
mkdir -p "$qos_root/results"

docker run --rm --add-host=host.docker.internal:host-gateway \
  --mount "type=bind,source=$qos_root,target=/qos" \
  --env HTTPS_PROXY --env HTTP_PROXY --env NO_PROXY \
  litellm-qos-bench:evalscope-1.14.0 eval \
  --model "$model" --eval-type openai_api --api-url "$base_url/v1" --api-key "$LITELLM_API_KEY" \
  --datasets "${datasets[@]}" --limit "$limit" \
  --work-dir "/qos/results/$run_name" --no-timestamp

printf '\n评测完成，结果目录：%s\n' "$qos_root/results/$run_name"
