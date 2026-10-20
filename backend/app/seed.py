from .database import SessionLocal
from . import models
from .schemas import COLLEGE_DOMAIN
from .security import hash_password

# Password for every real-staff login below. NOTE: "Mgm@123" is only 7 characters and does
# NOT satisfy the app's own password-strength rule (schemas.PW_RULE needs 8-64 chars with
# upper/lower/digit/special). It works fine as a seeded login, but if any of these people
# ever use "forgot password" to reset it through the site, the new password they pick will
# have to meet that rule - the seeded one bypasses it. Swap this constant if that's a problem.
STAFF_PASSWORD = "Mgm@123"

DEPTS = ["Lab Assistant", "Class Incharge", "Timetable Coordinator", "Exam Coordinator",
         "Project Placement Cell", "Admin Desk", "Departmental Coordinator"]

# --- Confirmed real staff (name, email-local-part, ...) -------------------------------
# Lab assistants: 4 people covering 10 labs between them (confirmed split 1-3 / 4-6 / 7-8 / 9-10).
LAB_ASSISTANTS = [
    ("Sangnor Suresh Nilkanthrao", "sangnor_suresh_nilkanthrao", "1,2,3"),
    ("Prashant Kishanrao Deshmukh", "prashant_kishanrao_deshmukh", "4,5,6"),
    ("Nirmale Pooja Kour Surjeet Singh", "nirmale_pooja_kour_surjeet_singh", "7,8"),
    ("Vaidya Madhav", "vaidya_madhav", "9,10"),
]

# Class Incharges: one per (year, section), confirmed.
CLASS_INCHARGES = {
    ("SY", "A"): ("K. P. People", "k_p_people"),
    ("SY", "B"): ("S. S. Wagre", "s_s_wagre"),
    ("SY", "C"): ("M. H. Khan", "m_h_khan"),
    ("TY", "A"): ("P. S. Bihade", "p_s_bihade"),
    ("TY", "B"): ("D. B. Aghor", "d_b_aghor"),
    ("TY", "C"): ("Sayed Ateeq B", "sayed_ateeq_b"),
    ("BTech", "A"): ("M. R. Chennoji", "m_r_chennoji"),
    ("BTech", "B"): ("M. G. Shelke", "m_g_shelke"),
}

# Project Incharges: only these two confirmed (BTech A/B). SY/TY project incharges are
# still pending, so those students' "Projects & Placements" complaints fall back to the
# generic Training & Placement officer (see pick_officer in routes/complaints.py).
PROJECT_INCHARGES = [
    ("Nitu L. Pariyal", "nitu_l_pariyal", "BTech", "A"),
    ("Wahi G. S.", "wahi_g_s", "BTech", "B"),
]

# Exam Coordinator: confirmed as Jadhav ("Central Test Coordinator" in the college's own
# wording - there's no separate office/category for that in this system, so he's seeded
# as the Exam Coordinator, the office the "Exams & Marks" category routes to).
EXAM_COORDINATOR = ("V. S. Jadhav", "v_s_jadhav")

# Timetable Coordinator: confirmed as these three people, but no split between them was
# given (unlike Class Incharge/Lab Assistant, which split by class/lab). Without a split,
# pick_officer now sends EVERY "Timetable & Attendance" complaint to Ms Dumne
# (dumne_rs@mgmcen.ac.in) and only she gets the alert mail; Bhandare and Naik stay as users.
TIMETABLE_COORDINATORS = [
    ("M. N. Bhandare", "m_n_bhandare"),
    ("R. S. Dumne", "r_s_dumne"),
    ("D. S. Naik", "d_s_naik"),
]

# --- REAL mailboxes ------------------------------------------------------------------------
# "login-slug": ("Name shown in the email", "real address").
# That person's login email is REPLACED by the real address (password stays the same), and
# alerts are mailed to:  Ms Dumne Rakhi Shivajirao <dumne_rs@mgmcen.ac.in>
# Nobody else is touched; routing of complaints is exactly as before.
REAL_CONTACTS = {
    "r_s_dumne": ("Ms Dumne Rakhi Shivajirao", "dumne_rs@mgmcen.ac.in"),
}

def apply_real_contacts(db):
    for slug, (display, real) in REAL_CONTACTS.items():
        u = db.query(models.User).filter(models.User.email.in_([f"{slug}@{COLLEGE_DOMAIN}", real])).first()
        if u:
            u.email, u.notify_email, u.notify_name = real, real, display
    db.commit()

def seed():
    """
    A student's own year+section (set at registration) is matched against a Class Incharge's
    or Project Incharge's year+section to find the right person; a complaint's lab_number is
    matched against a Lab Assistant's lab_numbers to find the right incharge.

    STILL PENDING confirmation from the user (kept as a generic placeholder below, password
    Officer@123, until real name/email is provided):
      - Admin Desk ("Other" complaints), Principal.
      - Whether Ms. Panchal S. / Ms. Shiledar J.T. are Project Incharges for SY/TY sections
        (for now, Project Incharge is only Pariyal/BTech-A and Wahi/BTech-B).
      - A split rule for the 3 Timetable Coordinators (Bhandare/Dumne/Naik), if one is wanted.
    """
    db = SessionLocal()
    if db.query(models.Department).count() == 0:
        dept_by_name = {}
        for name in DEPTS:
            d = models.Department(name=name); db.add(d); db.flush()
            dept_by_name[name] = d

        for full_name, slug, labs in LAB_ASSISTANTS:
            db.add(models.User(name=full_name, email=f"{slug}@{COLLEGE_DOMAIN}",
                               password_hash=hash_password(STAFF_PASSWORD), role="officer",
                               department_id=dept_by_name["Lab Assistant"].id, lab_numbers=labs))

        for (year, sec), (full_name, slug) in CLASS_INCHARGES.items():
            db.add(models.User(name=full_name, email=f"{slug}@{COLLEGE_DOMAIN}",
                               password_hash=hash_password(STAFF_PASSWORD), role="officer",
                               department_id=dept_by_name["Class Incharge"].id, year=year, section=sec))

        for full_name, slug, year, sec in PROJECT_INCHARGES:
            db.add(models.User(name=full_name, email=f"{slug}@{COLLEGE_DOMAIN}",
                               password_hash=hash_password(STAFF_PASSWORD), role="officer",
                               department_id=dept_by_name["Project Placement Cell"].id, year=year, section=sec))

        # Training & Placement: generic officer, no year/section - the fallback for SY/TY
        # project complaints, and general placement queries, until more incharges are confirmed.
        db.add(models.User(name="S. I. Titre", email=f"s_i_titre@{COLLEGE_DOMAIN}",
                           password_hash=hash_password(STAFF_PASSWORD), role="officer",
                           department_id=dept_by_name["Project Placement Cell"].id))

        # Departmental Coordinator (confirmed).
        db.add(models.User(name="Dr. Mrs. M.Y. Joshi", email=f"m_y_joshi@{COLLEGE_DOMAIN}",
                           password_hash=hash_password(STAFF_PASSWORD), role="officer",
                           department_id=dept_by_name["Departmental Coordinator"].id))

        # Exam Coordinator (confirmed: Jadhav / "Central Test Coordinator").
        name, slug = EXAM_COORDINATOR
        db.add(models.User(name=name, email=f"{slug}@{COLLEGE_DOMAIN}",
                           password_hash=hash_password(STAFF_PASSWORD), role="officer",
                           department_id=dept_by_name["Exam Coordinator"].id))

        # Timetable Coordinator (confirmed: Bhandare, Dumne, Naik - see note above re: no split).
        for name, slug in TIMETABLE_COORDINATORS:
            db.add(models.User(name=name, email=f"{slug}@{COLLEGE_DOMAIN}",
                               password_hash=hash_password(STAFF_PASSWORD), role="officer",
                               department_id=dept_by_name["Timetable Coordinator"].id))

        # --- Still pending confirmation: kept as a generic placeholder (password Officer@123) ---
        for name in ["Admin Desk"]:
            slug = name.lower().replace(" ", "").replace("-", "")
            db.add(models.User(name=name, email=f"{slug}@{COLLEGE_DOMAIN}", password_hash=hash_password("Officer@123"),
                               role="officer", department_id=dept_by_name[name].id))

        # HOD confirmed (Rajurkar); Principal still pending confirmation.
        db.add(models.User(name="Dr. A.M. Rajurkar", email=f"a_m_rajurkar@{COLLEGE_DOMAIN}",
                           password_hash=hash_password(STAFF_PASSWORD), role="authority", level=1))
        db.add(models.User(name="Principal", email=f"principal@{COLLEGE_DOMAIN}",
                           password_hash=hash_password("Officer@123"), role="authority", level=2))

        db.add(models.User(name="System Admin", email=f"admin@{COLLEGE_DOMAIN}", password_hash=hash_password("Admin@123"), role="admin"))
        db.add(models.User(name="Demo Student", email=f"s25_demo_student@{COLLEGE_DOMAIN}", password_hash=hash_password("Student@123"),
                           role="student", year="SY", section="A"))
        db.commit()
    apply_real_contacts(db)
    db.close()
