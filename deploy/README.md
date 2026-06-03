# 部署配置说明

本目录包含 MengASR2 的部署相关配置文件。

## 目录结构

```
deploy/
├── README.md                              # 本文件
├── systemd/                               # systemd 服务单元文件
│   ├── *.service.example                  # 服务模板（需复制后修改）
│   ├── mengasr.service                    # 单体模式（已弃用）
│   ├── mengasr-listener.service           # Listener（HTTP 网关）
│   ├── mengasr-worker.service             # Worker（MiMo 后端）
│   └── mengasr-worker-qwen3.service       # Worker（Qwen3 后端）
├── constraints.txt                        # MiMo 后端 pip 版本锁定
└── constraints-qwen3.txt                  # Qwen3 后端 pip 版本锁定
```

## 快速部署

### 1. 安装

```bash
bash scripts/install.sh
```

### 2. 配置

```bash
# 复制配置模板
cp config/mengasr.yaml.example config/mengasr.yaml
# 编辑配置（修改模型路径、HF Token 等）
vim config/mengasr.yaml
```

### 3. 安装 systemd 服务

```bash
# 复制服务文件（根据需要选择一个或多个后端）
sudo cp deploy/systemd/mengasr-listener.service /etc/systemd/system/
sudo cp deploy/systemd/mengasr-worker.service /etc/systemd/system/

# ⚠️ 编辑服务文件，修改以下占位符：
#   User=<你的用户名>
#   WorkingDirectory=<安装目录>/server
#   ExecStart=<安装目录>/.venv/bin/python -m mengasr_server
#   Environment=MENGASR_CONFIG=<安装目录>/mengasr.yaml
#   Environment=PIP_CONSTRAINT=<安装目录>/constraints.txt

sudo systemctl daemon-reload
sudo systemctl enable mengasr-listener mengasr-worker
sudo systemctl start mengasr-worker        # 先启动 Worker
sudo systemctl start mengasr-listener      # 再启动 Listener
```

## 服务文件说明

| 服务文件 | 说明 | 备注 |
|----------|------|------|
| `mengasr-listener.service` | HTTP API 网关 | 对外暴露，监听 8787 端口 |
| `mengasr-worker.service` | 模型推理（MiMo 后端） | 仅 localhost:8789，需要 GPU |
| `mengasr-worker-qwen3.service` | 模型推理（Qwen3 后端） | 独立 venv，与 MiMo 版本不兼容 |
| `mengasr.service` | 单体模式 | 已弃用，保留兼容 |

## 必须修改的占位符

所有 `.service` 文件中的以下值需根据实际部署环境替换：

| 占位符 | 示例值 | 说明 |
|--------|--------|------|
| `User=` | `mengasr` | 运行服务的系统用户 |
| `WorkingDirectory=` | `/srv/mengasr/server` | 服务端代码目录 |
| `ExecStart=` | `/srv/mengasr/.venv/bin/python ...` | Python 解释器路径 |
| `Environment=MENGASR_CONFIG=` | `/srv/mengasr/mengasr.yaml` | 配置文件路径 |
| `Environment=PIP_CONSTRAINT=` | `/srv/mengasr/constraints.txt` | pip 约束文件路径 |
| `MemoryMax=` | `24G` | 内存限制（根据 GPU 显存调整） |

## constraints 文件

| 文件 | 后端 | 说明 |
|------|------|------|
| `constraints.txt` | MiMo-V2.5-ASR | `transformers==4.49.0`（5.x 不兼容 MiMo） |
| `constraints-qwen3.txt` | Qwen3-ASR-1.7B | `transformers==4.57.6` |

⚠️ 两个后端的 `transformers` 版本**互不兼容**，因此 Qwen3 使用独立 venv。

## 环境要求

- Ubuntu 22.04+
- NVIDIA GPU（Ampere 架构及以上，≥16GB 显存）
- NVIDIA 驱动 ≥ 535
- CUDA Toolkit（flash-attn 编译需要）
- FFmpeg
- Python 3.11+
