@echo off
rem Opens the scenario editor in its own window.
cd /d "%~dp0tools"
start "" /min python editor_ventana.py escenarios
