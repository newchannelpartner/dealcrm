"""Users router — current-user info and admin-only user management."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.auth import get_current_user, require_admin, hash_password

router = APIRouter(tags=["users"])

MIN_PASSWORD_LEN = 6


class UserCreate(BaseModel):
    username: str
    password: str
    is_admin: bool = False


class UserUpdate(BaseModel):
    password: str | None = None
    is_admin: bool | None = None


@router.get("/me")
async def whoami(user: User = Depends(get_current_user)):
    return user.to_dict()


@router.get("/users")
def list_users(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    users = db.query(User).order_by(User.created_at.asc()).all()
    return [u.to_dict() for u in users]


@router.post("/users")
def create_user(
    data: UserCreate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    username = data.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    if len(data.password) < MIN_PASSWORD_LEN:
        raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD_LEN} characters")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="That username is already taken")

    salt, pwd_hash = hash_password(data.password)
    user = User(
        username=username,
        password_hash=pwd_hash,
        password_salt=salt,
        is_admin=bool(data.is_admin),
        owner_id=1,  # shared workspace
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.to_dict()


@router.put("/users/{user_id}")
def update_user(
    user_id: int,
    data: UserUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(user_id, db)

    if data.password is not None:
        if len(data.password) < MIN_PASSWORD_LEN:
            raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD_LEN} characters")
        user.password_salt, user.password_hash = hash_password(data.password)

    if data.is_admin is not None and bool(data.is_admin) != bool(user.is_admin):
        if not data.is_admin and _admin_count(db) <= 1 and user.is_admin:
            raise HTTPException(status_code=400, detail="Can't remove the last admin")
        user.is_admin = bool(data.is_admin)

    db.commit()
    db.refresh(user)
    return user.to_dict()


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(user_id, db)
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="You can't delete your own account")
    if user.is_admin and _admin_count(db) <= 1:
        raise HTTPException(status_code=400, detail="Can't delete the last admin")
    db.delete(user)
    db.commit()
    return {"ok": True}


def _admin_count(db: Session) -> int:
    return db.query(User).filter(User.is_admin == True).count()  # noqa: E712


def _get_user_or_404(user_id: int, db: Session) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
