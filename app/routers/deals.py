"""Deals router."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Deal, DealStage, DealType
from app.auth import get_current_owner

router = APIRouter(prefix="/deals", tags=["deals"])


class DealCreate(BaseModel):
    name: str
    type: str = "independent-sponsor"
    stage: str = "prospect"
    size_mm: float | None = None
    contact_ids: list[int] = []
    tags: list[str] = []
    notes_text: str = ""


class DealUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    stage: str | None = None
    size_mm: float | None = None
    contact_ids: list[int] | None = None
    tags: list[str] | None = None
    notes_text: str | None = None


@router.get("")
def list_deals(
    stage: str = Query(default=""),
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    q = db.query(Deal).filter(Deal.owner_id == owner_id)

    if stage:
        q = q.filter(Deal.stage == stage)

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
    db: Session = Depends(get_db),
):
    valid_stages = {e.value for e in DealStage}
    valid_types = {e.value for e in DealType}

    deal = Deal(
        name=data.name,
        stage=data.stage if data.stage in valid_stages else DealStage.prospect.value,
        type=data.type if data.type in valid_types else DealType.independent_sponsor.value,
        size_mm=data.size_mm,
        contact_ids=data.contact_ids,
        tags=data.tags,
        notes_text=data.notes_text,
        owner_id=owner_id,
    )
    db.add(deal)
    db.commit()
    db.refresh(deal)
    return deal.to_dict()


@router.put("/{deal_id}")
def update_deal(
    deal_id: int,
    data: DealUpdate,
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    deal = _get_deal_or_404(deal_id, owner_id, db)
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
    return deal.to_dict()


@router.delete("/{deal_id}")
def delete_deal(
    deal_id: int,
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    deal = _get_deal_or_404(deal_id, owner_id, db)
    db.delete(deal)
    db.commit()
    return {"ok": True}


def _get_deal_or_404(deal_id: int, owner_id: int, db: Session) -> Deal:
    deal = db.query(Deal).filter(
        Deal.id == deal_id, Deal.owner_id == owner_id
    ).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal
