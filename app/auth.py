"""
Backward compatibility layer for app.auth.
Security functions now live in app.core.security.
"""

from app.core.security import verify_api_key

__all__ = ["verify_api_key"]

