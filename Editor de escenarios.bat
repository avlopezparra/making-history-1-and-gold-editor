@echo off
rem Editores de Making History: mapa (regiones) en http://localhost:8765 y escenarios en http://localhost:8765/escenario
cd /d "%~dp0tools"
start "" http://localhost:8765/escenario
python editor_server.py --no-abrir
pause
