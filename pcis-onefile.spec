# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller ONE-FILE build spec for PCIS.

Build on Windows with:   pyinstaller pcis-onefile.spec --noconfirm
Output:                  dist/PCIS.exe   (a single file)

Read the trade-off before choosing this over pcis.spec: a one-file
build re-extracts the ENTIRE bundle to %TEMP%\\_MEIxxxxx on every
launch, so startup cost is paid each time rather than once at install.
For a Qt application that is seconds, not milliseconds. It also trips
antivirus heuristics more often, precisely because self-extraction is
what a lot of malware does.

Use one-file when handing someone a single attachment matters more
than start-up speed. Use pcis.spec for a tool used daily.

PyInstaller does NOT cross-compile. A Windows .exe must be produced on
a Windows machine with a Windows Python; building this spec on Linux or
macOS yields a binary for that platform instead.

Why one-folder rather than one-file
-----------------------------------
`--onefile` looks tidier but unpacks the entire bundle to a temp
directory on every launch, which for a Qt app means several seconds of
startup and a large disk churn each time. It also trips some antivirus
heuristics precisely because it self-extracts. One-folder starts fast
and is what the zip ships.

Excluded modules
----------------
PySide6 ships a very large Qt. PCIS uses QtWidgets, QtCore, QtGui and
QtCharts only. Everything below is explicitly excluded -- QtWebEngine
alone is well over 100 MB and would otherwise be pulled in. Also
excluded are libraries the base package no longer depends on at all
(numpy, scipy) so a stale environment cannot quietly bloat the build.
"""

import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

EXCLUDED = [
    # Qt subsystems PCIS never imports
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml", "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtBluetooth",
    "PySide6.QtNetworkAuth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtLocation",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtWebSockets", "PySide6.QtWebChannel",
    "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtSql",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    # Never imported by PCIS -- see pyproject.toml, base deps are empty
    "numpy", "scipy", "matplotlib", "pandas", "tkinter",
    # NOTE: PIL must NOT be excluded. reportlab imports it unconditionally
    # (reportlab/lib/utils.py), so excluding it builds cleanly and then
    # crashes on launch with ModuleNotFoundError. Found only by running
    # the frozen binary -- PyInstaller reported no error.
    "pytest", "_pytest", "setuptools", "pip",
]

a = Analysis(
    ["pcis/gui/main_window.py"],
    pathex=[],
    binaries=[],
    datas=[],
    # SQLAlchemy resolves its DBAPI driver by string at runtime, so
    # PyInstaller's static analysis cannot see pysqlite2/sqlite3 being
    # used and would omit it -- the app would then fail on first launch
    # with "Could not determine dialect".
    hiddenimports=collect_submodules("sqlalchemy.dialects.sqlite") + [
        "sqlalchemy.sql.default_comparator",
        # PySide6 cannot start without its binding layer. Listing Qt
        # submodules in `excludes` makes PyInstaller's PySide6 hook drop
        # shiboken6 along with them, and the app dies at import with
        # "No module named 'shiboken6.Shiboken'". Naming it explicitly
        # keeps the size savings from the exclusions without losing it.
        "shiboken6",
        "shiboken6.Shiboken",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDED,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="PCIS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX compression is a common false-positive trigger for antivirus
    console=False,      # GUI app: no console window behind it
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="web/icon-512.png" if sys.platform != "win32" else None,
)
