import os, re
from typing import Optional
from pydantic import BaseModel, field_validator, model_validator

COLLEGE_DOMAIN = os.getenv("COLLEGE_DOMAIN", "mgmcen.ac.in")
# Student emails look like s23_deshmukh_rutuja@mgmcen.ac.in  (s + 2-digit admission year, then surname and first name)
STUDENT_EMAIL_RE = os.getenv("STUDENT_EMAIL_REGEX", r"s\d{2}_[a-z]+(?:_[a-z]+)+")
PW_RULE = r"(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^\w\s]).{8,64}"

# Class structure: SY and TY each have sections A/B/C, BTech (final year) only has A/B.
SECTIONS_BY_YEAR = {"SY": ["A", "B", "C"], "TY": ["A", "B", "C"], "BTech": ["A", "B"]}

# The "s23"/"s24"/"s25" prefix in a student's email is their ADMISSION year, not their
# current class - it doesn't change as they move up each year, so we derive their current
# class from it instead of trusting a dropdown. ACADEMIC_YEAR_START is "which admission
# year is currently in its 1st year" and needs bumping by one every time the next batch's
# classes roll over (once a year, e.g. every July/August) - a one-line env var change.
ACADEMIC_YEAR_START = int(os.getenv("ACADEMIC_YEAR_START", "2026"))
# years since admission -> current class. offset 0 (this year's freshers, "FY") isn't in
# this system yet; offset 4+ means they've already graduated.
YEAR_BY_ADMISSION_OFFSET = {1: "SY", 2: "TY", 3: "BTech"}

def year_from_email(email: str) -> Optional[str]:
    """s23_... -> admitted 2023 -> BTech (final year) in the 2026-27 academic year, etc."""
    m = re.match(r"s(\d{2})_", email.split("@")[0])
    if not m:
        return None
    admission_year = 2000 + int(m.group(1))
    return YEAR_BY_ADMISSION_OFFSET.get(ACADEMIC_YEAR_START - admission_year)

def _email(v: str) -> str:
    v = v.strip().lower()
    if not re.fullmatch(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", v):
        raise ValueError("Invalid email format")
    return v

def _password(v: str) -> str:
    if not re.fullmatch(PW_RULE, v):
        raise ValueError("Password needs 8+ chars with upper, lower, digit and special character")
    return v

class RegisterIn(BaseModel):
    name: str
    email: str
    password: str
    section: str            # A | B | C
    year: Optional[str] = None   # not supplied by the client - derived below from the email's admission code

    @field_validator("name")
    @classmethod
    def name_ok(cls, v):
        v = v.strip()
        if not (2 <= len(v) <= 60):
            raise ValueError("Name must be 2-60 characters")
        if not re.fullmatch(r"[A-Za-z][A-Za-z .'-]*", v):
            raise ValueError("Name can only contain letters, spaces, apostrophes and hyphens")
        return v

    @field_validator("email")
    @classmethod
    def email_ok(cls, v):
        v = _email(v)
        if not v.endswith("@" + COLLEGE_DOMAIN):
            raise ValueError(f"Use your college email (@{COLLEGE_DOMAIN})")
        if not re.fullmatch(STUDENT_EMAIL_RE, v.split("@")[0]):
            raise ValueError(f"Student email must look like s23_surname_firstname@{COLLEGE_DOMAIN}")
        return v

    _pw = field_validator("password")(classmethod(lambda cls, v: _password(v)))

    @model_validator(mode="after")
    def derive_year_and_check_section(self):
        year = year_from_email(self.email)
        if not year:
            raise ValueError("Your email's admission year doesn't match a currently active class (SY/TY/BTech). "
                              "If you've just joined (this year's admission), this system isn't open to your batch yet.")
        allowed = SECTIONS_BY_YEAR[year]
        sec = self.section.strip().upper()
        if sec not in allowed:
            raise ValueError(f"Your email shows you're in {year} - section must be one of {', '.join(allowed)}")
        self.year, self.section = year, sec
        return self

class ForgotIn(BaseModel):
    email: str

class ResetIn(BaseModel):
    email: str
    otp: str
    new_password: str
    _pw = field_validator("new_password")(classmethod(lambda cls, v: _password(v)))

class StatusUpdateIn(BaseModel):
    status: str
    remarks: Optional[str] = None

    @field_validator("status")
    @classmethod
    def status_ok(cls, v):
        if v not in ("In Progress", "Query", "Resolved", "Closed"):
            raise ValueError("Status must be In Progress, Query, Resolved or Closed")
        return v

    @field_validator("remarks")
    @classmethod
    def remarks_ok(cls, v):
        if v and len(v) > 500:
            raise ValueError("Remarks must be under 500 characters")
        return v

    @model_validator(mode="after")
    def query_needs_question(self):
        if self.status == "Query" and not (self.remarks and self.remarks.strip()):
            raise ValueError("Write your question for the student in Remarks when setting status to Query")
        return self

class FeedbackIn(BaseModel):
    rating: int
    comment: Optional[str] = None

    @field_validator("rating")
    @classmethod
    def rating_ok(cls, v):
        if not 1 <= v <= 5:
            raise ValueError("Rating must be 1 to 5")
        return v

class AssignIn(BaseModel):
    officer_id: int

class CreateUserIn(BaseModel):
    name: str
    email: str
    password: str
    role: str
    department_id: Optional[int] = None
    level: int = 0
    year: Optional[str] = None            # Class Incharge officer: which year they coordinate
    section: Optional[str] = None         # Class Incharge officer: which section they coordinate
    lab_numbers: Optional[str] = None     # Lab Assistant officer: comma separated lab numbers, e.g. "1,2,3,4"
    notify_email: Optional[str] = None    # REAL mailbox for email alerts (login email may be a placeholder)
    notify_name: Optional[str] = None     # name shown in the mail, e.g. "Ms Dumne Rakhi Shivajirao"

    @field_validator("role")
    @classmethod
    def role_ok(cls, v):
        if v not in ("officer", "authority", "admin"):
            raise ValueError("Role must be officer, authority or admin")
        return v

    @field_validator("email")
    @classmethod
    def email_ok(cls, v):
        return _email(v)

    @field_validator("year")
    @classmethod
    def year_ok(cls, v):
        if v is not None and v not in SECTIONS_BY_YEAR:
            raise ValueError(f"Year must be one of {', '.join(SECTIONS_BY_YEAR)}")
        return v

    @field_validator("section")
    @classmethod
    def section_ok(cls, v):
        if v is not None and v.strip().upper() not in ("A", "B", "C"):
            raise ValueError("Section must be A, B or C")
        return v.strip().upper() if v else v

    @field_validator("lab_numbers")
    @classmethod
    def lab_numbers_ok(cls, v):
        if v is None:
            return v
        nums = [n.strip() for n in v.split(",") if n.strip()]
        if not nums or not all(n.isdigit() and 1 <= int(n) <= 10 for n in nums):
            raise ValueError("lab_numbers must be a comma separated list of numbers 1-10, e.g. '1,2,3'")
        return ",".join(nums)

    _pw = field_validator("password")(classmethod(lambda cls, v: _password(v)))


class NotifyEmailIn(BaseModel):
    notify_email: Optional[str] = None    # empty / null = switch email alerts off for this person
    notify_name: Optional[str] = None


class ClassInchargeAssignIn(BaseModel):
    officer_id: int                       # the Class Incharge officer to put in charge of the class

class UpdateStaffIn(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    year: Optional[str] = None            # Class Incharge only: SY | TY | BTech
    section: Optional[str] = None         # Class Incharge only: A | B | C

    @field_validator("email")
    @classmethod
    def email_ok(cls, v):
        return _email(v) if v else v
