@echo off
rem ===== Job3: start the local financial-KB QA service =====
rem NOTE: keep this file pure ASCII (cmd.exe reads .cmd in the system ANSI codepage).
cd /d "%~dp0"
".venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8010
