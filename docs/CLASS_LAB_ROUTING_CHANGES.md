# What changed: routing complaints to the right coordinator / lab incharge

Your college has multiple SY/TY/BTech sections (each with its own Class Incharge) and
10 labs shared across 3 Lab Assistants. The original system picked "the first officer in
that department" - fine with one coordinator, wrong with several. Here's everything that
was added to fix that, and where to find it.

## 1. Student's class is detected from their email, not typed in

A student's email prefix (`s23_`, `s24_`, `s25_...`) is their **admission year**, not
their current class - so instead of a Year dropdown that a student could fill in wrong,
the system works it out itself:

| Email prefix | Admitted | Current class (2026-27) |
|---|---|---|
| `s23_...` | 2023 | **BTech** (final year, sections A/B only) |
| `s24_...` | 2024 | **TY** (sections A/B/C) |
| `s25_...` | 2025 | **SY** (sections A/B/C) |

- Logic: `backend/app/schemas.py` -> `year_from_email()` and `ACADEMIC_YEAR_START`
  (currently `2026` - **bump this by 1 every year** when the next batch moves up; it's
  the only thing that needs manual updating).
- At registration the student only picks their **Section**; the server rejects it if
  that section doesn't exist for their detected year (e.g. BTech + section "C").
- Frontend: `frontend/index.html`, the `register` form shows the detected class
  read-only as soon as the email is typed (`onEmailChange()`).

## 2. Class Incharge is matched to the student's exact year+section

- `backend/app/models.py`: `User` gained `year` and `section` columns (used two ways -
  on a student, it's their class; on a Class Incharge officer, it's which class
  *they* coordinate).
- `backend/app/seed.py`: creates one coordinator per (year, section) combo -
  `coord_sy_a`, `coord_sy_b`, `coord_sy_c`, `coord_ty_a/b/c`, `coord_btech_a/b` - all
  password `Officer@123`.
- `backend/app/routes/complaints.py` -> `pick_officer()`: when a complaint is classified
  as "Teaching & Syllabus", it looks up the coordinator whose `year`+`section` matches
  the *submitting student's* `year`+`section`.

## 3. Lab Assistant is matched to the lab number, not just the department

- `backend/app/models.py`: `User.lab_numbers` (e.g. `"1,2,3,4"`) on a Lab Assistant
  officer; `Complaint.lab_number` on the complaint itself.
- `backend/app/seed.py`: 3 lab incharges - `labincharge1` (labs 1-4), `labincharge2`
  (labs 5-7), `labincharge3` (labs 8-10).
- Frontend: the complaint form (`frontend/index.html`, `studentView()`) has a **Lab
  number** dropdown (1-10, optional unless the category ends up lab-related).
- `pick_officer()` in `complaints.py` matches the submitted lab number against each
  incharge's `lab_numbers` to find the right one.

## 4. Officers can see who/where a complaint is from

- `to_dict()` in `complaints.py` now returns `student_class` (e.g. `"SY-A"`) and
  `lab_number` alongside every complaint.
- The staff dashboard card (`card()` in `index.html`) displays both, so a coordinator or
  lab incharge sees exactly which class/lab a complaint is about at a glance.

## 5. Category legend on the complaint form

- `studentView()` now shows a collapsible "What category will the AI pick?" legend with
  a one-line description of what each of the 8 categories covers (Teaching & Syllabus,
  Lab & Equipment, Classroom Infrastructure, Timetable & Attendance, Exams & Marks,
  Projects & Placements, Ragging & Harassment, Other). The AI still auto-detects the
  category from the title+description - this is just so students know what it's
  looking for.

## 6. Admin panel

- `backend/app/routes/admin.py`: creating a new officer now requires `year`+`section`
  if their department is "Class Incharge", or `lab_numbers` if it's "Lab Assistant" -
  you can't create one without saying which class/lab they own.
- `/admin/users` and `/admin/officers` now return `year`, `section`, `lab_numbers` so you
  can see the full mapping.

## Try it live

`docs/routing-preview.html` is a **self-contained interactive demo** (no server needed -
just open it in a browser) that walks through: typing an email and watching the class
get detected, submitting a complaint with a title/description/lab number, and seeing it
land in the correct officer's inbox with the full text attached.

## Tests

`backend/tests/test_api.py` was updated to match (uses `s25_...`/`s24_...` emails,
registers with `section` only, checks the rejection cases). All 8 tests pass:
`cd backend && pytest tests/test_api.py -q`

## 7. Wrong "Type of problem" is blocked (new)

If the description clearly belongs to a different type than the one selected (e.g. a lab
computer problem filed under "Classroom Infrastructure"), the complaint is **not submitted**.

- Frontend (`studentView()` in `index.html`): while typing, the form calls
  `POST /complaints/check-category`. If the AI is confident the text is, say, "Lab & Equipment",
  an orange warning appears, **every other type is disabled** except that one, and the
  Submit button is disabled until the right type is picked (or the description is edited).
- Backend (`submit()` in `routes/complaints.py`): the same check runs again on submit and
  returns a 422 with a clear message, so it can't be bypassed.
- Tuning: `MISMATCH_CONFIDENCE` in `backend/app/ml.py` (default 0.6). Raise it to block less often.
- If the AI is unsure, or the text is vague, nothing is blocked.
