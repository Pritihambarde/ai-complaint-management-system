from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from .database import Base

class Department(Base):
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="student")       # student | officer | authority | admin
    level = Column(Integer, default=0)             # authority: 1 = HOD, 2 = Principal
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    # class the person belongs to (student) or is responsible for (officer, role=Class Incharge)
    year = Column(String, nullable=True)           # SY | TY | BTech
    section = Column(String, nullable=True)        # A | B | C  (BTech only has A/B)
    # for an officer whose department is "Lab Assistant": which lab numbers they own, e.g. "1,2,3,4"
    lab_numbers = Column(String, nullable=True)
    failed_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)
    otp_hash = Column(String, nullable=True)
    otp_expires = Column(DateTime, nullable=True)
    # REAL mailbox used for email alerts. The login `email` can be a placeholder/fake address;
    # alerts go to notify_email, shown as: "notify_name <notify_email>".
    notify_email = Column(String, nullable=True)
    notify_name = Column(String, nullable=True)
    department = relationship("Department")

class Complaint(Base):
    __tablename__ = "complaints"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String)
    priority = Column(String)
    confidence = Column(Float)
    sentiment = Column(String)
    keywords = Column(String, default="")
    status = Column(String, default="Submitted")
    is_anonymous = Column(Boolean, default=False)
    attachment = Column(String, nullable=True)
    duplicate_of = Column(Integer, nullable=True)
    duplicate_count = Column(Integer, default=0)
    escalation_level = Column(Integer, default=0)
    sla_due = Column(DateTime, nullable=True)
    rating = Column(Integer, nullable=True)
    feedback = Column(Text, nullable=True)
    lab_number = Column(Integer, nullable=True)     # which of the 10 labs, when relevant
    student_id = Column(Integer, ForeignKey("users.id"))
    officer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    student = relationship("User", foreign_keys=[student_id])
    officer = relationship("User", foreign_keys=[officer_id])
    history = relationship("StatusHistory", back_populates="complaint", order_by="StatusHistory.id")

class StatusHistory(Base):
    __tablename__ = "status_history"
    id = Column(Integer, primary_key=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id"))
    status = Column(String)
    remarks = Column(Text, nullable=True)
    changed_by = Column(Integer, ForeignKey("users.id"), nullable=True)   # NULL = system
    changed_at = Column(DateTime, default=datetime.utcnow)
    complaint = relationship("Complaint", back_populates="history")

class Escalation(Base):
    __tablename__ = "escalations"
    id = Column(Integer, primary_key=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id"))
    to_level = Column(Integer)
    to_user_id = Column(Integer, ForeignKey("users.id"))
    reason = Column(String)
    at = Column(DateTime, default=datetime.utcnow)

class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    message = Column(String)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

# Note: the audit trail is no longer a SQL table. It's stored in MongoDB
# (see mongo.py / services.audit()) as a deliberate example of using a
# document database for an append-only, schema-flexible event log,
# alongside the relational database for everything with real relationships.
