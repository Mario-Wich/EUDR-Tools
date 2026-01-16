
@echo off
SETLOCAL
REM Change to this script folder (.App)
cd /d "%~dp0"

REM Per-user virtual environment
set VENV=%USERPROFILE%\.venvs\eudr-tools
if not exist "%VENV%" (
  python -m venv "%VENV%"
)
call "%VENV%\Scripts\activate"

pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

start "" http://localhost:8501/
streamlit run app.py

ENDLOCAL
