$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$ingest = Join-Path $root "ingest"
$python = Join-Path $ingest ".venv-visual\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python visual environment not found: $python"
}

Push-Location $ingest
try {
    & $python -m kmu_ingest.cli retention-cleanup
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
