from fastapi import Header, Query, HTTPException, status
import hmac
from app.config import GATEWAY_API_KEY

async def verify_api_key(
    authorization: str | None = Header(None, alias="Authorization"),
    x_api_key: str | None = Header(None, alias="x-api-key"),
    api_key: str | None = Query(None, alias="api_key")
) -> bool:
    """
    Verifies authentication via:
    1) Authorization: Bearer <key>
    2) x-api-key: <key>
    3) ?api_key=<key> query param (for direct file downloads)
    """
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    elif x_api_key:
        token = x_api_key.strip()
    elif api_key:
        token = api_key.strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Provide 'Authorization: Bearer <key>' or 'x-api-key: <key>' header."
        )

    # Constant time comparison to prevent timing attacks
    if not hmac.compare_digest(token, GATEWAY_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key."
        )

    return True
