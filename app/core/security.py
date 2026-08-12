"""
Core security & authentication mechanisms for ChooNova-Transcribe.
"""

import hmac
from fastapi import Header, HTTPException, status
from app.core.config import (
    GATEWAY_API_KEY,
    ALLOW_ACCESS_TRANSCRIBE_HISTORY,
    ALLOW_ACCESS_COMPRESS_HISTORY,
)


async def verify_api_key(
    x_api_key: str | None = Header(None, alias="x-api-key"),
) -> bool:
    """
    Verifies authentication via x-api-key header.
    """
    token = x_api_key.strip() if x_api_key else None

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Provide 'x-api-key: <key>' header."
        )

    # Constant time comparison to prevent timing attacks
    if not hmac.compare_digest(token, GATEWAY_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key."
        )

    return True


async def verify_transcribe_history_api_key(
    x_api_key: str | None = Header(None, alias="x-api-key"),
) -> bool:
    """
    Verifies authentication via x-api-key header for transcribe history endpoints,
    or bypasses if ALLOW_ACCESS_TRANSCRIBE_HISTORY is True.
    """
    if ALLOW_ACCESS_TRANSCRIBE_HISTORY:
        return True
    return await verify_api_key(x_api_key)


async def verify_compress_history_api_key(
    x_api_key: str | None = Header(None, alias="x-api-key"),
) -> bool:
    """
    Verifies authentication via x-api-key header for compress history endpoints,
    or bypasses if ALLOW_ACCESS_COMPRESS_HISTORY is True.
    """
    if ALLOW_ACCESS_COMPRESS_HISTORY:
        return True
    return await verify_api_key(x_api_key)

