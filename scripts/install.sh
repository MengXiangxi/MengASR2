#!/usr/bin/env bash
# MengASR2 服务器安装脚本（Ubuntu 22.04 + RTX 3090 Ti）
# 用法: bash scripts/install.sh
set -euo pipefail

INSTALL_DIR="/srv/mengasr"
VENV_DIR="$INSTALL_DIR/.venv"

echo "=== MengASR2 安装 ==="

# 1. 系统依赖
echo "[1/7] 安装系统依赖..."
sudo apt update && sudo apt install -y ffmpeg git curl

# 2. 安装 uv（Python 版本管理）
echo "[2/7] 安装 uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# 3. 安装 Python 3.12
echo "[3/7] 安装 Python 3.12..."
uv python install 3.12

# 4. 创建虚拟环境
echo "[4/7] 创建虚拟环境..."
mkdir -p "$INSTALL_DIR"
uv venv "$VENV_DIR" --python 3.12

# 5. 安装依赖（从项目根目录）
echo "[5/7] 安装 Python 依赖..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
uv pip install --python "$VENV_DIR/bin/python" -r "$PROJECT_DIR/requirements.txt"

# 6. 下载模型
echo "[6/7] 下载模型（需要 modelscope）..."
echo "  请手动运行: scripts/download_models.sh"

# 7. 安装 systemd 服务
echo "[7/7] 安装 systemd 服务..."
sudo cp "$PROJECT_DIR/deploy/systemd/mengasr.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable mengasr

echo ""
echo "=== 安装完成 ==="
echo "接下来："
echo "  1. 运行 scripts/download_models.sh 下载模型"
echo "  2. 编辑 /etc/systemd/system/mengasr.service 配置 HF Token"
echo "  3. sudo systemctl start mengasr"
