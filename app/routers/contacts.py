"""Contacts router."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Contact, User
from app.auth import get_current_owner, get_current_user

router = APIRouter(prefix="/contacts", tags=["contacts"])


class ContactCreate(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    firm: str = ""
    firm_id: int | None = None
    title: str = ""
    tags: list[str] = []
    summary_text: str = ""
    relationship_tier: str = ""


class ContactUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    firm: str | None = None
    firm_id: int | None = None
    title: str | None = None
    tags: list[str] | None = None
    summary_text: str | None = None
    last_contacted_at: str | None = None
    relationship_tier: str | None = None


@router.get("")
def list_contacts(
    search: str = Query(default=""),
    tag: str = Query(default=""),
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    q = db.query(Contact).filter(Contact.owner_id == owner_id)

    if search:
        q = q.filter(
            (Contact.name.ilike(f"%{search}%"))
            | (Contact.email.ilike(f"%{search}%"))
            | (Contact.firm.ilike(f"%{search}%"))
        )

    if tag:
        q = q.filter(Contact.tags.contains(tag))

    contacts = q.order_by(Contact.updated_at.desc()).all()
    return [c.to_dict() for c in contacts]


@router.get("/{contact_id}")
def get_contact(
    contact_id: int,
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    contact = _get_contact_or_404(contact_id, owner_id, db)
    return contact.to_dict()


@router.post("")
def create_contact(
    data: ContactCreate,
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    contact = Contact(
        name=data.name,
        email=data.email,
        phone=data.phone,
        firm=data.firm,
        firm_id=data.firm_id,
        title=data.title,
        tags=data.tags,
        summary_text=data.summary_text,
        relationship_tier=data.relationship_tier or "",
        owner_id=owner_id,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact.to_dict()


@router.put("/{contact_id}")
def update_contact(
    contact_id: int,
    data: ContactUpdate,
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    contact = _get_contact_or_404(contact_id, owner_id, db)
    update_data = data.model_dump(exclude_unset=True)

    # Handle last_contacted_at specially (ISO string → datetime)
    if "last_contacted_at" in update_data:
        val = update_data.pop("last_contacted_at")
        if val:
            try:
                contact.last_contacted_at = datetime.fromisoformat(val)
            except (ValueError, TypeError):
                pass
        else:
            contact.last_contacted_at = None

    for key, value in update_data.items():
        setattr(contact, key, value)
    contact.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(contact)
    return contact.to_dict()


@router.delete("/{contact_id}")
def delete_contact(
    contact_id: int,
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    contact = _get_contact_or_404(contact_id, owner_id, db)
    db.delete(contact)
    db.commit()
    return {"ok": True}


@router.post("/{contact_id}/enrich")
async def enrich_contact(
    contact_id: int,
    user: User = Depends(get_current_user),
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    """AI-enrich a contact with firm background, industry, and suggested tags."""
    contact = _get_contact_or_404(contact_id, owner_id, db)
    from app.ai import enrich_contact as ai_enrich

    result = await ai_enrich(contact.name, contact.firm or "", contact.email or "")
    if not result.get("firm_description") and not result.get("industry"):
        raise HTTPException(503, "AI enrichment unavailable — check LLM config")

    # Build summary from enrichment
    parts = []
    if result["firm_description"]:
        parts.append(result["firm_description"])
    if result["relevance"]:
        parts.append(result["relevance"])
    contact.summary_text = " ".join(parts) if parts else contact.summary_text

    # Merge suggested tags
    existing = set(contact.tags or [])
    for tag in result.get("suggested_tags", []):
        existing.add(tag)
    contact.tags = list(existing)[:20]

    db.commit()
    db.refresh(contact)
    return {"ok": True, "contact": contact.to_dict(), "enrichment": result}


def _get_contact_or_404(contact_id: int, owner_id: int, db: Session) -> Contact:
    contact = db.query(Contact).filter(
        Contact.id == contact_id, Contact.owner_id == owner_id
    ).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact
