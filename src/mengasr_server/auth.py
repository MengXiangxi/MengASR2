"""Bearer Token 鉴权。"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

_bearer = HTTPBearer(auto_error=False)


async def verify_token(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """校验 Bearer token。如果服务端未配置 api_key 则跳过鉴权。"""
    if not settings.api_key:
        # 未配置密钥 → 允许所有请求（适合可信内网环境）
        return ""

    if cred is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if cred.credentials != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return cred.credentials
