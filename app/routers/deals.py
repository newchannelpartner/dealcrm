"""Deals router."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models import Deal, DealStage, DealType, User, AuditLog
from app.auth import get_current_owner, get_current_user

router = APIRouter(prefix="/deals", tags=["deals"])


def _audit(user: User, action: str, entity_type: str = "deal", entity_id: int = None, detail: str = ""):
    """Record an audit log entry. Runs synchronously — lightweight."""
    db = SessionLocal()
    try:
        db.add(AuditLog(
            user_id=user.id,
            username=user.username,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            detail=detail,
        ))
        db.commit()
    except Exception:
        pass
    finally:
        db.close()


class DealCreate(BaseModel):
    name: str
    type: str = "independent-sponsor"
    stage: str = "prospect"
    size_mm: float | None = None
    expected_fee: float | None = None
    fee_type: str = ""
    assignee_user_id: int | None = None
    milestones: list[dict] = []
    contact_ids: list[int] = []
    tags: list[str] = []
    notes_text: str = ""


class DealUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    stage: str | None = None
    size_mm: float | None = None
    expected_fee: float | None = None
    fee_type: str | None = None
    assignee_user_id: int | None = None
    milestones: list[dict] | None = None
    contact_ids: list[int] | None = None
    tags: list[str] | None = None
    notes_text: str | None = None


@router.get("")
def list_deals(
    stage: str = Query(default=""),
    type: str = Query(default=""),
    search: str = Query(default=""),
    assignee_user_id: int = Query(default=0),
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    q = db.query(Deal).filter(Deal.owner_id == owner_id)

    if stage:
        q = q.filter(Deal.stage == stage)

    if type:
        q = q.filter(Deal.type == type)

    if assignee_user_id:
        q = q.filter(Deal.assignee_user_id == assignee_user_id)

    if search:
        q = q.filter(
            (Deal.name.ilike(f"%{search}%"))
            | (Deal.notes_text.ilike(f"%{search}%"))
        )

    deals = q.order_by(Deal.updated_at.desc()).all()
    return [d.to_dict() for d in deals]


@router.get("/{deal_id}")
def get_deal(
    deal_id: int,
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    deal = _get_deal_or_404(deal_id, owner_id, db)
    return deal.to_dict()


@router.post("")
def create_deal(
    data: DealCreate,
    owner_id: int = Depends(get_current_owner),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    valid_stages = {e.value for e in DealStage}
    valid_types = {e.value for e in DealType}

    deal = Deal(
        name=data.name,
        stage=data.stage if data.stage in valid_stages else DealStage.prospect.value,
        type=data.type if data.type in valid_types else DealType.independent_sponsor.value,
        size_mm=data.size_mm,
        expected_fee=data.expected_fee,
        fee_type=data.fee_type or "",
        assignee_user_id=data.assignee_user_id,
        milestones=data.milestones,
        contact_ids=data.contact_ids,
        tags=data.tags,
        notes_text=data.notes_text,
        owner_id=owner_id,
    )
    db.add(deal)
    db.commit()
    db.refresh(deal)
    _audit(user, "created", entity_id=deal.id, detail=f"Created deal '{deal.name}' (stage: {deal.stage})")
    return deal.to_dict()


@router.put("/{deal_id}")
def update_deal(
    deal_id: int,
    data: DealUpdate,
    owner_id: int = Depends(get_current_owner),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deal = _get_deal_or_404(deal_id, owner_id, db)
    old_stage = deal.stage
    update_data = data.model_dump(exclude_unset=True)

    valid_stages = {e.value for e in DealStage}
    valid_types = {e.value for e in DealType}

    if "stage" in update_data and update_data["stage"] not in valid_stages:
        raise HTTPException(status_code=400, detail=f"Invalid stage: {update_data['stage']}")
    if "type" in update_data and update_data["type"] not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid type: {update_data['type']}")

    for key, value in update_data.items():
        setattr(deal, key, value)
    deal.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(deal)

    # Audit stage changes
    new_stage = deal.stage
    if old_stage != new_stage:
        _audit(user, "stage_change", entity_id=deal.id,
               detail=f"Stage changed: {old_stage} → {new_stage}")
    else:
        _audit(user, "updated", entity_id=deal.id,
               detail=f"Updated deal '{deal.name}'")

    return deal.to_dict()


@router.delete("/{deal_id}")
def delete_deal(
    deal_id: int,
    owner_id: int = Depends(get_current_owner),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deal = _get_deal_or_404(deal_id, owner_id, db)
    name = deal.name
    db.delete(deal)
    db.commit()
    _audit(user, "deleted", entity_id=deal_id, detail=f"Deleted deal '{name}'")
    return {"ok": True}


def _get_deal_or_404(deal_id: int, owner_id: int, db: Session) -> Deal:
    deal = db.query(Deal).filter(
        Deal.id == deal_id, Deal.owner_id == owner_id
    ).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal
