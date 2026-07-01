$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$WebDir = Join-Path $Root "web"
$IngestDir = Join-Path $Root "ingest"
$PythonBin = Join-Path $IngestDir ".venv\Scripts\python.exe"
$NpmBin = "C:\Program Files\nodejs\npm.cmd"
$LogDir = Join-Path $env:LOCALAPPDATA "KMUWiki\logs"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Test-PortListening {
  param([int] $Port)

  $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  return $null -ne $connections
}

function Start-ApiServer {
  if (Test-PortListening -Port 8000) {
    "KMU Wiki API already listening on 8000"
    return
  }

  if (-not (Test-Path -LiteralPath $PythonBin)) {
    throw "Python virtualenv not found: $PythonBin"
  }

  Start-Process `
    -FilePath $PythonBin `
    -ArgumentList "-m uvicorn kmu_query.service:app --host 127.0.0.1 --port 8000" `
    -WorkingDirectory $IngestDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LogDir "api-server.log") `
    -RedirectStandardError (Join-Path $LogDir "api-server.err.log")

  "KMU Wiki API started on http://127.0.0.1:8000"
}

function Start-WebServer {
  if (Test-PortListening -Port 3000) {
    "KMU Wiki web already listening on 3000"
    return
  }

  if (-not (Test-Path -LiteralPath $NpmBin)) {
    throw "npm not found: $NpmBin"
  }

  Start-Process `
    -FilePath $NpmBin `
    -ArgumentList "run dev" `
    -WorkingDirectory $WebDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LogDir "web-server.log") `
    -RedirectStandardError (Join-Path $LogDir "web-server.err.log")

  "KMU Wiki web started on http://localhost:3000"
}

Start-ApiServer
Start-Sleep -Seconds 2
Start-WebServer
