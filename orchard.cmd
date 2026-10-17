@echo off
rem Start Orchard in its own window, or point the running one at another folder: orchard.cmd [folder] [--browser]
rem Installs Python packages on first run, and again when requirements.txt changes.
setlocal
set "ROOT=%~dp0"
set "VENV=%ROOT%.venv"
call :installed || call :install || goto failed
rem -P and PYTHONPATH load Orchard from its own folder without changing directory, so a relative folder still works.
set "PYTHONPATH=%ROOT:~0,-1%"
"%VENV%\Scripts\python.exe" -P -m server.api --window %*
if errorlevel 1 goto failed
exit /b %errorlevel%

:installed
rem .installed is a copy of the requirements.txt that was installed.
fc /b "%ROOT%requirements.txt" "%VENV%\.installed" >nul 2>&1
exit /b

:install
rem A second launch waits here instead of installing into the same environment at the same time. The lock is an
rem open file, which Windows closes however this launch ends, so a stale lock can't remain. 3>&2 keeps stderr for
rem the install while 2>nul hides the message when the lock is taken.
set "FAILED="
3>&2 2>nul (9>"%ROOT%.venv.lock" (call :locked 2>&3 || set "FAILED=1")) || (
  rem With no lock file, nobody holds it: this folder can't be written to.
  if not exist "%ROOT%.venv.lock" echo Orchard can't write to its folder, "%ROOT%". Move it somewhere you can, like Documents.& exit /b 1
  if not defined WAITED echo Another Orchard launch is installing Python packages. Waiting for it to finish...
  set "WAITED=1"
  ping -n 3 127.0.0.1 >nul
  goto install
)
del "%ROOT%.venv.lock" 2>nul
if defined FAILED exit /b 1
exit /b 0

:locked
call :installed && exit /b 0
call :find_python || exit /b 1
rem A fresh environment each time, so packages that requirements.txt drops are removed too. pip's cache keeps
rem unchanged packages from downloading again.
%PYTHON% -m venv --clear "%VENV%" || (
  echo Orchard could not make its Python environment in "%VENV%". If Orchard is open, close it and try again.
  exit /b 1
)
echo Installing Python packages. The first run downloads about 90 MB, which takes about a minute.
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -r "%ROOT%requirements.txt" || exit /b 1
copy /y "%ROOT%requirements.txt" "%VENV%\.installed" >nul
exit /b

:find_python
rem ONNX Runtime has no packages for Python 3.15 yet. Keep these versions in step with orchard.
rem Python's newer install manager would otherwise download a missing version, out of sight, when asked for it.
set "PYTHON_MANAGER_AUTOMATIC_INSTALL=false"
for %%v in (3.13 3.12 3.14) do py -%%v -c "" <nul >nul 2>&1 && (set "PYTHON=py -%%v" & exit /b 0)
python -c "import sys; sys.exit(not (3, 12) <= sys.version_info < (3, 15))" <nul >nul 2>&1 && (set "PYTHON=python" & exit /b 0)
set "FOUND=no Python"
for /f "delims=" %%f in ('python --version 2^>nul') do set "FOUND=%%f"
for /f "delims=" %%f in ('py --version 2^>nul') do set "FOUND=%%f"
echo Orchard needs Python 3.12, 3.13 or 3.14, and found %FOUND%.
echo Install Python 3.13 with: winget install Python.Python.3.13
echo or from https://www.python.org/downloads/windows/. Then open a new Command Prompt and run Orchard again.
exit /b 1

:failed
rem Started by double-clicking, the window would close before the message could be read.
pause
exit /b 1
