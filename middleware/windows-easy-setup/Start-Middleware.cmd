@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

REM ფოლდერი სადაც ეს .cmd ფაილი ზის
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"

REM ლოკალური კონფიგი (არ უნდა ავიდეს Git-ზე — hrms-bridge.local.json .gitignore-შია)
set "CFG=%HERE%\hrms-bridge.local.json"
set "EXAMPLE=%HERE%\hrms-bridge.local.EXAMPLE.json"

if not exist "%CFG%" (
  echo პირველი გაშვება: ვქმნით hrms-bridge.local.json შაბლონიდან...
  copy /Y "%EXAMPLE%" "%CFG%" >nul
  echo.
  echo გახსენი Notepad და შეავსე:
  echo   - api_base_url  (მაგ. https://hr.itgs.ge)
  echo   - middleware_key (HRMS ^> Settings ^> Worksites ^& Middleware Keys ^> Create Key)
  echo.
  pause
  notepad "%CFG%"
)

REM EXE: იგივე ფოლდერში, ან რეპოს dist, ან ხელით განსაზღვრული ცვლადით
set "EXE=%HERE%\hrms-middleware-bridge.exe"
if not exist "!EXE!" set "EXE=%HERE%\..\..\dist\middleware\hrms-middleware-bridge.exe"
if defined HRMS_BRIDGE_EXE set "EXE=!HRMS_BRIDGE_EXE!"

if not exist "!EXE!" (
  echo [შეცდომა] hrms-middleware-bridge.exe ვერ მოიძებნა.
  echo დააკოპირე EXE აქ: %HERE%
  echo ან დააყენე ცვლადი: set HRMS_BRIDGE_EXE=C:\ბილდი\hrms-middleware-bridge.exe
  echo ან გაუშვი რეპოში: python scripts\build_middleware.py
  pause
  exit /b 1
)

echo გაშვება: "!EXE!" --config "%CFG%" heartbeat
echo.
"!EXE!" --config "%CFG%" heartbeat
set ERR=!errorlevel!
echo.
echo დასრულდა (კოდი !ERR!). თუ სერვისად გინდა — გამოიყენე NSSM (იხილე README_DEPLOY.md).
pause
exit /b !ERR!
