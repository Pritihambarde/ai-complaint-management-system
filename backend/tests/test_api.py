import os, tempfile
_db = tempfile.mktemp(suffix=".db")
os.environ.update(DATABASE_URL=f"sqlite:///{_db}", ESCALATION_INTERVAL="0", SLA_SCALE="1", DEBUG_OTP="1", ACADEMIC_YEAR_START="2026", IMAGE_RELEVANCE="off")

from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app import models

import pytest
from app import services

c = TestClient(app)

@pytest.fixture(autouse=True)
def _reset_rate_limit():
    services._hits.clear()
D = "@mgmcen.ac.in"

def photo_bytes(kind="photo", fmt="PNG", size=(320, 240)):
    """A generated test picture: 'photo' has real detail, 'blank' is one flat colour."""
    import io, random
    from PIL import Image
    im = Image.new("RGB", size, (255, 255, 255))
    if kind == "photo":
        rnd = random.Random(1)
        im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(size[0] * size[1])])
    b = io.BytesIO(); im.save(b, fmt); return b.getvalue()

def login(email, pw):
    r = c.post("/auth/login", data={"username": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}

def submit(h, desc, title="Problem report", category="Other", **kw):
    return c.post("/complaints", data={"title": title, "description": desc, "category": category, **kw}, headers=h)

def reg(**over):
    body = {"name": "Rahul", "email": "s25_patil_rahul" + D, "password": "Student@123", "section": "A"}
    body.update(over)
    return c.post("/auth/register", json=body)

def test_register_validation():
    assert c.post("/auth/register", json={"name": "A", "email": "x@gmail.com", "password": "weak", "section": "A"}).status_code == 422
    assert reg(password="weakpass").status_code == 422
    assert reg(email="rahul" + D).status_code == 422              # not the s23_surname_firstname pattern
    assert reg(email="s21_patil_rahul" + D).status_code == 422    # s21 has already graduated - no active class
    assert reg(email="s26_patil_rahul" + D).status_code == 422    # s26 is this year's freshers (FY) - not in this system yet
    assert reg(email="s23_gaikwad_om" + D, section="C").status_code == 422   # s23 = BTech, which only has A/B, not C
    assert reg().status_code == 201     # s25 = SY, section A
    assert reg().status_code == 409

def test_full_flow_and_rbac():
    s = login("s25_patil_rahul" + D, "Student@123")
    r = submit(s, "Senior students are threatening us in the hostel at night and forcing us to do their work", category="Ragging & Harassment").json()
    assert r["category"] == "Ragging & Harassment" and r["priority"] == "Critical" and r["assigned_to"] == "HOD"
    assert r["code"].startswith("CMP-") and r["keywords"]
    o = login("a_m_rajurkar" + D, "Mgm@123")
    assert len(c.get("/complaints/assigned", headers=o).json()) == 1
    assert c.patch(f"/complaints/{r['id']}/status", json={"status": "In Progress", "remarks": "Meeting today"}, headers=o).json()["status"] == "In Progress"
    lib = login("sangnor_suresh_nilkanthrao" + D, "Mgm@123")
    assert c.patch(f"/complaints/{r['id']}/status", json={"status": "Resolved"}, headers=lib).status_code == 403
    assert c.get("/complaints/assigned", headers=s).status_code == 403
    assert c.get("/analytics", headers=s).status_code == 403
    assert c.get("/complaints/my").status_code == 401
    n = c.get("/notifications", headers=s).json()
    assert any("In Progress" in x["message"] for x in n)

def test_validation_and_spam():
    s = login("s25_patil_rahul" + D, "Student@123")
    assert submit(s, "too short").status_code == 422
    assert submit(s, "asdfgh qwrtyp zxcvbn mnbvcx lkjhgf poiuyt").status_code == 422      # gibberish
    assert submit(s, "This teacher is a stupid idiot and nobody likes the class").status_code == 422
    bad = c.post("/complaints", data={"title": "Hello there", "description": "x" * 30}, files={"file": ("a.exe", b"MZ")}, headers=s)
    assert bad.status_code == 422
    fake = c.post("/complaints", data={"title": "Hello there", "description": "The CS lab has very few systems for our course"}, files={"file": ("a.pdf", b"not a pdf")}, headers=s)
    assert fake.status_code == 422

def test_anonymous_and_attachment():
    s = login("s25_patil_rahul" + D, "Student@123")
    r = c.post("/complaints", data={"title": "Lab computers problem", "description": "Computers in the CS lab are not working and the lab systems keep hanging", "anonymous": "true", "category": "Lab & Equipment", "lab_number": "1"},
               files={"file": ("p.png", photo_bytes())}, headers=s)
    assert r.status_code == 201, r.text
    o = login("sangnor_suresh_nilkanthrao" + D, "Mgm@123")
    seen = c.get("/complaints/assigned", headers=o).json()[0]
    assert seen["student_name"] == "Anonymous"
    assert c.get(f"/complaints/{seen['id']}/attachment", headers=o).status_code == 200
    assert c.get(f"/complaints/{seen['id']}/attachment", headers=login("v_s_jadhav" + D, "Mgm@123")).status_code == 404

def test_duplicates_feedback_reopen():
    s2 = None
    c.post("/auth/register", json={"name": "Sneha", "email": "s24_shinde_sneha" + D, "password": "Student@123", "section": "A"})
    s1, s2 = login("s25_patil_rahul" + D, "Student@123"), login("s24_shinde_sneha" + D, "Student@123")
    a = submit(s1, "Faculty is not completing the Data Structures syllabus and lectures are not conducted", category="Teaching & Syllabus").json()
    b = submit(s2, "The Data Structures faculty is not completing the syllabus and no lectures are conducted", category="Teaching & Syllabus").json()
    assert b["duplicate_of"] == a["id"]
    w = login("k_p_people" + D, "Mgm@123")   # Rahul is SY-A, so it's routed to the SY-A coordinator
    c.patch(f"/complaints/{a['id']}/status", json={"status": "Resolved"}, headers=w)
    assert c.post(f"/complaints/{a['id']}/feedback", json={"rating": 9}, headers=s1).status_code == 422
    assert c.post(f"/complaints/{a['id']}/feedback", json={"rating": 4, "comment": "ok"}, headers=s1).json()["rating"] == 4
    assert c.post(f"/complaints/{a['id']}/reopen", headers=s1).json()["status"] == "Reopened"
    assert c.post(f"/complaints/{b['id']}/feedback", json={"rating": 3}, headers=s2).status_code == 400   # not resolved

def test_escalation_chain():
    s = login("s25_patil_rahul" + D, "Student@123")
    r = submit(s, "Semester result is not declared and my exam marks are missing from the portal", category="Exams & Marks").json()
    adm = login("admin" + D, "Admin@123")
    for level, who in [(1, "HOD"), (2, "Principal")]:
        with SessionLocal() as db:
            db.get(models.Complaint, r["id"]).sla_due = datetime.utcnow() - timedelta(hours=1); db.commit()
        assert c.post("/admin/run-escalation", headers=adm).json()["escalated"] == 1
        d = [x for x in c.get("/complaints/my", headers=s).json() if x["id"] == r["id"]][0]
        assert d["status"] == "Escalated" and d["escalation_level"] == level
    with SessionLocal() as db:
        db.get(models.Complaint, r["id"]).sla_due = datetime.utcnow() - timedelta(hours=1); db.commit()
    assert c.post("/admin/run-escalation", headers=adm).json()["escalated"] == 0        # already at top
    p = login("principal" + D, "Officer@123")
    assert any(x["id"] == r["id"] for x in c.get("/complaints/assigned", headers=p).json())
    assert c.patch(f"/complaints/{r['id']}/status", json={"status": "Resolved", "remarks": "Marks corrected"}, headers=p).status_code == 200
    stats = c.get("/analytics", headers=adm).json()
    assert stats["total"] >= 4 and stats["escalated"] >= 1 and stats["by_category"]

def test_admin_and_lockout_and_reset():
    adm = login("admin" + D, "Admin@123")
    assert c.get("/admin/audit", headers=adm).json()
    assert c.post("/admin/users", json={"name": "New HOD", "email": "hod2" + D, "password": "Strong@123", "role": "authority", "level": 1}, headers=adm).status_code == 201
    for _ in range(5):
        c.post("/auth/login", data={"username": "s24_shinde_sneha" + D, "password": "wrong"})
    assert c.post("/auth/login", data={"username": "s24_shinde_sneha" + D, "password": "Student@123"}).status_code == 423
    otp = c.post("/auth/forgot", json={"email": "s24_shinde_sneha" + D}).json()["debug_otp"]
    assert c.post("/auth/reset", json={"email": "s24_shinde_sneha" + D, "otp": "000000", "new_password": "Newpass@123"}).status_code == 400
    assert c.post("/auth/reset", json={"email": "s24_shinde_sneha" + D, "otp": otp, "new_password": "Newpass@123"}).status_code == 200
    login("s24_shinde_sneha" + D, "Newpass@123")

def test_frontend_served():
    assert c.get("/").status_code == 200 and c.get("/health").json()["status"] == "ok"


# ---------- deadlines, HOD escalation, email alerts ----------
def test_deadline_days_per_priority():
    assert services.SLA_HOURS["Low"] == 72 and services.SLA_HOURS["Medium"] == 48
    assert services.SLA_HOURS["High"] == 24 and services.SLA_HOURS["Critical"] == 24

def test_timetable_complaint_emails_real_address_and_escalates_to_hod(monkeypatch):
    sent = []
    monkeypatch.setattr(services, "send_email", lambda to, subject, body: sent.append((to, subject, body)))
    s = login("s25_patil_rahul" + D, "Student@123")
    r = c.post("/complaints", data={"title": "Timetable clash", "category": "Timetable & Attendance",
               "description": "Our timetable has two subjects at the same time on Tuesday and nobody can attend both"}, headers=s)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    # mail goes to the REAL address in "Name <address>" form, never to the placeholder login address
    targets = [t for t, _, _ in sent]
    assert "Ms Dumne Rakhi Shivajirao <dumne_rs@mgmcen.ac.in>" in targets
    assert not any("r_s_dumne" in t for t in targets)
    login("dumne_rs" + D, "Mgm@123")                    # her login email is now the real address
    assert any("before" in b for _, _, b in sent)       # mail states the deadline

    # deadline missed -> escalated to the HOD, who is told
    db = SessionLocal()
    cm = db.get(models.Complaint, cid)
    cm.sla_due = datetime.utcnow() - timedelta(minutes=1); db.commit()
    assert services.run_escalation(db) >= 1
    db.refresh(cm)
    assert cm.escalation_level == 1 and cm.status == "Escalated"
    db.close()
    hod = login("a_m_rajurkar" + D, "Mgm@123")
    assert any(x["id"] == cid for x in c.get("/complaints/assigned", headers=hod).json())

def test_admin_can_set_alert_email():
    a = login("admin" + D, "Admin@123")
    uid = next(u["id"] for u in c.get("/admin/users", headers=a).json() if u["email"] == "a_m_rajurkar" + D)
    assert c.patch(f"/admin/users/{uid}/notify-email", json={"notify_email": "bad"}, headers=a).status_code == 422
    assert c.patch(f"/admin/users/{uid}/notify-email", json={"notify_email": "hod.test@mgmcen.ac.in", "notify_name": "Dr. A. M. Rajurkar"}, headers=a).status_code == 200


def test_lab_complaint_needs_lab_number_and_routes_by_it():
    s = login("s25_patil_rahul" + D, "Student@123")
    base = {"title": "Lab systems problem", "category": "Lab & Equipment",
            "description": "Computers in the lab are not starting and the systems keep hanging during practicals"}
    r = c.post("/complaints", data=base, headers=s)
    assert r.status_code == 422 and "lab number" in r.json()["detail"].lower()
    assert c.post("/complaints", data={**base, "lab_number": "11"}, headers=s).status_code == 422
    r = c.post("/complaints", data={**base, "lab_number": "5"}, headers=s)
    assert r.status_code == 201, r.text
    assert r.json()["lab_number"] == 5 and r.json()["assigned_to"] == "Prashant Kishanrao Deshmukh"   # labs 4,5,6
    # non-lab complaints don't need (and ignore) a lab number
    r = c.post("/complaints", data={"title": "Timetable clash again", "category": "Timetable & Attendance", "lab_number": "3",
               "description": "Our timetable has two subjects at the same time on Wednesday and nobody can attend both"}, headers=s)
    assert r.status_code == 201 and r.json()["lab_number"] is None


def test_wrong_problem_type_is_blocked():
    s = login("s25_patil_rahul" + D, "Student@123")
    lab_text = "Computers in the lab are not working, system does not start and software is missing"
    # lab issue filed under Classroom Infrastructure -> rejected, tells the student the right type
    r = submit(s, lab_text, category="Classroom Infrastructure")
    assert r.status_code == 422 and "Lab & Equipment" in r.json()["detail"]
    assert submit(s, lab_text, category="Teaching & Syllabus").status_code == 422
    # live-check endpoint used by the form
    chk = c.post("/complaints/check-category", data={"title": "Lab problem", "description": lab_text}, headers=s).json()
    assert chk["suggested"] == "Lab & Equipment"
    # same text under the right type goes through
    assert submit(s, lab_text, category="Lab & Equipment", lab_number="2").status_code == 201
    # vague text never blocks
    assert c.post("/complaints/check-category", data={"title": "x", "description": "short"}, headers=s).json()["suggested"] is None


def test_blank_and_bad_pictures_rejected():
    s = login("s25_patil_rahul" + D, "Student@123")
    data = {"title": "Lab computers problem", "description": "Computers in the CS lab are not working and the lab systems keep hanging",
            "category": "Lab & Equipment", "lab_number": "1"}
    for name, blob in [("blank.png", photo_bytes("blank")), ("tiny.png", photo_bytes("photo", size=(40, 40))),
                       ("empty.png", b""), ("fake.png", b"\x89PNG\r\n" + b"0" * 50)]:
        r = c.post("/complaints", data=data, files={"file": (name, blob)}, headers=s)
        assert r.status_code == 422, (name, r.text)
        assert "Attachment" in r.json()["detail"] or "File" in r.json()["detail"], (name, r.text)

def test_picture_must_match_problem_type(monkeypatch):
    from app import image_check
    monkeypatch.setenv("IMAGE_RELEVANCE", "clip")
    s = login("s25_patil_rahul" + D, "Student@123")
    data = {"title": "Lab computers problem", "description": "Computers in the CS lab are not working and the lab systems keep hanging",
            "category": "Lab & Equipment", "lab_number": "1"}
    scores = {"lab": 0.02, "classroom": 0.03, "documents": 0.05, "unrelated": 0.90}      # e.g. a selfie
    monkeypatch.setattr(image_check, "group_scores", lambda img: scores)
    r = c.post("/complaints", data=data, files={"file": ("a.png", photo_bytes())}, headers=s)
    assert r.status_code == 422 and "lab or computer" in r.json()["detail"], r.text
    scores.update(lab=0.80, unrelated=0.12)                                                  # e.g. a keyboard / mouse
    r = c.post("/complaints", data=data, files={"file": ("a.png", photo_bytes())}, headers=s)
    assert r.status_code == 201, r.text
