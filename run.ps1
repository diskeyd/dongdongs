# The wizard. run.bat only starts this file (see install.ps1 for why).
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

& $uv run dongdongs start
Write-Host ''
Write-Host '문제가 있었다면 report.bat 을 실행해 보고서 zip 을 만드세요.'
