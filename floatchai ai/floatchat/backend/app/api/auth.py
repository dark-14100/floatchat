"""
FloatChat JWT Authentication

Minimal JWT validator providing FastAPI dependency for admin-only endpoints.
The main FloatChat auth service issues tokens; this module validates them.

Usage:
    @router.post("/secure-endpoint")
    async def secure(user: dict = Depends(get_current_admin_user)):
        ...
"""

from typing import Optional

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings

logger = structlog.get_logger(__name__)

# HTTP Bearer scheme for Authorization header
security = HTTPBearer(auto_error=False)

# JWT algorithm
ALGORITHM = "HS256"


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """
    FastAPI dependency to extract and validate JWT token.
    
    Verifies:
        - Token is present
        - Token signature is valid
        - Token is not expired (handled by python-jose)
    
    Returns:
        Decoded token payload as dict
    
    Raises:
        HTTPException(401): If token is missing or invalid
    """
    if not credentials:
        logger.warning("auth_missing_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[ALGORITHM],
        )
        
        # Ensure required claims exist
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing subject",
            )
        
        logger.debug(
            "auth_token_validated",
            user_id=user_id,
        )
        return payload
        
    except JWTError as e:
        logger.warning(
            "auth_invalid_token",
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_admin_user(
    payload: dict = Depends(get_current_user),
) -> dict:
    """
    FastAPI dependency for admin-only endpoints.
    
    Validates that the authenticated user has admin role.
    Chain with get_current_user to first validate the token.
    
    Returns:
        Decoded token payload if user is admin
    
    Raises:
        HTTPException(403): If user is not an admin
    """
    role = payload.get("role", "")
    
    if role != "admin":
        logger.warning(
            "auth_insufficient_permissions",
            user_id=payload.get("sub"),
            role=role,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    
    logger.info(
        "auth_admin_access_granted",
        user_id=payload.get("sub"),
    )
    return payload


def create_access_token(
    user_id: str,
    role: str = "user",
    expires_delta_minutes: int = 60,
) -> str:
    """
    Create a JWT access token for testing purposes.
    
    In production, tokens are issued by the main FloatChat auth service.
    This function is provided for development/testing convenience.
    
    Args:
        user_id: User identifier to encode in 'sub' claim
        role: User role (e.g., 'admin', 'user')
        expires_delta_minutes: Token validity in minutes
    
    Returns:
        Encoded JWT token string
    """
    from datetime import datetime, timedelta, timezone
    
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_delta_minutes)
    
    to_encode = {
        "sub": user_id,
        "role": role,
        "exp": expire,
    }
    
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt
