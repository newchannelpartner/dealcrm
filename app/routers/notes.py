"""Notes router — creates notes and triggers AI analysis in background."""
import threading

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models import Note, Todo, EntityType, TodoStatus, TodoSource
from app.auth import get_current_owner

router = APIRouter(prefix="/notes", tags=["notes"])


class NoteCreate(BaseModel):
    entity_type: str = "none"
    entity_id: int | None = None
    body_html: str = ""
    body_text: str = ""


@router.get("")
def list_notes(
    entity_type: str = Query(default=""),
    entity_id: int = Query(default=0),
    search: str = Query(default=""),
    limit: int = Query(default=50),
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    q = db.query(Note).filter(Note.owner_id == owner_id)

    if entity_type and entity_id:
        q = q.filter(Note.entity_type == entity_type, Note.entity_id == entity_id)
    elif entity_type:
        q = q.filter(Note.entity_type == entity_type)

    if search:
        q = q.filter(Note.body_text.ilike(f"%{search}%"))

    notes = q.order_by(Note.created_at.desc()).limit(limit).all()
    return [n.to_dict() for n in notes]


@router.get("/{note_id}")
def get_note(
    note_id: int,
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    note = _get_note_or_404(note_id, owner_id, db)
    return note.to_dict()


@router.post("")
def create_note(
    data: NoteCreate,
    owner_id: int = Depends(get_current_owner),
    db: Session = Depends(get_db),
):
    # Validate entity_type
    valid_entity_types = {e.value for e in EntityType}
    entity_type = data.entity_type if data.entity_type in valid_entity_types else EntityType.none.value

    note = Note(
        entity_type=entity_type,
        entity_id=data.entity_id,
        body_html=data.body_html,
        body_text=data.body_text,
        owner_id=owner_id,
    )
    db.add(note)
    db.commit()
    db.refresh(note)

    # Trigger AI analysis in background if there's text
    if data.body_text and data.body_text.strip():
        _trigger_ai_analysis(note.id, owner_id)

    return note.to_dict()


def _trigger_ai_analysis(note_id: int, owner_id: int):
    """Run AI analysis in a background thread. Non-blocking."""
    import asyncio

    def run():
        db = SessionLocal()
        try:
            note = db.query(Note).filter(Note.id == note_id).first()
            if not note or not note.body_text:
                return

            from app.ai import analyze_text, parse_priority, parse_due_date

            result = asyncio.run(analyze_text(note.body_text))

            # Store AI results on the note
            note.ai_summary = result.get("summary", "")
            note.ai_takeaways = result.get("takeaways", [])

            # Create Todo rows from AI-extracted todos
            for t in result.get("todos", []):
                if isinstance(t, dict) and t.get("title"):
                    due_date = parse_due_date(t.get("due_date_suggestion"))
                    priority = parse_priority(t.get("priority"))

                    todo = Todo(
                        title=str(t["title"])[:500],
                        due_date=due_date,
                        priority=priority,
                        status=TodoStatus.open.value,
                        source=TodoSource.ai.value,
                        linked_entity_type=note.entity_type if note.entity_type != EntityType.none.value else None,
                        linked_entity_id=note.entity_id,
                        owner_id=owner_id,
                    )
                    db.add(todo)

            db.commit()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("AI analysis failed")
        finally:
            db.close()

    t = threading.Thread(target=run, daemon=True)
    t.start()


def _get_note_or_404(note_id: int, owner_id: int, db: Session) -> Note:
    note = db.query(Note).filter(
        Note.id == note_id, Note.owner_id == owner_id
    ).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note
