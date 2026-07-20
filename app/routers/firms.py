"""Firms router."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Firm
from app.auth import get_current_owner

router = APIRouter(prefix="/firms", tags=["firms"])


class FirmCreate(BaseModel):
    name: str
    industry: str = ""
    website: str = ""
    notes_text: str = ""


class FirmUpdate(BaseModel):
    name: str | None = None
    industry: str | None = None
    website: str | None = None
    notes_text: str | None = None


@router.get("")
def list_firms(
    search: str = Query(default=""),
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    q = db.query(Firm).filter(Firm.owner_id == owner_id)
    if search:
        q = q.filter(Firm.name.ilike(f"%{search}%"))
    firms = q.order_by(Firm.name.asc()).all()
    return [f.to_dict() for f in firms]


@router.get("/{firm_id}")
def get_firm(
    firm_id: int,
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    firm = _get_firm_or_404(firm_id, owner_id, db)
    return firm.to_dict()


@router.post("")
def create_firm(
    data: FirmCreate,
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    firm = Firm(
        name=data.name,
        industry=data.industry,
        website=data.website,
        notes_text=data.notes_text,
        owner_id=owner_id,
    )
    db.add(firm)
    db.commit()
    db.refresh(firm)
    return firm.to_dict()


@router.put("/{firm_id}")
def update_firm(
    firm_id: int,
    data: FirmUpdate,
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    firm = _get_firm_or_404(firm_id, owner_id, db)
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(firm, key, value)
    firm.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(firm)
    return firm.to_dict()


@router.delete("/{firm_id}")
def delete_firm(
    firm_id: int,
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    firm = _get_firm_or_404(firm_id, owner_id, db)
    # Unlink contacts
    from app.models import Contact
    db.query(Contact).filter(Contact.firm_id == firm_id).update({Contact.firm_id: None})
    db.delete(firm)
    db.commit()
    return {"ok": True}


def _get_firm_or_404(firm_id: int, owner_id: int, db: Session) -> Firm:
    firm = db.query(Firm).filter(
        Firm.id == firm_id, Firm.owner_id == owner_id
    ).first()
    if not firm:
        raise HTTPException(status_code=404, detail="Firm not found")
    return firm
