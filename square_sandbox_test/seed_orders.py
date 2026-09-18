"""Create paid test orders in the Square sandbox, so square_fetch.py has data.

A fresh sandbox account has a location but no transactions, so a fetch returns
zero rows. This creates real orders through the API and pays each one with
Square's sandbox test token, which moves it to COMPLETED - the state
square_fetch.py searches for.

Reads the same .env as square_fetch.py. Press Run in VS Code, or:

    python seed_orders.py                 # 40 orders
    python seed_orders.py --count 200     # more

IMPORTANT LIMITATION
Square sets `closed_at` server-side, at the moment the order is paid. It
cannot be backdated, so every seeded order lands in the CURRENT hour. That is
enough to prove the fetch/aggregate/CSV path end to end, but it will not
manufacture a realistic spread of trading hours - you get one busy hour, not a
daily curve.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

SANDBOX_BASE_URL = "https://connect.squareupsandbox.com"

# Square's sandbox test payment token. Never a real card, never charged.
TEST_PAYMENT_TOKEN = "cnon:card-nonce-ok"

# A plausible cafe menu, priced in cents.
MENU = [
    ("Filter Coffee", 295),
    ("Latte", 425),
    ("Cappuccino", 395),
    ("Tea", 250),
    ("Breakfast Sandwich", 685),
    ("Chicken Wrap", 795),
    ("Fruit Pot", 350),
    ("Muffin", 315),
    ("Bottled Water", 195),
    ("Crisps", 175),
]


def load_env_file() -> Path | None:
    """Same loader as square_fetch.py: a real environment variable always wins
    over the file, so an export cannot be silently overridden."""
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


def _request(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(f"{SANDBOX_BASE_URL}{path}", data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        if exc.code == 401:
            raise SystemExit(f"401 Unauthorized - check SQUARE_SANDBOX_TOKEN in .env.\n{detail}")
        raise SystemExit(f"Square returned HTTP {exc.code} on {path}:\n{detail}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach {SANDBOX_BASE_URL}: {exc.reason}")


def create_order(token: str, location_id: str) -> dict:
    """One order of 1-4 random items. Square computes the total itself."""
    line_items = []
    for name, price in random.sample(MENU, random.randint(1, 4)):
        line_items.append({
            "name": name,
            "quantity": str(random.randint(1, 3)),
            "base_price_money": {"amount": price, "currency": "USD"},
        })
    body = {
        # Square rejects a repeated key rather than double-charging, so a fresh
        # uuid per call is what makes each order distinct.
        "idempotency_key": str(uuid.uuid4()),
        "order": {"location_id": location_id, "line_items": line_items},
    }
    return _request("POST", "/v2/orders", token, body)["order"]


def pay_order(token: str, order: dict, location_id: str) -> dict:
    """Paying in full is what moves the order to COMPLETED. Without this the
    order stays OPEN and square_fetch.py will not see it, because it filters on
    COMPLETED."""
    body = {
        "idempotency_key": str(uuid.uuid4()),
        "source_id": TEST_PAYMENT_TOKEN,
        "amount_money": order["total_money"],
        "order_id": order["id"],
        "location_id": location_id,
        "autocomplete": True,
    }
    return _request("POST", "/v2/payments", token, body)["payment"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed paid test orders into the Square sandbox.")
    parser.add_argument("--count", type=int, default=40, help="How many orders to create (default 40).")
    parser.add_argument("--location-id", help="Defaults to the first location on the account.")
    parser.add_argument("--token", help="Overrides SQUARE_SANDBOX_TOKEN.")
    args = parser.parse_args()

    env_path = load_env_file()
    print(f"Loaded {env_path}" if env_path else "No .env found - using environment and flags only.")

    token = args.token or os.environ.get("SQUARE_SANDBOX_TOKEN", "").strip()
    if not token or token.startswith("EAAA_paste"):
        print("No Square token set. Put SQUARE_SANDBOX_TOKEN in .env.", file=sys.stderr)
        return 1

    location_id = args.location_id or os.environ.get("SQUARE_LOCATION_IDS", "").split(",")[0].strip()
    if not location_id:
        locations = _request("GET", "/v2/locations", token).get("locations", [])
        if not locations:
            print("No locations on this account.", file=sys.stderr)
            return 1
        location_id = locations[0]["id"]

    print(f"Seeding {args.count} paid order(s) into {location_id} ...")
    total_cents = 0
    created = 0
    for index in range(1, args.count + 1):
        order = create_order(token, location_id)
        pay_order(token, order, location_id)
        created += 1
        total_cents += order["total_money"]["amount"]
        if index % 10 == 0 or index == args.count:
            print(f"  {index}/{args.count} ...")

    print()
    print(f"Created {created} COMPLETED order(s), ${total_cents / 100:,.2f} total.")
    print("Now run:  python square_fetch.py")
    print()
    print("Note: Square stamps closed_at at payment time and it cannot be backdated,")
    print("so these all land in the current hour rather than spread across a day.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
