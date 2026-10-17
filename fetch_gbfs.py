"""Archive the public GBFS feeds of Brussels shared-mobility operators.

Each run writes one compact CSV per operator with the vehicle or station status
at the time of the run, under data/<operator>/<YYYY-MM-DD>/<HHMM>Z.csv.
Once a day (first run after 03:00 UTC, or when the file is missing) it also
stores the slow-changing feeds (system_information, vehicle_types,
station_information, geofencing_zones, system_pricing_plans) as JSON under
meta/<operator>/<YYYY-MM-DD>/.

Standard library only. Python 3.10 or later.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FEEDS = json.loads((ROOT / "feeds.json").read_text(encoding="utf-8"))
UA = "brussels-gbfs-archive/1.0 (+https://github.com/aleladelfa/brussels-gbfs-archive)"
TIMEOUT = 40

VEHICLE_FIELDS = [
    "id", "lat", "lon", "vehicle_type_id", "is_disabled", "is_reserved",
    "current_range_meters", "current_fuel_percent", "station_id",
    "pricing_plan_id", "last_reported",
]
STATION_FIELDS = [
    "station_id", "num_vehicles_available", "num_vehicles_disabled",
    "num_docks_available", "num_docks_disabled", "is_installed",
    "is_renting", "is_returning", "vehicle_types_available", "last_reported",
]
META_FEEDS = [
    "system_information", "vehicle_types", "station_information",
    "geofencing_zones", "system_pricing_plans",
]


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as err:  # noqa: BLE001
            last_err = err
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"failed after 3 attempts: {url}: {last_err}")


def feed_urls(discovery: dict) -> dict[str, str]:
    """Map feed name to URL for GBFS 2.x (per language) and 3.0 (flat)."""
    data = discovery.get("data", {})
    feeds = data.get("feeds")
    if feeds is None:
        # GBFS 2.x: {"en": {"feeds": [...]}, "fr": {...}}
        for lang in ("en", "fr", "nl"):
            if lang in data and "feeds" in data[lang]:
                feeds = data[lang]["feeds"]
                break
        if feeds is None and data:
            feeds = next(iter(data.values())).get("feeds", [])
    return {f["name"]: f["url"] for f in feeds or []}


def norm_vehicle(row: dict) -> dict:
    out = {k: "" for k in VEHICLE_FIELDS}
    out["id"] = row.get("vehicle_id") or row.get("bike_id") or ""
    for k in VEHICLE_FIELDS[1:]:
        v = row.get(k)
        if v is None:
            continue
        if isinstance(v, bool):
            v = int(v)
        if isinstance(v, float) and k in ("lat", "lon"):
            v = f"{v:.6f}"
        out[k] = v
    return out


def norm_station(row: dict) -> dict:
    out = {k: "" for k in STATION_FIELDS}
    for k in STATION_FIELDS:
        v = row.get(k)
        if k == "num_vehicles_available" and v is None:
            v = row.get("num_bikes_available")
        if k == "num_vehicles_disabled" and v is None:
            v = row.get("num_bikes_disabled")
        if v is None:
            continue
        if isinstance(v, bool):
            v = int(v)
        if k == "vehicle_types_available" and isinstance(v, list):
            v = ";".join(f"{t.get('vehicle_type_id')}:{t.get('count')}" for t in v)
        out[k] = v
    return out


def write_csv(path: Path, fields: list[str], rows: list[dict], snapshot: str, source_updated) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["snapshot_utc", "source_last_updated", *fields])
        w.writeheader()
        for r in rows:
            w.writerow({"snapshot_utc": snapshot, "source_last_updated": source_updated, **r})


def archive_operator(name: str, cfg: dict | str, now: datetime, log: list[str]) -> None:
    if isinstance(cfg, str):
        cfg = {"url": cfg, "stations": True}
    discovery_url = cfg["url"]
    want_stations = bool(cfg.get("stations", True))
    stamp = now.strftime("%H%M") + "Z"
    day = now.strftime("%Y-%m-%d")
    snapshot = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        urls = feed_urls(get_json(discovery_url))
    except Exception as err:  # noqa: BLE001
        log.append(f"{name}: discovery failed: {err}")
        return

    # Vehicles (free-floating or docked bikes with positions)
    vurl = urls.get("vehicle_status") or urls.get("free_bike_status")
    if vurl:
        try:
            d = get_json(vurl)
            rows = d.get("data", {}).get("vehicles") or d.get("data", {}).get("bikes") or []
            rows = sorted((norm_vehicle(r) for r in rows), key=lambda r: str(r["id"]))
            write_csv(ROOT / "data" / name / day / f"{name}_{stamp}_vehicles.csv", VEHICLE_FIELDS, rows, snapshot, d.get("last_updated"))
            log.append(f"{name}: {len(rows)} vehicles")
        except Exception as err:  # noqa: BLE001
            log.append(f"{name}: vehicles failed: {err}")

    # Stations (docked systems only; Bolt and Dott publish thousands of virtual zones)
    surl = urls.get("station_status")
    if surl and want_stations:
        try:
            d = get_json(surl)
            rows = d.get("data", {}).get("stations") or []
            rows = sorted((norm_station(r) for r in rows), key=lambda r: str(r["station_id"]))
            if rows:
                write_csv(ROOT / "data" / name / day / f"{name}_{stamp}_stations.csv", STATION_FIELDS, rows, snapshot, d.get("last_updated"))
                log.append(f"{name}: {len(rows)} stations")
        except Exception as err:  # noqa: BLE001
            log.append(f"{name}: stations failed: {err}")

    # Slow-changing feeds: checked once a day, stored only when the content changed.
    # meta/<operator>/latest/<feed>.json holds the current copy; a dated folder gets
    # a copy on the day the content differs from the stored one.
    latest_dir = ROOT / "meta" / name / "latest"
    marker = latest_dir / f".checked-{day}"
    if not marker.exists() and (now.hour >= 3 or os.environ.get("FORCE_META")):
        latest_dir.mkdir(parents=True, exist_ok=True)
        for f in [*META_FEEDS, "gbfs"]:
            if f != "gbfs" and f not in urls:
                continue
            try:
                payload = urls if f == "gbfs" else get_json(urls[f])
                if isinstance(payload, dict):
                    payload = {k: v for k, v in payload.items() if k not in ("last_updated", "ttl")}
                text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1)
                target = latest_dir / f"{f}.json"
                if not target.exists() or target.read_text(encoding="utf-8") != text:
                    target.write_text(text, encoding="utf-8")
                    dated = ROOT / "meta" / name / day
                    dated.mkdir(parents=True, exist_ok=True)
                    (dated / f"{f}.json").write_text(text, encoding="utf-8")
                    log.append(f"{name}: meta {f} changed, stored")
            except Exception as err:  # noqa: BLE001
                log.append(f"{name}: meta {f} failed: {err}")
        for old in latest_dir.glob(".checked-*"):
            old.unlink()
        marker.write_text(snapshot, encoding="utf-8")


def main() -> int:
    now = datetime.now(timezone.utc)
    log: list[str] = [f"run {now.isoformat()}"]
    for name, cfg in FEEDS.items():
        archive_operator(name, cfg, now, log)
    (ROOT / "logs").mkdir(exist_ok=True)
    with (ROOT / "logs" / f"{now.strftime('%Y-%m')}.log").open("a", encoding="utf-8") as fh:
        fh.write("\n".join(log) + "\n")
    print("\n".join(log))
    return 0


if __name__ == "__main__":
    sys.exit(main())
