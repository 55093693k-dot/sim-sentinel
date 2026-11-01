@echo off
rem ---------------------------------------------------------------------------
rem sentinel_run.cmd -- one poll, then exit. This is what Task Scheduler runs.
rem All paths are derived from this file's own location, so nothing is
rem hard-coded (hard-coded paths are what broke v1 after a folder move).
rem ---------------------------------------------------------------------------
setlocal

set SCRIPT=%~dp0..\sentinel\sentinel.py
set LOGS=%~dp0..\logs
if not exist "%LOGS%" mkdir "%LOGS%"

rem Interpreter: py -3 first (Windows launcher), then python on PATH.
rem To force one, put its full path on the next line instead of clearing PY.
rem If neither exists, leave a line in the log and fail with a non-zero code.
set "PY="
for /f "delims=" %%I in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do if not defined PY set "PY=%%I"
if not defined PY for /f "delims=" %%I in ('where python 2^>nul') do if not defined PY set "PY=%%I"
if not defined PY (
    echo [%DATE% %TIME%] ERROR python not found >> "%LOGS%\sentinel_stdout.txt"
    exit /b 9009
)

rem HEARTBEAT FIRST: a fresh line here proves the task really started THIS file.
rem A stale heartbeat together with a fresh "Last Run Time" means the task was
rem launched but the body never executed -- that is exactly the symptom of the
rem LF + multi-line-block bug described in the tutorial.
rem NOTE: >> here and below. Using > would wipe the heartbeat we just wrote.
echo [%DATE% %TIME%] start >> "%LOGS%\sentinel_stdout.txt"

"%PY%" "%SCRIPT%" --once >> "%LOGS%\sentinel_stdout.txt" 2>&1
exit /b %ERRORLEVEL%
