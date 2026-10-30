@echo off
rem ---------------------------------------------------------------------------
rem sentinel_run.cmd -- one poll, then exit. This is what Task Scheduler runs.
rem All paths are derived from this file's own location, so nothing is
rem hard-coded (hard-coded paths are what broke v1 after a folder move).
rem ---------------------------------------------------------------------------
setlocal

rem === EDIT ME: the interpreter that runs sentinel.py (stdlib only, 3.8+) ===
set PY=C:\Python311\python.exe

set SCRIPT=%~dp0..\sentinel\sentinel.py
set LOGS=%~dp0..\logs
if not exist "%LOGS%" mkdir "%LOGS%"

rem HEARTBEAT FIRST: a fresh line here proves the task really started THIS file.
rem A stale heartbeat together with a fresh "Last Run Time" means the task was
rem launched but the body never executed -- that is exactly the symptom of the
rem LF + multi-line-block bug described in the tutorial.
rem NOTE: >> here and below. Using > would wipe the heartbeat we just wrote.
echo [%DATE% %TIME%] start >> "%LOGS%\sentinel_stdout.txt"

"%PY%" "%SCRIPT%" --once >> "%LOGS%\sentinel_stdout.txt" 2>&1
exit /b %ERRORLEVEL%
