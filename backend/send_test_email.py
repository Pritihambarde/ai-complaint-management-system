"""Check that email alerts really work.   Run from the backend folder:

    python send_test_email.py                      -> sends to Ms Dumne's real address
    python send_test_email.py someone@mgmcen.ac.in -> sends to any address you give

It reads SMTP_* from .env and prints the exact error if the mail server refuses.
"""
import os, sys
from dotenv import load_dotenv
load_dotenv()
from email.utils import formataddr
from app import services

if not os.getenv("SMTP_HOST") or not os.getenv("SMTP_PASS"):
    sys.exit("SMTP_HOST / SMTP_USER / SMTP_PASS are not filled in backend/.env yet - see README 'Email alerts'.")

to = sys.argv[1] if len(sys.argv) > 1 else formataddr(("Ms Dumne Rakhi Shivajirao", "dumne_rs@mgmcen.ac.in"))
print("Sending test mail to:", to)
services._smtp_send(to, "Complaint System - test email",
                    "If you can read this, email alerts from the Complaint System are working.")
