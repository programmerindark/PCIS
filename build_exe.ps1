# Build the PCIS Windows executable.
#
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1
#
# Must be run on Windows: PyInstaller does not cross-compile.

$ErrorActionPreference = "Stop"

Write-Host "== PCIS Windows build ==" -ForegroundColor Cyan

# 1. Refresh the web payload so a shipped build cannot contain stale physics.
Write-Host "`n[1/4] Rebuilding web payload..."
python tools/build_web_payload.py

# 2. Dependencies, including PyInstaller itself.
Write-Host "`n[2/4] Installing dependencies..."
python -m pip install -e ".[desktop,dev]" --quiet
python -m pip install pyinstaller --quiet

# 3. Never ship a build whose tests do not pass.
Write-Host "`n[3/4] Running test suite..."
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed - build aborted." }

# 4. Freeze.
Write-Host "`n[4/4] Building executable..."
if (Test-Path build) { Remove-Item build -Recurse -Force }
if (Test-Path dist)  { Remove-Item dist  -Recurse -Force }
pyinstaller pcis.spec --noconfirm --clean

$exe = "dist\PCIS\PCIS.exe"
if (-Not (Test-Path $exe)) { throw "Build produced no executable." }

$sizeMb = [math]::Round((Get-ChildItem dist\PCIS -Recurse |
                         Measure-Object -Property Length -Sum).Sum / 1MB, 1)
Write-Host "`nBuilt $exe ($sizeMb MB total)" -ForegroundColor Green
Write-Host "Ship the whole dist\PCIS folder - PCIS.exe needs the files beside it."
