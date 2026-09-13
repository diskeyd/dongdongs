@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==========================================
echo  dongdongs 설치
echo ==========================================
echo.

set "UV=%USERPROFILE%\.local\bin\uv.exe"
if exist "%UV%" goto have_uv
where uv >nul 2>nul && set "UV=uv" && goto have_uv

echo [1/3] 실행 도구(uv)를 내려받습니다. 잠시 기다리세요...
powershell -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not exist "%UV%" (
    echo.
    echo uv 설치에 실패했습니다. 인터넷 연결을 확인한 뒤 install.bat 을 다시 실행하세요.
    echo 계속 안 되면 README 의 "처음 쓸 때 - 순서와 보내 줄 것" 를 보세요.
    pause
    exit /b 1
)

:have_uv
echo [2/3] 필요한 프로그램(파이썬 3.12 포함)을 설치합니다. 처음에는 몇 분 걸립니다...
"%UV%" sync
if errorlevel 1 (
    echo.
    echo 설치 중 오류가 났습니다. 위 메시지를 복사해 두고 README 의 "처음 쓸 때 - 순서와 보내 줄 것" 를 보세요.
    pause
    exit /b 1
)

echo [3/3] 작업 폴더를 만듭니다...
if not exist input mkdir input
if not exist work mkdir work
if not exist reports mkdir reports
if not exist logs mkdir logs
if not exist dongdongs.env copy dongdongs.env.example dongdongs.env >nul

echo.
echo 설치가 끝났습니다.
echo  - Gemini 키가 있으면 dongdongs.env 파일을 메모장으로 열어 GEMINI_API_KEY= 뒤에 붙여 넣으세요. (선택)
echo  - 실행은 run.bat 을 더블클릭하세요.
echo.
pause
