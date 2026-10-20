import random
from datetime import datetime, timedelta
import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models, schemas
from ..security import hash_password, verify_password, create_token, current_user
from ..services import audit, send_email

router = APIRouter(prefix="/auth", tags=["Auth"])
MAX_FAILS, LOCK_MIN = 5, 15

@router.get("/config")
def config():
    return {"domain": schemas.COLLEGE_DOMAIN, "example": f"s23_surname_firstname@{schemas.COLLEGE_DOMAIN}",
            "sections_by_year": schemas.SECTIONS_BY_YEAR,
            "academic_year_start": schemas.ACADEMIC_YEAR_START,
            "year_by_admission_offset": schemas.YEAR_BY_ADMISSION_OFFSET}

@router.post("/register", status_code=201)
def register(data: schemas.RegisterIn, db: Session = Depends(get_db)):
    if db.query(models.User).filter_by(email=data.email).first():
        raise HTTPException(409, "Email already registered")
    db.add(models.User(name=data.name, email=data.email, password_hash=hash_password(data.password),
                       role="student", year=data.year, section=data.section))
    db.commit()
    return {"message": "Registered successfully"}

@router.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter_by(email=form.username.strip().lower()).first()
    if user and user.locked_until and user.locked_until > datetime.utcnow():
        raise HTTPException(423, "Account locked after too many failed attempts. Try again in 15 minutes")
    if not user or not verify_password(form.password, user.password_hash):
        if user:
            user.failed_attempts = (user.failed_attempts or 0) + 1
            if user.failed_attempts >= MAX_FAILS:
                user.locked_until = datetime.utcnow() + timedelta(minutes=LOCK_MIN)
                user.failed_attempts = 0
                audit(db, user.id, "ACCOUNT_LOCKED")
            db.commit()
        raise HTTPException(401, "Incorrect email or password")
    user.failed_attempts, user.locked_until = 0, None
    audit(db, user.id, "LOGIN"); db.commit()
    return {"access_token": create_token(user.id, user.role), "token_type": "bearer",
            "role": user.role, "name": user.name, "level": user.level,
            "department": user.department.name if user.department else None,
            "year": user.year, "section": user.section}

@router.get("/me")
def me(user: models.User = Depends(current_user)):
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role, "level": user.level,
            "department": user.department.name if user.department else None,
            "year": user.year, "section": user.section}

@router.post("/forgot")
def forgot(data: schemas.ForgotIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter_by(email=data.email.strip().lower()).first()
    resp = {"message": "If the email exists, an OTP has been sent"}     # same reply either way (no user enumeration)
    if user:
        otp = f"{random.SystemRandom().randint(0, 999999):06d}"
        user.otp_hash, user.otp_expires = hash_password(otp), datetime.utcnow() + timedelta(minutes=10)
        audit(db, user.id, "OTP_REQUESTED"); db.commit()
        send_email(user.email, "Password reset OTP", f"Your OTP is {otp}. Valid for 10 minutes.")
        if os.getenv("DEBUG_OTP", "1") == "1":
            resp["debug_otp"] = otp          # demo convenience only
    return resp

@router.post("/reset")
def reset(data: schemas.ResetIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter_by(email=data.email.strip().lower()).first()
    if not user or not user.otp_hash or user.otp_expires < datetime.utcnow() or not verify_password(data.otp, user.otp_hash):
        raise HTTPException(400, "Invalid or expired OTP")
    user.password_hash, user.otp_hash, user.otp_expires = hash_password(data.new_password), None, None
    user.failed_attempts, user.locked_until = 0, None
    audit(db, user.id, "PASSWORD_RESET"); db.commit()
    return {"message": "Password updated. Please log in."}
