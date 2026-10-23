#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

docker compose down
echo "已停止。数据保存在 Docker 卷中，再次运行 ./start.sh 即可恢复"
