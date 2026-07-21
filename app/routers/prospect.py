"""Prospecting router — AI-powered firm discovery for new leads."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Contact, User
from app.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/prospect", tags=["prospect"])


PROSPECT_SEARCH_PROMPT = (
    "You are a business development researcher for an M&A advisory firm "
    "focused on personal injury law firms. Based on the query, suggest relevant "
    "PI law firms that could be acquisition or partnership targets. "
    "Return ONLY valid JSON array (no markdown). Each item:\n"
    "{\n"
    '  "firm_name": "Full firm name",\n'
    '  "website": "firm website URL (best guess)",\n'
    '  "linkedin": "LinkedIn company URL or empty",\n'
    '  "location": "City, State",\n'
    '  "size_hint": "e.g. 10-50 attorneys, or revenue range",\n'
    '  "description": "1 sentence about their PI practice focus",\n'
    '  "key_contacts": [\n'
    '    {"name": "Full Name", "title": "e.g. Managing Partner", '
    '"email_hint": "likely email pattern like first@firm.com", "phone": ""}\n'
    '  ]\n'
    '}'
)

PROSPECT_ENRICH_PROMPT = (
    "You are researching a specific law firm for M&A prospecting. "
    "Given the firm name and any known location, provide the most accurate "
    "information you know. Return ONLY valid JSON:\n"
    "{\n"
    '  "website": "verified website URL",\n'
    '  "linkedin": "LinkedIn company URL",\n'
    '  "phone": "main office phone",\n'
    '  "attorney_count": "approximate number of attorneys",\n'
    '  "practice_areas": ["PI", "workers comp", etc.],\n'
    '  "description": "brief description",\n'
    '  "key_contacts": [\n'
    '    {"name": "Name", "title": "Role", "email": "email or best guess", '
    '"phone": "direct line if known"}\n'
    '  ]\n'
    '}'
)


class ProspectSearch(BaseModel):
    query: str = ""
    location: str = ""
    sector: str = ""
    count: int = 10


class ProspectEnrich(BaseModel):
    firm_name: str
    location: str = ""


class AddToOutreach(BaseModel):
    firm_name: str
    website: str = ""
    linkedin: str = ""
    location: str = ""
    contacts: list[dict] = []


@router.post("/search")
async def search_firms(
    data: ProspectSearch,
    user: User = Depends(get_current_user),
):
    """AI-powered PI law firm discovery."""
    from app.ai import _call_llm, _is_configured, _parse_json_defensively

    if not _is_configured():
        raise HTTPException(503, "AI not configured")

    context = f"Find {data.count} law firms"
    if data.sector:
        context += f" specializing in {data.sector}"
    if data.location:
        context += f" located in {data.location}"
    if data.query:
        context += f". Additional context: {data.query}"

    raw = await _call_llm(PROSPECT_SEARCH_PROMPT, context)
    if not raw:
        raise HTTPException(503, "AI returned no results")

    results = _parse_json_defensively(raw)
    if isinstance(results, dict):
        results = [results]
    if not isinstance(results, list):
        raise HTTPException(503, "AI returned unexpected format")

    return [
        {
            "firm_name": r.get("firm_name", ""),
            "website": r.get("website", ""),
            "linkedin": r.get("linkedin", ""),
            "location": r.get("location", ""),
            "size_hint": r.get("size_hint", ""),
            "description": r.get("description", ""),
            "key_contacts": r.get("key_contacts", []) if isinstance(r.get("key_contacts"), list) else [],
        }
        for r in results
        if isinstance(r, dict) and r.get("firm_name")
    ]


@router.post("/enrich")
async def enrich_firm(
    data: ProspectEnrich,
    user: User = Depends(get_current_user),
):
    """Enrich a specific firm with AI research."""
    from app.ai import _call_llm, _is_configured, _parse_json_defensively

    if not _is_configured():
        raise HTTPException(503, "AI not configured")

    context = f"Firm: {data.firm_name}"
    if data.location:
        context += f"\nLocation: {data.location}"

    raw = await _call_llm(PROSPECT_ENRICH_PROMPT, context)
    if not raw:
        raise HTTPException(503, "AI returned no results")

    result = _parse_json_defensively(raw) or {}
    return {
        "website": result.get("website", ""),
        "linkedin": result.get("linkedin", ""),
        "phone": result.get("phone", ""),
        "attorney_count": result.get("attorney_count", ""),
        "practice_areas": result.get("practice_areas", []),
        "description": result.get("description", ""),
        "key_contacts": result.get("key_contacts", []),
    }


@router.post("/add-to-outreach")
def add_to_outreach(
    data: AddToOutreach,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add prospected firm and contacts to the outreach pipeline."""
    created = []

    for contact_data in data.contacts:
        name = contact_data.get("name", "").strip() if isinstance(contact_data, dict) else ""
        email = contact_data.get("email", "").strip() if isinstance(contact_data, dict) else ""
        if not name:
            continue

        # Check if contact already exists by email
        existing = None
        if email and "@" in email:
            existing = db.query(Contact).filter(Contact.email == email).first()
        if not existing:
            existing = db.query(Contact).filter(
                Contact.name == name, Contact.firm == data.firm_name
            ).first()

        if existing:
            if not existing.outreach_status:
                existing.outreach_status = "not_contacted"
                existing.outreach_region = data.location
                existing.outreach_notes = f"Source: AI Prospecting\nWebsite: {data.website}\nLinkedIn: {data.linkedin}"
                existing.tags = list(set((existing.tags or []) + ["Prospected", "PI Law Firm"]))
                db.commit()
                created.append(existing.to_dict())
            continue

        contact = Contact(
            name=name,
            email=email,
            phone=contact_data.get("phone", "") if isinstance(contact_data, dict) else "",
            firm=data.firm_name,
            title=contact_data.get("title", "") if isinstance(contact_data, dict) else "",
            outreach_status="not_contacted",
            outreach_region=data.location,
            outreach_notes=f"Source: AI Prospecting\nWebsite: {data.website}\nLinkedIn: {data.linkedin}",
            tags=["Prospected", "PI Law Firm"],
        )
        db.add(contact)
        db.flush()
        created.append(contact.to_dict())

    db.commit()
    return {"ok": True, "created": len(created), "contacts": created}
