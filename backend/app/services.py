"""Notifications, audit log, rate limiting, SLA + escalation engine."""
import os, time, smtplib, threading
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from . import models

# Deadline to solve a complaint, by priority:
#   Low (less urgent) = 3 days, Medium = 2 days, High (serious) = 1 day. Critical is also 1 day.
# If it is not solved by then it is escalated to the HOD automatically.
SLA_HOURS = {"Critical": 24, "High": 24, "Medium": 48, "Low": 72}
# Offices where several officers share one queue (see routes/complaints.py) - everybody in
# such an office is alerted, not just the one officer the complaint was assigned to.
SPLIT_DEPTS = {"Class Incharge", "Lab Assistant", "Project Placement Cell", "Timetable Coordinator"}
# Every "Timetable & Attendance" complaint (and its alert mail) goes to this one mailbox.
TIMETABLE_OWNER_EMAIL = "dumne_rs@mgmcen.ac.in"
SLA_SCALE = float(os.getenv("SLA_SCALE", "1"))     # shrink for live demo
MAX_LEVEL = 2                                      # 1 = HOD, 2 = Principal

def sla_due(priority: str, start=None, factor: float = 1.0):
    return (start or datetime.utcnow()) + timedelta(hours=SLA_HOURS[priority] * SLA_SCALE * factor)

def mail_target(user):
    """Where to send a user's email alerts, or None.
    Staff -> their REAL mailbox (notify_email), written as  Name <address>.
    Their login address may be a placeholder, so it is never used for staff.
    Students -> their own college address."""
    if user is None:
        return None
    if user.notify_email:
        return formataddr((user.notify_name or user.name, user.notify_email))
    if user.role == "student":
        return user.email
    return None

def _smtp_send(to: str, subject: str, body: str):
    host = os.getenv("SMTP_HOST")
    if not host:
        print(f"[EMAIL (SMTP not configured) -> {to}] {subject}: {body}")
        return
    try:
        sender = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or "noreply@mgmcen.ac.in"
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = sender, to, subject
        msg.set_content(body)
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=15) as s:
            s.starttls()
            if os.getenv("SMTP_USER"):
                s.login(os.getenv("SMTP_USER", ""), os.getenv("SMTP_PASS", ""))
            s.send_message(msg)
        print(f"[EMAIL sent -> {to}] {subject}")
    except Exception as e:
        print(f"Email to {to} failed:", e)

def send_email(to: str, subject: str, body: str):
    """Sent in a background thread so a slow mail server never slows down the website."""
    threading.Thread(target=_smtp_send, args=(to, subject, body), daemon=True).start()

def notify(db, user, message: str, subject: str = "Complaint System Update"):
    """In-app notification + email to the person's real mailbox (if they have one)."""
    if user is None:
        return
    db.add(models.Notification(user_id=user.id, message=message))
    to = mail_target(user)
    if to:
        app_url = os.getenv("APP_URL", "http://127.0.0.1:8000")
        body = f"Hello {user.notify_name or user.name},\n\n{message}\n\nOpen the Complaint System to act on it: {app_url}\n\n- Complaint System, MGM College"
        send_email(to, subject, body)
    else:
        print(f"[no alert email set for {user.name}; in-app notification only]")

def office_staff(db, c):
    """Everyone who should hear about a complaint at officer level: the assigned officer, plus
    - for shared offices like Timetable Coordinator - every colleague in that office."""
    o = c.officer
    if o is None:
        return []
    if o.department_id and o.department and o.department.name not in SPLIT_DEPTS:
        return db.query(models.User).filter_by(role="officer", department_id=o.department_id).all()
    return [o]

def deadline_text(c) -> str:
    return c.sla_due.strftime("%d %b %Y, %I:%M %p UTC") if c.sla_due else "-"

def audit(db, user_id, action: str, detail: str = ""):
    """Writes each event straight to MongoDB (not the SQL database) so the audit
    trail lives in a document store. `db` is accepted for backward compatibility
    with existing call sites but is not used here."""
    try:
        from .mongo import audit_collection
        audit_collection().insert_one({"user_id": user_id, "action": action, "detail": detail, "at": datetime.utcnow()})
    except Exception as e:
        print("Mongo audit write failed (is MongoDB running?):", e)

_hits: dict = {}
def rate_limited(key, limit: int = 5, window: int = 600) -> bool:
    now = time.time()
    _hits[key] = [t for t in _hits.get(key, []) if now - t < window]
    if len(_hits[key]) >= limit:
        return True
    _hits[key].append(now)
    return False

def run_escalation(db) -> int:
    """Escalate every open complaint whose SLA has expired: Officer -> HOD -> Principal."""
    now, count = datetime.utcnow(), 0
    overdue = db.query(models.Complaint).filter(
        models.Complaint.status.notin_(["Resolved", "Closed"]),
        models.Complaint.sla_due < now,
        models.Complaint.escalation_level < MAX_LEVEL).all()
    for c in overdue:
        nxt = c.escalation_level + 1
        boss = db.query(models.User).filter_by(role="authority", level=nxt).first()
        if not boss:
            continue
        c.escalation_level, c.status, c.sla_due = nxt, "Escalated", sla_due(c.priority, now, 0.5)
        reason = "Deadline missed"
        db.add(models.Escalation(complaint_id=c.id, to_level=nxt, to_user_id=boss.id, reason=reason))
        db.add(models.StatusHistory(complaint_id=c.id, status="Escalated", remarks=f"{reason}; escalated to {boss.name}"))
        audit(db, None, "AUTO_ESCALATE", f"{c.code} -> {boss.name}")
        msg = (f'{c.code} "{c.title}" ({c.priority}) was NOT solved before its deadline and has been escalated to {boss.name}. '
               f'{"Please take action." if boss.role == "authority" else ""}')
        subj = f"[ESCALATED] {c.code} - deadline missed"
        notify(db, boss, msg, subj)
        for o in office_staff(db, c):
            notify(db, o, msg, subj)
        notify(db, c.student, f'Your complaint {c.code} "{c.title}" was not solved in time, so it was escalated to {boss.name}', subj)
        count += 1
    db.commit()
    return count
