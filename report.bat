@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not exist "%UV%" set "UV=uv"
"%UV%" run dongdongs report
if errorlevel 1 (
    echo.
    echo 보고서를 만들지 못했습니다. logs 폴더의 run-*.log 파일을 직접 첨부해 주세요.
    pause
    exit /b 1
)
echo.
echo reports 폴더에 생긴 zip 파일을 GitHub Issue 에 끌어다 붙이세요. (README "처음 쓸 때 - 순서와 보내 줄 것" 참고)
start "" explorer "%~dp0reports"
pause
