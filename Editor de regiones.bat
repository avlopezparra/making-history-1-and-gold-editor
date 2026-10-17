@echo off
rem Editores de Making History: mapa (regiones) en http://localhost:8765 y escenarios en http://localhost:8765/escenario
cd /d "%~dp0tools"
python editor_server.py
pause
