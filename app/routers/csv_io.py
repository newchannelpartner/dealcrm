"""CSV import / export — admin-only data management tools."""
import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Contact, Deal, Todo, User
from app.auth import get_current_owner, require_admin

router = APIRouter(tags=["csv"])


# ──────────────────────────────────────────
#  EXPORT
# ──────────────────────────────────────────
def _csv_response(rows: list[dict], filename: str) -> StreamingResponse:
    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    else:
        output.write("No data\n")
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/admin/export/contacts")
def export_contacts_csv(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    contacts = db.query(Contact).order_by(Contact.name.asc()).all()
    rows = []
    for c in contacts:
        rows.append({
            "id": str(c.id),
            "name": c.name,
            "email": c.email or "",
            "phone": c.phone or "",
            "firm": c.firm or "",
            "title": c.title or "",
            "tags": "; ".join(c.tags or []),
            "summary_text": (c.summary_text or "")[:500],
            "created_at": c.created_at.isoformat() if c.created_at else "",
            "updated_at": c.updated_at.isoformat() if c.updated_at else "",
        })
    return _csv_response(rows, "contacts_export.csv")


@router.get("/admin/export/deals")
def export_deals_csv(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    deals = db.query(Deal).order_by(Deal.name.asc()).all()
    rows = []
    for d in deals:
        rows.append({
            "id": str(d.id),
            "name": d.name,
            "type": d.type,
            "stage": d.stage,
            "size_mm": str(d.size_mm) if d.size_mm is not None else "",
            "tags": "; ".join(d.tags or []),
            "contact_ids": ";".join(str(x) for x in (d.contact_ids or [])),
            "notes_text": (d.notes_text or "")[:500],
            "created_at": d.created_at.isoformat() if d.created_at else "",
            "updated_at": d.updated_at.isoformat() if d.updated_at else "",
        })
    return _csv_response(rows, "deals_export.csv")


@router.get("/admin/export/todos")
def export_todos_csv(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    todos = db.query(Todo).order_by(Todo.created_at.desc()).all()
    rows = []
    for t in todos:
        rows.append({
            "id": str(t.id),
            "title": t.title,
            "due_date": str(t.due_date) if t.due_date else "",
            "priority": t.priority,
            "status": t.status,
            "source": t.source,
            "linked_entity_type": t.linked_entity_type or "",
            "linked_entity_id": str(t.linked_entity_id) if t.linked_entity_id else "",
            "created_at": t.created_at.isoformat() if t.created_at else "",
        })
    return _csv_response(rows, "todos_export.csv")


# ──────────────────────────────────────────
#  IMPORT
# ──────────────────────────────────────────
@router.post("/admin/import/contacts")
async def import_contacts_csv(
    file: UploadFile = File(...),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Import contacts from a CSV file.
    
    Expected columns (case-insensitive header): name, email, phone, firm, title, tags.
    Name is required for each row; all other columns are optional.
    Tags can be semicolon-separated: "Investor; Banker; LP".
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Please upload a .csv file")

    contents = await file.read()
    # Try to decode with utf-8 first, then fall back to latin-1 (for Excel exports)
    try:
        text = contents.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = contents.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HTTPException(400, "CSV file is empty")

    # Normalise header to lowercase
    header_map = {h.lower().strip(): h for h in reader.fieldnames}

    created = 0
    skipped = 0
    errors = []

    for row_num, row in enumerate(reader, start=2):
        # Normalise keys
        normalised = {k.lower().strip(): v.strip() for k, v in row.items() if v}

        name = normalised.get("name", "")
        if not name:
            skipped += 1
            continue

        # Check for duplicate by name + firm (case-insensitive)
        firm = normalised.get("firm", "")
        existing = db.query(Contact).filter(
            Contact.name == name,
            Contact.firm == firm,
        ).first()
        if existing:
            skipped += 1
            continue

        # Parse tags: semicolon or comma separated
        raw_tags = normalised.get("tags", "")
        tags = [t.strip() for t in raw_tags.replace(";", ",").split(",") if t.strip()]

        contact = Contact(
            name=name,
            email=normalised.get("email", ""),
            phone=normalised.get("phone", ""),
            firm=firm,
            title=normalised.get("title", ""),
            tags=tags,
            summary_text=normalised.get("summary_text", ""),
            owner_id=1,
        )
        try:
            db.add(contact)
            db.commit()
            created += 1
        except Exception as e:
            db.rollback()
            errors.append(f"Row {row_num} ({name}): {e}")

    return {
        "ok": True,
        "created": created,
        "skipped": skipped,
        "errors": errors,
    }
