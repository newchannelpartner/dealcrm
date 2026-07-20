"""Audit log router — view-only for admins."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuditLog, User
from app.auth import require_admin

router = APIRouter(prefix="/admin/audit-log", tags=["audit"])


@router.get("")
def list_audit_logs(
    entity_type: str = Query(default=""),
    limit: int = Query(default=100),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(AuditLog)
    if entity_type:
        q = q.filter(AuditLog.entity_type == entity_type)
    logs = q.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [l.to_dict() for l in logs]
