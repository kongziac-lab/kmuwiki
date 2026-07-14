param(
  [string]$NasHost = "172.20.4.110",
  [string]$NasUser = "admin",
  [string]$RemoteDir = "/volume1/jdh/repo/deploy/hermes"
)

$ErrorActionPreference = "Stop"

Write-Host "Running Hermes final check on $NasUser@$NasHost ..."
Write-Host "You may be prompted for the NAS SSH password, then the sudo password."
Write-Host ""

ssh -t "$NasUser@$NasHost" "cd '$RemoteDir' && export HOME=/root && sh final-check-hermes.sh"

Write-Host ""
Write-Host "To inspect logs from Windows:"
Write-Host '  notepad "Y:\repo\deploy\hermes\logs\hermes-final-check.log"'
Write-Host '  notepad "Y:\repo\deploy\hermes\logs\hermes-status.log"'
