"""Shared route dependencies.

`require_user` is attached to every data router in main.py, so the login is
not just a screen the UI puts in front of the pages - the API itself refuses
to answer without a valid token.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import AppUser

# auto_error=False so a missing header lands in our own 401 below with the
# same body as an invalid one, rather than FastAPI's default 403.
_bearer = HTTPBearer(auto_error=False, description="Bearer token from POST /api/auth/login")

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated. Sign in again.",
    headers={"WWW-Authenticate": "Bearer"},
)


def require_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> AppUser:
    if credentials is None or not credentials.credentials:
        raise _UNAUTHENTICATED
    username = decode_access_token(credentials.credentials)
    if username is None:
        raise _UNAUTHENTICATED
    user = db.execute(select(AppUser).where(AppUser.username == username)).scalar_one_or_none()
    # Re-checked on every request, not just at login: an account deactivated or
    # deleted mid-session stops working immediately instead of staying valid
    # until its token happens to expire.
    if user is None or not user.is_active:
        raise _UNAUTHENTICATED
    return user
