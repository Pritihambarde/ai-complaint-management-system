@echo off
setlocal
cd /d "%~dp0"
if not exist backend\requirements.txt (
  echo ERROR: Extract the ZIP fully first ^(right-click - Extract All^), then run run.bat from the extracted folder.
  pause
  exit /b 1
)
cd backend
if not exist venv python -m venv venv
call venv\Scripts\activate
python -m pip install -q -r requirements.txt
if not exist ..\ml\model.joblib (
  cd ..\ml
  python make_seed_data.py
  python train.py
  cd ..\backend
)
echo.
echo Open http://127.0.0.1:8000 in your browser  (Ctrl+C to stop)
python -m uvicorn app.main:app
pause
