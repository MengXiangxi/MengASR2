#!/usr/bin/env bash
# MengASR2 服务启动脚本
# 用法: ./scripts/start.sh [--port 8787]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="${MENGASR_VENV:-/srv/mengasr/.venv}"

export MENGASR_MIMO_MODEL="${MENGASR_MIMO_MODEL:-/srv/mengasr/models/XiaomiMiMo/MiMo-V2.5-ASR}"
export MENGASR_MIMO_TOKENIZER="${MENGASR_MIMO_TOKENIZER:-/srv/mengasr/models/XiaomiMiMo/MiMo-Audio-Tokenizer}"
export MENGASR_MIMO_CODE="${MENGASR_MIMO_CODE:-/srv/mengasr/MiMo-V2.5-ASR-code}"
export MENGASR_PORT="${MENGASR_PORT:-8787}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

source "$VENV_DIR/bin/activate"
cd "$PROJECT_DIR/src"

echo "=== MengASR2 v0.2.0 ==="
echo "Python: $(python --version)"
echo "模型:   $MENGASR_MIMO_MODEL"
echo "端口:   $MENGASR_PORT"
echo "========================"

exec python -m mengasr_server "$@"
