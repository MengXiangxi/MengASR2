#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MengASR2 批量转写工具
调用 MengASR2 服务端 API 进行批量音频/视频转写，支持说话人分离。
"""

import sys
import time
import argparse
from pathlib import Path

try:
    import httpx
except ImportError:
    print("错误: httpx 未安装，请运行: pip install httpx")
    sys.exit(1)


# ── 支持的音频/视频格式 ─────────────────────────────────────
AUDIO_EXTENSIONS = {
    ".mp3", ".mp4", ".wav", ".m4a", ".aac",
    ".flac", ".ogg", ".wma", ".opus", ".webm",
}


# ── 输出格式化 ───────────────────────────────────────────────

def format_segments_with_speakers(segments: list[dict]) -> str:
    """将 segments 格式化为带说话人标签的纯文本。

    同一说话人的连续段落合并，换说话人时另起一段。
    """
    if not segments:
        return ""

    lines = []
    prev_speaker = None

    for seg in segments:
        speaker = seg.get("speaker") or "Unknown"
        text = seg.get("text", "").strip()
        if not text:
            continue

        if speaker == prev_speaker:
            # 同一说话人连续段落，追加到上一行
            lines[-1] += text
        else:
            lines.append(f"[{speaker}]: {text}")
            prev_speaker = speaker

    return "\n\n".join(lines)


# ── API 交互 ─────────────────────────────────────────────────

def check_health(base_url: str, api_key: str, timeout: float = 10.0) -> bool:
    """检查服务端是否可用。"""
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        resp = httpx.get(f"{base_url}/health", headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data.get("model_loaded", False)
    except Exception as e:
        print(f"  服务端连接失败: {e}")
        return False


def transcribe_sync(
    base_url: str,
    api_key: str,
    file_path: Path,
    language: str,
    diarization: bool,
    num_speakers: int,
    timeout: float,
) -> dict:
    """同步转写：POST /v1/audio/transcriptions"""
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    data = {
        "model": "mimo-v2.5-asr",
        "language": language,
        "response_format": "json",
        "timestamps": "segment",          # diarization 需要 segment
        "diarization": "true" if diarization else "false",
        "num_speakers": str(num_speakers),
    }

    with open(file_path, "rb") as f:
        resp = httpx.post(
            f"{base_url}/v1/audio/transcriptions",
            headers=headers,
            data=data,
            files={"file": (file_path.name, f)},
            timeout=timeout,
        )

    resp.raise_for_status()
    return resp.json()


def transcribe_async(
    base_url: str,
    api_key: str,
    file_path: Path,
    language: str,
    diarization: bool,
    num_speakers: int,
    poll_interval: float = 3.0,
    max_wait: float = 1800.0,
) -> dict:
    """异步转写：提交任务 → 轮询状态 → 返回结果"""
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # 1) 提交任务
    data = {
        "language": language,
        "response_format": "json",
        "timestamps": "segment",
        "diarization": "true" if diarization else "false",
        "num_speakers": str(num_speakers),
    }

    with open(file_path, "rb") as f:
        resp = httpx.post(
            f"{base_url}/v1/jobs",
            headers=headers,
            data=data,
            files={"file": (file_path.name, f)},
            timeout=300.0,
        )
    resp.raise_for_status()
    job_id = resp.json()["job_id"]
    print(f"    任务已提交: {job_id}")

    # 2) 轮询状态
    start = time.monotonic()
    while True:
        elapsed = time.monotonic() - start

        resp = httpx.get(
            f"{base_url}/v1/jobs/{job_id}",
            headers=headers,
            timeout=30.0,
        )
        resp.raise_for_status()
        status = resp.json()
        state = status.get("status", "unknown")

        if state == "completed":
            print(f"    转写完成 (耗时 {elapsed:.0f}s)")
            return status

        if state == "failed":
            raise RuntimeError(f"任务失败: {status.get('error', '未知错误')}")

        if state == "cancelled":
            raise RuntimeError("任务被取消")

        if elapsed > max_wait:
            raise TimeoutError(f"等待超时 ({max_wait:.0f}s)")

        # 显示进度
        duration = status.get("duration")
        dur_str = f" ({duration:.0f}s 音频)" if duration else ""
        print(f"    等待中... 状态={state} 已等 {elapsed:.0f}s{dur_str}")
        time.sleep(poll_interval)


# ── 单文件处理 ───────────────────────────────────────────────

def process_file(
    base_url: str,
    api_key: str,
    file_path: Path,
    output_path: Path,
    language: str,
    diarization: bool,
    num_speakers: int,
    use_async: bool,
    poll_interval: float,
    max_wait: float,
    sync_timeout: float,
) -> bool:
    """处理单个文件，返回是否成功。"""
    print(f"\n{'─' * 50}")
    print(f"  文件: {file_path.name}")
    print(f"  大小: {file_path.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"  输出: {output_path.name}")

    try:
        if use_async:
            result = transcribe_async(
                base_url, api_key, file_path,
                language=language,
                diarization=diarization,
                num_speakers=num_speakers,
                poll_interval=poll_interval,
                max_wait=max_wait,
            )
        else:
            result = transcribe_sync(
                base_url, api_key, file_path,
                language=language,
                diarization=diarization,
                num_speakers=num_speakers,
                timeout=sync_timeout,
            )

        # ── 提取 segments 并格式化 ────────────────────────
        segments = result.get("segments")
        if segments and diarization:
            text = format_segments_with_speakers(segments)
        else:
            text = result.get("text", "")

        if not text:
            print("  [警告] 转写结果为空")
            text = ""

        output_path.write_text(text, encoding="utf-8")
        print(f"  [成功] 已保存")
        return True

    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            detail = e.response.text[:200]
        print(f"  [失败] HTTP {e.response.status_code}: {detail}")
        return False

    except TimeoutError as e:
        print(f"  [失败] {e}")
        return False

    except Exception as e:
        print(f"  [失败] {e}")
        return False


# ── 主函数 ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="MengASR2 批量转写工具 — 调用远程服务端 API 进行音频转写",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 扫描 ./data 目录，批量转写（默认参数）
  python batch_transcribe.py

  # 指定服务端地址和输入目录
  python batch_transcribe.py --server http://your-server:8787 --input ./recordings

  # 使用同步模式
  python batch_transcribe.py --no-async

  # 指定说话人数量
  python batch_transcribe.py --num-speakers 2

  # 转写单个文件
  python batch_transcribe.py --file recording.mp3

  # 只列出待处理文件，不执行转写
  python batch_transcribe.py --dry-run
        """,
    )

    # ── 服务端 ────────────────────────────────────────────
    parser.add_argument(
        "--server", "-s",
        default="http://localhost:8787",
        help="MengASR2 服务端地址 (默认: http://localhost:8787)",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="API Key（如果服务端启用了鉴权）",
    )

    # ── 输入/输出 ─────────────────────────────────────────
    parser.add_argument(
        "--input", "-i",
        default="data",
        help="输入目录，扫描其中的音频文件 (默认: data)",
    )
    parser.add_argument(
        "--output", "-o",
        default="",
        help="输出目录（默认与输入文件同目录）",
    )
    parser.add_argument(
        "--file", "-f",
        help="转写单个文件（跳过目录扫描）",
    )

    # ── 转写参数 ─────────────────────────────────────────
    parser.add_argument(
        "--language", "-l",
        default="chinese",
        choices=["auto", "chinese", "english"],
        help="语言 (默认: chinese)",
    )
    parser.add_argument(
        "--no-diarization",
        action="store_true",
        help="禁用说话人分离",
    )
    parser.add_argument(
        "--num-speakers",
        type=int,
        default=0,
        help="说话人数量，0=自动检测 (默认: 0)",
    )

    # ── 模式 ──────────────────────────────────────────────
    parser.add_argument(
        "--no-async",
        action="store_true",
        help="使用同步模式（默认异步）",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        help="异步模式轮询间隔秒数 (默认: 5)",
    )
    parser.add_argument(
        "--max-wait",
        type=float,
        default=1800.0,
        help="单个文件最大等待秒数 (默认: 1800)",
    )
    parser.add_argument(
        "--sync-timeout",
        type=float,
        default=600.0,
        help="同步模式超时秒数 (默认: 600)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新转写（即使输出文件已存在）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅列出待处理文件，不执行转写",
    )

    args = parser.parse_args()

    # ── 参数整理（先设默认值） ────────────────────────────
    base_url = args.server.rstrip("/")
    api_key = args.api_key
    language = args.language
    diarization = not args.no_diarization
    num_speakers = args.num_speakers
    use_async = not args.no_async
    input_dir = Path(args.input)
    output_dir = Path(args.output) if args.output else None

    print("=" * 50)
    print("  MengASR2 批量转写工具")
    print("=" * 50)
    print()

    # ── 第一步：扫描待处理文件 ────────────────────────────
    if args.file:
        # 单文件模式
        files = [Path(args.file)]
    else:
        if not input_dir.exists():
            print(f"错误: 输入目录不存在: {input_dir}")
            sys.exit(1)

        files = sorted(
            f for f in input_dir.iterdir()
            if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
        )

    if not files:
        print("未找到音频文件")
        sys.exit(0)

    # 过滤已处理的文件
    pending = []
    for f in files:
        if output_dir:
            out = output_dir / f"{f.stem}.txt"
        else:
            out = f.with_suffix(".txt")

        if out.exists() and not args.force:
            continue
        pending.append((f, out))

    if not pending:
        print("所有文件已转写，无需处理。（使用 --force 强制重新转写）")
        sys.exit(0)

    print(f"找到 {len(pending)} 个待处理文件:")
    print("─" * 50)
    for f, out in pending:
        print(f"  {f.name}")
    print()

    if args.dry_run:
        print("[Dry Run] 仅列出文件，不执行转写")
        sys.exit(0)

    # ── 第二步：显示参数并允许修改 ────────────────────────
    def _show_config():
        print("  当前参数配置:")
        print(f"    [1] 服务端地址:  {base_url}")
        print(f"    [2] 语言:        {language}")
        print(f"    [3] 说话人分离:  {'开启' if diarization else '关闭'}")
        print(f"    [4] 说话人数量:  {num_speakers} {'(自动)' if num_speakers == 0 else ''}")
        print(f"    [5] 转写模式:    {'异步' if use_async else '同步'}")
        print(f"    [6] 输入目录:    {input_dir}")
        if output_dir:
            print(f"    [7] 输出目录:    {output_dir}")
        print()

    _show_config()

    while True:
        try:
            choice = input("  回车使用默认参数，输入编号修改 (1-7): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            sys.exit(0)

        if not choice:
            break

        if choice == "1":
            print(f"    当前: {base_url}")
            val = input("    新地址 (回车保留): ").strip()
            if val:
                base_url = val.rstrip("/")
                print(f"    -> 已改为: {base_url}")

        elif choice == "2":
            print(f"    当前: {language}")
            print("    选项: 1=auto  2=chinese  3=english")
            val = input("    选择 (1-3): ").strip()
            lang_map = {"1": "auto", "2": "chinese", "3": "english"}
            if val in lang_map:
                language = lang_map[val]
                print(f"    -> 已改为: {language}")

        elif choice == "3":
            print(f"    当前: {'开启' if diarization else '关闭'}")
            val = input("    开启说话人分离? (Y/N): ").strip()
            if val.lower() in ("y", "yes"):
                diarization = True
            elif val.lower() in ("n", "no"):
                diarization = False
            print(f"    -> 已改为: {'开启' if diarization else '关闭'}")

        elif choice == "4":
            print(f"    当前: {num_speakers} {'(自动)' if num_speakers == 0 else ''}")
            val = input("    输入说话人数量 (0=自动): ").strip()
            if val.isdigit():
                num_speakers = int(val)
                print(f"    -> 已改为: {num_speakers} {'(自动)' if num_speakers == 0 else ''}")

        elif choice == "5":
            print(f"    当前: {'异步' if use_async else '同步'}")
            print("    选项: 1=异步  2=同步")
            val = input("    选择 (1-2): ").strip()
            if val == "1":
                use_async = True
                print("    -> 已改为: 异步")
            elif val == "2":
                use_async = False
                print("    -> 已改为: 同步")

        elif choice == "6":
            print(f"    当前: {input_dir}")
            val = input("    新目录 (回车保留): ").strip()
            if val:
                input_dir = Path(val)
                print(f"    -> 已改为: {input_dir}")

        elif choice == "7":
            cur = output_dir or "(与输入文件同目录)"
            print(f"    当前: {cur}")
            val = input("    新目录 (留空=同目录): ").strip()
            if val:
                output_dir = Path(val)
                print(f"    -> 已改为: {output_dir}")
            else:
                output_dir = None
                print("    -> 已改为: 与输入文件同目录")

        else:
            print("    无效选项")
            continue

        # 修改后重新显示当前配置
        print()
        _show_config()

    # ── 第三步：健康检查 ──────────────────────────────────
    print("检查服务端状态...")
    if not check_health(base_url, api_key):
        print("错误: 服务端不可用或模型未加载")
        sys.exit(1)
    print("  服务端正常\n")

    # ── 确认开始 ──────────────────────────────────────────
    try:
        confirm = input("开始转写？(Y/N): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        sys.exit(0)

    if confirm.lower() not in ("y", "yes"):
        print("已取消")
        sys.exit(0)

    # ── 确保输出目录存在 ──────────────────────────────────
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)

    # ── 逐文件处理 ────────────────────────────────────────
    print(f"\n{'=' * 50}")
    print("  开始批量转写")
    print(f"{'=' * 50}")

    success_count = 0
    fail_count = 0

    for idx, (f, out) in enumerate(pending, 1):
        print(f"\n[{idx}/{len(pending)}]", end="")
        ok = process_file(
            base_url=base_url,
            api_key=api_key,
            file_path=f,
            output_path=out,
            language=language,
            diarization=diarization,
            num_speakers=num_speakers,
            use_async=use_async,
            poll_interval=args.poll_interval,
            max_wait=args.max_wait,
            sync_timeout=args.sync_timeout,
        )
        if ok:
            success_count += 1
        else:
            fail_count += 1

    # ── 汇总 ──────────────────────────────────────────────
    print(f"\n{'=' * 50}")
    print("  批量转写完成!")
    print(f"{'=' * 50}")
    print(f"  成功: {success_count} 个文件")
    print(f"  失败: {fail_count} 个文件")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
