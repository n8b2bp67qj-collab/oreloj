# Changelog

All notable changes to Oreloj are documented here.
Format: [date] — what changed and why.

---

## 2026-06-10

### Added
- **FM tuning static** (`globe.py`) — a soft, synthesized radio-static loop (`sounds/tuning.wav`, generated on first run) starts the instant a country is tapped and is cut by a watchdog the moment the stream actually produces audio. Covers the announce/connect gap like the website's white-noise effect.
- **Off-air announcement** (`globe.py`) — if the player dies or produces no audio within 12 s (webpage URL, 404, dead host), the globe says "This station seems to be off air" instead of failing silently, kills the stuck player and clears state.
- **Station health-check** (`check_stations.py`) — probes every `stations.csv` stream URL concurrently and flags webpages, HTTP errors, timeouts and non-audio responses. Exit code 1 when something is broken (cron-friendly). First run: 110/131 healthy.
- **Bluetooth auto-reconnect** (`bt-autoconnect.service` + `.timer`) — user systemd timer (every 2 min, 30 s after boot) connects any paired-but-disconnected speaker. The Pi no longer waits for the speaker to initiate.

### Changed
- **Re-tap behaviour** (`globe.py`) — tapping the country already playing no longer re-announces its name or restarts the stream: it cycles to another of that country's stations (favourites first); with a single station it just keeps playing.
- **BT pairing is verified** (`admin.py`) — `/api/bt/pair` re-checks `Paired: yes` via `bluetoothctl info` (pair output alone can lie — Bose drops bonds silently when its device list is full), reports honestly, and auto-rebuilds the PipeWire combine sink with all paired speakers so newly paired speakers receive audio without manual config. `/api/bt/connect` does the same for speakers paired outside the UI.

### Fixed
- **Radio Alhara stream URL** (`stations.csv`) — `radioalhara.net/stream` is a webpage; replaced with the real RadioJar stream.

### Device-side (documented for reference, not in repo)
- Wi-Fi: cloud-init's instance-id is pinned in `cmdline.txt` (`ds=nocloud;i=…`) — bump it there, not in `meta-data`, to re-apply `network-config`. The "Freebox Bestron " SSID ends with a real trailing space.
- Bluetooth audio on headless: `~/.config/wireplumber/wireplumber.conf.d/80-bluez-headless.conf` disables seat-monitoring; lightdm disabled (its greeter session's pipewire stole BT endpoints); rogue *system-level* `admin.service` disabled (it squatted port 5000 and made the user unit crash-loop).

---

## 2026-05-25

### Added
- **Volume persistence** (`globe.py`) — `_current_volume` is now saved to `volume.json` on every change and loaded at startup. Volume no longer resets to 80 after a service restart.
- **"Stream lost" detection** (`globe.py`) — the main loop now monitors mpv every second. If mpv exits unexpectedly (station offline, network drop), globe.py speaks "stream lost" via TTS and clears the playback state cleanly.
- **Local D3 + topojson** (`d3.min.js`, `topojson-client.min.js`) — downloaded and bundled with the project (273 KB + 7 KB). Globe map now renders fully offline without depending on unpkg CDN.

### Changed
- **`admin.service` converted to user systemd unit** — was a system service (`User=oreloj`, `WantedBy=multi-user.target`), now matches `globe.service` style (`%h` paths, `WantedBy=default.target`). Installed on Pi at `~/.config/systemd/user/admin.service`, enabled for boot, replaces the previous bare-process approach. Admin UI now auto-restarts on crash.
- **`index.html` script tags** — `<script src="d3.min.js">` and `<script src="topojson-client.min.js">` (local paths, no CDN).

---

## 2026-05-24

### Added
- **Country-tap cycling** (`globe.py`) — tapping a country now steps through stations in a fixed order instead of picking randomly. Order: presets matching that country (slot 1→6) → liked stations → other stations → random API fallback. Tapping a different country or waiting 25 s resets the sequence to the top. Each tap within the sequence plays the next station ("channel button" behaviour).
- **`build_country_playlist()`** (`globe.py`) — new function that builds the ordered playlist for a tap, resolving preset-to-country via stored `iso` field or URL/name matching against `stations.csv`.
- **`DELETE /api/stations/by-key`** (`admin.py`) — new endpoint to remove a station by stable key (stream URL, or name if URL is empty). Used by the website when deleting stations so the Pi stays in sync.
- **`piDelete()` helper** (`index.html`) — mirrors `piPost()` but sends a DELETE with a JSON body. Used by station deletion and future key-based removes.
- **Pi-authoritative sync (`pollPi`)** (`index.html`) — replaces the one-shot `syncFromPi()`. Runs once on load and every 20 seconds. Reconciles local custom stations against Pi using a `_piOrigin` tag: adds Pi-side additions, updates changed fields, removes Pi-side deletions, and pushes locally-added stations up to the Pi on reconnect.

### Changed
- **`DEBOUNCE_SEC` 2.0 → 0.5** (`globe.py`) — allows deliberate "next station" taps (~1 s apart) while still suppressing the pen's accidental double-reads from a single physical touch. Added `CYCLE_RESET_SEC = 25`.
- **`POST /api/stations` is now an upsert** (`admin.py`) — matches by URL Link first, then Radio Station name. Updates the existing row in place if found; appends only if new. Eliminates duplicate rows from repeated syncs. Returns `{ok, added, updated}`.
- **`PUT /api/presets/<slot>`** (`admin.py`) — now accepts optional `iso` field (ISO 3166-1 alpha-2 country code), stored in `actions.json` so `globe.py` can match presets to countries without URL scanning.
- **`saveStation()` pushes all edits to Pi** (`index.html`) — previously only new stations were sent to the Pi. Now edits to custom stations and built-in overrides are also upserted via `POST /api/stations`.
- **`deleteCurrentEdit()` deletes from Pi** (`index.html`) — calls `DELETE /api/stations/by-key` so deletions made on the website propagate to the Pi's `stations.csv`.
- **Preset modal captures country code** (`index.html`) — when a station is selected from the Radio Browser search in the preset modal, `s.countrycode` is stored as `_pmIso` and included in the `PUT /api/presets/<slot>` body as `iso`.

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
