import os, threading, time
from dotenv import load_dotenv
load_dotenv()   # reads backend/.env so DATABASE_URL, MONGO_URL etc. are picked up automatically
from contextlib import asynccontextmanager
from pathlib import Path
import traceback
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .database import Base, engine, SessionLocal, migrate, fix_classroom_routing
from .routes import auth, complaints, admin
from .seed import seed
from .services import run_escalation
from . import image_check

Base.metadata.create_all(engine)
migrate()
seed()
fix_classroom_routing()

def _escalation_loop(interval: int):
    while True:                     # background scheduler: checks SLAs every `interval` seconds
        time.sleep(interval)
        db = SessionLocal()
        try:
            run_escalation(db)
        except Exception as e:
            print("Escalation error:", e)
        finally:
            db.close()

@asynccontextmanager
async def lifespan(app):
    image_check.warmup()           # loads the picture-checking model in the background
    interval = int(os.getenv("ESCALATION_INTERVAL", "60"))
    if interval > 0:
        threading.Thread(target=_escalation_loop, args=(interval,), daemon=True).start()
    yield

app = FastAPI(title="AI College Complaint Classification & Escalation System", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    traceback.print_exc()          # full details appear in the server window
    if os.getenv("DEBUG_ERRORS", "1") == "1":     # set DEBUG_ERRORS=0 in production
        return JSONResponse({"detail": f"Server error: {type(exc).__name__}: {str(exc)[:200]}"}, status_code=500)
    return JSONResponse({"detail": "Something went wrong on the server"}, status_code=500)

app.include_router(auth.router)
app.include_router(complaints.router)
app.include_router(admin.admin)
app.include_router(admin.analytics_router)
app.include_router(admin.notif_router)

@app.get("/health")
def health():
    return {"status": "ok"}

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="ui")   # UI served at http://127.0.0.1:8000/
