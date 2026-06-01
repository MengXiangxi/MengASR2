#!/usr/bin/env bash
# MengASR2 模型下载脚本
# 用法: bash scripts/download_models.sh
set -euo pipefail

VENV_DIR="${MENGASR_VENV:-/srv/mengasr/.venv}"
MODEL_DIR="/srv/mengasr/models"
source "$VENV_DIR/bin/activate"

echo "=== 下载 MiMo-V2.5-ASR 模型 ==="
echo "使用 ModelScope（国内直连）"

python -c "
from modelscope import snapshot_download
import os

model_dir = '$MODEL_DIR'

print('下载 MiMo-V2.5-ASR...')
snapshot_download('XiaomiMiMo/MiMo-V2.5-ASR', cache_dir=model_dir)

print('下载 MiMo-Audio-Tokenizer...')
snapshot_download('XiaomiMiMo/MiMo-Audio-Tokenizer', cache_dir=model_dir)

print('模型下载完成 ✅')
"

# 克隆 MiMo 官方推理代码
echo "=== 克隆 MiMo 推理代码 ==="
if [ ! -d "/srv/mengasr/MiMo-V2.5-ASR-code" ]; then
    git clone https://github.com/XiaoMi/MiMo-V2.5-ASR.git /srv/mengasr/MiMo-V2.5-ASR-code
fi

echo ""
echo "=== 模型下载完成 ==="
echo "模型路径: $MODEL_DIR"
echo "推理代码: /srv/mengasr/MiMo-V2.5-ASR-code"
