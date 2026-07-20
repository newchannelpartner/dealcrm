"""AI-powered tools — pitch generation, deal briefing, follow-up emails."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Deal, Contact, Note, Todo, TodoStatus, User
from app.auth import get_current_user
from app.ai import generate_deal_pitch, generate_deal_briefing, generate_followup_email

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/deal-pitch/{deal_id}")
async def ai_deal_pitch(
    deal_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if not deal:
        raise HTTPException(404, "Deal not found")

    pitch = await generate_deal_pitch(
        name=deal.name,
        deal_type=deal.type,
        stage=deal.stage,
        size_mm=deal.size_mm,
        notes=deal.notes_text or "",
        milestones=deal.milestones or [],
    )
    if pitch is None:
        raise HTTPException(503, "AI service unavailable (no LLM configured)")

    return {"pitch": pitch}


@router.post("/deal-briefing/{deal_id}")
async def ai_deal_briefing(
    deal_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if not deal:
        raise HTTPException(404, "Deal not found")

    # Gather context
    contacts = []
    if deal.contact_ids:
        contacts = db.query(Contact).filter(Contact.id.in_(deal.contact_ids)).all()
    contact_names = ", ".join(c.name for c in contacts)

    notes = db.query(Note).filter(
        Note.entity_type == "deal", Note.entity_id == deal_id
    ).order_by(Note.created_at.desc()).limit(5).all()
    notes_summary = "; ".join(
        (n.ai_summary or n.body_text or "")[:200] for n in notes
    )

    todos = db.query(Todo).filter(
        Todo.linked_entity_type == "deal",
        Todo.linked_entity_id == deal_id,
        Todo.status == TodoStatus.open.value,
    ).all()
    open_todos = [{"title": t.title, "priority": t.priority} for t in todos]

    result = await generate_deal_briefing(
        deal_name=deal.name,
        deal_type=deal.type,
        deal_stage=deal.stage,
        size_mm=deal.size_mm,
        expected_fee=deal.expected_fee,
        fee_type=deal.fee_type or "",
        milestones=deal.milestones or [],
        contact_names=contact_names,
        notes_summary=notes_summary,
        open_todos=open_todos,
        notes_text=deal.notes_text or "",
    )
    if result is None:
        raise HTTPException(503, "AI service unavailable (no LLM configured)")

    return result


@router.post("/followup-email/{contact_id}")
async def ai_followup_email(
    contact_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(404, "Contact not found")

    # Get recent notes for context
    recent_note = db.query(Note).filter(
        Note.entity_type == "contact", Note.entity_id == contact_id
    ).order_by(Note.created_at.desc()).first()

    context = ""
    if recent_note:
        context = recent_note.ai_summary or recent_note.body_text or ""
    context = context or (contact.summary_text or "")

    email_body = await generate_followup_email(
        contact_name=contact.name,
        firm=contact.firm or "",
        tier=contact.relationship_tier or "B",
        recent_context=context,
    )
    if email_body is None:
        raise HTTPException(503, "AI service unavailable (no LLM configured)")

    return {
        "email_body": email_body,
        "contact_name": contact.name,
        "contact_firm": contact.firm,
    }


@router.post("/cold-followups")
async def ai_cold_followups(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List A-tier contacts not contacted in 90+ days, with AI-drafted follow-ups."""
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)

    cold_contacts = db.query(Contact).filter(
        Contact.relationship_tier == "A",
    ).filter(
        (Contact.last_contacted_at == None) | (Contact.last_contacted_at < cutoff)
    ).order_by(Contact.last_contacted_at.asc().nullsfirst()).limit(10).all()

    results = []
    for c in cold_contacts:
        # Get last note context
        note = db.query(Note).filter(
            Note.entity_type == "contact", Note.entity_id == c.id
        ).order_by(Note.created_at.desc()).first()

        context = (note.ai_summary or note.body_text or "") if note else ""
        context = context or (c.summary_text or "")

        results.append({
            "id": c.id,
            "name": c.name,
            "firm": c.firm,
            "last_contacted_at": c.last_contacted_at.isoformat() if c.last_contacted_at else None,
        })

    # Only generate follow-ups if LLM is configured and contacts found
    from app.ai import _is_configured
    if _is_configured() and results:
        for r in results[:3]:  # Limit AI calls to 3
            note = db.query(Note).filter(
                Note.entity_type == "contact", Note.entity_id == r["id"]
            ).order_by(Note.created_at.desc()).first()
            ctx = (note.ai_summary or note.body_text or "") if note else ""
            email = await generate_followup_email(
                contact_name=r["name"],
                firm=r["firm"] or "",
                tier="A",
                recent_context=ctx or "",
            )
            r["draft_email"] = email

    return {"contacts": results}
