# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/).
This project uses [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-07-21

First packaged release.

### Added
- Windows installer (`PCIS_Setup.exe`) via Inno Setup, with Start Menu and
  optional desktop shortcuts, an uninstaller, and version metadata.
- First-run setup: `settings.json` plus `logs`, `reports`, `exports` and
  `backups` directories created under `%LOCALAPPDATA%\PCIS`.
- Application logging to `logs\application.log` (rotating, 2 MB x 5) and a
  global exception hook that shows a readable error dialog instead of the
  window vanishing.
- About dialog reporting version, build date, git commit, and the location
  of the data folder and log file.
- `UpdateService` interface with a null default. No update mechanism is
  implemented; nothing contacts the network.
- Offline mobile web build (`web/`) running the real engineering core in the
  browser via Pyodide, deployable to Vercel.
- Digital twin: fan/pad schedules across a day or a grow-out.
- Metric/imperial unit switching, display-only — SI is used throughout the
  engineering core and the database regardless.
- Light and dark themes, following the operating system.
- Automatic logging of every recommendation, exportable as CSV for future
  calibration or ML work.

### Fixed
- **Unreachable target temperatures were reported as if achievable.** When
  supply air is at or above the target, no fan count reaches target; the app
  now says so and states that more fans will not help.
- Indoor humidity above 70% crashed the app; now clamped to the published
  table edge and flagged, with the THI reading unaffected.
- Body weight is derived from bird age via the Aviagen Ross 308 curve rather
  than typed in by hand.
- Frozen builds wrote their database to the working directory, which may be
  read-only or invisible to the user; now `%LOCALAPPDATA%\PCIS`.
- Numerous UI defects found by inspecting rendered output at minimum window
  size and in dark mode: colliding metric labels, silently truncated
  explanation text, a chart y-axis that misrepresented bar magnitudes,
  unreadable text on dark desktops.

### Known limitations
- The engineering model has not been validated against measurements from a
  real house. This is the most significant outstanding gap.
- Manufacturer and extension-service cooling-pad efficiencies disagree by
  15 percentage points; PCIS uses the conservative figure.
- Ross 308 only. No Cobb 500 data is included and no code path assumes it.
- The mobile web build cannot log readings yet.
