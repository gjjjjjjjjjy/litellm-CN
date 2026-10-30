#!/bin/bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  printf '用法：%s <模型名或部署 ID> <数据集...>\n例如：%s GLM-5.3 gpqa_diamond ifeval aime26 general_fc\n' "$0" "$0" >&2
  exit 2
fi
: "${LITELLM_API_KEY:?请设置 LITELLM_API_KEY 为网关的虚拟密钥}"
: "${QOS_EVAL_GENERATION:?请设置 QOS_EVAL_GENERATION 为该模型的采样参数 JSON，写法见 qos/README.md}"

qos_root="$(cd "$(dirname "$0")" && pwd)"
model="$1"
shift
datasets=("$@")
base_url="${LITELLM_BASE_URL:-http://host.docker.internal:4000}"
limit="${QOS_EVAL_LIMIT:-50}"
repeats="${QOS_EVAL_REPEATS:-1}"
concurrency="${QOS_EVAL_CONCURRENCY:-4}"
tag="eval-$(date +%Y%m%d-%H%M%S)-$(printf '%s' "$model" | tr -c 'A-Za-z0-9.-' '-')"
generation="$(python3 -c '
import json, sys
print(json.dumps({**json.loads(sys.argv[1]), "stream": True, "extra_headers": {"x-litellm-tags": sys.argv[2]}}))
' "$QOS_EVAL_GENERATION" "$tag")"
mkdir -p "$qos_root/results"

docker run --rm --add-host=host.docker.internal:host-gateway \
  --mount "type=bind,source=$qos_root,target=/qos" \
  --env HTTPS_PROXY --env HTTP_PROXY --env NO_PROXY \
  litellm-qos-bench:evalscope-1.14.0 eval \
  --model "$model" --eval-type openai_api --api-url "$base_url/v1" --api-key "$LITELLM_API_KEY" \
  --datasets "${datasets[@]}" --limit "$limit" --repeats "$repeats" --eval-batch-size "$concurrency" \
  --generation-config "$generation" --ignore-errors \
  --work-dir "/qos/results/$tag" --no-timestamp

printf '\n评测完成，请求标签：%s\n结果目录：%s\n' "$tag" "$qos_root/results/$tag"
