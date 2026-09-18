"""Standalone Square sandbox -> hourly cafe sales extractor.

Self-contained: standard library only, no pip install, no imports from any
project. Copy this single file anywhere and run it.

    # 1. get a Sandbox Access Token
    #    https://developer.squareup.com -> Developer Console -> create an app
    #    -> Credentials -> switch the toggle to *Sandbox* -> copy (starts EAAA...)

    # 2. pass it in, or set SQUARE_SANDBOX_TOKEN in the environment
    python square_fetch_standalone.py --token EAAA... --list-locations
    python square_fetch_standalone.py --token EAAA... --start 2026-01-01 --end 2026-09-15
    python square_fetch_standalone.py --start 2026-01-01 --out cafe_sales.csv

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

# ===========================================================================
# EDIT HERE to just press Run in VS Code, with no command-line flags.
# Anything passed on the command line, or set in the environment, wins over
# these - so filling them in does not stop the CLI usage above from working.
# ===========================================================================
TOKEN = ""                    # paste the Sandbox Access Token between the quotes (EAAA...)
LIST_LOCATIONS_ONLY = True    # True: just list locations and stop. Set False once you have an ID.
START_DATE = ""               # "2026-01-01". Leave "" for 30 days ago.
END_DATE = ""                 # "2026-09-15". Leave "" for today.
LOCATION_IDS: list[str] = []  # ["L123..."]. Leave empty for all locations.
OUTPUT_CSV = ""               # "cafe_sales.csv". Leave "" to print a preview instead.
# ===========================================================================
# Do not commit this file with a real token in it.

SANDBOX_BASE_URL = "https://connect.squareupsandbox.com"
PRODUCTION_BASE_URL = "https://connect.squareup.com"

# Square caps a page at 1000 and defaults to 500.
PAGE_LIMIT = 1000
TIMEOUT_SECONDS = 30

# Local assumption, NOT a Square field: one cafe associate handles about four
# transactions an hour. required_manpower is computed from it, and that is the
# forecast target - agree the real figure with operations before relying on it.
CAFE_TRANSACTIONS_PER_FTE = 4.0


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


# --- Timezone handling -----------------------------------------------------

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


# --- CLI -------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--token", help="Square access token. Falls back to $SQUARE_SANDBOX_TOKEN.")
    parser.add_argument("--production", action="store_true", help="Use the production host instead of sandbox.")
    parser.add_argument("--list-locations", action="store_true", help="Show locations and timezones, then exit.")
    parser.add_argument("--location-id", action="append", help="Limit to this location (repeatable). Default: all, max 10.")
    parser.add_argument("--start", help="Start date YYYY-MM-DD. Default: 30 days ago.")
    parser.add_argument("--end", help="End date YYYY-MM-DD, exclusive. Default: today.")
    parser.add_argument("--out", help="Write all hourly rows to this CSV instead of printing a preview.")
    parser.add_argument("--raw-out", help="Also dump the raw Square orders JSON here.")
    args = parser.parse_args()

    # Precedence: command line, then environment, then the EDIT HERE block.
    token = args.token or os.environ.get("SQUARE_SANDBOX_TOKEN") or TOKEN
    if not token:
        print("No token found.", file=sys.stderr)
        print("Either paste it into TOKEN at the top of this file, pass --token EAAA...,", file=sys.stderr)
        print("or set SQUARE_SANDBOX_TOKEN in the environment.", file=sys.stderr)
        print("Get one at https://developer.squareup.com -> your app -> Credentials -> Sandbox.", file=sys.stderr)
        return 1

    base_url = PRODUCTION_BASE_URL if args.production else SANDBOX_BASE_URL

    end_text = args.end or END_DATE
    start_text = args.start or START_DATE
    end = date.fromisoformat(end_text) if end_text else date.today()
    start = date.fromisoformat(start_text) if start_text else end - timedelta(days=30)
    if start >= end:
        parser.error("start date must be before end date")

    locations = list_locations(base_url, token)
    if not locations:
        print("No locations on this account.", file=sys.stderr)
        return 1

    if args.list_locations or LIST_LOCATIONS_ONLY:
        print(f"{len(locations)} location(s):")
        for location in locations:
            print(f"  {location['id']:24} {location.get('name', '?'):28} "
                  f"tz={location.get('timezone', '?')} status={location.get('status', '?')}")
        return 0

    zone_by_location = {loc["id"]: _zone(loc.get("timezone"), loc["id"]) for loc in locations}
    location_ids = args.location_id or LOCATION_IDS or [loc["id"] for loc in locations]
    if len(location_ids) > 10:
        print(f"Square allows at most 10 location_ids per search; using the first 10 of {len(location_ids)}.", file=sys.stderr)
        location_ids = location_ids[:10]

    print(f"Searching {len(location_ids)} location(s), closed_at {start} .. {end} ...")
    orders = search_orders(base_url, token, location_ids, start, end)
    print(f"  {len(orders)} completed order(s) returned")

    if args.raw_out:
        with open(args.raw_out, "w", encoding="utf-8") as handle:
            json.dump(orders, handle, indent=2)
        print(f"  wrote {args.raw_out}")

    rows = to_hourly(orders, zone_by_location)
    print(f"  {len(rows)} hourly row(s) after aggregation")
    if not rows:
        print("\nNo orders in that window. Seed some in the Sandbox Square Dashboard, or widen --start/--end.")
        return 0

    out_path = args.out or OUTPUT_CSV
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
        print(f"... {len(rows) - 20} more row(s). Use --out to write them all.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
