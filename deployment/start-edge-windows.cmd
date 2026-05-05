@echo off
setlocal

set ENV_FILE=%~1
if "%ENV_FILE%"=="" set ENV_FILE=.\deployment\edge.env.windows.example

powershell -ExecutionPolicy Bypass -File ".\deployment\start-edge-windows.ps1" -EnvFile "%ENV_FILE%"

endlocal
