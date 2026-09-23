@echo off
echo Starting CleanPixel...
cd /d "%~dp0backend"
start "" "http://localhost:8000"
python main.py
pause
