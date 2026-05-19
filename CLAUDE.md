# Oreloj — Claude Code Context

Oreloj is a hacked children's educational globe that plays live web radio from wherever you point the stylus. Tap a country, hear radio from that region. Built by Adrien. The globe is a product — it will be shipped to end users.

## Hardware

- **Globe:** Oregon Scientific Horizon Globe. The original USB stylus (SONiX HID, VID:0x0c45 PID:0x7700) acts as a barcode scanner for geography — each country tap sends a 6-char hex code (e.g. `a0387f` = UK).
- **Pi:** Raspberry Pi 3 A+, runs headless inside/beside the globe.
- **Audio:** Bluetooth speaker primary, 3.5mm jack fallback.

## Repo & live site

- **Repo:** https://github.com/n8b2bp67qj-collab/oreloj
- **Live site:** https://n8b2bp67qj-collab.github.io/oreloj/ (GitHub Pages, served from `index.html` at repo root)
- **Pi admin UI:** http://oreloj.local:5000 on local network, or via the `oreloj` Wi-Fi hotspot captive portal

## Key files

| File | What it does |
|---|---|
| `index.html` | Single-file app (~3200 lines): public website AND Pi admin UI |
| `globe.py` | Pi main process: reads pen HID events, resolves country codes, plays streams via mpv, TTS via espeak-ng |
| `admin.py` | Flask on port 5000: REST API for stations, BT, Wi-Fi, presets, zones |
| `stations.csv` | Canonical station list (Continent, Country, City, Radio Station, Description, Website, URL Link, Favourite) |
| `actions.json` | Pen code → action/zone/preset mappings |
| `globe.service` / `admin.service` | systemd services for the two Pi processes |
| `99-globe-hid.rules` | udev rules so globe.py can read the HID device without root |
| `oreloj-hotspot.sh` | iptables + dnsmasq captive portal for initial Wi-Fi setup |

## Architecture

### Two Pi services, loosely coupled via shared files

**globe.py** reads pen codes via evdev (Pi) or pynput (Mac, for dev). Resolves codes against an embedded CODE_MAP (250+ country entries). Station priority: curated favourites → any curated → Radio Browser API fallback. Plays via mpv child process + Unix socket for volume control.

**admin.py** serves index.html and a REST API. Key endpoints: `/api/stations`, `/api/favourites`, `/api/zones`, `/api/presets`, `/api/bt/*`, `/api/wifi/*`, `/api/status`, `/api/volume`. Sends SIGHUP to globe.py after data writes so it reloads without restart.

### index.html — dual-role file

The same file is the public GitHub Pages website and the Pi admin UI. `PI_BASE` is `''` on `oreloj.local`/`localhost`, otherwise `http://oreloj.local:5000`. All Pi API calls are fire-and-forget (2s timeout, silent fail when Pi is offline).

### Client-side data model (localStorage)

| Key | Contents |
|---|---|
| `rw_custom` | User-added stations (JSON array) |
| `rw_overrides` | Edits to BUILT_IN stations (JSON object) |
| `rw_hidden_builtin` | Deleted BUILT_IN names (JSON array) |
| `rw_favs` | Favourite station names (JSON array) |
| `rw_user_pen_map` | User pen code → country overrides |
| `rw_action_map` | User pen code → action mappings |
| `oreloj_gh_token` | GitHub PAT for repo writes |
| `oreloj_gh_repo` | GitHub repo (default: `n8b2bp67qj-collab/oreloj`) |
| `oreloj_gh_branch` | Branch (default: `main`) |

`BUILT_IN` is a hardcoded array of 100+ curated stations in index.html. `rebuildStations()` merges BUILT_IN + overrides + custom into the working `stations` array.

### GitHub as database

`stations.csv` in the repo is the canonical station list. index.html writes back to it via the GitHub Contents API on every station add/delete/fav toggle. PAT is stored in localStorage (never in source). Functions: `ghGetFile`, `ghPutFile`, `ghSaveStations`, `ghLoadStations`. The `● developer` section in the sidebar is where the PAT and repo are configured.

## Active development priorities

1. **Add radio stations** — build up the curated list in stations.csv before shipping
2. **Calibrate pen codes** — plug pen into laptop, run `globe.py --calibrate`, codes print to terminal, paste into the website assign UI to map to countries or actions
3. **Create action zones** — draw zones on the physical globe surface, tap to get codes, assign actions (volume up/down, presets 1–6, favourite toggle)

## Planned features (not yet built)

- **Globe detection:** website tries `fetch('http://oreloj.local:5000/api/status')` on load; if it responds, show "Globe connected" banner. Requires `Access-Control-Allow-Private-Network: true` header in admin.py.
- **Public access tiers:** anyone can browse/play/fav (localStorage); globe owners get add/calibrate/preset features when globe is detected on the same network.
- **Onboarding flow:** first-time welcome modal on the admin UI guiding through Wi-Fi → Bluetooth setup. `localStorage` flag so it only shows once.
- **Presets GitHub sync:** preset slots (6 stations) should persist to GitHub like stations do.

## Decisions already made

- **No streaming calibration** — plug pen into laptop, copy-paste codes from terminal into website. Simpler and already works.
- **localStorage for anonymous favs** — users without a globe get browser-local favourites only; no backend needed.
- **GitHub as database** — PAT in localStorage, no backend server. Fine for solo development; would need a proxy for multi-user.
- **Concurrent writes:** two devices writing at the same moment cause a 409 SHA mismatch — acceptable for solo use.
