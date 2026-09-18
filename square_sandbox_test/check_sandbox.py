"""What is actually in this Square sandbox account?

square_fetch.py searches for COMPLETED orders and found none. Square documents
that a default sandbox test account ships with sample data, so this checks each
resource separately to see what really exists - orders in ANY state, payments,
customers and catalog items - rather than guessing why the search came back
empty.

Reads the same .env. Run it, then paste the output.

    python check_sandbox.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

SANDBOX_BASE_URL = "https://connect.squareupsandbox.com"


def load_env_file() -> Path | None:
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


def _request(method: str, path: str, token: str, body: dict | None = None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(f"{SANDBOX_BASE_URL}{path}", data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"_http_error": exc.code, "_detail": exc.read().decode("utf-8", errors="replace")[:300]}
    except urllib.error.URLError as exc:
        return {"_http_error": "network", "_detail": str(exc.reason)}


def _show(label: str, payload: dict, key: str) -> list:
    if "_http_error" in payload:
        print(f"  {label:26} ERROR {payload['_http_error']}: {payload['_detail'][:120]}")
        return []
    items = payload.get(key) or []
    print(f"  {label:26} {len(items)}")
    return items


def main() -> int:
    env_path = load_env_file()
    print(f"Loaded {env_path}\n" if env_path else "No .env found.\n")

    token = os.environ.get("SQUARE_SANDBOX_TOKEN", "").strip()
    if not token or token.startswith("EAAA_paste"):
        print("No Square token set. Put SQUARE_SANDBOX_TOKEN in .env.", file=sys.stderr)
        return 1

    locations = _show("locations", _request("GET", "/v2/locations", token), "locations")
    if not locations:
        return 1
    location_ids = [loc["id"] for loc in locations]

    # Orders in ANY state, not just COMPLETED - this is the key question. If
    # sample orders exist but sit in OPEN or DRAFT, the fetch filter is what
    # hid them, not an empty account.
    orders_payload = _request("POST", "/v2/orders/search", token, {
        "return_entries": False,
        "limit": 500,
        "location_ids": location_ids,
    })
    orders = _show("orders (any state)", orders_payload, "orders")
    if orders:
        states = Counter(o.get("state", "?") for o in orders)
        print(f"      states: {dict(states)}")
        stamps = sorted(o.get("closed_at") or o.get("created_at") or "" for o in orders)
        print(f"      earliest: {stamps[0]}")
        print(f"      latest:   {stamps[-1]}")

    payments = _show("payments", _request("GET", "/v2/payments?limit=100", token), "payments")
    if payments:
        stamps = sorted(p.get("created_at", "") for p in payments)
        print(f"      earliest: {stamps[0]}")
        print(f"      latest:   {stamps[-1]}")

    _show("customers", _request("GET", "/v2/customers?limit=100", token), "customers")
    _show("catalog items", _request("GET", "/v2/catalog/list?types=ITEM", token), "objects")

    print()
    if orders:
        print("There ARE orders. If square_fetch.py found none, the COMPLETED filter")
        print("or the date window excluded them - see the states and dates above.")
    else:
        print("No orders of any state exist in this sandbox. The 'sample data' in a")
        print("default test account is customers/catalog, not historical transactions.")
        print("Run seed_orders.py to create some.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
