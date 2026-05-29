@echo off
REM Launches Don't Seat 1h in the background (no console window).
cd /d "%~dp0"
set PYTHONPATH=%~dp0src
set "PYTHONW="
for /f "usebackq delims=" %%P in (`py -3.12 -c "import pathlib, sys; print(pathlib.Path(sys.executable).with_name('pythonw.exe'))"`) do set "PYTHONW=%%P"

if not exist "%PYTHONW%" (
	echo Could not find Python 3.12 pythonw.exe. Please install Python 3.12 or update run.bat.
	exit /b 1
)

start "" "%PYTHONW%" -m dont_seat
