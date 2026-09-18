from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models import AppUser

router = APIRouter(prefix="/api/auth", tags=["auth"])

# A genuine hash, computed once at import. Verifying against it costs the same
# bcrypt work as verifying a real user's, which is the point: a hand-written
# invalid salt would fail instantly and leak which usernames exist through
# response timing alone.
_ABSENT_USER_HASH = hash_password("no-such-user-placeholder")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


def _public(user: AppUser) -> dict:
    """Everything the UI needs and nothing it does not - the hash never leaves
    the server, in this or any other response."""
    return {"username": user.username, "full_name": user.full_name, "role": user.role}


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    username = payload.username.strip().lower()
    user = db.execute(select(AppUser).where(AppUser.username == username)).scalar_one_or_none()

    # One message and one code path for "no such user" and "wrong password".
    # Distinguishing them tells an attacker which usernames are real, and a
    # visibly faster reject does the same, so the hash check runs either way.
    password_ok = verify_password(payload.password, user.password_hash if user else _ABSENT_USER_HASH)
    if user is None or not user.is_active or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
        )

    user.last_login_at = datetime.utcnow()
    db.commit()

    token, expires_in = create_access_token(user.username)
    return {"access_token": token, "token_type": "bearer", "expires_in": expires_in, "user": _public(user)}


@router.get("/me")
def me(user: AppUser = Depends(require_user)):
    """Lets the UI confirm a stored token is still good before showing the app,
    so an expired session lands on the login screen rather than on a page of
    failed requests."""
    return {"user": _public(user)}


@router.post("/logout")
def logout(user: AppUser = Depends(require_user)):
    """Tokens are stateless, so the client discarding it *is* the logout - this
    endpoint exists so the UI has something to call, and so a real
    server-side revocation list can be added here later without changing the
    frontend."""
    return {"detail": "Signed out."}
