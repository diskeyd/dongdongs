# Reports whether this PC can drive 한글 through COM. No report data in the output.
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

& $uv run dongdongs doctor
Write-Host ''
Write-Host '위 내용을 그대로 복사해 GitHub Issue 에 올려 주세요. (성적서·보고서 내용은 들어 있지 않습니다)'
