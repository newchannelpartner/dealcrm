"""Attachments router — file upload / download / delete."""
import os
import uuid
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db, DATABASE_PATH
from app.models import Attachment, EntityType, User
from app.auth import get_current_user

router = APIRouter(prefix="/attachments", tags=["attachments"])

# Store files next to the database
UPLOAD_DIR = Path(DATABASE_PATH).parent / "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.get("")
def list_attachments(
    entity_type: str,
    entity_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    attachments = db.query(Attachment).filter(
        Attachment.entity_type == entity_type,
        Attachment.entity_id == entity_id,
    ).order_by(Attachment.created_at.desc()).all()
    return [a.to_dict() for a in attachments]


@router.post("")
async def upload_attachment(
    entity_type: str,
    entity_id: int,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if entity_type not in {"contact", "deal", "firm"}:
        raise HTTPException(400, "Invalid entity_type")

    # Generate unique filename
    ext = Path(file.filename or "file").suffix or ""
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = UPLOAD_DIR / unique_name

    # Save file
    contents = await file.read()
    file_path.write_bytes(contents)

    mime, _ = mimetypes.guess_type(file.filename or "file")

    attachment = Attachment(
        entity_type=entity_type,
        entity_id=entity_id,
        filename=unique_name,
        original_filename=file.filename or "file",
        file_size=len(contents),
        mime_type=mime or "",
        owner_id=user.owner_id,
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment.to_dict()


@router.get("/{attachment_id}/download")
def download_attachment(
    attachment_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    attachment = db.query(Attachment).filter(Attachment.id == attachment_id).first()
    if not attachment:
        raise HTTPException(404, "Attachment not found")

    file_path = UPLOAD_DIR / attachment.filename
    if not file_path.exists():
        raise HTTPException(404, "File not found on disk")

    return FileResponse(
        path=str(file_path),
        filename=attachment.original_filename,
        media_type=attachment.mime_type or "application/octet-stream",
    )


@router.delete("/{attachment_id}")
def delete_attachment(
    attachment_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    attachment = db.query(Attachment).filter(Attachment.id == attachment_id).first()
    if not attachment:
        raise HTTPException(404, "Attachment not found")

    file_path = UPLOAD_DIR / attachment.filename
    if file_path.exists():
        file_path.unlink()

    db.delete(attachment)
    db.commit()
    return {"ok": True}
