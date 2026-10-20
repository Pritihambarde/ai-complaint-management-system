import os, uuid
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, schemas, ml, image_check
from ..security import require_role, current_user
from ..services import TIMETABLE_OWNER_EMAIL, notify, audit, sla_due, rate_limited, SPLIT_DEPTS, office_staff, deadline_text

router = APIRouter(prefix="/complaints", tags=["Complaints"])
UPLOAD_DIR = "uploads"
ALLOWED = {".jpg": b"\xff\xd8", ".jpeg": b"\xff\xd8", ".png": b"\x89PNG", ".pdf": b"%PDF"}
MAX_SIZE = 5 * 1024 * 1024
REOPEN_DAYS = 7

ROUTING = {   # category -> office (an officer of that office gets the complaint)
    "Lab & Equipment": "Lab Assistant", "Classroom Infrastructure": "Class Incharge",   # classroom problems go to the student's own class incharge
    "Teaching & Syllabus": "Class Incharge", "Timetable & Attendance": "Timetable Coordinator",
    "Exams & Marks": "Exam Coordinator", "Projects & Placements": "Project Placement Cell",
    "Ragging & Harassment": "HOD", "Other": "Admin Desk",
}
DIRECT_TO_HOD = {"Ragging & Harassment"}   # sensitive: goes straight to the HOD (authority level 1), no officer in between
# Departments where one specific person is picked per complaint (by class/lab/section) -
# only that exact person can see/manage it. Every other department is a "shared office":
# a complaint still gets assigned to one officer there (for notifications/records), but
# any officer in that same department can see it and act on it, since the office is staffed
# by multiple people jointly covering the same queue (e.g. Timetable Coordinator).
# (SPLIT_DEPTS now lives in services.py so the alert emails use the same rule)

def pick_officer(db, dept, student, lab_number):
    """Pick the right officer within a department, not just 'the first one'.

    - Class Incharge: there's one coordinator per (year, section) - SY/TY each have
      A/B/C, BTech has A/B - so match on the student's own year+section.
    - Project Placement Cell: BTech A/B each have a dedicated Project Incharge (matched the
      same way as Class Incharge); everyone else (SY/TY, until their own incharges are
      confirmed) falls back to the generic Training & Placement officer (no year/section set).
    - Lab Assistant: there are 10 labs shared across a few incharges, each owning a few labs
      (see seed.py) - match on the lab_number the student picked when submitting.
    - Every other office (Timetable/Exam Coordinator, Admin Desk) has a single officer, so
      just return them.
    """
    if not dept:
        return None
    officers = db.query(models.User).filter_by(role="officer", department_id=dept.id).all()
    if not officers:
        return None
    if dept.name == "Class Incharge" and student:
        for o in officers:
            if o.year == student.year and o.section == student.section:
                return o
        return None   # no Class Incharge set for this exact class: stays unassigned for the admin (never sent to another class's incharge)
    if dept.name == "Project Placement Cell" and student:
        for o in officers:
            if o.year == student.year and o.section == student.section:
                return o
        generic = next((o for o in officers if not o.year and not o.section), None)
        return generic or officers[0]   # fallback: generic Training & Placement officer
    if dept.name == "Lab Assistant" and lab_number:
        for o in officers:
            nums = [n.strip() for n in (o.lab_numbers or "").split(",") if n.strip()]
            if str(lab_number) in nums:
                return o
        return officers[0]   # fallback: lab number wasn't given or doesn't match anyone's range
    if dept.name == "Timetable Coordinator":
        # ALL timetable complaints go to Ms Dumne (real mailbox dumne_rs@mgmcen.ac.in)
        for o in officers:
            if (o.notify_email or "").lower() == TIMETABLE_OWNER_EMAIL or (o.email or "").lower() == TIMETABLE_OWNER_EMAIL:
                return o
    return officers[0]

def to_dict(c: models.Complaint, viewer: models.User):
    hide = c.is_anonymous and viewer.id != c.student_id          # anonymity: only the owner sees identity
    return {"id": c.id, "code": c.code, "title": c.title, "description": c.description,
            "category": c.category, "priority": c.priority, "confidence": c.confidence,
            "sentiment": c.sentiment, "keywords": [k for k in (c.keywords or "").split(",") if k],
            "status": c.status, "is_anonymous": c.is_anonymous,
            "student_name": "Anonymous" if hide else c.student.name,
            "student_class": None if hide else (f"{c.student.year}-{c.student.section}" if c.student.year else None),
            "lab_number": c.lab_number,
            "assigned_to": c.officer.name if c.officer else ("HOD" if c.category in DIRECT_TO_HOD else None),
            "escalation_level": c.escalation_level, "direct_to_hod": c.category in DIRECT_TO_HOD and c.officer_id is None and c.escalation_level == 1, "sla_due": c.sla_due.isoformat() if c.sla_due else None,
            "duplicate_of": c.duplicate_of, "duplicate_count": c.duplicate_count,
            "rating": c.rating, "feedback": c.feedback, "has_attachment": bool(c.attachment),
            "created_at": c.created_at.isoformat(),
            "history": [{"status": h.status, "remarks": h.remarks, "at": h.changed_at.isoformat()} for h in c.history]}

def find_duplicate(db, text, category):
    since = datetime.utcnow() - timedelta(days=30)
    rows = db.query(models.Complaint).filter(
        models.Complaint.category == category, models.Complaint.created_at > since,
        models.Complaint.status.notin_(["Resolved", "Closed"]), models.Complaint.duplicate_of.is_(None)).all()
    if not rows:
        return None
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    try:
        m = TfidfVectorizer(stop_words="english").fit_transform([r.description for r in rows] + [text])
    except ValueError:
        return None
    sims = cosine_similarity(m[-1], m[:-1])[0]
    return rows[int(sims.argmax())] if sims.max() >= 0.5 else None

def mismatch_message(chosen, suggested):
    return (f"Your description looks like a '{suggested}' problem, but you selected '{chosen}'. "
            f"Please choose '{suggested}' as the Type of problem (or edit your description) before submitting.")

@router.post("/check-category")
def check_category(title: str = Form(""), description: str = Form(""),
                   user: models.User = Depends(require_role("student"))):
    """Live check used by the form: which problem type does the text clearly belong to?"""
    text = f"{title.strip()}. {description.strip()}"
    if len(description.strip()) < 20:
        return {"suggested": None, "confidence": 0}
    r = ml.predict(text)
    if r["category"] == "Other" or r["confidence"] < ml.MISMATCH_CONFIDENCE:
        return {"suggested": None, "confidence": r["confidence"]}
    return {"suggested": r["category"], "confidence": r["confidence"]}

@router.post("", status_code=201)
async def submit(title: str = Form(...), description: str = Form(...), anonymous: bool = Form(False),
                 category: str = Form(...), lab_number: Optional[int] = Form(None), file: Optional[UploadFile] = File(None),
                 user: models.User = Depends(require_role("student")), db: Session = Depends(get_db)):
    if category not in ROUTING:
        raise HTTPException(422, "Invalid problem type")
    if category == "Lab & Equipment":
        if lab_number is None:
            raise HTTPException(422, "Please mention the lab number (1-10) for a lab complaint")
        if not 1 <= lab_number <= 10:
            raise HTTPException(422, "Lab number must be between 1 and 10")
    else:
        lab_number = None          # only lab complaints carry a lab number
    if rate_limited(("submit", user.id)):
        raise HTTPException(429, "Too many complaints submitted. Please wait a few minutes")
    title, description = title.strip(), description.strip()
    if not (5 <= len(title) <= 120):
        raise HTTPException(422, "Title must be 5-120 characters")
    if not (20 <= len(description) <= 2000):
        raise HTTPException(422, "Description must be 20-2000 characters")
    reason = ml.is_spam(description) or ("Please use respectful language in your complaint" if ml.is_abusive(title) else None)
    if reason:
        raise HTTPException(422, reason)

    content, ext = None, ""
    if file and file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED:
            raise HTTPException(422, "Only jpg, png or pdf files allowed")
        content = await file.read()
        if len(content) > MAX_SIZE:
            raise HTTPException(422, "File must be under 5 MB")
        if not content:
            raise HTTPException(422, image_check.PREFIX + "the file is empty. Please choose a file that has content.")
        if not content.startswith(ALLOWED[ext]):
            raise HTTPException(422, "File content does not match its type")
        # evidence must be a real, non-blank file that is related to the chosen problem type
        try:
            await run_in_threadpool(image_check.validate, content, ext, category)
        except image_check.AttachmentError as e:
            raise HTTPException(422, str(e))

    text = f"{title}. {description}"
    mm = ml.category_mismatch(text, category)
    if mm:      # wrong "Type of problem" chosen -> do NOT submit, tell the student which one fits
        raise HTTPException(422, mismatch_message(category, mm["suggested"]))
    path = None
    if content is not None:        # everything checked out - only now is the evidence file stored
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex}{ext}")
        with open(path, "wb") as f:
            f.write(content)
    r = ml.predict(text)
    r["category"] = category   # student's own choice of problem type overrides the AI-guessed category
    hod = db.query(models.User).filter_by(role="authority", level=1).first() if r["category"] in DIRECT_TO_HOD else None
    dept = db.query(models.Department).filter_by(name=ROUTING[r["category"]]).first()
    officer = None if hod else pick_officer(db, dept, user, lab_number)
    handler = hod or officer
    dup = find_duplicate(db, description, r["category"])

    c = models.Complaint(title=title, description=description, category=r["category"], priority=r["priority"],
                         confidence=r["confidence"], sentiment=r["sentiment"], keywords=",".join(r["keywords"]),
                         is_anonymous=anonymous, attachment=path, student_id=user.id, lab_number=lab_number,
                         officer_id=officer.id if officer else None, escalation_level=1 if hod else 0,
                         status="Assigned" if handler else "Submitted",
                         sla_due=sla_due(r["priority"]), duplicate_of=dup.id if dup else None)
    if dup:
        dup.duplicate_count = (dup.duplicate_count or 0) + 1
    db.add(c); db.flush()
    c.code = f"CMP-{datetime.utcnow().year}-{c.id:05d}"
    db.add(models.StatusHistory(complaint_id=c.id, status=c.status, remarks="Auto-classified and routed", changed_by=user.id))
    audit(db, user.id, "COMPLAINT_SUBMITTED", f"{c.code} {c.category}/{c.priority}")
    new_msg = (f"New {c.priority} complaint {c.code} \"{c.title}\" ({c.category}{f', Lab {c.lab_number}' if c.lab_number else ''}) has been assigned to you. "
               f"Please solve it before {deadline_text(c)}, otherwise it will go to the HOD automatically.")
    new_subj = f"New {c.priority} complaint {c.code} - {c.title}"
    if hod:
        notify(db, hod, new_msg, new_subj)
    else:
        for person in (office_staff(db, c) or [handler]):
            notify(db, person, new_msg, new_subj)
    notify(db, user, f"Your complaint {c.code} ({c.title}) was received and routed to {handler.name if handler else 'admin'}")
    db.commit(); db.refresh(c)
    return to_dict(c, user)

@router.get("/my")
def my_complaints(user: models.User = Depends(require_role("student")), db: Session = Depends(get_db)):
    rows = db.query(models.Complaint).filter_by(student_id=user.id).order_by(models.Complaint.id.desc()).all()
    return [to_dict(c, user) for c in rows]

@router.get("/assigned")
def assigned(user: models.User = Depends(require_role("officer", "authority", "admin")), db: Session = Depends(get_db)):
    q = db.query(models.Complaint)
    if user.role == "officer":
        if user.department_id and (not user.department or user.department.name not in SPLIT_DEPTS):
            # Shared office (e.g. Timetable Coordinator): any officer in this department
            # sees every complaint assigned within it, not just the ones addressed to them.
            colleague_ids = [o.id for o in db.query(models.User)
                             .filter_by(role="officer", department_id=user.department_id).all()]
            q = q.filter(models.Complaint.officer_id.in_(colleague_ids))
        else:
            q = q.filter(models.Complaint.officer_id == user.id)
    elif user.role == "authority":
        q = q.filter(models.Complaint.escalation_level >= user.level)
    return [to_dict(c, user) for c in q.order_by(models.Complaint.id.desc()).all()]

def _can_manage(user, c):
    if user.role == "admin":
        return True
    if user.role == "authority":
        return c.escalation_level >= user.level
    if user.role == "officer":
        if c.officer_id == user.id:
            return True
        # Shared office: a colleague in the same non-split department can also act on it.
        if (c.officer and user.department_id and c.officer.department_id == user.department_id
                and (not user.department or user.department.name not in SPLIT_DEPTS)):
            return True
    return False

@router.patch("/{complaint_id}/status")
def update_status(complaint_id: int, data: schemas.StatusUpdateIn,
                  user: models.User = Depends(require_role("officer", "authority", "admin")), db: Session = Depends(get_db)):
    c = db.get(models.Complaint, complaint_id)
    if not c:
        raise HTTPException(404, "Complaint not found")
    if not _can_manage(user, c):
        raise HTTPException(403, "This complaint is not assigned to you")
    if data.status == "Query" and not (user.department and user.department.name == "Lab Assistant"):
        raise HTTPException(403, "Only the Lab Incharge can send a Query")
    c.status = data.status
    if data.status in ("Resolved", "Closed"):
        c.resolved_at = datetime.utcnow()
    db.add(models.StatusHistory(complaint_id=c.id, status=data.status, remarks=data.remarks, changed_by=user.id))
    audit(db, user.id, "STATUS_UPDATE", f"{c.code} -> {data.status}")
    notify(db, c.student, f"Your complaint {c.code} ({c.title}) is now '{data.status}'" + (f": {data.remarks}" if data.remarks else ""))
    db.commit(); db.refresh(c)
    return to_dict(c, user)

def _own(db, cid, user):
    c = db.get(models.Complaint, cid)
    if not c or c.student_id != user.id:
        raise HTTPException(404, "Complaint not found")
    return c

@router.post("/{complaint_id}/feedback")
def feedback(complaint_id: int, data: schemas.FeedbackIn, user: models.User = Depends(require_role("student")), db: Session = Depends(get_db)):
    c = _own(db, complaint_id, user)
    if c.status not in ("Resolved", "Closed"):
        raise HTTPException(400, "You can rate only after the complaint is resolved")
    if c.rating:
        raise HTTPException(400, "Feedback already submitted")
    c.rating, c.feedback = data.rating, (data.comment or "")[:500]
    audit(db, user.id, "FEEDBACK", f"{c.code} {data.rating}/5"); db.commit()
    return to_dict(c, user)

@router.post("/{complaint_id}/reopen")
def reopen(complaint_id: int, user: models.User = Depends(require_role("student")), db: Session = Depends(get_db)):
    c = _own(db, complaint_id, user)
    if c.status not in ("Resolved", "Closed"):
        raise HTTPException(400, "Only resolved complaints can be reopened")
    if c.resolved_at and datetime.utcnow() - c.resolved_at > timedelta(days=REOPEN_DAYS):
        raise HTTPException(400, f"Reopen window ({REOPEN_DAYS} days) has passed")
    c.status, c.resolved_at, c.sla_due = "Reopened", None, sla_due(c.priority)
    db.add(models.StatusHistory(complaint_id=c.id, status="Reopened", remarks="Reopened by student", changed_by=user.id))
    audit(db, user.id, "REOPEN", c.code)
    for person in office_staff(db, c):
        notify(db, person, f"Complaint {c.code} ({c.title}) was reopened by the student. New deadline: {deadline_text(c)}", f"Reopened: {c.code}")
    db.commit(); db.refresh(c)
    return to_dict(c, user)

@router.get("/{complaint_id}/attachment")
def attachment(complaint_id: int, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(models.Complaint, complaint_id)
    if not c or not c.attachment or not (c.student_id == user.id or _can_manage(user, c)):
        raise HTTPException(404, "Attachment not found")
    return FileResponse(c.attachment)
