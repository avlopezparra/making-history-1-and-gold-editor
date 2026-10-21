@echo off
rem Captures the game's internal messages (why a scenario does not load, invalid regions...).
rem Leave it open, start the game, reproduce the problem and close this window with Ctrl+C.
cd /d "%~dp0tools"
python game_log.py
pause
