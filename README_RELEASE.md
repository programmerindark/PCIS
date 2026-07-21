# Releasing PCIS

## One command

```bat
release.bat
```

Cleans, builds, compiles the installer, assembles `Release\`, and verifies
required files exist. It aborts if the test suite fails.

Output:

```
Release\
    PCIS_Setup.exe
    LICENSE
    CHANGELOG.md
    User Manual.pdf        (if generated - see below)
    Release Notes.pdf      (if generated)
```

The PDFs are produced by `python tools\build_docs.py`. They are warned
about, not required — a missing manual should not block an otherwise good
release.

## Before releasing

1. **Bump the version** in `pcis/version.py` (`MAJOR`/`MINOR`/`PATCH`) *and*
   `#define AppVersion` in `installer.iss`. These are deliberately separate
   files; keeping them in sync is a manual step. A mismatch shows up as a
   wrong version in Add/Remove Programs.
2. **Update `CHANGELOG.md`.** Include what changed in the engineering, not
   just the UI — users act on these numbers.
3. **Commit first.** The build stamps the current commit into the About
   dialog; releasing from a dirty tree gives a hash that does not describe
   what shipped.

## Manual verification (Step 12)

Automated tests cover the code. These check the *package*, and must be done
on a machine that has never had the app installed:

- [ ] Installer runs without a Python installation present
- [ ] Installs to `C:\Program Files\PCIS`
- [ ] Desktop and Start Menu shortcuts appear and launch
- [ ] Icon renders in Explorer, taskbar and title bar
- [ ] App launches with no missing-DLL error
- [ ] `%LOCALAPPDATA%\PCIS` is created with `settings.json` and the
      `logs`, `reports`, `exports`, `backups` folders
- [ ] Run a recommendation; confirm a row is logged
- [ ] Export a PDF report; confirm it opens
- [ ] Export training data CSV; confirm it has a header and data
- [ ] Switch units and themes; reopen and confirm the choice persisted
- [ ] Close the app; no orphaned process remains in Task Manager
- [ ] Uninstall; confirm it offers to keep your data and honours the answer

## Expected first-run warnings

**SmartScreen: "Windows protected your PC."** Unavoidable for unsigned
executables. Click *More info* → *Run anyway*.

Removing it requires an Authenticode code-signing certificate (a few hundred
dollars a year from a CA, and reputation accrues over time even once signed).
Worth it if you distribute to other farms; unnecessary for your own machines.

**Antivirus false positives.** PyInstaller bundles trip heuristic scanners.
UPX compression is disabled in the spec because it makes this markedly worse.
