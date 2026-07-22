"""DealCRM data models — SQLAlchemy ORM."""
import enum
import json
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Float, Text, DateTime, JSON, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base, relationship

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
    firm = "firm"
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
    analyzing = "analyzing"
    pending = "pending"
    approved = "approved"
    dismissed = "dismissed"
    error = "error"


class FeeType(str, enum.Enum):
    retainer = "retainer"
    success_fee = "success-fee"
    hybrid = "hybrid"


class RelationshipTier(str, enum.Enum):
    a = "A"
    b = "B"
    c = "C"


class User(Base):
    """Login account. Shared-workspace model: every user owns the same data (owner_id=1)."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(150), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    password_salt = Column(String(64), nullable=False)
    display_name = Column(String(255), default="")
    email = Column(String(255), default="")
    is_admin = Column(Boolean, default=False)
    owner_id = Column(Integer, default=1)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name or self.username,
            "email": self.email or "",
            "is_admin": bool(self.is_admin),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Firm(Base):
    __tablename__ = "firms"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    industry = Column(String(255), default="")
    website = Column(String(500), default="")
    notes_text = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    owner_id = Column(Integer, default=1)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "industry": self.industry or "",
            "website": self.website or "",
            "notes_text": self.notes_text or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "owner_id": self.owner_id,
        }


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), default="")
    phone = Column(String(50), default="")
    firm = Column(String(255), default="")
    firm_id = Column(Integer, ForeignKey("firms.id"), nullable=True)
    title = Column(String(255), default="")
    tags = Column(JSON, default=list)
    summary_text = Column(Text, default="")
    last_contacted_at = Column(DateTime, nullable=True)
    relationship_tier = Column(String(2), default="")
    outreach_status = Column(String(20), default="")
    outreach_region = Column(String(50), default="")
    outreach_notes = Column(Text, default="")
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
            "firm_id": self.firm_id,
            "title": self.title,
            "tags": self.tags or [],
            "summary_text": self.summary_text or "",
            "last_contacted_at": self.last_contacted_at.isoformat() if self.last_contacted_at else None,
            "relationship_tier": self.relationship_tier or "",
            "outreach_status": self.outreach_status or "",
            "outreach_region": self.outreach_region or "",
            "outreach_notes": self.outreach_notes or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "owner_id": self.owner_id,
        }


class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_email = Column(String(255), nullable=False, unique=True, index=True)
    client_name = Column(String(255), default="")
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    last_contact_time = Column(DateTime, nullable=True)
    last_sync_time = Column(DateTime, nullable=True)
    reminder_sent_at = Column(DateTime, nullable=True)
    reminder_threshold_days = Column(Integer, default=7)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    owner = relationship("User", backref="clients")

    def to_dict(self):
        return {
            "id": self.id,
            "client_email": self.client_email,
            "client_name": self.client_name or "",
            "owner_id": self.owner_id,
            "owner_name": self.owner.display_name or self.owner.username if self.owner else "",
            "last_contact_time": self.last_contact_time.isoformat() if self.last_contact_time else None,
            "last_sync_time": self.last_sync_time.isoformat() if self.last_sync_time else None,
            "reminder_sent_at": self.reminder_sent_at.isoformat() if self.reminder_sent_at else None,
            "reminder_threshold_days": self.reminder_threshold_days,
            "days_since_contact": _days_since(self.last_contact_time),
            "notes": self.notes or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def _days_since(dt):
    if not dt:
        return None
    delta = datetime.now(timezone.utc) - dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else datetime.now(timezone.utc) - dt
    return delta.days


class Deal(Base):
    __tablename__ = "deals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    stage = Column(String(20), default=DealStage.prospect.value)
    type = Column(String(20), default=DealType.independent_sponsor.value)
    size_mm = Column(Float, nullable=True)
    expected_fee = Column(Float, nullable=True)
    fee_type = Column(String(20), default="")
    assignee_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    milestones = Column(JSON, default=list)
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
            "expected_fee": self.expected_fee,
            "fee_type": self.fee_type or "",
            "assignee_user_id": self.assignee_user_id,
            "milestones": self.milestones or [],
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
    assigned_to_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
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
            "assigned_to_user_id": self.assigned_to_user_id,
            "linked_entity_type": self.linked_entity_type,
            "linked_entity_id": self.linked_entity_id,
            "owner_id": self.owner_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String(20), nullable=False)
    entity_id = Column(Integer, nullable=False)
    filename = Column(String(500), nullable=False)
    original_filename = Column(String(500), nullable=False)
    file_size = Column(Integer, default=0)
    mime_type = Column(String(100), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    owner_id = Column(Integer, default=1)

    def to_dict(self):
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "filename": self.filename,
            "original_filename": self.original_filename,
            "file_size": self.file_size,
            "mime_type": self.mime_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "owner_id": self.owner_id,
        }


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String(150), default="")
    entity_type = Column(String(20), nullable=False)
    entity_id = Column(Integer, nullable=True)
    action = Column(String(50), nullable=False)
    detail = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.username,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "action": self.action,
            "detail": self.detail or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EmailTemplate(Base):
    __tablename__ = "email_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    subject = Column(String(500), nullable=False)
    body_template = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    owner_id = Column(Integer, default=1)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "subject": self.subject,
            "body_template": self.body_template or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "owner_id": self.owner_id,
        }


class EmailCampaign(Base):
    __tablename__ = "email_campaigns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    template_id = Column(Integer, ForeignKey("email_templates.id"), nullable=True)
    target_filters = Column(JSON, default=dict)
    target_count = Column(Integer, default=0)
    sent_count = Column(Integer, default=0)
    status = Column(String(20), default="draft")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    owner_id = Column(Integer, default=1)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "template_id": self.template_id,
            "target_filters": self.target_filters or {},
            "target_count": self.target_count,
            "sent_count": self.sent_count,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "owner_id": self.owner_id,
        }


class EmailSendLog(Base):
    __tablename__ = "email_send_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(Integer, ForeignKey("email_campaigns.id"), nullable=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    contact_name = Column(String(255), default="")
    recipient_email = Column(String(255), default="")
    subject = Column(String(500), default="")
    body = Column(Text, default="")
    status = Column(String(20), default="pending")
    error_msg = Column(Text, default="")
    sent_at = Column(DateTime, nullable=True)
    owner_id = Column(Integer, default=1)

    def to_dict(self):
        return {
            "id": self.id,
            "campaign_id": self.campaign_id,
            "contact_id": self.contact_id,
            "contact_name": self.contact_name,
            "recipient_email": self.recipient_email,
            "subject": self.subject,
            "body": self.body or "",
            "status": self.status,
            "error_msg": self.error_msg or "",
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "owner_id": self.owner_id,
        }
