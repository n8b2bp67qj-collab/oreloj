#!/usr/bin/env python3
"""Health-check every stream URL in stations.csv.

A station is healthy when its URL actually serves audio — not an HTML page,
not a 404, not a dead host. Webpages are the sneakiest failure: mpv opens
them, finds no audio and exits silently, so the globe announces a station
and then plays nothing.

Usage:
    python3 check_stations.py [stations.csv] [--all] [--workers N] [--timeout S]

Exit code 0 = all healthy, 1 = at least one problem (cron-friendly).
"""

import argparse, csv, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

AUDIO_TYPES = ("audio/", "application/ogg", "application/octet-stream", "video/mp2t")
PLAYLIST_TYPES = ("mpegurl", "x-scpls", "pls+xml")
HEADERS = {"User-Agent": "oreloj-station-check/1.0", "Icy-MetaData": "1"}


def probe(url: str, timeout: float, _depth: int = 0) -> tuple[bool, str]:
    """Return (healthy, detail). Follows one level of .m3u/.pls playlist."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, stream=True,
                         allow_redirects=True)
    except requests.exceptions.Timeout:
        return False, "timeout"
    except requests.exceptions.RequestException as e:
        return False, f"unreachable ({type(e).__name__})"
    try:
        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}"
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if any(ctype.startswith(t) for t in AUDIO_TYPES) or "icy-name" in {k.lower() for k in r.headers}:
            return True, ctype or "icy stream"
        if any(t in ctype for t in PLAYLIST_TYPES) or url.split("?")[0].endswith((".m3u", ".m3u8", ".pls")):
            if _depth > 0:
                return False, "nested playlist"
            body = r.raw.read(4096, decode_content=True).decode("utf-8", "replace")
            targets = [ln.split("=", 1)[-1].strip() for ln in body.splitlines()
                       if ln.strip().startswith("http") or ln.strip().lower().startswith("file")]
            targets = [t for t in targets if t.startswith("http")]
            if not targets:
                return False, "empty playlist"
            return probe(targets[0], timeout, _depth + 1)
        if ctype.startswith("text/html"):
            return False, "webpage, not a stream"
        return False, f"not audio ({ctype or 'no content-type'})"
    finally:
        r.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv", nargs="?", default="stations.csv", type=Path)
    ap.add_argument("--all", action="store_true", help="list healthy stations too")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--timeout", type=float, default=8.0)
    args = ap.parse_args()

    if not args.csv.exists():
        print(f"ERROR: {args.csv} not found"); return 2
    with open(args.csv, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("URL Link") or "").strip()]

    def job(row):
        ok, detail = probe(row["URL Link"].strip(), args.timeout)
        return row, ok, detail

    bad = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for row, ok, detail in pool.map(job, rows):
            name = f"{row.get('Radio Station', '?')} ({row.get('Country', '?')})"
            if not ok:
                bad += 1
                print(f"  ✗  {name:<45} {detail}\n      {row['URL Link']}")
            elif args.all:
                print(f"  ✓  {name:<45} {detail}")

    print(f"\n{len(rows) - bad}/{len(rows)} stations healthy" + (f" — {bad} need fixing" if bad else " ✓"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
