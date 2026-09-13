@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not exist "%UV%" set "UV=uv"
"%UV%" --version >nul 2>nul
if errorlevel 1 (
    echo 아직 설치되지 않았습니다. 먼저 install.bat 을 더블클릭하세요.
    pause
    exit /b 1
)
"%UV%" run dongdongs start
echo.
echo 문제가 있었다면 report.bat 을 실행해 보고서 zip 을 만드세요.
pause
