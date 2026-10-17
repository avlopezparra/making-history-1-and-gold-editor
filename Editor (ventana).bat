@echo off
rem Abre el editor en su propia ventana (como un programa), sin barras del navegador.
cd /d "%~dp0tools"
start "" /min python editor_ventana.py mapa
