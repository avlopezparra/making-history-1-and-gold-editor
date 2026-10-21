@echo off
rem Opens the editor in its own window (like a program), without browser bars.
cd /d "%~dp0tools"
start "" /min python editor_ventana.py mapa
