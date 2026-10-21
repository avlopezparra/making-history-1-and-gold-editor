@echo off
rem Making History editors: map (regions) at http://localhost:8765 and scenarios at http://localhost:8765/scenario
cd /d "%~dp0tools"
start "" http://localhost:8765/scenario
python editor_server.py --no-abrir
pause
