"""Auth — bcrypt passwords + JWT tokens + HTTP Basic fallback."""
import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", secrets.token_hex(16))
INBOUND_TOKEN = os.environ.get("INBOUND_TOKEN", "")

JWT_SECRET = os.environ.get("JWT_SECRET", secrets.token_hex(32))
JWT_EXPIRE_HOURS = 72

security_basic = HTTPBasic(auto_error=False)
security_bearer = HTTPBearer(auto_error=False)


# ── Password helpers ──

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against bcrypt or legacy PBKDF2 hash."""
    try:
        # bcrypt hash starts with $2b$
        if hashed.startswith("$2b$"):
            return bcrypt.checkpw(password.encode(), hashed.encode())
        # Legacy PBKDF2 — check the user's password_salt field
        return _verify_legacy(password, hashed)
    except Exception:
        return False


def _verify_legacy(password: str, expected_hash: str) -> bool:
    """Fallback for old PBKDF2-hashed passwords."""
    import hmac, hashlib
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        from app.models import User
        user = db.query(User).filter(User.password_hash == expected_hash).first()
        if not user or not user.password_salt:
            return False
        salt = user.password_salt
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
        return hmac.compare_digest(dk.hex(), expected_hash)
    finally:
        db.close()


# ── Token helpers ──

def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "is_admin": user.is_admin,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except JWTError:
        return None


# ── Seed admin ──

def seed_admin_user(db: Session) -> None:
    if db.query(User).count() == 0:
        db.add(User(
            username=ADMIN_USER,
            display_name="Admin",
            password_hash=hash_password(ADMIN_PASSWORD),
            password_salt="",
            is_admin=True,
            owner_id=1,
        ))
        db.commit()


# ── Get current user (JWT first, then Basic fallback) ──

async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    # Try JWT Bearer first
    credentials: HTTPBasicCredentials | None = await security_bearer(request)
    if credentials:
        payload = decode_token(credentials.credentials)
        if payload:
            user = db.query(User).filter(User.id == int(payload["sub"])).first()
            if user:
                return user

    # Fallback: HTTP Basic Auth
    basic: HTTPBasicCredentials | None = await security_basic(request)
    if basic:
        user = db.query(User).filter(User.username == basic.username).first()
        if user and verify_password(basic.password, user.password_hash):
            return user
        if not user:
            hash_password(secrets.token_hex(16))

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_owner(user: User = Depends(get_current_user)) -> int:
    return user.owner_id


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
