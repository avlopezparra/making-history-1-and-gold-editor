@echo off
rem Compila MHEditor.exe (carpeta MHEditor\). Requiere Python 3.12 o superior.
cd /d "%~dp0"
python -m pip install -r requirements.txt
python tools\build_exe.py
pause
