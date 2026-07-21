"""Users router — register, login, profile, admin management."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.auth import get_current_user, require_admin, hash_password, verify_password, create_token

router = APIRouter(tags=["users"])

MIN_PASSWORD_LEN = 6


# ── Schemas ──

class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""
    email: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class ProfileUpdate(BaseModel):
    display_name: str | None = None
    email: str | None = None
    current_password: str | None = None
    new_password: str | None = None


class UserCreate(BaseModel):
    username: str
    password: str
    display_name: str = ""
    email: str = ""
    is_admin: bool = False


class UserUpdate(BaseModel):
    password: str | None = None
    is_admin: bool | None = None


# ── Auth endpoints ──

@router.post("/auth/register")
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(400, "Username already taken")
    if len(data.password) < MIN_PASSWORD_LEN:
        raise HTTPException(400, f"Password must be at least {MIN_PASSWORD_LEN} characters")

    user = User(
        username=data.username,
        display_name=data.display_name or data.username,
        email=data.email,
        password_hash=hash_password(data.password),
        password_salt="",
        is_admin=False,
        owner_id=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"token": create_token(user), "user": user.to_dict()}


@router.post("/auth/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Invalid username or password")
    return {"token": create_token(user), "user": user.to_dict()}


# ── Profile ──

@router.get("/me")
def whoami(user: User = Depends(get_current_user)):
    return user.to_dict()


@router.put("/me")
def update_profile(data: ProfileUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if data.display_name is not None:
        user.display_name = data.display_name
    if data.email is not None:
        user.email = data.email
    if data.new_password:
        if not data.current_password:
            raise HTTPException(400, "Current password required to change password")
        if not verify_password(data.current_password, user.password_hash):
            raise HTTPException(400, "Current password is incorrect")
        if len(data.new_password) < MIN_PASSWORD_LEN:
            raise HTTPException(400, f"New password must be at least {MIN_PASSWORD_LEN} characters")
        user.password_hash = hash_password(data.new_password)
        user.password_salt = ""
    db.commit()
    db.refresh(user)
    return user.to_dict()


# ── Admin user management ──

@router.get("/users")
def list_users(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [u.to_dict() for u in db.query(User).order_by(User.username).all()]


@router.post("/users")
def create_user(data: UserCreate, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(400, "Username already taken")
    if len(data.password) < MIN_PASSWORD_LEN:
        raise HTTPException(400, f"Password must be at least {MIN_PASSWORD_LEN} characters")

    user = User(
        username=data.username,
        display_name=data.display_name or data.username,
        email=data.email,
        password_hash=hash_password(data.password),
        password_salt="",
        is_admin=data.is_admin,
        owner_id=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.to_dict()


@router.delete("/users/{user_id}")
def delete_user(user_id: int, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    db.delete(user)
    db.commit()
    return {"ok": True}
