"""Client follow-up router — IMAP inbox reading + reminder logic."""
import email
import logging
import os
import ssl
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Client, User
from app.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/clients", tags=["clients"])

# ── Inbox config ──
INBOX_EMAIL = os.environ.get("INBOX_EMAIL", "ncpdealcrm@outlook.com")
INBOX_PASSWORD = os.environ.get("INBOX_APP_PASSWORD", "")  # Outlook app password
INBOX_HOST = os.environ.get("INBOX_HOST", "outlook.office365.com")
INBOX_PORT = int(os.environ.get("INBOX_PORT", "993"))

# Reminder cooldown: don't remind again until N days after last reminder
REMINDER_COOLDOWN_DAYS = int(os.environ.get("REMINDER_COOLDOWN_DAYS", "3"))


class ClientCreate(BaseModel):
    client_email: str
    client_name: str = ""
    owner_id: int | None = None
    reminder_threshold_days: int = 7
    notes: str = ""


class ClientUpdate(BaseModel):
    client_name: str | None = None
    owner_id: int | None = None
    reminder_threshold_days: int | None = None
    notes: str | None = None


# ── IMAP sync ──

def _imap_connect():
    """Connect to the monitoring inbox via IMAP. Returns None if not configured."""
    if not INBOX_PASSWORD:
        return None
    import imaplib
    ctx = ssl.create_default_context()
    conn = imaplib.IMAP4_SSL(INBOX_HOST, INBOX_PORT, ssl_context=ctx)
    conn.login(INBOX_EMAIL, INBOX_PASSWORD)
    conn.select("INBOX")
    return conn


def _extract_client_from_message(msg: email.message.Message) -> dict | None:
    """Extract client info from a CC'd email message."""
    sender = ""
    for hdr in ["From", "from"]:
        sender = str(msg.get(hdr, "")).lower()
        if sender:
            break

    # Who sent it
    owner_email = ""
    if "andrew" in sender:
        owner_email = "andrew"
    elif "will" in sender:
        owner_email = "will"
    else:
        return None  # Not from a known sender

    # Extract recipients
    to_list = []
    for hdr in ["To", "to", "Cc", "cc"]:
        val = str(msg.get(hdr, ""))
        if val:
            to_list.extend([a.strip().lower() for a in val.replace(",", " ").split() if "@" in a])

    # Find client email (recipient that is NOT a known internal address)
    internal = {INBOX_EMAIL.lower(), "andrew@newchannelpartners.com", "will@newchannelpartners.com",
                "andrew@newchannel.partners", "will@newchannel.partners"}
    client_emails = [e for e in to_list if e not in internal]
    if not client_emails:
        return None

    # Get date
    date_str = msg.get("Date", "")
    mail_date = None
    try:
        mail_date = parsedate_to_datetime(date_str)
    except Exception:
        pass

    return {
        "owner_email": owner_email,
        "client_email": client_emails[0],
        "date": mail_date or datetime.now(timezone.utc),
    }


@router.post("/imap-sync")
def imap_sync(
    days_back: int = Query(default=7, description="How many days of inbox to scan"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pull new CC'd emails from the monitoring inbox and update client records."""
    conn = _imap_connect()
    if not conn:
        raise HTTPException(503, "IMAP not configured — set INBOX_APP_PASSWORD in .env")

    since_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%d-%b-%Y")
    status, messages = conn.search(None, f"(SINCE {since_date})")
    if status != "OK":
        conn.logout()
        raise HTTPException(500, "IMAP search failed")

    msg_ids = messages[0].split()
    updated = 0
    created = 0

    for num in msg_ids[-500:]:  # limit to last 500
        status, data = conn.fetch(num, "(RFC822)")
        if status != "OK":
            continue
        raw = data[0][1] if isinstance(data[0], tuple) else None
        if not raw:
            continue
        msg = email.message_from_bytes(raw)
        info = _extract_client_from_message(msg)
        if not info:
            continue

        # Find owner user
        owner = db.query(User).filter(User.username == info["owner_email"]).first()
        if not owner:
            continue

        client = db.query(Client).filter(Client.client_email == info["client_email"]).first()
        if client:
            if not client.last_contact_time or info["date"] > client.last_contact_time:
                client.last_contact_time = info["date"]
                client.last_sync_time = datetime.now(timezone.utc)
                # Reset reminder if new contact happened
                if client.reminder_sent_at and client.last_contact_time > client.reminder_sent_at:
                    client.reminder_sent_at = None
                updated += 1
        else:
            client = Client(
                client_email=info["client_email"],
                owner_id=owner.id,
                last_contact_time=info["date"],
                last_sync_time=datetime.now(timezone.utc),
            )
            db.add(client)
            created += 1

    db.commit()
    conn.logout()
    return {"ok": True, "created": created, "updated": updated, "scanned": len(msg_ids)}


# ── CRUD ──

@router.get("")
def list_clients(
    owner_id: int = Query(default=0),
    stale: bool = Query(default=False),
    search: str = Query(default=""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Client)
    if owner_id:
        q = q.filter(Client.owner_id == owner_id)
    if stale:
        q = q.filter(
            Client.last_contact_time < datetime.now(timezone.utc) - timedelta(days=Client.reminder_threshold_days)
        )
    if search:
        q = q.filter(
            (Client.client_email.ilike(f"%{search}%")) |
            (Client.client_name.ilike(f"%{search}%"))
        )
    return [c.to_dict() for c in q.order_by(Client.last_contact_time.asc().nullsfirst()).all()]


@router.post("")
def create_client(
    data: ClientCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.query(Client).filter(Client.client_email == data.client_email).first()
    if existing:
        raise HTTPException(409, "Client with this email already exists")

    client = Client(
        client_email=data.client_email,
        client_name=data.client_name,
        owner_id=data.owner_id,
        reminder_threshold_days=data.reminder_threshold_days,
        notes=data.notes,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return {"ok": True, "client": client.to_dict()}


@router.put("/{client_id}")
def update_client(
    client_id: int,
    data: ClientUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(404, "Client not found")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(client, key, val)
    db.commit()
    return {"ok": True, "client": client.to_dict()}


@router.put("/{client_id}/touch")
def touch_client(
    client_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually update last_contact_time to now."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(404, "Client not found")
    client.last_contact_time = datetime.now(timezone.utc)
    client.reminder_sent_at = None
    db.commit()
    return {"ok": True, "last_contact_time": client.last_contact_time.isoformat()}


@router.delete("/{client_id}")
def delete_client(
    client_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(404, "Client not found")
    db.delete(client)
    db.commit()
    return {"ok": True}


# ── Reminders ──

@router.post("/send-reminders")
def send_reminders(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check all clients and send reminder emails for stale ones."""
    now = datetime.now(timezone.utc)

    # Find stale clients
    stale = []
    for client in db.query(Client).all():
        if not client.last_contact_time:
            continue
        threshold = timedelta(days=client.reminder_threshold_days)
        if now - client.last_contact_time.replace(tzinfo=timezone.utc) <= threshold:
            continue
        # Cooldown check
        if client.reminder_sent_at:
            cooldown = timedelta(days=REMINDER_COOLDOWN_DAYS)
            if now - client.reminder_sent_at.replace(tzinfo=timezone.utc) <= cooldown:
                continue
        stale.append(client)

    if not stale:
        return {"ok": True, "reminders_sent": 0, "message": "No stale clients"}

    # Send emails
    import asyncio

    async def _send_reminders():
        from app.email_utils import send_email
        sent = 0
        for client in stale:
            if not client.owner or not client.owner.email:
                continue
            days = (now - client.last_contact_time.replace(tzinfo=timezone.utc)).days
            subject = f"Follow-up: {client.client_name or client.client_email} — {days} days since last contact"
            body = (
                f"Hi {client.owner.display_name or client.owner.username},\n\n"
                f"This is an automated reminder from DealCRM.\n\n"
                f"Client: {client.client_name or client.client_email}\n"
                f"Email:  {client.client_email}\n"
                f"Days since last contact: {days}\n"
                f"Threshold: {client.reminder_threshold_days} days\n\n"
                f"Please reach out to this client when you have a moment.\n\n"
                f"— DealCRM Client Follow-up"
            )
            ok, _ = await send_email(client.owner.email, client.client_name or "Client", subject, body)
            if ok:
                client.reminder_sent_at = now
                sent += 1

        if sent:
            db.commit()
        return sent

    sent = asyncio.run(_send_reminders())
    return {"ok": True, "reminders_sent": sent, "stale_clients": len(stale)}
