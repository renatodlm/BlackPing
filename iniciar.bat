@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "%~dp0main.py"
  exit /b 0
)
where pyw >nul 2>&1 && start "" pyw "%~dp0main.py" && exit /b 0
where pythonw >nul 2>&1 && start "" pythonw "%~dp0main.py" && exit /b 0
python main.py
