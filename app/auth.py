"""Authentication — HTTP Basic Auth against a users table with PBKDF2-hashed passwords."""
import os
import hmac
import hashlib
import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

# Seed credentials for the first admin (only used when the users table is empty).
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", secrets.token_hex(16))

# Shared secret for the inbound-email webhook (?token=...). Empty = webhook disabled.
INBOUND_TOKEN = os.environ.get("INBOUND_TOKEN", "")

PBKDF2_ITERATIONS = 200_000
security = HTTPBasic(auto_error=False)


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Return (salt_hex, hash_hex) for a password using PBKDF2-HMAC-SHA256."""
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return salt, dk.hex()


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    try:
        _, computed = hash_password(password, salt)
    except ValueError:
        return False
    return hmac.compare_digest(computed, expected_hash)


def seed_admin_user(db: Session) -> None:
    """Create the initial admin from env vars if no users exist yet."""
    if db.query(User).count() == 0:
        salt, pwd_hash = hash_password(ADMIN_PASSWORD)
        db.add(User(
            username=ADMIN_USER,
            password_hash=pwd_hash,
            password_salt=salt,
            is_admin=True,
            owner_id=1,
        ))
        db.commit()


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Validate Basic Auth credentials against the users table. Returns the User."""
    credentials: HTTPBasicCredentials | None = await security(request)
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )

    user = db.query(User).filter(User.username == credentials.username).first()

    if user is None:
        # Compute a dummy hash to keep timing roughly constant for unknown usernames.
        hash_password(credentials.password)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    if not verify_password(credentials.password, user.password_salt, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return user


async def get_current_owner(user: User = Depends(get_current_user)) -> int:
    """Data-scoping dependency. Shared workspace: everyone maps to the same owner_id."""
    return user.owner_id


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
