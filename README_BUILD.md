# Building PCIS

## Requirements

| Requirement | Notes |
|---|---|
| Windows 10 (1809+) or 11, 64-bit | Qt ships 64-bit only; the installer refuses 32-bit hosts |
| Python 3.10+ (64-bit) from python.org | Tick **"Add Python to PATH"** during setup |
| Inno Setup 6 | Only needed for the installer: https://jrsoftware.org/isdl.php |
| Git | Optional. Without it the build stamps the commit as `unknown` |

**PyInstaller does not cross-compile.** A Windows `.exe` must be built on
Windows. Building on Linux or macOS produces a binary for that platform.

## Build

```bat
build.bat
```

Creates `.venv` if absent, installs dependencies, rebuilds the web payload,
**runs the full test suite**, stamps version metadata, freezes the app, then
removes intermediates.

Output: `dist\PCIS\PCIS.exe`

`build.bat --no-test` skips the tests. Do not use it for anything you ship.

## Why PyInstaller rather than Nuitka

Nuitka was evaluated and rejected for this project:

- Compiling PySide6 takes 20–40 minutes versus roughly two for PyInstaller,
  on every build.
- It needs a full C toolchain (MSVC) on the build machine.
- Its Qt plugin handling is more fragile, and this application depends on
  QtCharts.
- The PyInstaller path here is *verified working*, including two crash bugs
  found by running the frozen binary (see below).

The gain would be faster startup and harder-to-decompile output. Neither
matters for an internal engineering tool. If you later need Nuitka, the
entry point and asset handling are already correct for it — only the build
script changes.

## Two bugs a successful build will NOT report

Both were found only by *launching* the frozen binary. A clean PyInstaller
build is not evidence of a working application.

1. **`reportlab` imports `PIL` unconditionally.** Excluding PIL to save space
   builds cleanly and crashes at launch with `ModuleNotFoundError`.
2. **Listing Qt submodules in `excludes` makes PyInstaller's PySide6 hook
   drop `shiboken6`** — the binding layer PySide6 cannot start without. Also
   a clean build, also a dead app.

Both fixes are in `pcis.spec` with comments. Do not "tidy them away".

**Always launch `dist\PCIS\PCIS.exe` before shipping.**

## Layout

| Path | Purpose |
|---|---|
| `pcis.spec` | One-folder build (recommended) |
| `pcis-onefile.spec` | Single-file build; re-extracts ~180 MB per launch |
| `assets/pcis.ico` | Application and installer icon |
| `tools/stamp_version.py` | Writes build date + commit into `pcis/version.py` |
| `tools/build_web_payload.py` | Packs the engineering core for the web build |

## Troubleshooting

**`python` not recognised** — Python is not on PATH. Reinstall with the
"Add Python to PATH" box ticked.

**`ModuleNotFoundError` when the exe runs** — a hidden import. Add it to
`hiddenimports` in `pcis.spec`. This is the most common freezing failure.

**Build succeeds, exe does nothing** — run it from `cmd` to see stderr, and
check `%LOCALAPPDATA%\PCIS\logs\application.log`.

**~180 MB output** — almost entirely Qt. The spec already excludes
QtWebEngine, QtQuick, Qt3D and QtMultimedia; QtWebEngine alone would add
over 100 MB.
