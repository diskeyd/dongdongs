@echo off
rem Korean text lives in the .ps1 file: cmd mis-parses batch files that mix
rem Korean with a code page change, which closed the window on first use.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
echo.
pause
