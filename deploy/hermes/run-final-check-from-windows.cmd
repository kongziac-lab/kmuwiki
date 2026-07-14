@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-final-check-from-windows.ps1" %*
endlocal
