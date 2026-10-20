#!/bin/bash
# One-command start (Mac/Linux): sets up venv, trains model if missing, starts server
cd "$(dirname "$0")/backend"
[ -d venv ] || python3 -m venv venv
source venv/bin/activate
pip install -q -r requirements.txt
[ -f ../ml/model.joblib ] || (cd ../ml && python make_seed_data.py && python train.py)
echo "Open http://127.0.0.1:8000"
uvicorn app.main:app --reload
