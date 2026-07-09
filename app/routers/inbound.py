"""Inbound router — ingest forwarded call-note emails / pasted text, parse with AI,
stage proposals for review, then create contacts / todos / deal links on approval."""
import secrets
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Query, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models import (
    Ingestion, Contact, Deal, Note, Todo,
    IngestionSource, IngestionStatus, EntityType,
    TodoStatus, TodoSource, DealStage, DealType,
)
from app.auth import get_current_owner, INBOUND_TOKEN

router = APIRouter(prefix="/inbound", tags=["inbound"])

MAX_PDF_BYTES = 20 * 1024 * 1024  # 20 MB

# Order matters: prefer full-body fields over "stripped" ones, because forwarded
# Gemini notes live in the quoted/forwarded portion that stripping would remove.
_BODY_FIELDS = ["body-plain", "text", "plain", "body", "stripped-text"]
_SUBJECT_FIELDS = ["subject", "Subject"]
_SENDER_FIELDS = ["sender", "from", "From", "envelope-from"]


# ─── Schemas ───

class PasteCreate(BaseModel):
    text: str
    subject: str = ""


class ApproveContact(BaseModel):
    name: str
    email: str = ""
    firm: str = ""
    title: str = ""
    match_id: int | None = None   # existing contact to link instead of creating
    skip: bool = False


class ApproveTodo(BaseModel):
    title: str
    priority: str = "medium"
    due_date_suggestion: str = ""
    skip: bool = False


class ApprovePayload(BaseModel):
    deal_id: int | None = None            # link to existing deal
    new_deal_name: str | None = None      # or create a new deal
    new_deal_type: str = "independent-sponsor"
    new_deal_stage: str = "prospect"
    contacts: list[ApproveContact] = []
    todos: list[ApproveTodo] = []


# ─── Ingestion entry points ───

@router.post("/paste")
def create_from_paste(
    data: PasteCreate,
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    if not data.text or not data.text.strip():
        raise HTTPException(status_code=400, detail="Text is empty")
    ing = _create_ingestion(db, owner_id, IngestionSource.paste.value,
                            subject=data.subject, sender="", raw_text=data.text)
    _process_async(ing.id)
    return ing.to_dict()


@router.post("/pdf")
async def create_from_pdf(
    file: UploadFile = File(...),
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    """Upload a PDF (e.g. a call-note export). Extracts text — with OCR fallback for
    scanned PDFs — then runs the same parse-and-review pipeline as pasted notes."""
    filename = file.filename or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a .pdf file")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF too large (max 20 MB)")

    from app.pdf_utils import extract_pdf_text, OcrUnavailable
    try:
        text, used_ocr = extract_pdf_text(data)
    except OcrUnavailable as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        import logging
        logging.getLogger(__name__).exception("PDF extraction failed")
        raise HTTPException(status_code=422, detail="Could not read this PDF — it may be corrupt or password-protected.")

    if not text.strip():
        raise HTTPException(status_code=422, detail="No text could be extracted from this PDF.")

    ing = _create_ingestion(db, owner_id, IngestionSource.pdf.value,
                            subject=filename, sender="", raw_text=text)
    _process_async(ing.id)
    result = ing.to_dict()
    result["used_ocr"] = used_ocr
    return result


@router.post("/email")
async def create_from_email(request: Request, token: str = Query(default="")):
    """Public webhook for inbound-email providers (Mailgun, CloudMailin, SendGrid, ...).

    Secured by a shared secret token (?token=...). Provider-agnostic: accepts JSON or
    form-encoded payloads and pulls the plain-text body, subject and sender from any of
    the common field names.
    """
    if not INBOUND_TOKEN:
        raise HTTPException(status_code=503, detail="Inbound email not configured")
    if not secrets.compare_digest(token, INBOUND_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid token")

    ctype = request.headers.get("content-type", "")
    attachment_texts: list[str] = []
    if "application/json" in ctype:
        try:
            data = await request.json()
        except Exception:
            data = {}
        if isinstance(data, dict):
            attachment_texts = _pdf_text_from_json_attachments(data.get("attachments"))
    else:
        form = await request.form()
        data = {k: v for k, v in form.items() if isinstance(v, str)}
        attachment_texts = await _pdf_text_from_form_files(form)

    if not isinstance(data, dict):
        data = {}

    text = _first_field(data, _BODY_FIELDS)
    subject = _first_field(data, _SUBJECT_FIELDS)
    sender = _first_field(data, _SENDER_FIELDS)

    # Append any PDF attachment text (e.g. a Gemini notes PDF) to the email body so it
    # gets parsed too. Uses OCR for scanned attachments when Tesseract is available.
    full_text = text
    for att in attachment_texts:
        full_text = (full_text + "\n\n--- PDF attachment ---\n" + att).strip()

    if not full_text.strip():
        raise HTTPException(status_code=400, detail="No email body or readable PDF attachment found")

    db = SessionLocal()
    try:
        ing = _create_ingestion(db, owner_id=1, source=IngestionSource.email.value,
                                subject=subject, sender=sender, raw_text=full_text)
        ing_id = ing.id
    finally:
        db.close()
    _process_async(ing_id)
    return {"ok": True, "id": ing_id, "attachments_read": len(attachment_texts)}


# ─── Review queue ───

@router.get("")
def list_ingestions(
    status: str = Query(default=""),
    limit: int = Query(default=50),
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    q = db.query(Ingestion).filter(Ingestion.owner_id == owner_id)
    if status:
        q = q.filter(Ingestion.status == status)
    rows = q.order_by(Ingestion.created_at.desc()).limit(limit).all()
    return [r.to_dict() for r in rows]


@router.get("/{ingestion_id}")
def get_ingestion(
    ingestion_id: int,
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    return _get_or_404(ingestion_id, owner_id, db).to_dict()


@router.post("/{ingestion_id}/approve")
def approve_ingestion(
    ingestion_id: int,
    payload: ApprovePayload,
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    ing = _get_or_404(ingestion_id, owner_id, db)
    if ing.status == IngestionStatus.approved.value:
        raise HTTPException(status_code=400, detail="Already approved")

    # 1. Resolve/create contacts
    contact_ids: list[int] = []
    for c in payload.contacts:
        if c.skip or not c.name.strip():
            continue
        if c.match_id:
            existing = db.query(Contact).filter(
                Contact.id == c.match_id, Contact.owner_id == owner_id
            ).first()
            if existing:
                contact_ids.append(existing.id)
                continue
        contact = Contact(
            name=c.name.strip(), email=c.email.strip(), firm=c.firm.strip(),
            title=c.title.strip(), tags=[], summary_text="", owner_id=owner_id,
        )
        db.add(contact)
        db.flush()
        contact_ids.append(contact.id)

    # 2. Resolve/create deal
    deal: Deal | None = None
    if payload.new_deal_name and payload.new_deal_name.strip():
        valid_stages = {e.value for e in DealStage}
        valid_types = {e.value for e in DealType}
        deal = Deal(
            name=payload.new_deal_name.strip(),
            stage=payload.new_deal_stage if payload.new_deal_stage in valid_stages else DealStage.prospect.value,
            type=payload.new_deal_type if payload.new_deal_type in valid_types else DealType.independent_sponsor.value,
            contact_ids=list(contact_ids), tags=[], notes_text="", owner_id=owner_id,
        )
        db.add(deal)
        db.flush()
    elif payload.deal_id:
        deal = db.query(Deal).filter(
            Deal.id == payload.deal_id, Deal.owner_id == owner_id
        ).first()
        if deal and contact_ids:
            merged = list(deal.contact_ids or [])
            for cid in contact_ids:
                if cid not in merged:
                    merged.append(cid)
            deal.contact_ids = merged

    # 3. Determine what todos/note link to
    if deal:
        link_type, link_id = EntityType.deal.value, deal.id
    elif len(contact_ids) == 1:
        link_type, link_id = EntityType.contact.value, contact_ids[0]
    else:
        link_type, link_id = None, None

    # 4. Create todos
    from app.ai import parse_due_date, parse_priority
    todo_ids: list[int] = []
    for t in payload.todos:
        if t.skip or not t.title.strip():
            continue
        todo = Todo(
            title=t.title.strip()[:500],
            due_date=parse_due_date(t.due_date_suggestion),
            priority=parse_priority(t.priority),
            status=TodoStatus.open.value,
            source=TodoSource.ai.value,
            linked_entity_type=link_type,
            linked_entity_id=link_id,
            owner_id=owner_id,
        )
        db.add(todo)
        db.flush()
        todo_ids.append(todo.id)

    # 5. Save a Note with the transcript + AI summary
    note = Note(
        entity_type=link_type or EntityType.none.value,
        entity_id=link_id,
        body_html="",
        body_text=ing.raw_text or "",
        ai_summary=ing.ai_summary or "",
        ai_takeaways=ing.ai_takeaways or [],
        owner_id=owner_id,
    )
    db.add(note)
    db.flush()

    ing.status = IngestionStatus.approved.value
    ing.processed_at = datetime.now(timezone.utc)
    ing.result = {
        "deal_id": deal.id if deal else None,
        "contact_ids": contact_ids,
        "todo_ids": todo_ids,
        "note_id": note.id,
    }
    db.commit()
    db.refresh(ing)
    return ing.to_dict()


@router.post("/{ingestion_id}/dismiss")
def dismiss_ingestion(
    ingestion_id: int,
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    ing = _get_or_404(ingestion_id, owner_id, db)
    ing.status = IngestionStatus.dismissed.value
    ing.processed_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.delete("/{ingestion_id}")
def delete_ingestion(
    ingestion_id: int,
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    ing = _get_or_404(ingestion_id, owner_id, db)
    db.delete(ing)
    db.commit()
    return {"ok": True}


# ─── Background parsing + entity resolution ───

def _process_async(ingestion_id: int):
    t = threading.Thread(target=_process_ingestion, args=(ingestion_id,), daemon=True)
    t.start()


def _process_ingestion(ingestion_id: int):
    """Run AI extraction, resolve against existing records, store proposals. Non-blocking."""
    import asyncio

    db = SessionLocal()
    try:
        ing = db.get(Ingestion, ingestion_id)
        if not ing:
            return

        from app.ai import analyze_call_notes
        result = asyncio.run(analyze_call_notes(ing.raw_text))

        ing.ai_summary = result.get("summary", "")
        ing.ai_takeaways = result.get("takeaways", [])
        ing.proposals = {
            "summary": result.get("summary", ""),
            "takeaways": result.get("takeaways", []),
            "deal": _resolve_deal(db, ing.owner_id, result.get("deal_hint") or {}),
            "contacts": _resolve_contacts(db, ing.owner_id, result.get("contacts") or []),
            "todos": _normalize_todos(result.get("todos") or []),
        }
        ing.status = IngestionStatus.pending.value
        db.commit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Ingestion parsing failed")
        try:
            ing = db.get(Ingestion, ingestion_id)
            if ing:
                ing.status = IngestionStatus.error.value
                ing.error_msg = str(e)[:500]
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _resolve_contacts(db: Session, owner_id: int, contacts: list) -> list:
    """Match each AI-extracted contact against existing records by email, then name."""
    resolved = []
    for c in contacts:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name", "")).strip()
        if not name:
            continue
        email = str(c.get("email", "")).strip()
        match = None
        if email:
            match = db.query(Contact).filter(
                Contact.owner_id == owner_id, Contact.email.ilike(email)
            ).first()
        if not match:
            match = db.query(Contact).filter(
                Contact.owner_id == owner_id, Contact.name.ilike(name)
            ).first()
        resolved.append({
            "name": name,
            "email": email,
            "firm": str(c.get("firm", "")).strip(),
            "title": str(c.get("title", "")).strip(),
            "role": str(c.get("role", "")).strip(),
            "match_id": match.id if match else None,
            "match_name": match.name if match else None,
        })
    return resolved


def _resolve_deal(db: Session, owner_id: int, deal_hint: dict) -> dict:
    """Find the existing deal this call most likely belongs to."""
    name = str(deal_hint.get("name", "")).strip()
    keywords = [str(k).strip() for k in (deal_hint.get("keywords") or []) if str(k).strip()]
    deals = db.query(Deal).filter(Deal.owner_id == owner_id).all()

    best = None
    if name:
        low = name.lower()
        for d in deals:
            dl = d.name.lower()
            if low == dl or low in dl or dl in low:
                best = d
                break
    if not best and keywords:
        for d in deals:
            hay = (d.name + " " + " ".join(d.tags or [])).lower()
            if any(k.lower() in hay for k in keywords):
                best = d
                break
    return {
        "match_id": best.id if best else None,
        "match_name": best.name if best else None,
        "suggested_name": name,
    }


def _normalize_todos(todos: list) -> list:
    out = []
    for t in todos:
        if not isinstance(t, dict) or not t.get("title"):
            continue
        out.append({
            "title": str(t.get("title", "")).strip()[:500],
            "priority": str(t.get("priority", "medium")).strip().lower(),
            "due_date_suggestion": str(t.get("due_date_suggestion", "")).strip(),
        })
    return out


# ─── Helpers ───

def _first_field(data: dict, keys: list) -> str:
    for k in keys:
        v = data.get(k)
        if v is not None and str(v).strip():
            return str(v)
    return ""


def _safe_pdf_text(raw: bytes) -> str:
    """Extract text (with OCR fallback) from PDF bytes, swallowing any failure so a bad
    attachment never breaks the whole webhook. Returns '' if it can't be read."""
    from app.pdf_utils import extract_pdf_text
    try:
        text, _ = extract_pdf_text(raw)
        return text.strip()
    except Exception:
        import logging
        logging.getLogger(__name__).warning("Skipping unreadable PDF attachment", exc_info=True)
        return ""


def _looks_like_pdf(filename: str, content_type: str) -> bool:
    return (filename or "").lower().endswith(".pdf") or "pdf" in (content_type or "").lower()


async def _pdf_text_from_form_files(form) -> list[str]:
    """Pull text from PDF file parts of a multipart webhook (Mailgun, SendGrid, ...)."""
    from starlette.datastructures import UploadFile as StarletteUploadFile
    out = []
    for _key, val in form.multi_items():
        if isinstance(val, StarletteUploadFile) and _looks_like_pdf(val.filename, val.content_type):
            try:
                raw = await val.read()
            except Exception:
                continue
            if len(raw) > MAX_PDF_BYTES:
                continue
            txt = _safe_pdf_text(raw)
            if txt:
                out.append(txt)
    return out


def _pdf_text_from_json_attachments(attachments) -> list[str]:
    """Pull text from base64 PDF attachments in a JSON webhook (e.g. CloudMailin)."""
    import base64
    out = []
    if not isinstance(attachments, list):
        return out
    for att in attachments:
        if not isinstance(att, dict):
            continue
        filename = att.get("file_name") or att.get("filename") or att.get("name") or ""
        content_type = att.get("content_type") or att.get("type") or ""
        if not _looks_like_pdf(filename, content_type):
            continue
        b64 = att.get("content") or att.get("data")
        if not b64:
            continue
        try:
            raw = base64.b64decode(b64)
        except Exception:
            continue
        if len(raw) > MAX_PDF_BYTES:
            continue
        txt = _safe_pdf_text(raw)
        if txt:
            out.append(txt)
    return out


def _create_ingestion(db: Session, owner_id: int, source: str,
                      subject: str, sender: str, raw_text: str) -> Ingestion:
    ing = Ingestion(
        source=source,
        subject=(subject or "")[:500],
        sender=(sender or "")[:255],
        raw_text=raw_text or "",
        status=IngestionStatus.analyzing.value,
        owner_id=owner_id,
    )
    db.add(ing)
    db.commit()
    db.refresh(ing)
    return ing


def _get_or_404(ingestion_id: int, owner_id: int, db: Session) -> Ingestion:
    ing = db.query(Ingestion).filter(
        Ingestion.id == ingestion_id, Ingestion.owner_id == owner_id
    ).first()
    if not ing:
        raise HTTPException(status_code=404, detail="Ingestion not found")
    return ing
