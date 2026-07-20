"""Email campaigns — templates, targeting, AI generation, batch send."""
import asyncio
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models import (
    EmailTemplate, EmailCampaign, EmailSendLog,
    Contact, Note, Deal, DealStage, User,
)
from app.auth import get_current_user, require_admin, get_current_owner
from app.email_utils import (
    render_template, send_email, personalize_with_ai, is_smtp_configured,
)

router = APIRouter(prefix="/admin/campaigns", tags=["campaigns"])


# ── Schemas ──

class TemplateCreate(BaseModel):
    name: str
    subject: str
    body_template: str = ""


class TemplateUpdate(BaseModel):
    name: str | None = None
    subject: str | None = None
    body_template: str | None = None


class CampaignCreate(BaseModel):
    name: str
    template_id: int | None = None
    target_filters: dict = {}
    # target_filters keys: firm, tag, tier, stage, has_deal (bool)
    # Example: {"tag": "Investor", "tier": "A"}


# ── Templates ──

@router.get("/templates")
def list_templates(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    templates = db.query(EmailTemplate).order_by(EmailTemplate.created_at.desc()).all()
    return [t.to_dict() for t in templates]


@router.post("/templates")
def create_template(
    data: TemplateCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    t = EmailTemplate(
        name=data.name,
        subject=data.subject,
        body_template=data.body_template,
        owner_id=user.owner_id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t.to_dict()


@router.put("/templates/{template_id}")
def update_template(
    template_id: int,
    data: TemplateUpdate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    t = db.query(EmailTemplate).filter(EmailTemplate.id == template_id).first()
    if not t:
        raise HTTPException(404, "Template not found")
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(t, key, value)
    db.commit()
    db.refresh(t)
    return t.to_dict()


@router.delete("/templates/{template_id}")
def delete_template(
    template_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    t = db.query(EmailTemplate).filter(EmailTemplate.id == template_id).first()
    if not t:
        raise HTTPException(404, "Template not found")
    db.delete(t)
    db.commit()
    return {"ok": True}


# ── Campaigns ──

@router.get("")
def list_campaigns(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    campaigns = db.query(EmailCampaign).order_by(EmailCampaign.created_at.desc()).all()
    return [c.to_dict() for c in campaigns]


@router.post("")
def create_campaign(
    data: CampaignCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    campaign = EmailCampaign(
        name=data.name,
        template_id=data.template_id,
        target_filters=data.target_filters,
        status="draft",
        owner_id=user.owner_id,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign.to_dict()


@router.post("/{campaign_id}/preview")
def preview_campaign(
    campaign_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Show which contacts would be targeted by this campaign."""
    campaign = _get_campaign(campaign_id, db)
    contacts = _apply_filters(db, campaign.target_filters)
    template = db.query(EmailTemplate).filter(EmailTemplate.id == campaign.template_id).first()

    return {
        "total": len(contacts),
        "contacts": [
            {
                "id": c.id,
                "name": c.name,
                "email": c.email,
                "firm": c.firm,
                "tier": c.relationship_tier or "",
            }
            for c in contacts[:50]  # cap at 50 for preview
        ],
        "template": template.to_dict() if template else None,
    }


@router.post("/{campaign_id}/generate")
async def generate_campaign_emails(
    campaign_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Generate personalized emails for all targets. Clears previous send log."""
    campaign = _get_campaign(campaign_id, db)
    contacts = _apply_filters(db, campaign.target_filters)
    template = db.query(EmailTemplate).filter(EmailTemplate.id == campaign.template_id).first()

    if not template:
        raise HTTPException(400, "Campaign has no template assigned")

    # Clear old send logs for this campaign
    db.query(EmailSendLog).filter(EmailSendLog.campaign_id == campaign_id).delete()

    # Update target count
    campaign.target_count = len(contacts)

    from app.ai import _is_configured
    use_ai = _is_configured()
    logs = []

    for c in contacts:
        if not c.email:
            continue

        # Get recent context
        note = db.query(Note).filter(
            Note.entity_type == "contact", Note.entity_id == c.id
        ).order_by(Note.created_at.desc()).first()
        context = (note.ai_summary or note.body_text or "") if note else ""
        context = context or (c.summary_text or "")

        # Render subject
        vars_dict = {"contact_name": c.name, "firm": c.firm or "", "tier": c.relationship_tier or ""}
        subject = render_template(template.subject, vars_dict)

        # Render body, with optional AI personalization
        body = render_template(template.body_template, vars_dict)
        if use_ai:
            body = await personalize_with_ai(c.name, c.firm or "", context, body)

        log = EmailSendLog(
            campaign_id=campaign_id,
            contact_id=c.id,
            contact_name=c.name,
            recipient_email=c.email,
            subject=subject,
            body=body,
            status="pending",
            owner_id=campaign.owner_id,
        )
        db.add(log)
        logs.append(log)

    campaign.status = "ready"
    db.commit()

    return {
        "ok": True,
        "target_count": len(contacts),
        "generated": len(logs),
        "use_ai": use_ai,
    }


@router.post("/{campaign_id}/send")
async def send_campaign(
    campaign_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Send all pending emails in this campaign."""
    campaign = _get_campaign(campaign_id, db)
    if not is_smtp_configured():
        raise HTTPException(503, "SMTP not configured — set SMTP_HOST, SMTP_USER, SMTP_PASSWORD in .env")

    logs = db.query(EmailSendLog).filter(
        EmailSendLog.campaign_id == campaign_id,
        EmailSendLog.status == "pending",
    ).all()

    if not logs:
        raise HTTPException(400, "No pending emails to send. Run generate first.")

    campaign.status = "sending"
    campaign.started_at = datetime.now(timezone.utc)
    db.commit()

    sent = 0
    failed = 0

    for log in logs:
        success, error = await send_email(
            to_email=log.recipient_email,
            to_name=log.contact_name,
            subject=log.subject,
            body=log.body,
        )
        log.sent_at = datetime.now(timezone.utc)
        if success:
            log.status = "sent"
            sent += 1
        else:
            log.status = "failed"
            log.error_msg = error[:500]
            failed += 1
        db.commit()
        # Small delay to avoid rate limiting
        await asyncio.sleep(0.5)

    campaign.sent_count = sent
    campaign.status = "sent"
    campaign.finished_at = datetime.now(timezone.utc)
    db.commit()

    return {"ok": True, "sent": sent, "failed": failed}


@router.get("/{campaign_id}/log")
def campaign_send_log(
    campaign_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    logs = db.query(EmailSendLog).filter(
        EmailSendLog.campaign_id == campaign_id,
    ).order_by(EmailSendLog.sent_at.asc()).all()
    return [l.to_dict() for l in logs]


@router.delete("/{campaign_id}")
def delete_campaign(
    campaign_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    campaign = _get_campaign(campaign_id, db)
    db.query(EmailSendLog).filter(EmailSendLog.campaign_id == campaign_id).delete()
    db.delete(campaign)
    db.commit()
    return {"ok": True}


# ── Helpers ──

def _get_campaign(campaign_id: int, db: Session) -> EmailCampaign:
    campaign = db.query(EmailCampaign).filter(EmailCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    return campaign


def _apply_filters(db: Session, filters: dict) -> list:
    """Query contacts matching the campaign target filters."""
    q = db.query(Contact)

    if filters.get("firm"):
        q = q.filter(Contact.firm.ilike(f"%{filters['firm']}%"))

    if filters.get("tag"):
        q = q.filter(Contact.tags.contains(filters["tag"]))

    if filters.get("tier"):
        q = q.filter(Contact.relationship_tier == filters["tier"])

    # Only contacts with email
    q = q.filter(Contact.email != "")
    q = q.filter(Contact.email.isnot(None))

    return q.order_by(Contact.name.asc()).all()
