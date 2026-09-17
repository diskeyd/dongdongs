# Installer. install.bat only starts this file: cmd mis-parses batch files that
# mix Korean text with a code page change, which broke the window on first use.
Set-Location -LiteralPath $PSScriptRoot

Write-Host '=========================================='
Write-Host ' dongdongs 설치'
Write-Host '=========================================='
Write-Host ''

$uv = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
if (-not (Test-Path -LiteralPath $uv)) {
    $found = Get-Command uv -ErrorAction SilentlyContinue
    if ($found) { $uv = $found.Source }
}
if (-not (Test-Path -LiteralPath $uv)) {
    Write-Host '[1/3] 실행 도구(uv)를 내려받습니다. 잠시 기다리세요...'
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $uv = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
}
if (-not (Test-Path -LiteralPath $uv)) {
    Write-Host ''
    Write-Host 'uv 설치에 실패했습니다. 인터넷 연결을 확인한 뒤 install.bat 을 다시 실행하세요.'
    Write-Host '계속 안 되면 README 의 "처음 쓸 때 - 순서와 보내 줄 것" 를 보세요.'
    exit 1
}

Write-Host '[2/3] 필요한 프로그램(파이썬 3.12 포함)을 설치합니다. 처음에는 몇 분 걸립니다...'
& $uv sync
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host '설치 중 오류가 났습니다. 위 메시지를 복사해 두고 README 의 "처음 쓸 때 - 순서와 보내 줄 것" 를 보세요.'
    exit 1
}

Write-Host '[3/3] 작업 폴더를 만듭니다...'
foreach ($folder in 'input', 'work', 'reports', 'logs') {
    if (-not (Test-Path -LiteralPath $folder)) { New-Item -ItemType Directory -Path $folder | Out-Null }
}
if (-not (Test-Path -LiteralPath 'dongdongs.env')) { Copy-Item 'dongdongs.env.example' 'dongdongs.env' }

Write-Host ''
Write-Host '설치가 끝났습니다.'
Write-Host ' - Gemini 키가 있으면 dongdongs.env 파일을 메모장으로 열어 GEMINI_API_KEY= 뒤에 붙여 넣으세요. (선택)'
Write-Host ' - 실행은 run.bat 을 더블클릭하세요.'
