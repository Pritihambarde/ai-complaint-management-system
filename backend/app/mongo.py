"""MongoDB connection for the audit trail (kept separate from the main SQL database
on purpose, to demonstrate using a NoSQL store where it fits: an append-only,
schema-flexible event log)."""
import os
from pymongo import MongoClient

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB", "complaints_system")

_client = None

def get_mongo_db():
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=3000)
    return _client[MONGO_DB_NAME]

def audit_collection():
    return get_mongo_db()["audit_logs"]
