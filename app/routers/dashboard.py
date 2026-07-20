"""Dashboard router — aggregate stats for the frontend."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Todo, Deal, Contact, Note, User, TodoStatus, DealStage
from app.auth import get_current_owner, get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats")
def get_stats(
    owner_id: int = Depends(get_current_owner),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)

    open_todos = db.query(Todo).filter(
        Todo.status == TodoStatus.open.value,
        Todo.owner_id == owner_id,
    ).count()

    overdue_todos = db.query(Todo).filter(
        Todo.status == TodoStatus.open.value,
        Todo.owner_id == owner_id,
        Todo.due_date.isnot(None),
        Todo.due_date < now,
    ).count()

    my_open_todos = db.query(Todo).filter(
        Todo.status == TodoStatus.open.value,
        Todo.owner_id == owner_id,
        Todo.assigned_to_user_id == user.id,
    ).count()

    active_deals = db.query(Deal).filter(
        Deal.stage.in_([DealStage.prospect.value, DealStage.active.value]),
        Deal.owner_id == owner_id,
    ).count()

    my_active_deals = db.query(Deal).filter(
        Deal.stage.in_([DealStage.prospect.value, DealStage.active.value]),
        Deal.owner_id == owner_id,
        Deal.assignee_user_id == user.id,
    ).count()

    total_contacts = db.query(Contact).filter(
        Contact.owner_id == owner_id,
    ).count()

    recent_notes = db.query(Note).filter(
        Note.owner_id == owner_id,
    ).order_by(Note.created_at.desc()).limit(5).all()

    return {
        "open_todos": open_todos,
        "overdue_todos": overdue_todos,
        "my_open_todos": my_open_todos,
        "active_deals": active_deals,
        "my_active_deals": my_active_deals,
        "total_contacts": total_contacts,
        "recent_notes": [n.to_dict() for n in recent_notes],
    }
