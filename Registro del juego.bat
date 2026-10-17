@echo off
rem Captura los mensajes internos del juego (por que no carga un escenario, regiones invalidas...).
rem Dejalo abierto, abre el juego, reproduce el problema y cierra esta ventana con Ctrl+C.
cd /d "%~dp0tools"
python game_log.py
pause
