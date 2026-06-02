# MengASR2

本地部署的 ASR（自动语音识别）HTTP 服务，支持多后端切换，带 CLI 客户端。当前生产环境运行 [Qwen3-ASR-1.7B](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)，可选切换 [MiMo-V2.5-ASR](https://huggingface.co/Xiaomi-MiMo/MiMo-V2.5-ASR)。

## 特性

- **多后端支持** — Qwen3-ASR-1.7B（默认） / MiMo-V2.5-ASR（7.5B），改配置即可切换
- **双进程架构** — Listener（HTTP 网关）+ Worker（模型推理），独立 venv 隔离
- **句段时间戳** — Silero VAD 分段，输出 SRT/VTT 字幕
- **说话人分离** — pyannote.audio，自动区分多人对话
- **同步 + 异步 API** — 小文件秒出结果，大文件后台排队
- **CLI 客户端** — `mengasr transcribe` 一键转写，支持 JSON/SRT/VTT 输出
- **OpenAI 兼容** — `/v1/audio/transcriptions` 接口格式兼容 Whisper API
- **systemd 常驻** — 开机自启，故障自动重启

## 后端对比

| | Qwen3-ASR-1.7B（默认） | MiMo-V2.5-ASR |
|---|---|---|
| 参数量 | 1.7B | 7.5B |
| 显存占用 | **5.8 GB** | ~20 GB |
| 模型大小 | 4.4 GB | 34 GB |
| 加载时间 | **2.3s** | ~12s |
| VAD 分段推理（72s） | ~15s | ~9s |
| transformers | 4.57.6 | 4.49.0 |
| venv | `.venv-qwen3asr` | `.venv` |

> **切换后端：** 修改 `mengasr.yaml` 中 `worker.backend`，重启对应 systemd 服务即可。

## 架构

```
┌──────────────┐  localhost:8789  ┌──────────────┐
│   Listener   │◄────────────────►│    Worker    │
│   :8787      │  HTTP (内部协议)  │   :8789      │
│              │                  │              │
│ 鉴权/FFmpeg   │                  │ 模型推理      │
│ 文件管理      │                  │ VAD 分段     │
│ Job 队列     │                  │ 说话人分离    │
│ SRT/VTT 格式化│                  │              │
└──────────────┘                  └──────────────┘
```

## 目录结构

```
MengASR2/
├── config/                    # 配置文件
│   ├── mengasr.yaml           #   默认配置（当前指向 MiMo）
│   └── mengasr-qwen3.yaml     #   Qwen3-ASR 配置
├── src/
│   ├── mengasr_server/        # 服务端源码
│   │   ├── listener.py        #   Listener 进程（HTTP 网关）
│   │   ├── worker.py          #   Worker 进程（模型推理）
│   │   ├── worker_client.py   #   Listener → Worker 客户端
│   │   ├── app.py             #   单体模式（兼容旧版）
│   │   ├── config.py          #   向后兼容配置（env vars）
│   │   ├── config_schema.py   #   YAML 配置加载器
│   │   ├── schemas.py         #   Pydantic 数据模型
│   │   ├── auth.py            #   Bearer Token 鉴权
│   │   ├── audio.py           #   FFmpeg 标准化
│   │   ├── jobs.py            #   异步任务队列
│   │   ├── backends/          #   ASR 后端
│   │   │   ├── base.py        #     抽象基类
│   │   │   ├── mimo.py        #     MiMo-V2.5-ASR
│   │   │   └── qwen3.py       #     Qwen3-ASR-1.7B
│   │   ├── timestamps/        #   时间戳
│   │   │   └── vad.py         #     Silero VAD 分段器
│   │   ├── formatters/        #   输出格式化
│   │   │   ├── srt.py         #     SRT 字幕
│   │   │   └── vtt.py         #     WebVTT 字幕
│   │   └── diarization/       #   说话人分离
│   │       └── pyannote_engine.py  # pyannote 实现
│   └── mengasr_client/        # 客户端源码
│       ├── client.py          #   HTTP 客户端
│       └── cli.py             #   CLI 命令行工具
├── deploy/                    # 部署配置
│   ├── systemd/
│   │   ├── mengasr-listener.service
│   │   ├── mengasr-worker.service        # MiMo
│   │   └── mengasr-worker-qwen3.service  # Qwen3
│   ├── constraints.txt                    # MiMo 版本锁定
│   └── constraints-qwen3.txt              # Qwen3 版本锁定
├── scripts/                   # 安装和运维脚本
├── docs/                      # 设计文档
│   └── dual-process-architecture.md
├── ops/                       # 开发日志
├── requirements.txt
├── requirements.lock
├── pyproject.toml
└── README.md
```
│   │   ├── app.py             # FastAPI 入口 + 路由
│   │   ├── config.py          # 环境变量配置
│   │   ├── schemas.py         # Pydantic 数据模型
│   │   ├── auth.py            # Bearer Token 鉴权
│   │   ├── audio.py           # FFmpeg 标准化
│   │   ├── jobs.py            # 异步任务队列
│   │   ├── backends/          # ASR 后端
│   │   │   ├── base.py        #   抽象基类
│   │   │   └── mimo.py        #   MiMo-V2.5-ASR 实现
│   │   ├── timestamps/        # 时间戳
│   │   │   └── vad.py         #   Silero VAD 分段器
│   │   ├── formatters/        # 输出格式化
│   │   │   ├── srt.py         #   SRT 字幕
│   │   │   └── vtt.py         #   WebVTT 字幕
│   │   └── diarization/       # 说话人分离
│   │       └── pyannote_engine.py  # pyannote 实现
│   └── mengasr_client/        # 客户端源码
│       ├── __init__.py        # 包入口
│       ├── client.py          # HTTP 客户端（同步/异步/轮询）
│       └── cli.py             # CLI 命令行工具
├── deploy/                    # 部署配置
│   └── systemd/mengasr.service
├── scripts/                   # 安装和运维脚本
│   ├── install.sh             # 服务器安装
│   ├── download_models.sh     # 模型下载
│   └── start.sh               # 手动启动
├── docs/                      # 设计文档
├── requirements.txt           # 依赖（锁定版本）
├── requirements.lock          # pip freeze 精确版本
├── pyproject.toml
└── README.md
```

## 快速开始

### 环境要求

- Ubuntu 22.04+
- NVIDIA GPU（Ampere 架构，≥16GB 显存）
- NVIDIA 驱动 ≥ 535
- FFmpeg

### 1. 安装

```bash
git clone https://github.com/MengXiangxi/MengASR2.git
cd MengASR2
bash scripts/install.sh
```

### 2. 下载模型

```bash
bash scripts/download_models.sh
```

### 3. 配置

编辑 `/etc/systemd/system/mengasr.service`，设置：

```ini
# HuggingFace Token（说话人分离需要）
# 创建: https://hf.co/settings/tokens
# 需接受 pyannote/speaker-diarization-community-1 的使用条款
Environment=MENGASR_HF_TOKEN=hf_your_token_here
```

### 4. 启动

```bash
sudo systemctl start mengasr
sudo systemctl status mengasr
```

### 5. 测试

```bash
# 健康检查
curl http://localhost:8787/health

# 转写音频
curl -X POST http://localhost:8787/v1/audio/transcriptions \
  -F "file=@录音.mp3" \
  -F "language=chinese"

# 带说话人分离的 SRT 字幕
curl -X POST http://localhost:8787/v1/audio/transcriptions \
  -F "file=@录音.mp3" \
  -F "language=chinese" \
  -F "diarization=true" \
  -F "response_format=srt" \
  -o 输出.srt
```

## CLI 客户端

安装后可通过 `mengasr` 命令直接使用：

```bash
# 安装客户端（需要 httpx）
pip install -e ".[client]"

# 健康检查
mengasr --server-url http://bchnm-dl.bchnm:8787 health

# 同步转写（JSON 输出到 stdout）
mengasr transcribe audio.mp3 --server-url http://bchnm-dl.bchnm:8787 -l chinese

# 带时间戳的 SRT 字幕
mengasr transcribe audio.mp3 --server-url http://bchnm-dl.bchnm:8787 \
  --timestamps segment -f srt -o output.srt

# 说话人分离
mengasr transcribe meeting.mp3 --server-url http://bchnm-dl.bchnm:8787 \
  --timestamps segment --diarization -f srt -o meeting.srt

# 异步任务（推荐用于大文件）
mengasr transcribe long_recording.mp3 --server-url http://bchnm-dl.bchnm:8787 \
  --timestamps segment --async -f srt -o output.srt

# 查看任务列表
mengasr --server-url http://bchnm-dl.bchnm:8787 jobs

# 查看/下载指定任务
mengasr --server-url http://bchnm-dl.bchnm:8787 job <job_id> --result srt
```

### CLI 命令一览

| 命令 | 说明 |
|------|------|
| `mengasr health` | 检查服务端健康状态 |
| `mengasr transcribe <file>` | 转写音频/视频文件（别名 `t`） |
| `mengasr jobs` | 列出异步任务 |
| `mengasr job <id>` | 查看/删除/下载指定任务 |

### transcribe 参数

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `--language` | `-l` | `auto` | 语言：`auto` / `chinese` / `english` |
| `--format` | `-f` | `json` | 输出格式：`json` / `text` / `srt` / `vtt` |
| `--timestamps` | | `none` | 时间戳模式：`none` / `segment` |
| `--diarization` | | `false` | 启用说话人分离（自动启用 segment 时间戳） |
| `--num-speakers` | | `0` | 说话人数量（0=自动检测） |
| `--async` | | `false` | 使用异步任务模式（适合大文件） |
| `--poll-interval` | | `2` | 异步模式轮询间隔（秒） |
| `--output` | `-o` | stdout | 输出文件路径 |

## API 文档

启动服务后访问 `http://localhost:8787/docs` 查看 Swagger UI。

### 端点一览

| 端点 | 方法 | 功能 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/v1/models` | GET | 模型列表 |
| `/v1/audio/transcriptions` | POST | 同步转写 |
| `/v1/jobs` | POST | 创建异步任务 |
| `/v1/jobs` | GET | 列出任务 |
| `/v1/jobs/{id}` | GET | 查询任务状态 |
| `/v1/jobs/{id}/result` | GET | 下载结果 |
| `/v1/jobs/{id}` | DELETE | 取消/删除任务 |

### 请求参数（POST /v1/audio/transcriptions）

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `file` | file | 必填 | 音频/视频文件 |
| `language` | string | `auto` | 语言：`auto` / `chinese` / `english` |
| `response_format` | string | `json` | 输出格式：`json` / `text` / `srt` / `vtt` |
| `timestamps` | string | `none` | 时间戳：`none` / `segment` |
| `diarization` | string | `false` | 说话人分离：`true` / `false`（自动启用 timestamps=segment） |
| `num_speakers` | int | `0` | 说话人数量（0=自动检测） |

### 示例

```bash
# 纯文本转写
curl -X POST http://server:8787/v1/audio/transcriptions \
  -F "file=@audio.mp3" -F "language=chinese"

# 带时间戳的 JSON
curl -X POST http://server:8787/v1/audio/transcriptions \
  -F "file=@audio.mp3" -F "timestamps=segment"

# SRT 字幕 + 说话人分离
curl -X POST http://server:8787/v1/audio/transcriptions \
  -F "file=@meeting.mp3" -F "diarization=true" -F "response_format=srt" \
  -o meeting.srt

# 异步任务（大文件推荐）
curl -X POST http://server:8787/v1/jobs \
  -F "file=@long_recording.mp3" -F "diarization=true"
# 返回 {"job_id":"abc123","status":"queued"}

# 轮询结果
curl http://server:8787/v1/jobs/abc123

# 下载 SRT 结果
curl "http://server:8787/v1/jobs/abc123/result?response_format=srt" -o output.srt
```

## 配置项

所有配置通过环境变量驱动：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MENGASR_HOST` | `0.0.0.0` | 监听地址 |
| `MENGASR_PORT` | `8787` | 监听端口 |
| `MENGASR_API_KEY` | 空（跳过鉴权） | Bearer Token |
| `MENGASR_MIMO_MODEL` | `/srv/mengasr/models/XiaomiMiMo/MiMo-V2.5-ASR` | MiMo 模型路径 |
| `MENGASR_MIMO_TOKENIZER` | `/srv/mengasr/models/XiaomiMiMo/MiMo-Audio-Tokenizer` | Audio Tokenizer 路径 |
| `MENGASR_MIMO_CODE` | `/srv/mengasr/MiMo-V2.5-ASR-code` | MiMo 推理代码路径 |
| `MENGASR_MAX_UPLOAD_MB` | `2000` | 最大上传文件（MB） |
| `MENGASR_JOB_TTL_HOURS` | `24` | 异步任务过期时间 |
| `MENGASR_JOB_MAX_QUEUE` | `20` | 最大排队任务数 |
| `MENGASR_HF_TOKEN` | 空 | HuggingFace Token（说话人分离需要） |
| `HF_ENDPOINT` | `https://hf-mirror.com` | HuggingFace 镜像地址 |

## 运维

```bash
# 查看状态
sudo systemctl status mengasr

# 查看实时日志
sudo journalctl -u mengasr -f

# 重启（代码更新后）
sudo systemctl restart mengasr

# 停止
sudo systemctl stop mengasr

# 开机自启
sudo systemctl enable mengasr
```

## 后续开发

### 已完成

- [x] 阶段 0：环境确认
- [x] 阶段 1：MiMo 模型验证
- [x] 阶段 2：HTTP 服务 MVP
- [x] 阶段 3：异步任务队列
- [x] 阶段 4：句段级时间戳（VAD + SRT/VTT）
- [x] 阶段 5：说话人分离（pyannote）
- [x] 阶段 6：客户端 CLI 工具
- [x] 阶段 7：Qwen3-ASR 后端（多后端可切换，当前生产后端）

### 待开发

- [ ] Qwen3-ForcedAligner-0.6B 精确时间戳（需下载 ~1.2 GB 模型）
- [ ] Docker + NVIDIA Container Toolkit 容器化
- [ ] 压力测试与性能调优
- [ ] Dae 网络不稳定（医院网络环境）

### 扩展点

- **新后端**：继承 `src/mengasr_server/backends/base.py` 的 `ASRBackend` 即可接入新模型
- **新格式**：在 `src/mengasr_server/formatters/` 下添加新格式化器
- **新 VAD**：替换 `src/mengasr_server/timestamps/vad.py` 即可更换 VAD 引擎
- **云端后端**：在 `src/mengasr_client/` 中新增 DashScope 后端作为 fallback

## 致谢

- [MiMo-V2.5-ASR](https://github.com/XiaoMi/MiMo-V2.5-ASR) — 小米 ASR 大模型
- [pyannote.audio](https://github.com/pyannote/pyannote-audio) — 说话人分离
- [Silero VAD](https://github.com/snakers4/silero-vad) — 语音活动检测

## License

MIT
