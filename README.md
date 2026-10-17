# Brussels shared-mobility GBFS archive

Every fifteen minutes a GitHub Actions workflow fetches the public GBFS feeds of the shared-mobility operators in the Brussels-Capital Region and stores a compact snapshot. The feeds are live only and keep no history. This archive keeps it.

Started 17 October 2026. Context: Lime left Brussels on 2 July 2025. Bolt and Dott are due to leave on 1 January 2027. The archive records the fleets before and after.

## Layout

The snapshots are release assets, one release per day, tagged `snap-YYYY-MM-DD`. Each asset is a gzip CSV named `<operator>_<HHMM>Z_vehicles.csv.gz` or `<operator>_<HHMM>Z_stations.csv.gz`. The git tree holds only the code, the daily metadata and the logs, so it stays small.

- `<operator>_<HHMM>Z_vehicles.csv.gz`: one row per vehicle on the street at that minute (id, position, vehicle type, disabled, reserved, range). Operators rotate vehicle ids for privacy, as the GBFS standard requires, so an id is not a vehicle over time.
- `<operator>_<HHMM>Z_stations.csv.gz`: one row per docking station (vehicles and docks available, by vehicle type where published). Docked systems only (Villo, nextbike); the virtual parking zones of Bolt and Dott are not stored, their vehicle positions carry the same information.
- `meta/<operator>/<YYYY-MM-DD>/`: the slow-changing feeds once a day: system information, vehicle types, station information, geofencing zones (service area and rules), pricing plans.
- `logs/<YYYY-MM>.log`: one block per run with row counts and failures.

To download a day: `gh release download snap-2026-10-18 --dir snapshots/2026-10-18`.

## Operators and feeds

See `feeds.json`. Discovery addresses come from the MobilityData `systems.csv`. The feeds are published by the operators under their own terms; this archive stores them as published and adds nothing.

| Operator | What | GBFS |
|---|---|---|
| Bolt | e-scooters and e-bikes, free-floating | 3.0 |
| Dott | e-scooters and e-bikes, free-floating | 2.3 |
| Villo (JCDecaux) | docked bikes, 360 stations | 3.0 |
| Cooltra (Felyx) | shared mopeds | 3.0 |
| nextbike Vlaamse Rand | docked and free bikes around Brussels | 2.3 |
| Lime | left Brussels in July 2025; feed kept for the record | 2.2 |

## Use

Trips can be inferred from vehicles that disappear from one position and reappear at another between snapshots, at the fleet level. Fleet size, service area (geofencing) and station stock come straight from the files.

Maintainer: Alessandro La Delfa, Ghent University.
