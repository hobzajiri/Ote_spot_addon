import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

SUPERVISOR_URL = "http://supervisor/core/api"
SENSOR_ENTITY_ID = "sensor.ote_spot_15min"
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN")

DEFAULT_OTE_API_URL = "https://spotovaelektrina.cz/api/v1/price/get-prices-json-qh"
DEFAULT_UPDATE_INTERVAL_SECONDS = 900
DEFAULT_REQUEST_TIMEOUT_SECONDS = 20
DEFAULT_LOCAL_TIMEZONE = "Europe/Prague"


def load_addon_options() -> dict[str, Any]:
    try:
        with open("/data/options.json", "r", encoding="utf-8") as file:
            data = json.load(file)
            if isinstance(data, dict):
                return data
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        print(f"[ERROR] Failed to read /data/options.json: {exc}")
    return {}


def resolve_int(
    options: dict[str, Any], option_key: str, env_key: str, default: int
) -> int:
    raw = options.get(option_key, os.environ.get(env_key, default))
    try:
        return int(raw)
    except (TypeError, ValueError):
        print(f"[ERROR] Invalid value for {option_key}/{env_key}, using default {default}.")
        return default


ADDON_OPTIONS = load_addon_options()
OTE_API_URL = str(ADDON_OPTIONS.get("ote_api_url", os.environ.get("OTE_API_URL", DEFAULT_OTE_API_URL)))
UPDATE_INTERVAL_SECONDS = resolve_int(
    ADDON_OPTIONS,
    "update_interval_seconds",
    "UPDATE_INTERVAL_SECONDS",
    DEFAULT_UPDATE_INTERVAL_SECONDS,
)
REQUEST_TIMEOUT_SECONDS = resolve_int(
    ADDON_OPTIONS,
    "request_timeout_seconds",
    "REQUEST_TIMEOUT_SECONDS",
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
)
LOCAL_TIMEZONE_NAME = str(
    ADDON_OPTIONS.get("local_timezone", os.environ.get("LOCAL_TIMEZONE", DEFAULT_LOCAL_TIMEZONE))
)
try:
    LOCAL_TIMEZONE = ZoneInfo(LOCAL_TIMEZONE_NAME)
except Exception:
    print(f"[ERROR] Invalid timezone '{LOCAL_TIMEZONE_NAME}', using {DEFAULT_LOCAL_TIMEZONE}.")
    LOCAL_TIMEZONE = ZoneInfo(DEFAULT_LOCAL_TIMEZONE)


def parse_daily_refresh_time(raw: Any) -> tuple[int, int] | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    parts = s.split(":")
    if len(parts) != 2:
        print("[WARN] daily_refresh_time must be HH:MM (24h); ignoring.")
        return None
    try:
        hour = int(parts[0].strip())
        minute = int(parts[1].strip())
    except ValueError:
        print("[WARN] daily_refresh_time must be HH:MM; ignoring.")
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        print("[WARN] daily_refresh_time out of range; ignoring.")
        return None
    return hour, minute


DAILY_REFRESH_HM = parse_daily_refresh_time(
    ADDON_OPTIONS.get("daily_refresh_time", os.environ.get("DAILY_REFRESH_TIME", ""))
)


def next_local_api_slot(after: datetime, hour: int, minute: int) -> datetime:
    slot = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if after <= slot:
        return slot
    return slot + timedelta(days=1)


def build_headers() -> dict[str, str]:
    if not SUPERVISOR_TOKEN:
        raise RuntimeError("Missing SUPERVISOR_TOKEN environment variable.")
    return {
        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
        "Content-Type": "application/json",
    }


def fetch_ote_data() -> list[dict[str, Any]] | None:
    try:
        response = requests.get(OTE_API_URL, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        print(f"[ERROR] Failed to fetch OTE data: {exc}")
        return None
    except ValueError as exc:
        print(f"[ERROR] OTE API did not return valid JSON: {exc}")
        return None

    cleaned: list[dict[str, Any]]
    if isinstance(data, list):
        cleaned = parse_array_payload(data)
    elif isinstance(data, dict):
        cleaned = parse_spotova_qh_payload(data)
    else:
        print("[ERROR] OTE API payload has unsupported JSON type.")
        return None

    if not cleaned:
        print("[ERROR] OTE API payload did not contain usable price records.")
        return None

    return cleaned


def parse_array_payload(data: list[Any]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        start = item.get("start")
        price_mwh = item.get("price")
        if start is None or price_mwh is None:
            continue

        try:
            price_kwh = float(price_mwh) / 1000.0
        except (TypeError, ValueError):
            continue

        cleaned.append(
            {
                "start": start,
                "price_mwh": float(price_mwh),
                "price_kwh": round(price_kwh, 6),
            }
        )

    return cleaned


def parse_spotova_qh_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    today = datetime.now(LOCAL_TIMEZONE).date()
    tomorrow = today + timedelta(days=1)
    cleaned: list[dict[str, Any]] = []

    def add_rows(rows: Any, day: date) -> None:
        if not isinstance(rows, list):
            return
        for item in rows:
            if not isinstance(item, dict):
                continue

            hour = item.get("hour")
            minute = item.get("minute")
            price_mwh = item.get("priceCZK")
            if hour is None or minute is None or price_mwh is None:
                continue

            try:
                slot_dt = datetime(
                    day.year,
                    day.month,
                    day.day,
                    int(hour),
                    int(minute),
                    tzinfo=LOCAL_TIMEZONE,
                )
                price_mwh_float = float(price_mwh)
                price_kwh = price_mwh_float / 1000.0
            except (TypeError, ValueError):
                continue

            cleaned.append(
                {
                    "start": slot_dt.isoformat(),
                    "price_mwh": price_mwh_float,
                    "price_kwh": round(price_kwh, 6),
                }
            )

    add_rows(data.get("hoursToday"), today)
    add_rows(data.get("hoursTomorrow"), tomorrow)

    cleaned.sort(key=lambda x: str(x["start"]))
    return cleaned


def pick_current_slot(records: list[dict[str, Any]]) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    default_record = records[0]

    for idx, record in enumerate(records):
        try:
            current_start = datetime.fromisoformat(
                str(record["start"]).replace("Z", "+00:00")
            )
        except ValueError:
            continue

        if idx + 1 < len(records):
            try:
                next_start = datetime.fromisoformat(
                    str(records[idx + 1]["start"]).replace("Z", "+00:00")
                )
            except ValueError:
                next_start = None
        else:
            next_start = None

        if current_start <= now_utc and (next_start is None or now_utc < next_start):
            return record

    return default_record


def slot_local_date(record: dict[str, Any]) -> date | None:
    try:
        dt = datetime.fromisoformat(str(record["start"]).replace("Z", "+00:00"))
        return dt.astimezone(LOCAL_TIMEZONE).date()
    except ValueError:
        return None


def split_forecast_today_tomorrow(
    records: list[dict[str, Any]],
) -> tuple[str, str, list[dict[str, Any]], list[dict[str, Any]]]:
    today_d = datetime.now(LOCAL_TIMEZONE).date()
    tomorrow_d = today_d + timedelta(days=1)
    today_slots: list[dict[str, Any]] = []
    tomorrow_slots: list[dict[str, Any]] = []
    for row in records:
        d = slot_local_date(row)
        if d == today_d:
            today_slots.append(row)
        elif d == tomorrow_d:
            tomorrow_slots.append(row)
    return (
        today_d.isoformat(),
        tomorrow_d.isoformat(),
        today_slots,
        tomorrow_slots,
    )


def push_sensor_state(records: list[dict[str, Any]]) -> bool:
    current = pick_current_slot(records)
    today_iso, tomorrow_iso, today_fc, tomorrow_fc = split_forecast_today_tomorrow(records)

    payload = {
        "state": current["price_kwh"],
        "attributes": {
            "friendly_name": "OTE Spot Price (15 min)",
            "unit_of_measurement": "CZK/kWh",
            "device_class": "monetary",
            "icon": "mdi:transmission-tower",
            "source": "OTE",
            "last_update_utc": datetime.now(timezone.utc).isoformat(),
            "current_slot_start": current["start"],
            "current_price_mwh": current["price_mwh"],
            "forecast_15min": records,
            "forecast_today_date": today_iso,
            "forecast_tomorrow_date": tomorrow_iso,
            "forecast_today_15min": today_fc,
            "forecast_tomorrow_15min": tomorrow_fc,
            "has_tomorrow_prices": len(tomorrow_fc) > 0,
        },
    }

    try:
        response = requests.post(
            f"{SUPERVISOR_URL}/states/{SENSOR_ENTITY_ID}",
            headers=build_headers(),
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        print(f"[ERROR] Failed to push sensor state: {exc}")
        return False
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return False


def run() -> None:
    print("[INFO] OTE spot prices add-on started.")
    print(f"[INFO] OTE API URL: {OTE_API_URL}")
    print(f"[INFO] Update interval: {UPDATE_INTERVAL_SECONDS}s")
    if DAILY_REFRESH_HM:
        print(
            f"[INFO] Daily API refresh at {DAILY_REFRESH_HM[0]:02d}:{DAILY_REFRESH_HM[1]:02d} "
            f"({LOCAL_TIMEZONE_NAME}); between refreshes only HA state is updated from cache."
        )
    else:
        print("[INFO] Fetching from API on every update interval (no daily_refresh_time).")

    records: list[dict[str, Any]] | None = None

    if DAILY_REFRESH_HM is None:
        while True:
            fetched = fetch_ote_data()
            if fetched is not None:
                records = fetched
                if push_sensor_state(records):
                    print(
                        f"[INFO] Updated {SENSOR_ENTITY_ID}: "
                        f"{pick_current_slot(records)['price_kwh']} CZK/kWh"
                    )
            time.sleep(UPDATE_INTERVAL_SECONDS)

    hour, minute = DAILY_REFRESH_HM
    fetched = fetch_ote_data()
    if fetched is not None:
        records = fetched
        if push_sensor_state(records):
            print(
                f"[INFO] Updated {SENSOR_ENTITY_ID}: "
                f"{pick_current_slot(records)['price_kwh']} CZK/kWh"
            )

    next_api_at = next_local_api_slot(datetime.now(LOCAL_TIMEZONE), hour, minute)
    print(f"[INFO] Next scheduled API fetch (local): {next_api_at.isoformat()}")

    while True:
        now_local = datetime.now(LOCAL_TIMEZONE)
        sec_to_api = (next_api_at - now_local).total_seconds()
        wait = min(float(UPDATE_INTERVAL_SECONDS), max(1.0, sec_to_api))
        time.sleep(wait)
        now_local = datetime.now(LOCAL_TIMEZONE)

        if now_local >= next_api_at:
            fetched = fetch_ote_data()
            if fetched is not None:
                records = fetched
                if push_sensor_state(records):
                    print(
                        f"[INFO] Updated {SENSOR_ENTITY_ID}: "
                        f"{pick_current_slot(records)['price_kwh']} CZK/kWh"
                    )
            next_api_at = next_api_at + timedelta(days=1)
            print(f"[INFO] Next scheduled API fetch (local): {next_api_at.isoformat()}")
            continue

        if records is not None and push_sensor_state(records):
            print(
                f"[INFO] Refreshed HA state from cache: "
                f"{pick_current_slot(records)['price_kwh']} CZK/kWh"
            )


if __name__ == "__main__":
    run()
