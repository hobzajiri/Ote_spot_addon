# OTE Spot Prices Home Assistant Add-on

Local Home Assistant add-on that fetches 15-minute electricity spot prices and publishes them to Home Assistant as `sensor.ote_spot_15min`.

## HACS vs Home Assistant add-ons

**This repository is a Supervisor add-on** (Docker container managed by Home Assistant).  
**HACS does not install add-ons.** HACS is for custom integrations, Lovelace plugins, themes, etc.

To use this project, install it from the **Home Assistant Add-on Store** by adding this GitHub repository as a **custom add-on repository** (see below).  
If you need HACS-only workflows, you would need a separate **custom integration** project (different structure than this repo).

## Publish to GitHub

1. Create a new empty repository on GitHub (no README/license required).
2. In this folder:

```bash
git init
git add .
git commit -m "Initial OTE spot prices add-on"
git branch -M main
git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git
git push -u origin main
```

Replace the URL with your repository. Use SSH if you prefer (`git@github.com:...`).

### Versioning and git tags

Home Assistant reads the add-on version from `config.yaml` → `version:`. Git tags are always `v` + that value.

**Option A — set version and release in one go** (updates `config.yaml`, commits that file, pushes branch, creates tag, pushes tag):

```bash
./scripts/release.sh 1.0.4
# same: ./scripts/release.sh --version 1.0.4   or   ./scripts/release.sh v1.0.4
```

**Option B — version already in `config.yaml`** (only tag + push):

```bash
./scripts/release.sh
```

If the branch is already on GitHub and you only want to tag the current commit:

```bash
./scripts/release.sh --no-push-branch
```

Dry-run (no file changes, commits, pushes, or tags):

```bash
./scripts/release.sh 1.0.4 --dry-run
./scripts/release.sh --dry-run
```

Only write `config.yaml` (no git operations):

```bash
python3 scripts/tag_from_config.py --set-version 1.0.4
```

Manual tag after editing `config.yaml` yourself:

```bash
python3 scripts/tag_from_config.py
git push origin TAG   # script prints the tag, e.g. v1.0.3
```

Preview tag from current `config.yaml`:

```bash
python3 scripts/tag_from_config.py --dry-run
```

On GitHub, when you push a tag `v*`, the workflow **Verify version on tag** fails if the tag does not match `version:` on that commit.

## Install in Home Assistant (Add-on Store)

Requires **Home Assistant OS** or **Supervised** (Supervisor). Not available on plain Container/Core-only installs in the same way.

This repo includes **`repository.yaml`** in the root. Supervisor **requires** that file for custom Git repositories; without it you get *“is not a valid add-on repository”* even if `config.yaml` and `Dockerfile` exist.

1. **Settings → Add-ons → Add-on Store**.
2. Open the **⋮** menu (top right) → **Repositories**.
3. Add your GitHub repo URL, e.g. `https://github.com/YOUR_USER/YOUR_REPO`  
   Use the default branch (usually `main`). No trailing slash; `https://` is fine.
4. After refresh, find **OTE Spot Prices** (`slug`: `ote_spot_prices`), **Install**, then **Start**.
5. Optional: open **Configuration** and set options (URL, intervals, timezone, daily refresh time).

The add-on creates/updates entity `sensor.ote_spot_15min` via the internal Supervisor API.

**Build failures on Supervisor:** the image must use Home Assistant base images from `build.yaml` and install dependencies with **`apk`** (Alpine), not `pip` on a Debian `python:*` image. See `Dockerfile` and `build.yaml` in this repo.

## Features

- Fetches OTE spot prices in 15-minute slots.
- Converts prices from MWh to kWh for easier dashboard usage.
- Pushes current slot price to Home Assistant using the Supervisor API.
- Stores the complete forecast in sensor attributes for ApexCharts or template sensors.
- Handles transient HTTP errors without crashing.

## Files

- `repository.yaml` - Store metadata required by Supervisor for custom Git repos.
- `build.yaml` - Official HA base image per architecture (required for Supervisor builds).
- `config.yaml` - Add-on metadata.
- `Dockerfile` - Container build (Alpine + `py3-requests`).
- `rootfs/etc/services.d/ote-spot/run` - s6 longrun so logs appear in the add-on log (unbuffered Python).
- `run.py` - Main update loop.

## Home Assistant Sensor

Entity ID:

- `sensor.ote_spot_15min`

State:

- Current 15-minute price in `CZK/kWh`.

Key attributes:

- `forecast_15min` (all slots returned by the API, today + tomorrow when available)
- `forecast_today_15min` / `forecast_tomorrow_15min` (split by local calendar day; use for “tomorrow” charts)
- `forecast_today_date` / `forecast_tomorrow_date` (ISO dates in `local_timezone`)
- `has_tomorrow_prices` (`true` once tomorrow’s auction data is in the feed, usually after ~13:00 local)
- `current_slot_start`
- `current_price_mwh`
- `last_update_utc`

Tomorrow’s prices are not in the API until OTE publishes them (often around 13:00 local, sometimes a few minutes later). The add-on calls the same JSON endpoint as your browser; there is no separate “tomorrow-only” URL—`hoursTomorrow` is either filled or empty in that response.

With `daily_refresh_time` set, the add-on **retries** every 15 minutes if the fetch succeeds but tomorrow is still empty, until `has_tomorrow_prices` becomes true; it retries every 5 minutes after a failed fetch or failed HA push. Once tomorrow’s data is present, the next API fetch is scheduled at the following day’s `daily_refresh_time` (normal 24 h cadence).

### Chart example (ApexCharts card)

Requires [ApexCharts card](https://github.com/RomRider/apexcharts-card).

**Rolling 24 hours forward from “now”** (from the **start of the current minute** through the next 24 h — `span.start: minute` + `graph_span: 24h` in `apexcharts-card`):

- Without `span`, the default `graph_span: 24h` is the **past** 24 hours, not the future.
- **Column chart:** every **15-minute** step in the window gets one bar. Known prices come from **today + tomorrow**; any slot without data (e.g. zítra ještě není v API) uses **0** so the chart stays full.

```yaml
type: custom:apexcharts-card
header:
  title: Spot (24 h dopředu)
graph_span: 24h
span:
  start: minute
now:
  show: true
  label: Teď
update_interval: 5min
series:
  - entity: sensor.ote_spot_15min
    type: column
    name: CZK/kWh
    data_generator: |
      const t1 = end.getTime();
      const STEP = 15 * 60 * 1000;
      const today = entity.attributes.forecast_today_15min || [];
      const tomorrow = entity.attributes.forecast_tomorrow_15min || [];
      const bySlot = new Map();
      for (const r of [...today, ...tomorrow]) {
        bySlot.set(new Date(r.start).getTime(), Number(r.price_kwh));
      }
      let m = moment(start).seconds(0).milliseconds(0);
      const rem = m.minute() % 15;
      if (rem) m = m.subtract(rem, 'minutes');
      const out = [];
      for (let t = m.valueOf(); t < t1; t += STEP) {
        let y = 0;
        if (bySlot.has(t)) y = bySlot.get(t);
        else {
          for (const [ts, v] of bySlot) {
            if (ts >= t && ts < t + STEP) {
              y = v;
              break;
            }
          }
        }
        out.push([t, y]);
      }
      return out;
```

Calendar **tomorrow only** (needs a fixed day window — here still **columns** and **0** for missing slots; adjust `span` if you want a different day):

```yaml
type: custom:apexcharts-card
header:
  title: Spot zítra (15 min)
graph_span: 24h
span:
  start: day
  offset: 1d
series:
  - entity: sensor.ote_spot_15min
    type: column
    name: CZK/kWh
    data_generator: |
      const t1 = end.getTime();
      const STEP = 15 * 60 * 1000;
      const rows = entity.attributes.forecast_tomorrow_15min || [];
      const bySlot = new Map();
      for (const r of rows) {
        bySlot.set(new Date(r.start).getTime(), Number(r.price_kwh));
      }
      let m = moment(start).seconds(0).milliseconds(0);
      const rem = m.minute() % 15;
      if (rem) m = m.subtract(rem, 'minutes');
      const out = [];
      for (let t = m.valueOf(); t < t1; t += STEP) {
        let y = 0;
        if (bySlot.has(t)) y = bySlot.get(t);
        else {
          for (const [ts, v] of bySlot) {
            if (ts >= t && ts < t + STEP) {
              y = v;
              break;
            }
          }
        }
        out.push([t, y]);
      }
      return out;
```

## Notes

- Authentication uses `SUPERVISOR_TOKEN`, which Home Assistant injects automatically for add-ons.
- Internal API endpoint used: `http://supervisor/core/api/states/sensor.ote_spot_15min`.
- Add-on options are configurable in UI (`Configuration`):
  - `ote_api_url` (default `https://spotovaelektrina.cz/api/v1/price/get-prices-json-qh`)
  - `update_interval_seconds` (default `900`) — how often to push state to HA; with `daily_refresh_time` set, this is also the wake interval between scheduled API fetches (cache refresh to HA).
  - `request_timeout_seconds` (default `20`)
  - `local_timezone` (default `Europe/Prague`)
  - `daily_refresh_time` (default `13:05`, format `HH:MM`) — local time for **daily API fetch**; leave empty to fetch from the API on **every** `update_interval_seconds` instead. If tomorrow is still missing after that fetch, the add-on polls again every 15 minutes until the feed contains tomorrow’s prices (see note above).
- For local Docker testing, env vars are still supported:
  - `OTE_API_URL`, `UPDATE_INTERVAL_SECONDS`, `REQUEST_TIMEOUT_SECONDS`, `LOCAL_TIMEZONE`, `DAILY_REFRESH_TIME` (empty = off)
