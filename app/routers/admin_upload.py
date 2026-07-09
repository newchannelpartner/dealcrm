"""Temporary admin endpoint for replacing the production SQLite database.

Admin-only, one-off data-seeding tool — remove once the real database has
been uploaded to the Railway volume.
"""
import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from app.auth import require_admin
from app.database import DATABASE_PATH, engine
from app.models import User

router = APIRouter(tags=["admin"])

SQLITE_MAGIC = b"SQLite format 3\x00"

UPLOAD_FORM = """<!doctype html>
<html>
<head><title>Upload database</title></head>
<body style="font-family: sans-serif; max-width: 480px; margin: 4rem auto;">
  <h2>Upload replacement database</h2>
  <p>Replaces the live crm.db on the server. The current file is backed up first.</p>
  <form action="/admin/upload-db" method="post" enctype="multipart/form-data">
    <input type="file" name="file" accept=".db" required />
    <button type="submit">Upload</button>
  </form>
</body>
</html>"""


@router.get("/admin/upload-db", response_class=HTMLResponse)
async def upload_db_form(_admin: User = Depends(require_admin)):
    return HTMLResponse(UPLOAD_FORM)


@router.post("/admin/upload-db")
async def upload_db(
    file: UploadFile = File(...),
    _admin: User = Depends(require_admin),
):
    contents = await file.read()
    if not contents.startswith(SQLITE_MAGIC):
        raise HTTPException(status_code=400, detail="Uploaded file is not a SQLite database")

    db_path = Path(DATABASE_PATH)
    backup_path = Path(str(db_path) + ".backup")
    tmp_path = Path(str(db_path) + ".upload-tmp")

    # Release pooled connections so the old file isn't held open while we swap it.
    engine.dispose()

    backed_up = db_path.exists()
    if backed_up:
        backup_path.write_bytes(db_path.read_bytes())

    tmp_path.write_bytes(contents)
    os.replace(tmp_path, db_path)

    # Drop stale WAL/SHM sidecars from the previous database — they don't apply
    # to the newly uploaded file and would otherwise confuse SQLite on next open.
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db_path) + suffix)
        if sidecar.exists():
            sidecar.unlink()

    return JSONResponse({
        "ok": True,
        "bytes_written": len(contents),
        "backup": str(backup_path) if backed_up else None,
    })
