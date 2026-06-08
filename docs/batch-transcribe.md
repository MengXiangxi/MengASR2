# 批量转写工具使用指南

`batch_transcribe.py` 是一个交互式批量音频转写工具，调用远程 MengASR2 服务端 API，将目录中的音频/视频文件批量转写为文本。支持说话人分离、异步排队、断点续转。

## 环境配置

### 前置条件

- Python ≥ 3.12
- [uv](https://docs.astral.sh/uv/)（推荐）或 pip

### 安装步骤（uv）

```bash
cd MengASR2

# 创建虚拟环境
uv venv

# 安装项目（客户端模式，仅包含 httpx 等轻量依赖）
uv pip install -e ".[client]"
```

安装完成后，`batch_transcribe.bat`（Windows）可直接双击运行。

### 安装步骤（pip）

```bash
cd MengASR2
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # Linux/macOS
pip install -e ".[client]"
```

## 配置服务端地址

工具通过以下优先级确定服务端地址：

| 优先级 | 方式 | 示例 |
|--------|------|------|
| 1（最高） | 命令行参数 `--server` | `--server http://100.84.192.117:8787` |
| 2 | 环境变量 `MENGASR_SERVER_URL` | 见下方设置方法 |
| 3（最低） | 默认值 | `http://localhost:8787` |

### 设置环境变量

**Windows（永久生效）：**

```powershell
# 用户级环境变量（新终端窗口生效）
[System.Environment]::SetEnvironmentVariable("MENGASR_SERVER_URL", "http://<服务器IP>:8787", "User")

# 或临时设置（仅当前终端）
$env:MENGASR_SERVER_URL = "http://<服务器IP>:8787"
```

**Linux/macOS（永久生效）：**

```bash
# 添加到 ~/.bashrc 或 ~/.zshrc
export MENGASR_SERVER_URL="http://<服务器IP>:8787"
```

## 使用方式

### Windows 双击运行

双击 `batch_transcribe.bat`，按提示操作即可。

### 命令行运行

```bash
# 激活虚拟环境后
python batch_transcribe.py [选项]
```

## 命令行参数

### 服务端

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `--server` | `-s` | 环境变量 / `localhost:8787` | 服务端地址 |
| `--api-key` | | 空 | API Key（服务端启用鉴权时需要） |

### 输入/输出

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `--input` | `-i` | `data` | 输入目录，扫描其中的音频文件 |
| `--output` | `-o` | 与输入同目录 | 输出目录 |
| `--file` | `-f` | | 转写单个文件（跳过目录扫描） |

### 转写参数

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `--language` | `-l` | `chinese` | 语言：`auto` / `chinese` / `english` |
| `--no-diarization` | | 关闭 | 禁用说话人分离 |
| `--num-speakers` | | `0`（自动） | 说话人数量 |

### 模式控制

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--no-async` | 异步 | 使用同步模式 |
| `--poll-interval` | `5` | 异步轮询间隔（秒） |
| `--max-wait` | `1800` | 单文件最大等待时间（秒） |
| `--sync-timeout` | `600` | 同步模式超时（秒） |
| `--force` | | 强制重新转写（即使输出文件已存在） |
| `--dry-run` | | 仅列出待处理文件，不执行转写 |

## 交互式菜单

运行后，工具会显示当前参数配置并等待确认：

```
  当前参数配置:
    [1] 服务端地址:  http://100.84.192.117:8787
    [2] 语言:        chinese
    [3] 说话人分离:  关闭
    [4] 说话人数量:  0 (自动)
    [5] 转写模式:    异步
    [6] 输入目录:    data

  回车使用默认参数，输入编号修改 (1-7):
```

输入对应编号即可修改参数，回车直接开始转写。

## 支持的文件格式

| 类别 | 扩展名 |
|------|--------|
| 音频 | `.mp3` `.wav` `.m4a` `.aac` `.flac` `.ogg` `.wma` `.opus` |
| 视频 | `.mp4` `.webm` |

> 服务端使用 FFmpeg 自动处理格式转换，客户端无需预转换。

## 输出说明

- 转写结果保存为与音频同名的 `.txt` 文件（如 `录音.mp3` → `录音.txt`）
- 已存在的 `.txt` 文件会自动跳过，使用 `--force` 可覆盖
- 开启说话人分离时，输出格式为 `[SPEAKER_XX]: 转写文本`，同一说话人的连续段落会自动合并

## 使用示例

```bash
# 默认参数，扫描 ./data 目录
python batch_transcribe.py

# 指定服务端和输入目录
python batch_transcribe.py -s http://100.84.192.117:8787 -i ./recordings

# 转写单个文件
python batch_transcribe.py -f meeting.mp3

# 开启说话人分离，指定 2 位说话人
python batch_transcribe.py --num-speakers 2

# 英语转写，输出到指定目录
python batch_transcribe.py -l english -o ./transcripts

# 同步模式（适合短音频）
python batch_transcribe.py --no-async

# 仅查看待处理文件
python batch_transcribe.py --dry-run

# 强制重新转写所有文件
python batch_transcribe.py --force
```

## 工作流程

```
扫描目录 → 过滤已处理 → 显示参数 → 健康检查 → 逐文件转写 → 汇总结果
                                         ↓
                                    提交任务 → 轮询状态 → 保存文本
```

1. **扫描**：在输入目录中查找支持的音频/视频文件
2. **过滤**：跳过已有对应 `.txt` 文件的音频（除非 `--force`）
3. **配置**：显示参数菜单，允许交互修改
4. **健康检查**：验证服务端可用性和模型加载状态
5. **转写**：逐文件提交转写任务，异步模式下自动轮询等待
6. **汇总**：显示成功/失败统计

## 常见问题

### 连接服务端失败

```
服务端连接失败: ...
```

- 检查服务端地址是否正确：`curl http://<地址>:8787/health`
- 检查网络连通性（VPN / Tailscale 是否已连接）
- 确认服务端进程正在运行

### httpx 未安装

```
错误: httpx 未安装
```

重新安装客户端依赖：

```bash
uv pip install -e ".[client]"
```

### 转写结果为空

- 音频文件可能没有有效语音内容
- 检查语言设置是否匹配（中文音频用 `chinese`，英文用 `english`）
- 尝试 `--language auto` 自动检测

### 所有文件已跳过

```
所有文件已转写，无需处理。
```

使用 `--force` 强制重新转写，或删除对应的 `.txt` 输出文件。
