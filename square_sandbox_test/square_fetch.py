"""Square sandbox -> hourly cafe sales. Press Run in VS Code.

Self-contained: standard library only, no pip install, no imports from any
project. Configuration comes from the .env file sitting next to this script,
so no credential is ever written into the code.

    1. https://developer.squareup.com -> Developer Console -> create an app
    2. Open the app -> Credentials -> switch the toggle to *Sandbox*
    3. Copy the Sandbox Access Token (starts EAAA...) into .env
    4. Press Run

Square returns one row per ORDER. This aggregates to one row per location per
HOUR: location_id, business_date, hour_of_day, sales_amount, transaction_count,
promotion_flag, event_flag, required_manpower.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SANDBOX_BASE_URL = "https://connect.squareupsandbox.com"
PRODUCTION_BASE_URL = "https://connect.squareup.com"

# Square caps a page at 1000 and defaults to 500.
PAGE_LIMIT = 1000
TIMEOUT_SECONDS = 30

# Local assumption, NOT a Square field: one cafe associate handles about four
# transactions an hour. required_manpower is computed from it, and that is the
# forecast target - agree the real figure with operations before relying on it.
CAFE_TRANSACTIONS_PER_FTE = 4.0


# --- .env ------------------------------------------------------------------

def load_env_file() -> Path | None:
    """Read KEY=VALUE pairs from a .env next to this script (or in the working
    directory) into the environment.

    A variable already present in the real environment always wins, so a .env
    can never silently override an explicit export - which is the behaviour
    people expect when debugging "why is it still using the old token".
    """
    for folder in (Path(__file__).resolve().parent, Path.cwd()):
        path = folder / ".env"
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        return path
    return None


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_flag(name: str, default: bool = False) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "y", "on")


# --- HTTP (stdlib only) ----------------------------------------------------

def _request(method: str, base_url: str, path: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(f"{base_url}{path}", data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        if exc.code == 401:
            raise SystemExit(
                "401 Unauthorized. Either the token is wrong, or it is a PRODUCTION "
                f"token being sent to the sandbox host.\n{detail}"
            )
        raise SystemExit(f"Square returned HTTP {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach {base_url}: {exc.reason}")


# --- Timezone --------------------------------------------------------------

def _zone(timezone_name: str | None, location_id: str = "?"):
    """The cafe's own timezone. Square timestamps are UTC, and bucketing them
    into hours without converting first shifts every trading day - the model
    then learns a daily shape that never happened.

    zoneinfo needs the IANA database, which Windows does not ship; if it is
    missing we fall back to UTC loudly rather than silently reporting wrong
    hours.
    """
    if not timezone_name:
        print(f"  ! location {location_id} has no timezone; using UTC", file=sys.stderr)
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(timezone_name)
    except Exception:
        print(
            f"  ! timezone {timezone_name!r} unavailable (on Windows: pip install tzdata); "
            "using UTC, so hour_of_day will be offset",
            file=sys.stderr,
        )
        return timezone.utc


# --- Square calls ----------------------------------------------------------

def list_locations(base_url: str, token: str) -> list[dict]:
    return _request("GET", base_url, "/v2/locations", token).get("locations", [])


def search_orders(base_url: str, token: str, location_ids: list[str], start: date, end: date) -> list[dict]:
    """Every COMPLETED order closed in the window, following the cursor.

    `closed_at` rather than `created_at`: an abandoned cart has a created_at
    too, and it never became a sale.
    """
    orders: list[dict] = []
    cursor: str | None = None
    while True:
        body = {
            # Full Order objects. Left at its default, Square returns lightweight
            # OrderEntry objects carrying only order_id/location_id/version - no
            # total_money at all, which is the usual reason this endpoint
            # appears to "return no sales".
            "return_entries": False,
            "limit": PAGE_LIMIT,
            "location_ids": location_ids,
            "query": {
                "filter": {
                    "state_filter": {"states": ["COMPLETED"]},
                    "date_time_filter": {"closed_at": {
                        "start_at": f"{start.isoformat()}T00:00:00Z",
                        "end_at": f"{end.isoformat()}T00:00:00Z",
                    }},
                },
                "sort": {"sort_field": "CLOSED_AT", "sort_order": "ASC"},
            },
        }
        if cursor:
            body["cursor"] = cursor
        payload = _request("POST", base_url, "/v2/orders/search", token, body)
        orders.extend(payload.get("orders", []))
        cursor = payload.get("cursor")
        if not cursor:
            return orders


# --- Transformation --------------------------------------------------------

def _closed_at(order: dict) -> datetime | None:
    stamp = order.get("closed_at") or order.get("created_at")
    if not stamp:
        return None
    # RFC 3339, e.g. 2026-09-04T23:59:33.123Z. fromisoformat handles the offset
    # form, so normalise the trailing Z first.
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc)


def to_hourly(orders: list[dict], zone_by_location: dict) -> list[dict]:
    """Orders -> one row per (location, business_date, hour_of_day)."""
    buckets: dict[tuple, dict] = defaultdict(
        lambda: {"sales_amount": 0.0, "transaction_count": 0, "promotion_flag": False}
    )
    for order in orders:
        closed = _closed_at(order)
        if closed is None:
            continue
        local = closed.astimezone(zone_by_location.get(order.get("location_id"), timezone.utc))
        bucket = buckets[(order.get("location_id"), local.date().isoformat(), local.hour)]
        # total_money.amount is in the smallest currency unit - cents for USD.
        # Skipping this division reports every sale as 100x its real value.
        bucket["sales_amount"] += (order.get("total_money") or {}).get("amount", 0) / 100.0
        bucket["transaction_count"] += 1
        # A proxy, not a real flag: Square has no "promotion" concept, so a
        # discounted order is the closest observable signal.
        if order.get("discounts"):
            bucket["promotion_flag"] = True

    rows = []
    for (location_id, business_date, hour), values in sorted(buckets.items()):
        count = values["transaction_count"]
        rows.append({
            "location_id": location_id,
            "business_date": business_date,
            "hour_of_day": hour,
            "sales_amount": round(values["sales_amount"], 2),
            "transaction_count": count,
            "promotion_flag": values["promotion_flag"],
            # Square has no equivalent. Kept so the column shape matches, rather
            # than being silently invented.
            "event_flag": False,
            # DERIVED, not sourced - see CAFE_TRANSACTIONS_PER_FTE above.
            "required_manpower": max(1, math.ceil(count / CAFE_TRANSACTIONS_PER_FTE)),
        })
    return rows


# --- Main ------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Square sandbox cafe sales.")
    parser.add_argument("--token", help="Overrides SQUARE_SANDBOX_TOKEN.")
    parser.add_argument("--list-locations", action="store_true")
    parser.add_argument("--start", help="YYYY-MM-DD")
    parser.add_argument("--end", help="YYYY-MM-DD, exclusive")
    parser.add_argument("--location-id", action="append")
    parser.add_argument("--out", help="Write all rows to this CSV.")
    parser.add_argument("--raw-out", help="Dump the raw Square orders JSON here.")
    parser.add_argument("--production", action="store_true", help="Use the live host instead of sandbox.")
    args = parser.parse_args()

    env_path = load_env_file()
    print(f"Loaded {env_path}" if env_path else "No .env found - using environment and flags only.")

    # Precedence throughout: command line, then environment/.env.
    token = args.token or _env("SQUARE_SANDBOX_TOKEN")
    if not token or token.startswith("EAAA_paste"):
        print("\nNo Square token set.", file=sys.stderr)
        print("Open .env next to this script and set SQUARE_SANDBOX_TOKEN=EAAA...", file=sys.stderr)
        print("Get one at https://developer.squareup.com -> your app -> Credentials -> Sandbox.", file=sys.stderr)
        return 1

    base_url = PRODUCTION_BASE_URL if (args.production or _env_flag("SQUARE_USE_PRODUCTION")) else SANDBOX_BASE_URL
    print(f"Host: {base_url}")

    end_text = args.end or _env("SQUARE_END_DATE")
    start_text = args.start or _env("SQUARE_START_DATE")
    end = date.fromisoformat(end_text) if end_text else date.today()
    start = date.fromisoformat(start_text) if start_text else end - timedelta(days=30)
    if start >= end:
        print(f"Start date {start} must be before end date {end}.", file=sys.stderr)
        return 1

    locations = list_locations(base_url, token)
    if not locations:
        print("No locations on this account.", file=sys.stderr)
        return 1

    if args.list_locations or _env_flag("SQUARE_LIST_LOCATIONS_ONLY"):
        print(f"\n{len(locations)} location(s):")
        for location in locations:
            print(f"  {location['id']:24} {location.get('name', '?'):28} "
                  f"tz={location.get('timezone', '?')} status={location.get('status', '?')}")
        print("\nSet SQUARE_LIST_LOCATIONS_ONLY=false in .env to pull sales.")
        return 0

    zone_by_location = {loc["id"]: _zone(loc.get("timezone"), loc["id"]) for loc in locations}
    configured = [v for v in _env("SQUARE_LOCATION_IDS").split(",") if v.strip()]
    location_ids = args.location_id or [v.strip() for v in configured] or [loc["id"] for loc in locations]
    if len(location_ids) > 10:
        print(f"Square allows at most 10 location_ids per search; using the first 10 of {len(location_ids)}.", file=sys.stderr)
        location_ids = location_ids[:10]

    print(f"Searching {len(location_ids)} location(s), closed_at {start} .. {end} ...")
    orders = search_orders(base_url, token, location_ids, start, end)
    print(f"  {len(orders)} completed order(s) returned")

    raw_path = args.raw_out or _env("SQUARE_RAW_JSON")
    if raw_path:
        Path(raw_path).write_text(json.dumps(orders, indent=2), encoding="utf-8")
        print(f"  wrote {raw_path}")

    rows = to_hourly(orders, zone_by_location)
    print(f"  {len(rows)} hourly row(s) after aggregation")
    if not rows:
        print("\nNo orders in that window. Seed some in the Sandbox Square Dashboard,")
        print("or widen SQUARE_START_DATE / SQUARE_END_DATE in .env.")
        return 0

    out_path = args.out or _env("SQUARE_OUTPUT_CSV")
    if out_path:
        with open(out_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"  wrote {out_path}")
        return 0

    columns = list(rows[0])
    print()
    print("  ".join(f"{name:>18}" for name in columns))
    for row in rows[:20]:
        print("  ".join(f"{str(row[name]):>18}" for name in columns))
    if len(rows) > 20:
        print(f"... {len(rows) - 20} more row(s). Set SQUARE_OUTPUT_CSV in .env to write them all.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
