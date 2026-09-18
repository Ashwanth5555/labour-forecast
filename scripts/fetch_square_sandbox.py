"""Pull cafe sales from the Square sandbox and shape them like fact_cafe_sales.

Square returns one row per ORDER; the forecast needs one row per location per
HOUR, so this aggregates rather than renames. Run it to see real POS data in
the same shape the mock /mock/pos/cafe-sales endpoint produces today.

Setup:
    1. https://developer.squareup.com -> Developer Console -> create an application
    2. Open the app -> Credentials -> switch the toggle to *Sandbox*
    3. Copy the Sandbox Access Token (starts with EAAA...)
    4. Add it to .env.sodexo:   SQUARE_SANDBOX_TOKEN=EAAA...

Usage:
    python scripts/fetch_square_sandbox.py --list-locations
    python scripts/fetch_square_sandbox.py --start 2026-01-01 --end 2026-09-15
    python scripts/fetch_square_sandbox.py --start 2026-01-01 --out cafe_sales.csv

Run from the repository root with the project venv:
    ../.venv/Scripts/python.exe scripts/fetch_square_sandbox.py --list-locations
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend_sodexo"))

from app.core.config import get_settings  # noqa: E402

SANDBOX_BASE_URL = "https://connect.squareupsandbox.com"

# Square caps a page at 1000 and defaults to 500.
PAGE_LIMIT = 1000

# Local assumption, NOT a Square field: one cafe associate handles about four
# transactions an hour. Mirrors CAFE_TRANSACTIONS_PER_FTE in the dataset
# generator so the output is comparable with the mock. Agree the real figure
# with operations before trusting anything computed from it.
CAFE_TRANSACTIONS_PER_FTE = 4.0


def _client(token: str) -> httpx.Client:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    # Omitted by default: with no Square-Version header Square uses the default
    # version pinned to your application, which is right far more often than a
    # version string hardcoded here and left to rot.
    version = get_settings().square_api_version
    if version:
        headers["Square-Version"] = version
    return httpx.Client(base_url=SANDBOX_BASE_URL, headers=headers, timeout=30.0)


def list_locations(client: httpx.Client) -> list[dict]:
    response = client.get("/v2/locations")
    response.raise_for_status()
    return response.json().get("locations", [])


def search_orders(client: httpx.Client, location_ids: list[str], start: date, end: date) -> list[dict]:
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
            # "returns no sales".
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
        response = client.post("/v2/orders/search", json=body)
        response.raise_for_status()
        payload = response.json()
        orders.extend(payload.get("orders", []))
        cursor = payload.get("cursor")
        if not cursor:
            return orders


def _zone(location: dict) -> ZoneInfo:
    """The cafe's own timezone. Square timestamps are UTC, and bucketing them
    into hours without converting first shifts every trading day - the model
    then learns a daily shape that never happened."""
    name = location.get("timezone")
    if not name:
        print(f"  ! location {location.get('id')} has no timezone; assuming UTC", file=sys.stderr)
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        print(f"  ! unknown timezone {name!r}; assuming UTC", file=sys.stderr)
        return ZoneInfo("UTC")


def _closed_at(order: dict) -> datetime | None:
    stamp = order.get("closed_at") or order.get("created_at")
    if not stamp:
        return None
    # RFC 3339, e.g. 2026-09-04T23:59:33.123Z - fromisoformat handles the offset
    # form, so normalise the Z first.
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc)


def to_hourly(orders: list[dict], zone_by_location: dict[str, ZoneInfo]) -> list[dict]:
    """Orders -> one row per (location, date, hour), matching fact_cafe_sales."""
    buckets: dict[tuple, dict] = defaultdict(lambda: {"sales_amount": 0.0, "transaction_count": 0, "promotion_flag": False})
    for order in orders:
        closed = _closed_at(order)
        if closed is None:
            continue
        local = closed.astimezone(zone_by_location.get(order.get("location_id"), ZoneInfo("UTC")))
        key = (order.get("location_id"), local.date().isoformat(), local.hour)
        bucket = buckets[key]
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
        transaction_count = values["transaction_count"]
        rows.append({
            "location_id": location_id,
            "business_date": business_date,
            "hour_of_day": hour,
            "sales_amount": round(values["sales_amount"], 2),
            "transaction_count": transaction_count,
            "promotion_flag": values["promotion_flag"],
            # Square has no equivalent. Left False so the column keeps its shape
            # rather than being silently invented.
            "event_flag": False,
            # DERIVED, not sourced - see CAFE_TRANSACTIONS_PER_FTE above.
            "required_manpower": max(1, math.ceil(transaction_count / CAFE_TRANSACTIONS_PER_FTE)),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list-locations", action="store_true", help="Show sandbox locations and their timezones, then exit.")
    parser.add_argument("--location-id", action="append", help="Limit to this location (repeatable). Default: all, max 10.")
    parser.add_argument("--start", help="Start date, YYYY-MM-DD. Default: 30 days ago.")
    parser.add_argument("--end", help="End date, YYYY-MM-DD (exclusive). Default: today.")
    parser.add_argument("--out", help="Write the hourly rows to this CSV instead of printing a preview.")
    args = parser.parse_args()

    token = get_settings().square_sandbox_token
    if not token:
        print("SQUARE_SANDBOX_TOKEN is not set in .env.sodexo.", file=sys.stderr)
        print("Get it from https://developer.squareup.com -> your app -> Credentials -> Sandbox.", file=sys.stderr)
        return 1

    end = date.fromisoformat(args.end) if args.end else date.today()
    start = date.fromisoformat(args.start) if args.start else end - timedelta(days=30)
    if start >= end:
        parser.error("--start must be before --end")

    try:
        with _client(token) as client:
            locations = list_locations(client)
            if not locations:
                print("No locations on this sandbox account.", file=sys.stderr)
                return 1

            if args.list_locations:
                print(f"{len(locations)} sandbox location(s):")
                for location in locations:
                    print(f"  {location['id']:24} {location.get('name', '?'):28} tz={location.get('timezone', '?')} status={location.get('status', '?')}")
                return 0

            zone_by_location = {location["id"]: _zone(location) for location in locations}
            location_ids = args.location_id or [location["id"] for location in locations]
            if len(location_ids) > 10:
                print(f"Square allows at most 10 location_ids per search; using the first 10 of {len(location_ids)}.", file=sys.stderr)
                location_ids = location_ids[:10]

            print(f"Searching {len(location_ids)} location(s), closed_at {start} .. {end} ...")
            orders = search_orders(client, location_ids, start, end)
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:400]
        if exc.response.status_code == 401:
            print("401 Unauthorized - the token is wrong, or it is a PRODUCTION token being sent to the sandbox host.", file=sys.stderr)
        print(f"Square returned {exc.response.status_code}: {detail}", file=sys.stderr)
        return 1

    print(f"  {len(orders)} completed order(s) returned")
    rows = to_hourly(orders, zone_by_location)
    print(f"  {len(rows)} hourly row(s) after aggregation")
    if not rows:
        print("\nNo orders in that window. Seed some in the Sandbox Square Dashboard, or widen --start/--end.")
        return 0

    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"  wrote {args.out}")
        return 0

    widths = list(rows[0])
    print()
    print("  ".join(f"{name:>18}" for name in widths))
    for row in rows[:20]:
        print("  ".join(f"{str(row[name]):>18}" for name in widths))
    if len(rows) > 20:
        print(f"... {len(rows) - 20} more row(s). Use --out to write them all.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
