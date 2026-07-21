# Building the PCIS Windows executable

## Requirements

- Windows 10 or 11
- Python 3.10+ (64-bit) from python.org, **"Add Python to PATH" ticked**

PyInstaller does not cross-compile. A Windows `.exe` must be built on
Windows; building on Linux or macOS produces a binary for that platform.

## Build

From the project root:

```powershell
powershell -ExecutionPolicy Bypass -File build_exe.ps1
```

That refreshes the web payload, installs dependencies, **runs the full
test suite (and aborts if it fails)**, then freezes the app.

Result: `dist\PCIS\PCIS.exe`, roughly 180 MB for the whole folder.

## Distributing it

Ship the **entire `dist\PCIS` folder**, not just the `.exe` — the
executable loads Qt and the Python runtime from the files beside it.
Zip that folder to hand it to someone.

The build is deliberately one-folder rather than `--onefile`. One-file
looks tidier but unpacks the whole bundle to a temp directory on every
launch, costing several seconds of startup for a Qt app, and its
self-extracting behaviour is a common antivirus false-positive trigger.

## Where the app keeps data

A frozen build does **not** write beside the executable — an app under
`C:\Program Files\` cannot, and an app launched from a shortcut may have
`C:\Windows\System32` as its working directory.

Data goes to `%LOCALAPPDATA%\PCIS\pcis.db` instead. Paste that path into
Explorer to find it. Delete that file to start a fresh history.

Export dialogs default to your Documents folder.

## Known issues

**SmartScreen warning on first run.** Windows shows "Windows protected
your PC" for unsigned executables from an unknown publisher. Click
*More info* → *Run anyway*. Removing this requires an Authenticode code-
signing certificate (a few hundred dollars a year from a CA) — worth it
if you distribute to other farms, unnecessary for your own machines.

**Antivirus false positives.** PyInstaller bundles trip heuristic
scanners. UPX compression is disabled in the spec because it makes this
markedly worse.

**Size.** ~180 MB, almost entirely Qt. The spec already excludes
QtWebEngine, QtQuick, Qt3D, QtMultimedia and others; QtWebEngine alone
would add well over 100 MB.

## Two bugs the build will NOT catch

Both of these were found only by *running* the frozen binary. A clean
PyInstaller build is not evidence of a working application — always
launch the exe before shipping it.

1. `reportlab` imports `PIL` unconditionally. Excluding PIL builds
   cleanly and crashes at launch with `ModuleNotFoundError`.
2. Listing Qt submodules in `excludes` makes PyInstaller's PySide6 hook
   drop `shiboken6`, PySide6's binding layer, so the app dies at import.
   It is now pinned in `hiddenimports`.

Both fixes are in `pcis.spec` with comments explaining why. Do not
"tidy them away".
