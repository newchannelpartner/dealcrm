"""DealCRM — bespoke CRM for M&A advisory and private credit."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.database import init_db, engine, SessionLocal
from app.routers import contacts, deals, notes, todos, dashboard, inbound, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _seed_admin()
    _start_scheduler()
    yield
    engine.dispose()


def _seed_admin():
    """Create the initial admin account from env vars if no users exist yet."""
    from app.auth import seed_admin_user
    db = SessionLocal()
    try:
        seed_admin_user(db)
    finally:
        db.close()


def _start_scheduler():
    """Start APScheduler with an empty job registry — placeholder for future daily scan."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        scheduler = BackgroundScheduler(daemon=True)
        scheduler.start()
        print("APScheduler started — job registry empty (placeholder for future daily scan)")
    except ImportError:
        print("APScheduler not installed — skipping scheduler")
    except Exception as e:
        print(f"Failed to start scheduler: {e}")


app = FastAPI(
    title="DealCRM",
    description="Bespoke CRM for M&A advisory and private credit professionals",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
app.include_router(contacts.router)
app.include_router(deals.router)
app.include_router(notes.router)
app.include_router(todos.router)
app.include_router(dashboard.router)
app.include_router(inbound.router)
app.include_router(users.router)


# Health check (no auth)
@app.get("/health")
def health():
    return {"status": "ok"}


# Static files (frontend + PWA assets)
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir, html=False), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(static_dir, "index.html"))

    @app.get("/manifest.json")
    async def serve_manifest():
        return FileResponse(os.path.join(static_dir, "manifest.json"))

    @app.get("/sw.js")
    async def serve_sw():
        return FileResponse(os.path.join(static_dir, "sw.js"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
