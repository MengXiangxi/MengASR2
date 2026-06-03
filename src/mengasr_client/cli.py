"""MengASR2 CLI — 音频/视频转写命令行工具。

用法:
    # 同步转写，结果输出到 stdout
    mengasr transcribe audio.mp3 --server-url http://localhost:8787

    # 带时间戳 + SRT 输出
    mengasr transcribe audio.mp3 --timestamps segment --format srt -o output.srt

    # 异步任务模式（适合大文件）
    mengasr transcribe audio.mp3 --async --poll-interval 3

    # 说话人分离
    mengasr transcribe meeting.mp3 --timestamps segment --diarization -o meeting.srt

    # 健康检查
    mengasr health --server-url http://localhost:8787

    # 查看任务列表
    mengasr jobs --server-url http://localhost:8787
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import httpx

from .client import MengASRClient

logger = logging.getLogger("mengasr.cli")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mengasr",
        description="MengASR2 — 音频/视频转写 CLI",
    )
    parser.add_argument(
        "--server-url",
        default=os.environ.get("MENGASR_SERVER_URL", "http://localhost:8787"),
        help="MengASR2 服务端地址 (default: MENGASR_SERVER_URL 环境变量 或 http://localhost:8787)",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="API Token（服务端未配置鉴权时可省略）",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="请求超时时间，秒 (default: 600)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="显示详细日志",
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # ── transcribe ──────────────────────────────────────────
    trans = subparsers.add_parser(
        "transcribe",
        help="转写音频/视频文件",
        aliases=["t"],
    )
    trans.add_argument(
        "file",
        type=str,
        help="音频/视频文件路径",
    )
    trans.add_argument(
        "-l", "--language",
        default="auto",
        choices=["auto", "chinese", "english"],
        help="语言 (default: auto)",
    )
    trans.add_argument(
        "-f", "--format",
        default="json",
        choices=["json", "text", "srt", "vtt"],
        dest="response_format",
        help="输出格式 (default: json)",
    )
    trans.add_argument(
        "--timestamps",
        default="none",
        choices=["none", "segment"],
        help="时间戳模式 (default: none)",
    )
    trans.add_argument(
        "--diarization",
        action="store_true",
        help="启用说话人分离（自动启用 segment 时间戳）",
    )
    trans.add_argument(
        "--num-speakers",
        type=int,
        default=0,
        help="说话人数量，0=自动检测 (default: 0)",
    )
    trans.add_argument(
        "--async",
        action="store_true",
        dest="async_mode",
        help="使用异步任务模式（适合大文件）",
    )
    trans.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="异步模式轮询间隔，秒 (default: 2)",
    )
    trans.add_argument(
        "-o", "--output",
        default=None,
        help="输出文件路径（不指定则输出到 stdout）",
    )
    trans.add_argument(
        "--model",
        default="mimo-v2.5-asr",
        help="模型标识 (default: mimo-v2.5-asr)",
    )

    # ── health ──────────────────────────────────────────────
    subparsers.add_parser(
        "health",
        help="检查服务端健康状态",
    )

    # ── jobs ────────────────────────────────────────────────
    jobs_parser = subparsers.add_parser(
        "jobs",
        help="查看异步任务列表",
    )
    jobs_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="显示数量 (default: 20)",
    )

    # ── job ─────────────────────────────────────────────────
    job_parser = subparsers.add_parser(
        "job",
        help="查看/删除指定任务",
    )
    job_parser.add_argument(
        "job_id",
        help="任务 ID",
    )
    job_parser.add_argument(
        "--delete",
        action="store_true",
        help="删除该任务",
    )
    job_parser.add_argument(
        "--result",
        default=None,
        choices=["json", "text", "srt", "vtt"],
        help="下载任务结果（指定格式）",
    )

    return parser


def _cmd_transcribe(args: argparse.Namespace, client: MengASRClient) -> None:
    """执行转写。"""
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"错误: 文件不存在: {file_path}", file=sys.stderr)
        sys.exit(1)

    file_size_mb = file_path.stat().st_size / 1024 / 1024
    logger.info("文件: %s (%.1f MB)", file_path.name, file_size_mb)

    try:
        result = client.transcribe_file(
            file_path,
            language=args.language,
            timestamps=args.timestamps,
            diarization=args.diarization,
            num_speakers=args.num_speakers,
            async_mode=args.async_mode,
            output_format=args.response_format,
            output_path=args.output,
            poll_interval=args.poll_interval,
        )
    except FileNotFoundError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(f"HTTP 错误 {e.response.status_code}: {e.response.text}", file=sys.stderr)
        sys.exit(1)
    except TimeoutError as e:
        print(f"超时: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"任务失败: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    # 输出结果
    if args.output:
        # 结果已保存到文件
        if isinstance(result, str):
            print(result)
        else:
            print(f"[OK] 结果已保存到: {result}")
    else:
        # 输出到 stdout
        if isinstance(result, dict):
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(result)


def _cmd_health(args: argparse.Namespace, client: MengASRClient) -> None:
    """健康检查。"""
    try:
        result = client.health()
        status_icon = "[OK]" if result.get("model_loaded") else "[!!]"
        print(f"{status_icon} 服务状态: {result.get('status')}")
        print(f"   模型加载: {'是' if result.get('model_loaded') else '否'}")
        print(f"   GPU 可用: {'是' if result.get('gpu_available') else '否'}")
    except httpx.ConnectError:
        print(f"[FAIL] 无法连接到服务端: {args.server_url}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[FAIL] 健康检查失败: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_jobs(args: argparse.Namespace, client: MengASRClient) -> None:
    """查看任务列表。"""
    try:
        result = client.list_jobs(limit=args.limit)
        jobs = result.get("data", [])
        if not jobs:
            print("暂无任务")
            return

        print(f"{'任务 ID':<15} {'状态':<12} {'文件名':<30} {'创建时间':<20}")
        print("-" * 77)
        for job in jobs:
            job_id = job.get("job_id", "")
            status = job.get("status", "")
            filename = job.get("filename") or ""
            created = job.get("created_at", "")[:19].replace("T", " ")
            print(f"{job_id:<15} {status:<12} {filename:<30} {created:<20}")
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


def _cmd_job(args: argparse.Namespace, client: MengASRClient) -> None:
    """查看/删除/下载指定任务。"""
    try:
        if args.delete:
            result = client.delete_job(args.job_id)
            print(f"任务 {args.job_id}: {result.get('status')}")
            return

        if args.result:
            result = client.get_job_result(args.job_id, response_format=args.result)
            if isinstance(result, dict):
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(result)
            return

        # 默认：显示任务状态
        status = client.get_job_status(args.job_id)
        print(json.dumps(status, ensure_ascii=False, indent=2))
    except httpx.HTTPStatusError as e:
        detail = e.response.text
        try:
            detail = json.loads(detail).get("detail", detail)
        except (json.JSONDecodeError, AttributeError):
            pass
        print(f"错误: {detail}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    # Windows 兼容：确保 stdout 使用 UTF-8
    if sys.platform == "win32":
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    parser = _build_parser()
    args = parser.parse_args()

    # 日志配置
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.command:
        parser.print_help()
        sys.exit(0)

    client = MengASRClient(
        server_url=args.server_url,
        api_key=args.api_key,
        timeout=args.timeout,
    )

    if args.command in ("transcribe", "t"):
        _cmd_transcribe(args, client)
    elif args.command == "health":
        _cmd_health(args, client)
    elif args.command == "jobs":
        _cmd_jobs(args, client)
    elif args.command == "job":
        _cmd_job(args, client)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
