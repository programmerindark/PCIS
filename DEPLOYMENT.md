# PCIS Deployment Guide

For whoever installs and supports PCIS on farm machines.

## What gets installed where

| Location | Contents | Writable |
|---|---|---|
| `C:\Program Files\PCIS\` | `PCIS.exe`, Qt, Python runtime, `manual\` | No (by design) |
| `%LOCALAPPDATA%\PCIS\` | `settings.json`, `pcis.db`, `logs\`, `reports\`, `exports\`, `backups\` | Yes |

**Application and user data are deliberately separate.** A standard user
cannot write to Program Files, so an app storing its database beside its
executable either fails outright or — worse — silently writes somewhere the
operator will never find. Two shortcuts launched from different folders would
also end up using two different databases, splitting the recorded history
that the CSV export depends on.

`%LOCALAPPDATA%` expands to `C:\Users\<name>\AppData\Local`. Paste it into
Explorer's address bar to get there.

**Data is per-user.** Two Windows accounts on one machine keep separate
histories. If several people share a house's records, either use one Windows
account or export CSVs and merge them.

## Installing

1. Copy `PCIS_Setup.exe` to the machine.
2. Double-click. Accept the UAC prompt (installing to Program Files requires
   administrator rights).
3. On the SmartScreen warning — *More info* → *Run anyway*. See below.
4. Choose whether to create a desktop shortcut.

### Silent install (multiple machines)

```bat
PCIS_Setup.exe /VERYSILENT /NORESTART /SUPPRESSMSGBOXES
PCIS_Setup.exe /VERYSILENT /NORESTART /TASKS="desktopicon"
```

Silent uninstall:

```bat
"C:\Program Files\PCIS\unins000.exe" /VERYSILENT
```

## SmartScreen

The installer is unsigned, so Windows shows "Windows protected your PC".
This is expected and not a sign of a problem.

Removing it needs an Authenticode code-signing certificate — a few hundred
dollars a year, and SmartScreen reputation still builds over time even after
signing. Worth it if you distribute beyond your own operation.

## Upgrading

Run the new `PCIS_Setup.exe` over the top. It replaces the program files and
leaves `%LOCALAPPDATA%\PCIS` untouched, so settings and logged history
survive. No need to uninstall first.

## Uninstalling

Settings → Apps → PCIS → Uninstall.

The uninstaller **asks** whether to delete your data, and defaults to *No*.
That history is the dataset behind the ML export; removing an application
should not destroy the data it produced.

## Backups

Worth doing once the logged history matters:

```bat
copy "%LOCALAPPDATA%\PCIS\pcis.db" "D:\backups\pcis-%DATE%.db"
```

Or use **Export Training Data (CSV)** in the app, which produces a portable
file that does not depend on the app to read.

## Support checklist

Ask for these before anything else:

1. **The log file** — `%LOCALAPPDATA%\PCIS\logs\application.log`. Unhandled
   errors land here with a full traceback, and the error dialog shows the
   path.
2. **Version, build date and commit** — the About button in the header.
3. **A screenshot** including the window, since several past defects were
   layout-only and invisible from logs.

### Common issues

| Symptom | Cause | Fix |
|---|---|---|
| Won't start, no window | Missing dependency in the frozen build | Check `application.log`; run the exe from `cmd` to see stderr |
| "Windows protected your PC" | Unsigned installer | *More info* → *Run anyway* |
| Antivirus quarantine | PyInstaller heuristic false positive | Allow-list `C:\Program Files\PCIS\` |
| Settings not saving | `%LOCALAPPDATA%` not writable (locked-down profile) | Check permissions; see log |
| History looks empty | Different Windows user account | Data is per-user |
| Text unreadable | Fixed in 1.0.0 (dark mode) | Upgrade |

## What this software is not

PCIS is decision support. Every figure traces to a cited published source,
and values that could not be verified are flagged rather than estimated —
but **the model has not been validated against measurements from a working
house.**

Treat recommendations as engineering guidance to be checked against observed
conditions and the birds themselves. Closing that gap needs measured
supply-air temperatures from a real house on a hot day, logged against
predictions; `pcis.core.validation` exists for exactly that.
