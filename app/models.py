"""DealCRM data models — SQLAlchemy ORM."""
import enum
import json
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Float, Text, DateTime, JSON, Boolean
from sqlalchemy.orm import declarative_base

Base = declarative_base()

PREDEFINED_TAGS = [
    "Investor", "LP", "Banker", "Lawyer", "Operator",
    "Founder", "Portfolio Co", "Service Provider", "Other",
]


class DealStage(str, enum.Enum):
    prospect = "prospect"
    active = "active"
    closed = "closed"
    dead = "dead"


class DealType(str, enum.Enum):
    sell_side = "sell-side"
    buy_side = "buy-side"
    credit = "credit"
    independent_sponsor = "independent-sponsor"


class EntityType(str, enum.Enum):
    contact = "contact"
    deal = "deal"
    none = "none"


class Priority(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"


class TodoStatus(str, enum.Enum):
    open = "open"
    done = "done"


class TodoSource(str, enum.Enum):
    manual = "manual"
    ai = "ai"


class IngestionSource(str, enum.Enum):
    paste = "paste"
    email = "email"
    pdf = "pdf"


class IngestionStatus(str, enum.Enum):
    analyzing = "analyzing"   # AI is parsing
    pending = "pending"       # parsed, awaiting user review
    approved = "approved"     # user approved, records created
    dismissed = "dismissed"   # user discarded
    error = "error"           # parsing failed


class User(Base):
    """Login account. Shared-workspace model: every user owns the same data (owner_id=1)."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(150), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    password_salt = Column(String(64), nullable=False)
    is_admin = Column(Boolean, default=False)
    owner_id = Column(Integer, default=1)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "is_admin": bool(self.is_admin),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), default="")
    phone = Column(String(50), default="")
    firm = Column(String(255), default="")
    title = Column(String(255), default="")
    tags = Column(JSON, default=list)
    summary_text = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    owner_id = Column(Integer, default=1)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "firm": self.firm,
            "title": self.title,
            "tags": self.tags or [],
            "summary_text": self.summary_text or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "owner_id": self.owner_id,
        }


class Deal(Base):
    __tablename__ = "deals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    stage = Column(String(20), default=DealStage.prospect.value)
    type = Column(String(20), default=DealType.independent_sponsor.value)
    size_mm = Column(Float, nullable=True)
    contact_ids = Column(JSON, default=list)
    tags = Column(JSON, default=list)
    notes_text = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    owner_id = Column(Integer, default=1)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "stage": self.stage,
            "type": self.type,
            "size_mm": self.size_mm,
            "contact_ids": self.contact_ids or [],
            "tags": self.tags or [],
            "notes_text": self.notes_text or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "owner_id": self.owner_id,
        }


class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String(20), default=EntityType.none.value)
    entity_id = Column(Integer, nullable=True)
    body_html = Column(Text, default="")
    body_text = Column(Text, default="")
    ai_summary = Column(Text, default="")
    ai_takeaways = Column(JSON, default=list)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    owner_id = Column(Integer, default=1)

    def to_dict(self):
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "body_html": self.body_html or "",
            "body_text": self.body_text or "",
            "ai_summary": self.ai_summary or "",
            "ai_takeaways": self.ai_takeaways or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "owner_id": self.owner_id,
        }


class Ingestion(Base):
    """A forwarded email or pasted call-note staged for review before records are created."""
    __tablename__ = "ingestions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(20), default=IngestionSource.paste.value)
    subject = Column(String(500), default="")
    sender = Column(String(255), default="")
    raw_text = Column(Text, default="")
    status = Column(String(20), default=IngestionStatus.analyzing.value)
    ai_summary = Column(Text, default="")
    ai_takeaways = Column(JSON, default=list)
    # Structured, DB-resolved proposals: {deal, contacts[], todos[]}
    proposals = Column(JSON, default=dict)
    # IDs of records created on approval: {deal_id, contact_ids[], todo_ids[], note_id}
    result = Column(JSON, default=dict)
    error_msg = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    processed_at = Column(DateTime, nullable=True)
    owner_id = Column(Integer, default=1)

    def to_dict(self):
        return {
            "id": self.id,
            "source": self.source,
            "subject": self.subject or "",
            "sender": self.sender or "",
            "raw_text": self.raw_text or "",
            "status": self.status,
            "ai_summary": self.ai_summary or "",
            "ai_takeaways": self.ai_takeaways or [],
            "proposals": self.proposals or {},
            "result": self.result or {},
            "error_msg": self.error_msg or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "owner_id": self.owner_id,
        }


class Todo(Base):
    __tablename__ = "todos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False)
    due_date = Column(DateTime, nullable=True)
    priority = Column(String(10), default=Priority.medium.value)
    status = Column(String(10), default=TodoStatus.open.value)
    source = Column(String(10), default=TodoSource.manual.value)
    linked_entity_type = Column(String(20), nullable=True)
    linked_entity_id = Column(Integer, nullable=True)
    owner_id = Column(Integer, default=1)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "priority": self.priority,
            "status": self.status,
            "source": self.source,
            "linked_entity_type": self.linked_entity_type,
            "linked_entity_id": self.linked_entity_id,
            "owner_id": self.owner_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
