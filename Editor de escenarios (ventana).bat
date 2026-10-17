@echo off
rem Abre el editor de escenarios en su propia ventana.
cd /d "%~dp0tools"
start "" /min python editor_ventana.py escenarios
