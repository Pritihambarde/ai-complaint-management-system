# AI Complaint Classification & Escalation System — Computer Science Department

Students of the CS department write a complaint in plain words. The system **classifies** it (NLP), sets its **priority**,
**routes** it to the right coordinator, and **auto-escalates** it (Departmental -> HOD -> Principal) if the deadline is missed.

## Run it (Windows)
```
cd backend
python -m pip install -r requirements.txt      (first time only)
python -m uvicorn app.main:app
```
Open **http://127.0.0.1:8000**. On the first start the AI model trains itself (a few seconds) and matches your scikit-learn version.
If port 8000 is busy, add `--port 8001`. Run the tests with `python -m pytest tests`.

## Databases used (SQL + NoSQL)
This project deliberately uses **two databases**, each for what it's good at:

| Database | What it stores | Why |
|---|---|---|
| **SQL** — SQLite by default, or MySQL/PostgreSQL if you set `DATABASE_URL` | Users, Complaints, Departments, Notifications, Status history | This data has clear relationships (a Complaint belongs to a Student, is handled by an Officer, etc.) — a relational database enforces that. |
| **MongoDB** — set `MONGO_URL` (defaults to `mongodb://localhost:27017`) | The **audit log** (who did what, when — login, escalation, status changes) | This is just a growing stream of one-off event records with no relationships to enforce, and its shape can change over time — a good fit for a document database. |

**To see the SQL database:** open `backend/complaints.db` with [DB Browser for SQLite](https://sqlitebrowser.net/) (default), or `complaints_db` in phpMyAdmin if you switched to MySQL.

**To see MongoDB:** install [MongoDB Community Server](https://www.mongodb.com/try/download/community) (or run `docker run -d -p 27017:27017 mongo`), then open it with [MongoDB Compass](https://www.mongodb.com/products/compass) — database `complaints_system`, collection `audit_logs`. Every login, status update, and escalation appears there as a JSON document in real time. The app still runs fine even if MongoDB isn't running — only the admin dashboard's "Audit log" panel needs it.

## Who handles what
| Category (AI decides) | Goes to | Login email |
|---|---|---|
| Lab & Equipment | Lab Assistant (by lab number) | labincharge@mgmcen.ac.in |
| Classroom Infrastructure | Class Incharge of the student's own class | - |
| Teaching & Syllabus | Class Incharge | classcoordinator@mgmcen.ac.in |
| Timetable & Attendance | Timetable Coordinator | timetablecoordinator@mgmcen.ac.in |
| Exams & Marks | Exam Coordinator | examcoordinator@mgmcen.ac.in |
| Projects & Placements | Project Placement Cell | projectplacementcell@mgmcen.ac.in |
| Other / AI unsure (< 35% confident) | Admin Desk | admindesk@mgmcen.ac.in |
| Ragging & Harassment | **HOD directly** (always Critical) | hod@mgmcen.ac.in |

All departmental logins use password `Officer@123`.

## Demo logins (created on first run)
| Role | Email | Password |
|---|---|---|
| Student (demo) | s23_demo_student@mgmcen.ac.in | Student@123 |
| Departmental staff (login via **Departmental Login**) | see the table above | Officer@123 |
| HOD (Level 1) | hod@mgmcen.ac.in | Officer@123 |
| Principal (Level 2) | principal@mgmcen.ac.in | Officer@123 |
| Admin | admin@mgmcen.ac.in | Admin@123 |

Students register themselves with their college email in the form `s23_surname_firstname@mgmcen.ac.in` (for example `s23_deshmukh_rutuja@mgmcen.ac.in`; `s22`, `s24` ... also work). Officers, HOD and Principal cannot self-register: the **Admin creates them**
(Admin dashboard -> Create staff account). Officers see their department in the header, for example "Departmental · Lab Assistant".

**Use your real college domain:** `set COLLEGE_DOMAIN=yourmgmcen.ac.in`, then delete `backend\complaints.db` and restart.

## Live escalation demo
```
set SLA_SCALE=0.0005
set ESCALATION_INTERVAL=15
python -m uvicorn app.main:app
```
Submit a Critical complaint (for example a lab problem containing the word "unsafe") and do not resolve it. About a minute later it moves to the HOD, then the Principal.
Ragging complaints start at the HOD and escalate to the Principal. You can also press "Run escalation check now" on the admin dashboard.

## Features
- Auth: college-domain registration, bcrypt hashing, JWT expiry, role checks on every API, lockout (5 fails / 15 min), forgot/reset password with OTP
- AI: TF-IDF + Logistic Regression category, hybrid priority (safety keyword rules), sentiment, explainable key terms, low-confidence triage, spam/abuse filter, duplicate detection
- Lab complaints must state the lab number (1-10); it decides which Lab Assistant receives them
- Complaint lifecycle: anonymous option, evidence upload (jpg/png/pdf), status history, rating, reopen within 7 days
- Deadlines: Low = 3 days, Medium = 2 days, High/serious = 1 day (Critical = 1 day). Not solved in time -> auto-escalated to the HOD (then Principal), background scheduler, full history
- Notifications: in-app + real email alerts (see below)

## Email alerts (staff do not need to log in)
Ms Dumne's login email is now her real address `dumne_rs@mgmcen.ac.in` (same password); everyone else keeps their existing login. Alerts go to her as
`Ms Dumne Rakhi Shivajirao <dumne_rs@mgmcen.ac.in>`. A mail is sent when a complaint is assigned, reopened, or escalated after a missed deadline.
1. Real addresses live in `REAL_CONTACTS` in `backend/app/seed.py` (one line per person), or set them in **Admin -> Users -> set/change**.
2. Fill `SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS` in `backend/.env` (Gmail/Google Workspace needs an *App Password*). Until then mails are only printed in the server window.
   Then check it with `python send_test_email.py` (run in `backend`) - it prints the exact error if the mail server refuses.
3. **All Timetable & Attendance complaints go only to Ms Dumne** and are emailed to `dumne_rs@mgmcen.ac.in`. People without a real address get in-app alerts only.
- Analytics, audit log, rate limiting

## Before a real deployment
Set `SECRET_KEY`, `DEBUG_OTP=0` and `DEBUG_ERRORS=0` (see `backend/.env.example`).

## Folders
`backend/app` server code | `backend/tests` 8 automated tests | `ml/` dataset, training script, confusion matrix | `frontend/index.html` web app | `docs/REPORT.md` report and viva answers


## Evidence pictures (photo / PDF upload)

Students can attach a photo or PDF to a complaint. The server checks it before the complaint is saved:

- it must be a real, readable JPG, PNG or PDF (not damaged, not tiny, max 5 MB);
- **blank images / blank PDFs are rejected**;
- the picture must be **related to the chosen problem type**: a *Lab & Equipment* complaint only accepts computer-lab pictures
  (computer, monitor, keyboard, mouse, printer, error screenshot...), *Classroom Infrastructure* accepts projector, fan, light, bench,
  board, washroom etc.; document-type complaints (timetable, exams, teaching, projects) accept documents and screenshots.
  *Ragging & Harassment* and *Other* only get the real / not-blank checks, because proof for those can be anything.

Relevance uses the free CLIP model (`backend/app/image_check.py`). Run `pip install -r requirements.txt` once; the first server start
downloads about 600 MB. In `backend/.env` you can set `IMAGE_RELEVANCE=off` to keep only the real / not-blank checks.
If the model is not installed, uploads are refused with a clear message instead of being accepted unchecked.
