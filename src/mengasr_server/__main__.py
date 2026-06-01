"""允许 python -m mengasr_server 启动服务。"""

import uvicorn

from .config import settings

uvicorn.run(
    "mengasr_server.app:app",
    host=settings.host,
    port=settings.port,
    log_level="info",
)
