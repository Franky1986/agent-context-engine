@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-monitor-windows.ps1" %*
exit /b %ERRORLEVEL%
