# Changelog

All notable changes to Oreloj are documented here.
Format: [date] — what changed and why.

---

## 2026-05-21

### Added
- **"Update available" banner** — when `oreloj.local:5000` is open, the UI silently checks GitHub's latest commit date against the Pi's deployment timestamp (admin.py file mtime). If GitHub is ahead, a `▲ update available` banner appears at the top of the sidebar with an "update now" button. Only visible in Globe Owner tier.
- **`calibration.csv` added to GitHub repo** — this file maps 316 pen hex codes to countries and is required by `globe.py` at startup. It was missing from the repo (and from the Pi). Now tracked in git and must be included in Pi deploys.
- **`build_time` field in `/api/status`** — `admin.py` now returns its own file mtime as an ISO-8601 UTC string. Used by the update banner to detect stale deployments.

### Changed
- **`.gitignore` updated** — added `.claude/` (Claude Cowork session data), `*.skill` (Claude plugin files), and `favourites.json` (runtime data that changes with use).

### Fixed
- **Pi was running 6-day-old `globe.py`** — local May 20 versions of `globe.py`, `admin.py`, and `index.html` deployed to Pi and GitHub.

---

## 2026-05-20

### Changed
- `globe.py` — pen code handling, CODE_MAP updates
- `admin.py` — API and admin UI improvements
- `index.html` — UI updates (3200+ line unified public + admin interface)

---

## 2026-05-19

### Added
- `99-globe-hid.rules` — udev rules for HID access without root
- `README.md` — project documentation

### Changed
- `globe.py` — cross-platform support (macOS pynput + Linux evdev)
- `admin.py` — Flask admin server with REST API

---

## 2026-05-15

### Added
- `audio_setup.sh` — PulseAudio/PipeWire combined sink setup (3.5mm + Bluetooth simultaneously)
- `globe.service` / `admin.service` — systemd service files
- `oreloj-hotspot.sh` / `oreloj-hotspot.service` — captive portal for Wi-Fi setup

---

## 2026-05-14

### Added
- Initial commit — `index.html`, `globe.py`, `admin.py`, `stations.csv`, `actions.json`
- Pi standalone build working: tap pen → country detected → stream plays via mpv
