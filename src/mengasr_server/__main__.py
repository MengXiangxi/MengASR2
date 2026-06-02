"""MengASR2 启动入口。

用法：
    python -m mengasr_server                  # 单体模式（兼容旧版）
    python -m mengasr_server --listener       # Listener 进程（新架构双进程）
    python -m mengasr_server --worker         # Worker 进程（新架构双进程）
"""

import sys

import uvicorn

if "--worker" in sys.argv:
    from .config_schema import get_worker_config
    cfg = get_worker_config()
    uvicorn.run(
        "mengasr_server.worker:app",
        host=cfg["host"],
        port=cfg["port"],
        log_level="info",
    )

elif "--listener" in sys.argv:
    from .config import settings
    uvicorn.run(
        "mengasr_server.listener:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
    )

else:
    # 默认：单体模式
    from .config import settings
    uvicorn.run(
        "mengasr_server.app:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
    )
