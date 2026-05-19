#!/usr/bin/env python3
"""
admin.py — Oreloj Globe Admin
Flask web UI: station management, Bluetooth speaker selection, Wi-Fi setup.

Install:  pip install flask --break-system-packages
Run:      python3 ~/globe/admin.py
Access:   http://oreloj.local:5000
"""

import csv, io, json, os, re, select, subprocess, threading, time, urllib.request
from pathlib import Path
from flask import Flask, render_template_string, jsonify, request, abort, redirect

SCRIPT_DIR   = Path(__file__).parent
STATIONS_CSV = SCRIPT_DIR / "stations.csv"
FAVS_PATH    = SCRIPT_DIR / "favourites.json"
ACTIONS_FILE = SCRIPT_DIR / "actions.json"
CSV_FIELDS   = ["Continent", "Country", "City", "Radio Station",
                 "Description", "Website", "URL Link", "Favourite"]

# Set this to the raw GitHub URL of stations.csv once it's committed to the
# human-ears repo, e.g.:
#   "https://raw.githubusercontent.com/<username>/human-ears/main/stations.csv"
# The Sync button in the UI calls /api/sync which fetches from this URL.
SYNC_URL = ""

# Set this to the SSH remote or HTTPS URL of the globe repo once it's on GitHub,
# e.g. "https://github.com/<username>/oreloj.git"
# (Only needed for documentation/reference — the update endpoint uses `git pull`
# directly on the Pi's local clone at ~/globe.)
REPO_URL = ""

app = Flask(__name__)


# ── CORS (allow index.html on GitHub Pages to reach the Pi API) ───────────────

@app.before_request
def _handle_options():
    if request.method == "OPTIONS":
        resp = app.make_default_options_response()
        resp.headers["Access-Control-Allow-Origin"]  = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp


@app.after_request
def _add_cors(response):
    response.headers["Access-Control-Allow-Origin"]  = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


# ── helpers ───────────────────────────────────────────────────────────────────

def _run(cmd: list, timeout: int = 10) -> tuple:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except FileNotFoundError:
        return -1, f"{cmd[0]}: not found"


def _parse_bt_lines(text: str) -> list:
    """Parse 'Device MAC Name' lines from bluetoothctl output."""
    devices = []
    for line in text.splitlines():
        parts = line.strip().split(" ", 2)
        if len(parts) == 3 and parts[0] == "Device":
            devices.append({"mac": parts[1], "name": parts[2]})
    return devices


# ── Favourites JSON ───────────────────────────────────────────────────────────

def read_favs() -> list:
    """Return list of favourite station names."""
    if not FAVS_PATH.exists():
        return []
    try:
        return json.loads(FAVS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def write_favs(names: list) -> None:
    tmp = Path(str(FAVS_PATH) + ".tmp")
    tmp.write_text(json.dumps(sorted(names), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, FAVS_PATH)


# ── CSV ───────────────────────────────────────────────────────────────────────

def read_csv() -> list:
    if not STATIONS_CSV.exists():
        return []
    with open(STATIONS_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(rows: list) -> None:
    tmp = Path(str(STATIONS_CSV) + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, STATIONS_CSV)


def _notify_globe() -> None:
    """Restart globe.py so it picks up CSV changes immediately.
    Runs best-effort — a failure here is non-fatal (stations were still saved)."""
    env = {**os.environ, "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"}
    try:
        subprocess.run(
            ["systemctl", "--user", "restart", "globe"],
            env=env, timeout=5, capture_output=True,
        )
    except Exception:
        pass


# ── API: status ───────────────────────────────────────────────────────────────

@app.get("/api/status")
def api_status():
    rc, _ = _run(["pgrep", "-x", "mpv"])
    playing = rc == 0

    _, bt_out = _run(["bluetoothctl", "devices", "Connected"])
    bt = _parse_bt_lines(bt_out)

    _, wifi_out = _run(["nmcli", "-t", "-f", "ACTIVE,NAME,TYPE",
                        "connection", "show", "--active"])
    wifi = None
    hotspot_mode = False
    for line in wifi_out.splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[0] == "yes":
            name, ctype = parts[1], parts[2]
            if name in ("lo", ""):
                continue
            if name == "hotspot":
                hotspot_mode = True
            elif ctype in ("802-11-wireless", "ethernet"):
                wifi = name
                break

    return jsonify({"playing": playing, "bt": bt, "wifi": wifi,
                    "hotspot_mode": hotspot_mode})


# ── API: stations ─────────────────────────────────────────────────────────────

@app.get("/api/stations")
def api_stations_get():
    return jsonify(read_csv())


@app.post("/api/stations")
def api_stations_post():
    data = request.json or {}
    rows = read_csv()
    row  = {k: data.get(k, "") for k in CSV_FIELDS}
    rows.append(row)
    write_csv(rows)
    _notify_globe()
    return jsonify({"ok": True, "index": len(rows) - 1})


@app.put("/api/stations/<int:idx>")
def api_stations_put(idx):
    rows = read_csv()
    if not (0 <= idx < len(rows)):
        abort(404)
    for k in CSV_FIELDS:
        if k in (request.json or {}):
            rows[idx][k] = request.json[k]
    write_csv(rows)
    _notify_globe()
    return jsonify({"ok": True})


@app.delete("/api/stations/<int:idx>")
def api_stations_delete(idx):
    rows = read_csv()
    if not (0 <= idx < len(rows)):
        abort(404)
    rows.pop(idx)
    write_csv(rows)
    _notify_globe()
    return jsonify({"ok": True})


@app.get("/api/stations/json")
def api_stations_json():
    """Return stations.csv as a JSON array (field names normalised for the web UI)."""
    rows = read_csv()
    return jsonify([
        {
            "name":      r.get("Radio Station", ""),
            "city":      r.get("City", ""),
            "country":   r.get("Country", ""),
            "stream":    r.get("URL Link", ""),
            "web":       r.get("Website", ""),
            "desc":      r.get("Description", ""),
            "continent": r.get("Continent", ""),
        }
        for r in rows
    ])


# ── API: favourites ───────────────────────────────────────────────────────────

@app.get("/api/favourites")
def api_favs_get():
    """Return list of favourite station names."""
    return jsonify({"favourites": read_favs()})


@app.post("/api/favourites")
def api_favs_post():
    """Toggle a station's favourite status by name. Body: {"name": "…"}."""
    name = (request.json or {}).get("name", "").strip()
    if not name:
        abort(400)
    favs = read_favs()
    if name in favs:
        favs.remove(name)
        added = False
    else:
        favs.append(name)
        favs.sort()
        added = True
    write_favs(favs)
    _notify_globe()
    return jsonify({"favourites": favs, "added": added})


# ── Actions JSON helpers ──────────────────────────────────────────────────────

def read_actions() -> dict:
    if not ACTIONS_FILE.exists():
        return {"zones": [], "presets": []}
    try:
        return json.loads(ACTIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"zones": [], "presets": []}


def write_actions(data: dict) -> None:
    tmp = Path(str(ACTIONS_FILE) + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, ACTIONS_FILE)


# ── API: zones ────────────────────────────────────────────────────────────────

@app.get("/api/zones")
def api_zones_get():
    """Return full actions.json (zones + presets)."""
    return jsonify(read_actions())


@app.post("/api/zones")
def api_zones_post():
    """Add a new zone. Body: {code, action, label, description, position}."""
    body = request.json or {}
    code = body.get("code", "").strip()
    action = body.get("action", "").strip()
    if not code or not action:
        abort(400)
    data = read_actions()
    data.setdefault("zones", [])
    data["zones"].append({
        "code":        code,
        "action":      action,
        "label":       body.get("label", code),
        "description": body.get("description", ""),
        "position":    body.get("position", None),
    })
    write_actions(data)
    _notify_globe()
    return jsonify({"ok": True})


@app.put("/api/zones/<code>")
def api_zones_put(code):
    """Update label, description, position for a zone by code."""
    data = read_actions()
    zones = data.get("zones", [])
    zone = next((z for z in zones if z["code"] == code), None)
    if zone is None:
        abort(404)
    body = request.json or {}
    for field in ("label", "description", "position"):
        if field in body:
            zone[field] = body[field]
    write_actions(data)
    _notify_globe()
    return jsonify({"ok": True})


@app.delete("/api/zones/<code>")
def api_zones_delete(code):
    """Remove a zone by code."""
    data = read_actions()
    zones = data.get("zones", [])
    new_zones = [z for z in zones if z["code"] != code]
    if len(new_zones) == len(zones):
        abort(404)
    data["zones"] = new_zones
    write_actions(data)
    _notify_globe()
    return jsonify({"ok": True})


# ── API: presets ──────────────────────────────────────────────────────────────

@app.get("/api/presets")
def api_presets_get():
    """Return presets list."""
    return jsonify({"presets": read_actions().get("presets", [])})


@app.put("/api/presets/<int:slot>")
def api_presets_put(slot):
    """Update a preset slot (1-6). Body: {name, url, label}."""
    if not (1 <= slot <= 6):
        abort(400)
    data = read_actions()
    presets = data.get("presets", [])
    preset = next((p for p in presets if p.get("slot") == slot), None)
    if preset is None:
        # Create the slot if it doesn't exist yet
        preset = {"slot": slot, "name": "", "url": "", "label": f"Preset {slot}"}
        presets.append(preset)
        data["presets"] = presets
    body = request.json or {}
    for field in ("name", "url", "label"):
        if field in body:
            preset[field] = body[field]
    write_actions(data)
    _notify_globe()
    return jsonify({"ok": True})


# ── API: Bluetooth ────────────────────────────────────────────────────────────

@app.get("/api/bt/devices")
def api_bt_devices():
    _, paired_out = _run(["bluetoothctl", "devices", "Paired"])
    _, conn_out   = _run(["bluetoothctl", "devices", "Connected"])
    paired    = _parse_bt_lines(paired_out)
    connected = {d["mac"] for d in _parse_bt_lines(conn_out)}
    for d in paired:
        d["connected"] = d["mac"] in connected
    return jsonify(paired)


@app.post("/api/bt/scan")
def api_bt_scan():
    """6-second BT scan; returns all discovered devices."""
    mac_re = re.compile(r'([0-9A-F]{2}(?::[0-9A-F]{2}){5})\s+(.+)', re.IGNORECASE)
    discovered = {}  # mac -> name

    proc = subprocess.Popen(
        ["bluetoothctl"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    proc.stdin.write("scan on\n")
    proc.stdin.flush()

    deadline = time.time() + 6
    while time.time() < deadline:
        ready, _, _ = select.select([proc.stdout], [], [], 0.3)
        if ready:
            line = proc.stdout.readline()
            if not line:
                break
            if "Device" in line:
                m = mac_re.search(line)
                if m:
                    discovered[m.group(1).upper()] = m.group(2).strip()

    try:
        proc.stdin.write("scan off\nquit\n")
        proc.stdin.flush()
        proc.wait(timeout=2)
    except Exception:
        proc.kill()

    _, paired_out = _run(["bluetoothctl", "devices", "Paired"])
    paired = {d["mac"] for d in _parse_bt_lines(paired_out)}

    return jsonify([
        {"mac": mac, "name": name, "paired": mac in paired}
        for mac, name in discovered.items()
    ])


@app.post("/api/bt/connect")
def api_bt_connect():
    mac = (request.json or {}).get("mac", "").strip()
    if not mac:
        abort(400)
    rc, out = _run(["bluetoothctl", "connect", mac], timeout=15)
    return jsonify({"ok": rc == 0, "msg": out})


@app.post("/api/bt/disconnect")
def api_bt_disconnect():
    mac = (request.json or {}).get("mac", "").strip()
    if not mac:
        abort(400)
    rc, out = _run(["bluetoothctl", "disconnect", mac])
    return jsonify({"ok": rc == 0, "msg": out})


@app.post("/api/bt/pair")
def api_bt_pair():
    mac = (request.json or {}).get("mac", "").strip()
    if not mac:
        abort(400)
    rc, out = _run(["bluetoothctl", "pair", mac], timeout=20)
    if rc == 0:
        _run(["bluetoothctl", "trust", mac])
    return jsonify({"ok": rc == 0, "msg": out})


# ── API: Wi-Fi ────────────────────────────────────────────────────────────────

@app.get("/api/wifi/networks")
def api_wifi_networks():
    _run(["nmcli", "device", "wifi", "rescan"])
    time.sleep(2)
    _, out = _run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,ACTIVE",
                   "device", "wifi", "list"])
    networks, seen = [], set()
    for line in out.splitlines():
        # rsplit from right so SSIDs with colons survive
        parts = line.rsplit(":", 3)
        if len(parts) < 4:
            continue
        ssid, signal, security, active = (p.strip() for p in parts)
        if ssid and ssid not in seen:
            seen.add(ssid)
            networks.append({
                "ssid":      ssid,
                "signal":    int(signal) if signal.isdigit() else 0,
                "security":  security or "open",
                "connected": active.lower() == "yes",
            })
    networks.sort(key=lambda x: -x["signal"])
    return jsonify(networks)


@app.post("/api/wifi/connect")
def api_wifi_connect():
    data     = request.json or {}
    ssid     = data.get("ssid", "").strip()
    password = data.get("password", "").strip()
    if not ssid:
        abort(400)
    cmd = ["nmcli", "device", "wifi", "connect", ssid]
    if password:
        cmd += ["password", password]
    rc, out = _run(cmd, timeout=30)
    return jsonify({"ok": rc == 0, "msg": out})


# ── API: sync from remote CSV ─────────────────────────────────────────────────

@app.post("/api/sync")
def api_sync():
    """Fetch a remote stations.csv (SYNC_URL) and add any new stations locally."""
    if not SYNC_URL:
        return jsonify({"ok": False, "added": 0,
                        "msg": "SYNC_URL not configured in admin.py"}), 400
    try:
        req = urllib.request.Request(SYNC_URL, headers={"User-Agent": "oreloj/1"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return jsonify({"ok": False, "added": 0, "msg": str(e)}), 502

    remote = list(csv.DictReader(io.StringIO(raw)))
    local  = read_csv()
    existing_urls = {r["URL Link"].strip() for r in local if r.get("URL Link")}

    added = 0
    for row in remote:
        url = row.get("URL Link", "").strip()
        if url and url not in existing_urls:
            local.append({k: row.get(k, "") for k in CSV_FIELDS})
            existing_urls.add(url)
            added += 1

    if added:
        write_csv(local)
        _notify_globe()

    return jsonify({"ok": True, "added": added})


# ── API: git update ───────────────────────────────────────────────────────────

@app.post("/api/update")
def api_update():
    """Run `git pull origin main` on ~/globe and restart services if anything changed."""
    globe_dir = str(Path.home() / "globe")
    rc, out = _run(["git", "-C", globe_dir, "pull", "origin", "main"], timeout=30)
    if rc != 0:
        return jsonify({"ok": False, "updated": False, "msg": out, "restart": False}), 500

    updated = "Already up to date." not in out
    if updated:
        env = {**os.environ, "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"}
        # Restart globe immediately, then restart admin after a short delay
        # (admin restart kills this very response, so we detach it).
        try:
            subprocess.run(
                ["systemctl", "--user", "restart", "globe.service"],
                env=env, timeout=5, capture_output=True,
            )
            subprocess.Popen(
                ["bash", "-c",
                 "sleep 2 && systemctl --user restart admin.service"],
                env=env,
            )
        except Exception as e:
            return jsonify({"ok": True, "updated": True, "msg": out,
                            "restart": False, "warn": str(e)})
        return jsonify({"ok": True, "updated": True, "msg": out, "restart": True})

    return jsonify({"ok": True, "updated": False, "msg": out, "restart": False})


# ── captive portal ───────────────────────────────────────────────────────────
# When a device joins the Oreloj hotspot, the OS fires a background probe to
# one of these well-known URLs to test for internet.  We return a redirect
# instead of the expected response, which triggers the "Sign in to network"
# popup — automatically opening the admin UI without typing anything.
#
# Requires: iptables rule redirecting port 80 → 5000 on wlan0
# (added by oreloj-hotspot.sh when the hotspot activates).

_CAPTIVE_URL = "http://192.168.4.1:5000/"

for _path in [
    "/hotspot-detect.html",        # iOS / macOS
    "/library/test/success.html",  # macOS (older)
    "/generate_204",               # Android
    "/gen_204",                    # Android (alt)
    "/connecttest.txt",            # Windows
    "/redirect",                   # Windows (alt)
    "/ncsi.txt",                   # Windows (alt)
    "/success.txt",                # Firefox
]:
    app.add_url_rule(
        _path, f"captive_{_path.strip('/').replace('/', '_')}",
        lambda: redirect(_CAPTIVE_URL, 302),
    )


# ── Frontend ──────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Oreloj</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:ital,wght@0,400;0,700;1,400&family=Syne:wght@400;700;800&display=swap" rel="stylesheet">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:       #0e0e0e;
  --surface:  #161616;
  --surface2: #1e1e1e;
  --border:   #2e2e2e;
  --text:     #f0f0f0;
  --dim:      #888;
  --muted:    #555;
  --red:      #d42b2b;
  --red-dim:  rgba(212,43,43,0.18);
  --blue:     #2b6dd4;
  --green:    #3ecf6e;
  --pop-bg:   #141414;
  /* legacy aliases so any leftover rules still work */
  --bg1:      #161616;
  --bg2:      #1e1e1e;
  --fg:       #f0f0f0;
  --accent:   #ffffff;
  --fav:      #d42b2b;
  --danger:   #d42b2b;
  --ok:       #3ecf6e;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: 'Space Mono', monospace;
  font-size: 13px;
  line-height: 1.55;
  min-height: 100vh;
  -webkit-font-smoothing: antialiased;
}

/* ── status bar ── */
#statusbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  border-bottom: 1px dashed var(--border);
  font-size: 11px;
  color: var(--muted);
  flex-wrap: wrap;
}
.wordmark {
  font-family: 'Syne', sans-serif;
  font-weight: 800;
  font-size: 18px;
  color: var(--text);
  letter-spacing: -0.5px;
  text-decoration: underline;
  text-decoration-style: wavy;
  text-underline-offset: 5px;
  text-decoration-color: var(--red);
  margin-right: 6px;
  white-space: nowrap;
}
.pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px dashed var(--border);
  border-radius: 2px;
  font-size: 10px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  white-space: nowrap;
  color: var(--dim);
}
.dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: #3a3a3a;
  transition: background .2s, box-shadow .2s;
}
.dot.on { background: var(--red); box-shadow: 0 0 6px var(--red); }
.spacer { flex: 1; }
#btn-sync {
  background: transparent;
  border: 1px dashed var(--border);
  color: var(--muted);
  padding: 6px 11px;
  border-radius: 2px;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  cursor: pointer;
  white-space: nowrap;
  transition: color .15s, border-color .15s;
}
#btn-sync:hover { color: var(--text); border-color: var(--text); }
#btn-sync:disabled { opacity: 0.4; cursor: default; }
#btn-update {
  background: transparent;
  border: 1px dashed var(--border);
  color: var(--muted);
  padding: 6px 11px;
  border-radius: 2px;
  font-family: 'Space Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  cursor: pointer;
  white-space: nowrap;
  transition: color .15s, border-color .15s;
}
#btn-update:hover { color: var(--text); border-color: var(--text); }
#btn-update:disabled { opacity: 0.4; cursor: default; }

/* ── setup banner ── */
#setup-banner {
  background: rgba(212,43,43,0.06) !important;
  border-bottom: 1px dashed var(--red) !important;
  padding: 10px 20px !important;
  font-size: 12px !important;
  color: var(--text) !important;
}
#setup-banner strong { color: var(--red); }

/* ── tabs ── */
#tabs {
  display: flex;
  gap: 0;
  padding: 0 20px;
  border-bottom: 1px dashed var(--border);
}
.tab {
  padding: 12px 18px;
  font-family: 'Syne', sans-serif;
  font-weight: 700;
  font-size: 11px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: color .15s, border-color .15s;
  user-select: none;
}
.tab:hover  { color: var(--text); }
.tab.active { color: var(--text); border-bottom-color: var(--red); }

/* ── main content ── */
#content { padding: 26px 20px; max-width: 1100px; }
.panel { display: none; }
.panel.active { display: block; }

/* ── toolbar row ── */
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

/* ── inputs ── */
input[type="text"],
input[type="password"],
input[type="url"] {
  background: transparent;
  border: none;
  border-bottom: 1px solid var(--border);
  color: var(--text);
  padding: 6px 4px;
  font-family: 'Space Mono', monospace;
  font-size: 12px;
  outline: none;
  transition: border-color .15s;
  font-style: italic;
}
input:focus { border-bottom-color: var(--red); }
input::placeholder { color: var(--muted); font-style: italic; }

select {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 7px 10px;
  border-radius: 2px;
  font-family: 'Space Mono', monospace;
  font-size: 12px;
  outline: none;
  transition: border-color .15s;
}
select:focus { border-color: var(--red); }
select option { background: var(--surface2); }

/* ── buttons ── */
button {
  background: transparent;
  border: 1px dashed var(--border);
  color: var(--muted);
  padding: 7px 13px;
  border-radius: 2px;
  font-family: 'Syne', sans-serif;
  font-weight: 700;
  font-size: 11px;
  letter-spacing: 0.05em;
  cursor: pointer;
  white-space: nowrap;
  transition: color .15s, border-color .15s, background .15s;
}
button:hover { color: var(--text); border-color: var(--text); }
button.primary {
  background: var(--text);
  color: var(--bg);
  border: 1px solid var(--text);
}
button.primary:hover { background: #fff; border-color: #fff; color: var(--bg); }
button.ghost {
  background: transparent;
  border: 1px dashed transparent;
  color: var(--muted);
  padding: 5px 9px;
}
button.ghost:hover { color: var(--text); border-color: transparent; background: var(--surface2); }
button.danger { color: var(--red); border-color: rgba(212,43,43,0.35); }
button.danger:hover { color: #fff; background: var(--red); border-color: var(--red); }
button:disabled { opacity: 0.35; cursor: default; }

/* ── tables (stations) ── */
table { width: 100%; border-collapse: collapse; }
th {
  text-align: left;
  font-family: 'Syne', sans-serif;
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
  padding: 8px 10px;
  border-bottom: 1px dashed var(--border);
  font-weight: 700;
}
td {
  padding: 11px 10px;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: rgba(255,255,255,0.015); }

/* combined info cell (name + city / country) */
.cell-info { min-width: 0; max-width: 320px; }
.cell-info .stn-name {
  font-family: 'Syne', sans-serif;
  font-weight: 700;
  font-size: 13px;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cell-info .stn-loc {
  font-size: 11px;
  color: var(--muted);
  font-style: italic;
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* heart icon (was star) */
.cell-heart { width: 28px; text-align: center; padding: 11px 0; }
.heart {
  cursor: pointer;
  font-size: 13px;
  color: var(--muted);
  user-select: none;
  transition: color .15s;
  line-height: 1;
  display: inline-block;
}
.heart.on { color: var(--red); }
.heart:hover { color: var(--text); }

/* url cell */
.cell-url {
  font-family: ui-monospace, monospace;
  font-size: 10px;
  color: var(--muted);
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cell-url a { color: var(--muted); text-decoration: none; }
.cell-url a:hover { color: var(--text); }

.cell-actions { width: 86px; white-space: nowrap; text-align: right; }

/* edit row */
.edit-row td {
  padding: 12px 8px;
  background: var(--surface);
  border-bottom: 1px dashed var(--border);
}
.edit-row input, .edit-row select { width: 100%; font-style: normal; }
.edit-row .edit-stack { display: flex; flex-direction: column; gap: 6px; }
.edit-row .edit-row-cc { display: flex; gap: 8px; }
.edit-row .edit-row-cc input { flex: 1; }

/* ── add form ── */
#add-form {
  display: none;
  background: var(--surface);
  border: 1px dashed var(--border);
  border-radius: 2px;
  padding: 20px;
  margin-bottom: 20px;
  box-shadow: 4px 4px 0 rgba(0,0,0,0.45);
}
#add-form.visible { display: block; }
#add-form h3 {
  font-family: 'Syne', sans-serif;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 16px;
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 16px;
}
.form-grid label { display: flex; flex-direction: column; gap: 5px; }
.form-grid label span {
  font-family: 'Syne', sans-serif;
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  font-weight: 700;
}
.form-grid .full { grid-column: 1 / -1; }
.form-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }

/* ── BT / Wi-Fi sections ── */
.section { margin-bottom: 36px; }
.section h2 {
  font-family: 'Syne', sans-serif;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 14px;
  padding-bottom: 8px;
  border-bottom: 1px dashed var(--border);
}
.device-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
}
.device-row:last-child { border-bottom: none; }
.device-name {
  flex: 1;
  font-family: 'Syne', sans-serif;
  font-weight: 700;
  font-size: 13px;
  color: var(--text);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.device-mac {
  font-family: ui-monospace, monospace;
  font-size: 10px;
  color: var(--muted);
  font-style: italic;
}
.device-actions { display: flex; gap: 6px; align-items: center; }
.device-status {
  font-family: 'Syne', sans-serif;
  font-size: 9px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--red);
  margin-right: 4px;
  font-weight: 700;
}

/* ── signal bars ── */
.signal {
  display: inline-flex;
  align-items: flex-end;
  gap: 2px;
  height: 14px;
  margin-right: 8px;
}
.signal span {
  width: 3px;
  background: #3a3a3a;
  border-radius: 1px;
}
.signal span:nth-child(1) { height: 25%; }
.signal span:nth-child(2) { height: 50%; }
.signal span:nth-child(3) { height: 75%; }
.signal span:nth-child(4) { height: 100%; }
.signal.s25  span:nth-child(1) { background: var(--text); }
.signal.s50  span:nth-child(1),
.signal.s50  span:nth-child(2) { background: var(--text); }
.signal.s75  span:nth-child(1),
.signal.s75  span:nth-child(2),
.signal.s75  span:nth-child(3) { background: var(--text); }
.signal.s100 span { background: var(--text); }

/* ── password input row ── */
.pw-row {
  display: none;
  gap: 8px;
  margin-top: 0;
  padding: 10px 0;
  align-items: center;
  border-bottom: 1px solid var(--border);
}
.pw-row.visible { display: flex; }
.pw-row .pw-input {
  width: 220px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 7px 10px;
  font-style: normal;
}

/* ── toast ── */
#toast {
  position: fixed;
  bottom: 28px;
  left: 50%;
  transform: translateX(-50%) translateY(20px);
  background: var(--pop-bg);
  border: 1px dashed var(--border);
  color: var(--text);
  padding: 10px 18px;
  border-radius: 2px;
  font-family: 'Space Mono', monospace;
  font-size: 12px;
  letter-spacing: 0.03em;
  opacity: 0;
  transition: opacity .2s, transform .2s;
  pointer-events: none;
  z-index: 999;
  box-shadow: 4px 4px 0 rgba(0,0,0,0.6);
  white-space: nowrap;
}
#toast.show {
  opacity: 1;
  transform: translateX(-50%) translateY(0);
}

/* ── spinner ── */
.spin {
  display: inline-block;
  width: 11px; height: 11px;
  border: 2px solid var(--border);
  border-top-color: var(--red);
  border-radius: 50%;
  animation: spin .7s linear infinite;
  vertical-align: middle;
  margin-right: 4px;
}
@keyframes spin { to { transform: rotate(360deg); } }

.empty {
  color: var(--muted);
  font-style: italic;
  font-size: 12px;
  padding: 22px 0;
  text-align: center;
}

#search {
  width: 240px;
  font-style: italic;
}

/* ── responsive ── */
@media (max-width: 700px) {
  #content { padding: 18px 14px; }
  #statusbar { padding: 10px 14px; gap: 8px; }
  .wordmark { font-size: 15px; }
  #tabs { padding: 0 14px; overflow-x: auto; }
  .tab { padding: 12px 14px; font-size: 10px; }
  .form-grid { grid-template-columns: 1fr; }
  #search { width: 160px; }
  .cell-url { max-width: 110px; }
  .device-mac { display: none; }
  .pill { font-size: 9px; padding: 3px 7px; }
}
@media (max-width: 480px) {
  .cell-url, th.col-url { display: none; }
  .wordmark { font-size: 13px; }
}
</style>
</head>
<body>

<!-- status bar -->
<div id="statusbar">
  <span class="wordmark">ORELOJ</span>
  <span class="pill">
    <span class="dot" id="dot-play"></span>
    <span id="lbl-play">—</span>
  </span>
  <span class="pill">
    <span id="lbl-bt">BT —</span>
  </span>
  <span class="pill">
    <span id="lbl-wifi">Wi-Fi —</span>
  </span>
  <span class="spacer"></span>
  <button id="btn-sync" title="Pull new stations from oreilles.fm (configure SYNC_URL in admin.py)">↻ sync</button>
  <button id="btn-update" title="Pull latest code from GitHub and restart services">↑ update</button>
</div>

<!-- setup banner (visible only in hotspot/AP mode) -->
<div id="setup-banner" style="display:none;background:#1a1a0e;border-bottom:1px solid #3a3a10;padding:10px 20px;font-size:13px;color:#c8c870;">
  <strong>Setup mode</strong> — the globe is broadcasting a Wi-Fi hotspot.
  Use the <strong>Wi-Fi</strong> tab to connect it to a network,
  then reconnect your device and visit <strong>http://oreloj.local:5000</strong>.
</div>

<!-- tabs -->
<div id="tabs">
  <div class="tab active" data-panel="stations">Stations</div>
  <div class="tab" data-panel="bluetooth">Bluetooth</div>
  <div class="tab" data-panel="wifi">Wi-Fi</div>
</div>

<div id="content">

  <!-- ── STATIONS ─────────────────────────────────────── -->
  <div id="panel-stations" class="panel active">
    <div class="toolbar">
      <input id="search" type="text" placeholder="Search stations…">
      <button id="btn-add" class="primary">+ Add Station</button>
    </div>

    <div id="add-form">
      <h3>Add Station</h3>
      <div class="form-grid">
        <label>
          <span>Country</span>
          <input type="text" id="f-country" placeholder="France">
        </label>
        <label>
          <span>City</span>
          <input type="text" id="f-city" placeholder="Paris">
        </label>
        <label>
          <span>Station Name</span>
          <input type="text" id="f-name" placeholder="FIP">
        </label>
        <label>
          <span>Continent</span>
          <select id="f-continent">
            <option>Europe</option>
            <option>North America</option>
            <option>South America</option>
            <option>Africa</option>
            <option>Asia</option>
            <option>Oceania</option>
            <option>Global</option>
          </select>
        </label>
        <label class="full">
          <span>Stream URL</span>
          <input type="url" id="f-url" placeholder="https://…">
        </label>
        <label class="full">
          <span>Website</span>
          <input type="url" id="f-website" placeholder="https://…">
        </label>
        <label class="full">
          <span>Description</span>
          <input type="text" id="f-desc" placeholder="One-line description">
        </label>
      </div>
      <div class="form-actions">
        <button class="primary" id="btn-add-save">Save</button>
        <button id="btn-add-cancel">Cancel</button>
        <label style="display:flex;align-items:center;gap:6px;margin-left:8px;font-size:12px;cursor:pointer;">
          <input type="checkbox" id="f-fav"> Favourite
        </label>
      </div>
    </div>

    <table id="station-table">
      <thead>
        <tr>
          <th style="width:28px"></th>
          <th>Station</th>
          <th class="col-url">Stream URL</th>
          <th style="width:86px"></th>
        </tr>
      </thead>
      <tbody id="station-body">
        <tr><td colspan="4" class="empty">Loading…</td></tr>
      </tbody>
    </table>
  </div>

  <!-- ── BLUETOOTH ─────────────────────────────────────── -->
  <div id="panel-bluetooth" class="panel">
    <div class="section">
      <h2>Paired Devices</h2>
      <div id="bt-paired-list"><p class="empty">Loading…</p></div>
    </div>

    <div class="section">
      <h2>Discover Devices</h2>
      <div class="toolbar" style="margin-bottom:14px;">
        <button id="btn-bt-scan">Scan (6 s)</button>
        <span id="bt-scan-status" style="font-size:12px;color:var(--dim);"></span>
      </div>
      <div id="bt-discover-list"></div>
    </div>
  </div>

  <!-- ── WI-FI ─────────────────────────────────────────── -->
  <div id="panel-wifi" class="panel">
    <div class="section">
      <h2>Networks</h2>
      <div class="toolbar" style="margin-bottom:14px;">
        <button id="btn-wifi-scan">Scan</button>
        <span id="wifi-scan-status" style="font-size:12px;color:var(--dim);"></span>
      </div>
      <div id="wifi-list"><p class="empty">Press Scan to see available networks.</p></div>
    </div>
  </div>

</div><!-- #content -->

<div id="toast"></div>

<script>
'use strict';

// ── toast ──────────────────────────────────────────────────────────────────
const toast = document.getElementById('toast');
let toastTimer;
function showToast(msg) {
  toast.textContent = msg;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 2800);
}

// ── api ────────────────────────────────────────────────────────────────────
async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

// ── tabs ───────────────────────────────────────────────────────────────────
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('panel-' + tab.dataset.panel).classList.add('active');
    if (tab.dataset.panel === 'bluetooth') loadBtDevices();
  });
});

// ── status bar ─────────────────────────────────────────────────────────────
let hotspotMode = false;

async function refreshStatus() {
  try {
    const s = await api('GET', '/api/status');
    hotspotMode = !!s.hotspot_mode;

    const dot = document.getElementById('dot-play');
    const lbl = document.getElementById('lbl-play');
    dot.classList.toggle('on', s.playing);
    lbl.textContent = s.playing ? 'Playing' : 'Stopped';

    const btLbl = document.getElementById('lbl-bt');
    btLbl.textContent = s.bt.length
      ? 'BT: ' + s.bt.map(d => d.name).join(', ')
      : 'BT —';

    const wifiLbl = document.getElementById('lbl-wifi');
    wifiLbl.textContent = hotspotMode ? 'Hotspot active'
      : s.wifi ? 'Wi-Fi: ' + s.wifi : 'Wi-Fi —';

    document.getElementById('setup-banner').style.display =
      hotspotMode ? 'block' : 'none';
  } catch (e) { /* offline */ }
}
refreshStatus();
setInterval(refreshStatus, 10000);

// ── stations ───────────────────────────────────────────────────────────────
let stations = [];
let editingIdx = null;

async function loadStations() {
  stations = await api('GET', '/api/stations');
  renderStations();
}

function renderStations() {
  const q = document.getElementById('search').value.toLowerCase();
  const tbody = document.getElementById('station-body');
  tbody.innerHTML = '';

  const filtered = stations
    .map((s, i) => ({ ...s, _i: i }))
    .filter(s => !q ||
      s['Radio Station'].toLowerCase().includes(q) ||
      s['Country'].toLowerCase().includes(q) ||
      s['City'].toLowerCase().includes(q));

  if (!filtered.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="empty">No stations found.</td></tr>';
    return;
  }

  filtered.forEach(s => {
    if (editingIdx === s._i) {
      tbody.appendChild(buildEditRow(s._i));
      return;
    }
    const tr = document.createElement('tr');
    tr.dataset.idx = s._i;
    const fav = s['Favourite'].toLowerCase() === 'yes';
    const url = s['URL Link'];
    const city = (s['City'] || '').trim();
    const country = (s['Country'] || '').trim();
    const loc = [city, country].filter(Boolean).join(', ') || '—';
    tr.innerHTML = `
      <td class="cell-heart"><span class="heart ${fav ? 'on' : ''}" data-idx="${s._i}" title="Toggle favourite">♥</span></td>
      <td class="cell-info">
        <div class="stn-name">${esc(s['Radio Station'])}</div>
        <div class="stn-loc">${esc(loc)}</div>
      </td>
      <td class="cell-url col-url">${url
        ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(truncate(url,40))}</a>`
        : '<span style="color:var(--border)">—</span>'}</td>
      <td class="cell-actions">
        <button class="ghost btn-edit" data-idx="${s._i}" title="Edit">✎</button>
        <button class="ghost danger btn-del" data-idx="${s._i}" title="Delete">×</button>
      </td>`;
    tbody.appendChild(tr);
  });

  // fav toggles
  tbody.querySelectorAll('.heart').forEach(el => {
    el.addEventListener('click', async () => {
      const idx = +el.dataset.idx;
      const cur = stations[idx]['Favourite'].toLowerCase() === 'yes';
      await api('PUT', `/api/stations/${idx}`, { 'Favourite': cur ? '' : 'yes' });
      await loadStations();
    });
  });

  // edit buttons
  tbody.querySelectorAll('.btn-edit').forEach(el => {
    el.addEventListener('click', () => {
      editingIdx = +el.dataset.idx;
      renderStations();
    });
  });

  // delete buttons
  tbody.querySelectorAll('.btn-del').forEach(el => {
    el.addEventListener('click', async () => {
      const idx = +el.dataset.idx;
      const name = stations[idx]['Radio Station'];
      if (!confirm(`Delete "${name}"?`)) return;
      await api('DELETE', `/api/stations/${idx}`);
      showToast(`Deleted: ${name}`);
      await loadStations();
    });
  });
}

function buildEditRow(idx) {
  const s = stations[idx];
  const tr = document.createElement('tr');
  tr.className = 'edit-row';
  tr.innerHTML = `
    <td></td>
    <td class="cell-info">
      <div class="edit-stack">
        <input type="text" class="e-name" value="${esc(s['Radio Station'])}" placeholder="Station name">
        <div class="edit-row-cc">
          <input type="text" class="e-city" value="${esc(s['City'])}" placeholder="City">
          <input type="text" class="e-country" value="${esc(s['Country'])}" placeholder="Country">
        </div>
      </div>
    </td>
    <td class="col-url"><input type="url" class="e-url" value="${esc(s['URL Link'])}" placeholder="Stream URL"></td>
    <td class="cell-actions">
      <button class="primary btn-edit-save" data-idx="${idx}">✓</button>
      <button class="ghost btn-edit-cancel">✕</button>
    </td>`;

  tr.querySelector('.btn-edit-save').addEventListener('click', async () => {
    await api('PUT', `/api/stations/${idx}`, {
      'Country':       tr.querySelector('.e-country').value,
      'City':          tr.querySelector('.e-city').value,
      'Radio Station': tr.querySelector('.e-name').value,
      'URL Link':      tr.querySelector('.e-url').value,
    });
    editingIdx = null;
    showToast('Saved');
    await loadStations();
  });

  tr.querySelector('.btn-edit-cancel').addEventListener('click', () => {
    editingIdx = null;
    renderStations();
  });

  return tr;
}

// search
document.getElementById('search').addEventListener('input', renderStations);

// add form
const addForm = document.getElementById('add-form');
document.getElementById('btn-add').addEventListener('click', () => {
  addForm.classList.toggle('visible');
});
document.getElementById('btn-add-cancel').addEventListener('click', () => {
  addForm.classList.remove('visible');
});
document.getElementById('btn-add-save').addEventListener('click', async () => {
  const row = {
    'Continent':     document.getElementById('f-continent').value,
    'Country':       document.getElementById('f-country').value.trim(),
    'City':          document.getElementById('f-city').value.trim(),
    'Radio Station': document.getElementById('f-name').value.trim(),
    'Description':   document.getElementById('f-desc').value.trim(),
    'Website':       document.getElementById('f-website').value.trim(),
    'URL Link':      document.getElementById('f-url').value.trim(),
    'Favourite':     document.getElementById('f-fav').checked ? 'yes' : '',
  };
  if (!row['Radio Station']) { showToast('Station name required'); return; }
  await api('POST', '/api/stations', row);
  showToast(`Added: ${row['Radio Station']}`);
  addForm.classList.remove('visible');
  ['f-country','f-city','f-name','f-url','f-website','f-desc'].forEach(id => {
    document.getElementById(id).value = '';
  });
  document.getElementById('f-fav').checked = false;
  await loadStations();
});

loadStations();

// ── Sync button ────────────────────────────────────────────────────────────
document.getElementById('btn-sync').addEventListener('click', async () => {
  const btn = document.getElementById('btn-sync');
  btn.disabled = true;
  btn.textContent = '↻ syncing…';
  try {
    const r = await api('POST', '/api/sync');
    if (r.ok) {
      showToast(r.added > 0
        ? `Synced — ${r.added} new station(s) added`
        : 'Already up to date');
      if (r.added > 0) await loadStations();
    } else {
      showToast('Sync failed: ' + r.msg.slice(0, 60));
    }
  } catch(e) {
    showToast('Sync error — check SYNC_URL in admin.py');
  } finally {
    btn.disabled = false;
    btn.textContent = '↻ sync';
  }
});

// ── Update button ──────────────────────────────────────────────────────────
document.getElementById('btn-update').addEventListener('click', async () => {
  const btn = document.getElementById('btn-update');
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span> updating…';
  try {
    const r = await api('POST', '/api/update');
    if (r.ok) {
      if (r.restart) {
        showToast('Updated — restarting…');
        // admin.service will restart itself; warn and trigger a page reload
        setTimeout(() => {
          toast.textContent = 'Reloading in 3 s…';
          toast.classList.add('show');
          setTimeout(() => location.reload(), 3000);
        }, 1200);
      } else {
        showToast(r.msg.includes('Already up to date') ? 'Already up to date' : r.msg.slice(0, 80));
        btn.disabled = false;
        btn.textContent = '↑ update';
      }
    } else {
      showToast('Update failed: ' + (r.msg || '').slice(0, 60));
      btn.disabled = false;
      btn.textContent = '↑ update';
    }
  } catch(e) {
    showToast('Update error — check Pi connection');
    btn.disabled = false;
    btn.textContent = '↑ update';
  }
});

// ── Bluetooth ──────────────────────────────────────────────────────────────
async function loadBtDevices() {
  const list = document.getElementById('bt-paired-list');
  list.innerHTML = '<p class="empty"><span class="spin"></span> Loading…</p>';
  try {
    const devices = await api('GET', '/api/bt/devices');
    renderBtPaired(devices);
  } catch(e) {
    list.innerHTML = '<p class="empty">Could not load devices.</p>';
  }
}

function renderBtPaired(devices) {
  const list = document.getElementById('bt-paired-list');
  if (!devices.length) {
    list.innerHTML = '<p class="empty">No paired devices.</p>';
    return;
  }
  list.innerHTML = '';
  devices.forEach(d => {
    const row = document.createElement('div');
    row.className = 'device-row';
    row.innerHTML = `
      <div class="device-name">${esc(d.name)}</div>
      <div class="device-mac">${esc(d.mac)}</div>
      <div class="device-actions">
        ${d.connected
          ? `<span class="device-status">● Connected</span>
             <button class="danger btn-bt-disc" data-mac="${esc(d.mac)}">Disconnect</button>`
          : `<button class="btn-bt-conn" data-mac="${esc(d.mac)}">Connect</button>`}
      </div>`;
    list.appendChild(row);
  });

  list.querySelectorAll('.btn-bt-conn').forEach(btn => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      btn.textContent = '…';
      try {
        const r = await api('POST', '/api/bt/connect', { mac: btn.dataset.mac });
        showToast(r.ok ? 'Connected' : 'Failed: ' + r.msg.slice(0,60));
      } finally {
        await loadBtDevices();
      }
    });
  });

  list.querySelectorAll('.btn-bt-disc').forEach(btn => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        const r = await api('POST', '/api/bt/disconnect', { mac: btn.dataset.mac });
        showToast(r.ok ? 'Disconnected' : 'Failed: ' + r.msg.slice(0,60));
      } finally {
        await loadBtDevices();
        refreshStatus();
      }
    });
  });
}

document.getElementById('btn-bt-scan').addEventListener('click', async () => {
  const btn = document.getElementById('btn-bt-scan');
  const status = document.getElementById('bt-scan-status');
  const discList = document.getElementById('bt-discover-list');

  btn.disabled = true;
  status.innerHTML = '<span class="spin"></span> Scanning…';
  discList.innerHTML = '';

  try {
    const devices = await api('POST', '/api/bt/scan');
    status.textContent = `Found ${devices.length} device(s)`;

    if (!devices.length) {
      discList.innerHTML = '<p class="empty">No devices found.</p>';
    } else {
      discList.innerHTML = '';
      devices.forEach(d => {
        const row = document.createElement('div');
        row.className = 'device-row';
        row.innerHTML = `
          <div class="device-name">${esc(d.name)}</div>
          <div class="device-mac">${esc(d.mac)}</div>
          <div class="device-actions">
            ${d.paired
              ? `<span style="font-size:10px;color:var(--muted);font-style:italic;">Paired</span>`
              : `<button class="btn-bt-pair" data-mac="${esc(d.mac)}" data-name="${esc(d.name)}">Pair</button>`}
          </div>`;
        discList.appendChild(row);
      });

      discList.querySelectorAll('.btn-bt-pair').forEach(btn => {
        btn.addEventListener('click', async () => {
          btn.disabled = true;
          btn.textContent = '…';
          const r = await api('POST', '/api/bt/pair', { mac: btn.dataset.mac });
          showToast(r.ok ? `Paired: ${btn.dataset.name}` : 'Pairing failed: ' + r.msg.slice(0,50));
          if (r.ok) {
            btn.textContent = 'Paired ✓';
            await loadBtDevices();
          } else {
            btn.disabled = false;
            btn.textContent = 'Pair';
          }
        });
      });
    }
  } catch(e) {
    status.textContent = 'Scan failed';
  } finally {
    btn.disabled = false;
  }
});

// ── Wi-Fi ──────────────────────────────────────────────────────────────────
document.getElementById('btn-wifi-scan').addEventListener('click', async () => {
  const btn    = document.getElementById('btn-wifi-scan');
  const status = document.getElementById('wifi-scan-status');
  const list   = document.getElementById('wifi-list');

  btn.disabled = true;
  status.innerHTML = '<span class="spin"></span> Scanning…';
  list.innerHTML = '';

  try {
    const networks = await api('GET', '/api/wifi/networks');
    status.textContent = `${networks.length} network(s)`;
    renderWifiList(networks);
  } catch(e) {
    status.textContent = 'Scan failed';
    list.innerHTML = '<p class="empty">Could not scan networks.</p>';
  } finally {
    btn.disabled = false;
  }
});

function renderWifiList(networks) {
  const list = document.getElementById('wifi-list');
  if (!networks.length) {
    list.innerHTML = '<p class="empty">No networks found.</p>';
    return;
  }
  list.innerHTML = '';
  networks.forEach(n => {
    const wrap = document.createElement('div');
    const sigClass = n.signal >= 75 ? 's100'
                   : n.signal >= 50 ? 's75'
                   : n.signal >= 25 ? 's50' : 's25';
    wrap.innerHTML = `
      <div class="device-row">
        <div class="device-name">
          <span class="signal ${sigClass}">
            <span></span><span></span><span></span><span></span>
          </span>
          ${esc(n.ssid)}
          ${n.connected ? '<span class="device-status" style="margin-left:8px;">● Connected</span>' : ''}
        </div>
        <div class="device-mac">${esc(n.security)}</div>
        <div class="device-actions">
          ${n.connected
            ? ''
            : `<button class="btn-wifi-conn" data-ssid="${esc(n.ssid)}" data-sec="${esc(n.security)}">Connect</button>`}
        </div>
      </div>
      <div class="pw-row" id="pw-${CSS.escape(n.ssid)}">
        <input type="password" placeholder="Password" class="pw-input" style="width:200px;">
        <button class="primary btn-wifi-do" data-ssid="${esc(n.ssid)}">Connect</button>
        <button class="ghost btn-wifi-cancel" data-ssid="${esc(n.ssid)}">Cancel</button>
      </div>`;
    list.appendChild(wrap);
  });

  list.querySelectorAll('.btn-wifi-conn').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = `pw-${CSS.escape(btn.dataset.ssid)}`;
      const row = document.getElementById(id);
      if (row) row.classList.add('visible');
      btn.style.display = 'none';
    });
  });

  list.querySelectorAll('.btn-wifi-cancel').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = `pw-${CSS.escape(btn.dataset.ssid)}`;
      const row = document.getElementById(id);
      if (row) row.classList.remove('visible');
      // re-show connect button
      const connBtn = list.querySelector(`.btn-wifi-conn[data-ssid="${btn.dataset.ssid}"]`);
      if (connBtn) connBtn.style.display = '';
    });
  });

  list.querySelectorAll('.btn-wifi-do').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = `pw-${CSS.escape(btn.dataset.ssid)}`;
      const row = document.getElementById(id);
      const pw  = row ? row.querySelector('.pw-input').value : '';
      btn.disabled = true;
      const orig = btn.textContent;
      btn.textContent = '…';
      try {
        const r = await api('POST', '/api/wifi/connect', { ssid: btn.dataset.ssid, password: pw });
        if (r.ok && hotspotMode) {
          // Hotspot will drop — show persistent reconnect instructions
          document.getElementById('wifi-list').innerHTML = `
            <div style="padding:20px 0;line-height:1.7;color:var(--fg);">
              <div style="font-size:18px;margin-bottom:12px;">✓ Connected to <strong>${esc(btn.dataset.ssid)}</strong></div>
              <div style="color:var(--dim);">
                The hotspot is closing. On your device:<br>
                1. Rejoin your Wi-Fi network (<strong>${esc(btn.dataset.ssid)}</strong>)<br>
                2. Open <strong>http://oreloj.local:5000</strong>
              </div>
            </div>`;
          document.getElementById('setup-banner').style.display = 'none';
        } else if (r.ok) {
          showToast(`Connected to ${btn.dataset.ssid}`);
          await refreshStatus();
        } else {
          showToast('Failed: ' + r.msg.slice(0, 60));
        }
      } finally {
        btn.disabled = false;
        btn.textContent = orig;
      }
    });
  });
}

// ── utils ──────────────────────────────────────────────────────────────────
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  })[c]);
}
function truncate(s, n) {
  return s.length > n ? s.slice(0, n) + '…' : s;
}
</script>
</body>
</html>"""

# ── run ───────────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return render_template_string(HTML)


if __name__ == "__main__":
    print("Oreloj admin — http://oreloj.local:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
