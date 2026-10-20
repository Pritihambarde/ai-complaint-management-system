import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

URL = os.getenv("DATABASE_URL", "sqlite:///./complaints.db")
engine = create_engine(URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def migrate():
    """Adds columns introduced after the first release to an EXISTING database (create_all
    only creates missing tables, never missing columns). Safe to run on every start."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    wanted = {"users": {"notify_email": "VARCHAR", "notify_name": "VARCHAR"}}
    with engine.begin() as conn:
        for table, cols in wanted.items():
            if not insp.has_table(table):
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for name, typ in cols.items():
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {typ}"))


def fix_classroom_routing():
    """One-time, safe to repeat: open 'Classroom Infrastructure' complaints that were earlier sent to a
    Lab Assistant are moved to the Class Incharge of the student's own year+section."""
    from . import models
    db = SessionLocal()
    try:
        ci = db.query(models.Department).filter_by(name="Class Incharge").first()
        if not ci:
            return
        rows = db.query(models.Complaint).filter(
            models.Complaint.category == "Classroom Infrastructure",
            models.Complaint.status.notin_(["Resolved", "Closed"]), models.Complaint.escalation_level == 0).all()
        for c in rows:
            if c.officer and c.officer.department_id == ci.id:
                continue
            right = db.query(models.User).filter_by(role="officer", department_id=ci.id,
                                                    year=c.student.year, section=c.student.section).first()
            if right:
                c.officer_id = right.id
                db.add(models.StatusHistory(complaint_id=c.id, status=c.status, remarks=f"Re-routed to Class Incharge {right.name}"))
        db.commit()
    finally:
        db.close()
