"""Database setup for DealCRM."""
import os
from pathlib import Path

# Auto-load .env file for local development
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip()
                if key not in os.environ:
                    os.environ[key] = val

from sqlalchemy import create_engine, event, text

DATABASE_PATH = os.environ.get("DATABASE_PATH", "/data/crm.db")
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# Ensure data directory exists
db_dir = os.path.dirname(DATABASE_PATH)
if db_dir:
    os.makedirs(db_dir, exist_ok=True)

connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args, echo=False)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


from sqlalchemy.orm import sessionmaker

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables and run migrations."""
    import app.models  # noqa: ensure models are registered

    # SQLAlchemy creates new tables automatically
    app.models.Base.metadata.create_all(bind=engine)

    # Run column migrations for existing tables
    _migrate_columns()


def _migrate_columns():
    """Add any missing columns to existing tables, and migrate data.

    SQLite does not support ALTER TABLE ADD COLUMN IF NOT EXISTS, so we
    inspect the table_info before running each DDL statement.
    """
    import logging
    log = logging.getLogger(__name__)

    with engine.connect() as conn:
        # ── Contacts ──
        _add_column_if_missing(conn, "contacts", "firm_id", "INTEGER")
        _add_column_if_missing(conn, "contacts", "last_contacted_at", "TIMESTAMP")
        _add_column_if_missing(conn, "contacts", "relationship_tier", "VARCHAR(2) DEFAULT ''")
        _add_column_if_missing(conn, "contacts", "summary_text", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "contacts", "outreach_status", "VARCHAR(20) DEFAULT ''")
        _add_column_if_missing(conn, "contacts", "outreach_region", "VARCHAR(50) DEFAULT ''")
        _add_column_if_missing(conn, "contacts", "outreach_notes", "TEXT DEFAULT ''")

        # ── Deals ──
        _add_column_if_missing(conn, "deals", "expected_fee", "FLOAT")
        _add_column_if_missing(conn, "deals", "fee_type", "VARCHAR(20) DEFAULT ''")
        _add_column_if_missing(conn, "deals", "assignee_user_id", "INTEGER")
        _add_column_if_missing(conn, "deals", "milestones", "JSON")
        _add_column_if_missing(conn, "deals", "contact_ids", "JSON")
        _add_column_if_missing(conn, "deals", "tags", "JSON")

        # ── Todos ──
        _add_column_if_missing(conn, "todos", "assigned_to_user_id", "INTEGER")

        # ── Notes ── (ensure older DBs have these)
        _add_column_if_missing(conn, "notes", "ai_takeaways", "JSON")
        _add_column_if_missing(conn, "notes", "body_text", "TEXT DEFAULT ''")

        conn.commit()

        # ── Migrate: firm strings → Firm records ──
        _migrate_firms(conn, log)

        conn.commit()


def _add_column_if_missing(conn, table: str, column: str, col_type: str):
    """Add a column to a table if it doesn't already exist."""
    result = conn.execute(text(f"PRAGMA table_info({table})"))
    existing = {row[1] for row in result.fetchall()}
    if column not in existing:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))


def _migrate_firms(conn, log):
    """Create Firm records from distinct firm strings on contacts."""
    result = conn.execute(text("SELECT DISTINCT firm FROM contacts WHERE firm IS NOT NULL AND firm != ''"))
    firm_names = [row[0] for row in result.fetchall()]
    if not firm_names:
        return

    # Check how many contacts already have firm_id set
    already = conn.execute(text("SELECT COUNT(*) FROM contacts WHERE firm_id IS NOT NULL")).scalar()
    if already > 0:
        return  # already migrated

    # Check if any Firms already exist
    firm_count = conn.execute(text("SELECT COUNT(*) FROM firms")).scalar()
    if firm_count > 0:
        return  # firms already exist, probably from prior migration

    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()

    for name in firm_names:
        # Insert Firm
        conn.execute(
            text("INSERT INTO firms (name, created_at, updated_at, owner_id) VALUES (:name, :now, :now, 1)"),
            {"name": name, "now": now},
        )
        firm_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()

        # Link contacts with this firm string
        conn.execute(
            text("UPDATE contacts SET firm_id = :fid WHERE firm = :name"),
            {"fid": firm_id, "name": name},
        )

    log.info(f"Migrated {len(firm_names)} firms from contact strings")
