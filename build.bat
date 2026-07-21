@echo off
REM ===================================================================
REM PCIS - build the Windows executable  (Step 3)
REM
REM   build.bat            build
REM   build.bat --no-test  skip the test suite (not for releases)
REM
REM Creates a venv if needed, installs dependencies, freezes the app,
REM then removes intermediates. Must run on Windows: PyInstaller does
REM not cross-compile.
REM ===================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo === PCIS Windows build ===

REM --- Python present? -----------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found on PATH.
    echo         Install Python 3.10+ from python.org and tick
    echo         "Add Python to PATH" during setup.
    exit /b 1
)

REM --- Virtual environment -------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [1/6] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 ( echo [ERROR] venv creation failed. & exit /b 1 )
) else (
    echo [1/6] Using existing virtual environment.
)
set "PY=.venv\Scripts\python.exe"

echo [2/6] Installing dependencies...
"%PY%" -m pip install --upgrade pip --quiet
"%PY%" -m pip install -e ".[desktop,dev]" --quiet
if errorlevel 1 ( echo [ERROR] Dependency install failed. & exit /b 1 )
"%PY%" -m pip install pyinstaller --quiet
if errorlevel 1 ( echo [ERROR] PyInstaller install failed. & exit /b 1 )

echo [3/6] Rebuilding web payload...
"%PY%" tools\build_web_payload.py
if errorlevel 1 ( echo [ERROR] Web payload build failed. & exit /b 1 )

REM --- Tests ----------------------------------------------------------
if /I "%~1"=="--no-test" (
    echo [4/6] Tests SKIPPED ^(--no-test^). Do not ship this build.
) else (
    echo [4/6] Running test suite...
    "%PY%" -m pytest -q
    if errorlevel 1 (
        echo.
        echo [ERROR] Tests failed - build aborted.
        echo         Shipping a build whose tests fail is not acceptable
        echo         for software that produces numbers people act on.
        exit /b 1
    )
)

echo [5/6] Stamping version...
"%PY%" tools\stamp_version.py
if errorlevel 1 ( echo [ERROR] Version stamping failed. & exit /b 1 )

echo [6/6] Building executable...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
"%PY%" -m PyInstaller pcis.spec --noconfirm --clean --log-level WARN
if errorlevel 1 ( echo [ERROR] PyInstaller failed. & exit /b 1 )

if not exist "dist\PCIS\PCIS.exe" (
    echo [ERROR] Build finished but produced no executable.
    exit /b 1
)

REM --- Verify the FROZEN bundle, not the source tree -------------------
REM A clean PyInstaller build is not proof of a working application.
REM Two bugs in this project (reportlab->PIL, and PySide6's hook dropping
REM shiboken6) produced clean builds that died at launch. This runs the
REM real executable and exercises every subsystem that has broken under
REM freezing.
echo.
echo [6b/6] Self-testing the frozen build...
"dist\PCIS\PCIS.exe" --self-test
if errorlevel 1 (
    echo.
    echo [ERROR] The executable built but FAILED its self-test.
    echo         Do not ship this build. Details above and in:
    echo         %%LOCALAPPDATA%%\PCIS\logs\application.log
    exit /b 1
)

echo Cleaning intermediates...
if exist build rmdir /s /q build
"%PY%" tools\stamp_version.py --reset

echo.
echo === BUILD OK ===
echo Output: dist\PCIS\PCIS.exe
echo.
echo NOTE: a clean build is not proof of a working app. Launch the exe
echo       before shipping - two crash bugs in this project were only
echo       visible at runtime.
endlocal
