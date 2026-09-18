"""Password hashing and bearer-token issuing for the application's login.

bcrypt is called directly rather than through passlib: the installed
passlib 1.7.4 reads `bcrypt.__about__.__version__`, which bcrypt dropped
after 4.0, so that pairing breaks on the next bcrypt upgrade. The direct API
has no such coupling.

Tokens are stateless JWTs. That means "log out" is the client discarding its
token rather than the server revoking one - fine for this POC, but the reason
the expiry is kept short.
"""
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings

ALGORITHM = "HS256"

# bcrypt hashes at most 72 bytes and raises on anything longer. Truncating in
# one place keeps hashing and verifying consistent - doing it in only one of
# the two would silently reject correct long passwords.
_MAX_PASSWORD_BYTES = 72


def _encode(password: str) -> bytes:
    return password.encode("utf-8")[:_MAX_PASSWORD_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_encode(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_encode(password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        # A malformed or truncated hash in the row has to read as "wrong
        # password", never as an exception that turns a failed login into a 500.
        return False


def create_access_token(username: str) -> tuple[str, int]:
    """Returns (token, seconds_until_expiry)."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {"sub": username, "iat": now, "exp": now + timedelta(minutes=settings.jwt_expire_minutes)},
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )
    return token, settings.jwt_expire_minutes * 60


def decode_access_token(token: str) -> str | None:
    """The username the token was issued to, or None if it is invalid,
    tampered with, signed with a different secret, or expired."""
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGORITHM])
    except JWTError:
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None
