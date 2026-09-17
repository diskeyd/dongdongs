# The error report. report.bat only starts this file (see install.ps1 for why).
Set-Location -LiteralPath $PSScriptRoot

$uv = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
if (-not (Test-Path -LiteralPath $uv)) {
    $found = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $found) {
        Write-Host '아직 설치되지 않았습니다. 먼저 install.bat 을 더블클릭하세요.'
        exit 1
    }
    $uv = $found.Source
}

& $uv run dongdongs report
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host '보고서를 만들지 못했습니다. logs 폴더의 run-*.log 파일을 직접 첨부해 주세요.'
    exit 1
}

Write-Host ''
Write-Host 'reports 폴더에 생긴 zip 파일을 GitHub Issue 에 끌어다 붙이세요. (README "처음 쓸 때 - 순서와 보내 줄 것" 참고)'
Start-Process explorer.exe (Join-Path $PSScriptRoot 'reports')
