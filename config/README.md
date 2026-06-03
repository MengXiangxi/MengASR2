# 配置文件说明

本目录包含 MengASR2 的 YAML 配置文件模板。

## 快速开始

```bash
# 复制模板，根据实际环境修改
cp config/mengasr.yaml.example config/mengasr.yaml

# 编辑配置（模型路径、HF Token 等）
vim config/mengasr.yaml
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `mengasr.yaml.example` | 主配置模板（MiMo 后端，可切换 Qwen3） |
| `mengasr-qwen3.yaml.example` | Qwen3-ASR 后端专用配置模板 |
| `mengasr.yaml` | 实际配置（**不纳入版本控制**） |
| `mengasr-qwen3.yaml` | Qwen3 实际配置（**不纳入版本控制**） |

## 关键配置项

### 必须修改

| 配置项 | 说明 |
|--------|------|
| `worker.mimo_model_path` | MiMo 模型文件路径 |
| `worker.mimo_tokenizer_path` | MiMo Audio Tokenizer 路径 |
| `worker.mimo_code_path` | MiMo 推理代码路径 |
| `diarization.hf_token` | HuggingFace Token（启用说话人分离时必填） |

### 可选修改

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `worker.backend` | `mimo` | 后端选择：`mimo` 或 `qwen3-asr` |
| `listener.host` | `0.0.0.0` | 监听地址 |
| `listener.port` | `8787` | 监听端口 |
| `auth.api_key` | 空 | Bearer Token（空=不鉴权） |
| `diarization.hf_endpoint` | `https://huggingface.co` | HF 镜像地址（中国大陆可用 `https://hf-mirror.com`） |

## 优先级

配置值的优先级从高到低：

1. **环境变量**（如 `MENGASR_MIMO_MODEL`）
2. **YAML 配置文件**（`mengasr.yaml`）
3. **代码默认值**（`config_schema.py` 中的 DEFAULTS）

## HuggingFace Token

说话人分离功能需要 HuggingFace Token：

1. 注册 [huggingface.co](https://huggingface.co) 账号
2. 前往 [Settings → Tokens](https://huggingface.co/settings/tokens) 创建 Token
3. 前往 [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) 接受使用条款
4. 将 Token 填入 `diarization.hf_token`
