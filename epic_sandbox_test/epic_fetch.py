"""Epic FHIR sandbox -> hourly inpatient census.

Authenticates with Epic's backend (server-to-server) OAuth: signs a JWT with
the private key from make_keys.py, exchanges it for an access token, then
queries Encounter resources and derives an occupancy count per hour.

    pip install cryptography
    python make_keys.py          # once, then register the cert with Epic
    python epic_fetch.py

Configuration lives in the .env next to this script.

HOW CENSUS IS DERIVED
There is no "occupied_beds" field in FHIR. Occupancy is computed: an inpatient
Encounter with period.start <= T and (no period.end or period.end > T) means
that patient occupied a bed at time T. This counts those per hour - the same
thing an interface engine does when it replays ADT admit/transfer/discharge
messages.
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_FHIR_BASE = "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4"
# Read straight from Epic's own CapabilityStatement (/metadata), not guessed.
DEFAULT_TOKEN_URL = "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token"

# SMART Backend Services requires RS384, and caps the assertion's lifetime at
# five minutes.
JWT_ALGORITHM = "RS384"
JWT_LIFETIME_SECONDS = 300


# --- .env ------------------------------------------------------------------

def load_env_file() -> Path | None:
    """A real environment variable always wins over the file, so an export
    cannot be silently overridden."""
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


# --- JWT signing -----------------------------------------------------------

def _b64url(raw: bytes) -> bytes:
    """JWTs use base64url with the padding stripped."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def build_signed_jwt(client_id: str, token_url: str, private_key_path: Path) -> str:
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        raise SystemExit("This needs the 'cryptography' package:\n    pip install cryptography")

    if not private_key_path.is_file():
        raise SystemExit(f"Private key not found: {private_key_path}\nRun make_keys.py first.")

    private_key = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)

    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    now = datetime.now(timezone.utc)
    claims = {
        # Epic expects the client id as BOTH issuer and subject, and the token
        # endpoint itself as the audience - a mismatch here is the usual cause
        # of "invalid_client".
        "iss": client_id,
        "sub": client_id,
        "aud": token_url,
        # Must be unique per request; Epic rejects a replayed jti.
        "jti": str(uuid.uuid4()),
        "exp": int((now + timedelta(seconds=JWT_LIFETIME_SECONDS)).timestamp()),
        "iat": int(now.timestamp()),
    }
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + b"."
        + _b64url(json.dumps(claims, separators=(",", ":")).encode())
    )
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA384())
    return (signing_input + b"." + _b64url(signature)).decode()


def get_access_token(client_id: str, token_url: str, private_key_path: Path) -> str:
    assertion = build_signed_jwt(client_id, token_url, private_key_path)
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "client_assertion": assertion,
    }).encode()
    request = urllib.request.Request(token_url, data=body, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())["access_token"]
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        if exc.code == 400:
            raise SystemExit(
                f"Epic rejected the token request (400):\n{detail}\n\n"
                "Common causes:\n"
                "  - the client ID has not propagated to the sandbox yet (wait ~60 minutes)\n"
                "  - EPIC_CLIENT_ID is the PRODUCTION id; the sandbox needs the NON-PRODUCTION one\n"
                "  - the uploaded certificate does not match epic_private_key.pem"
            )
        raise SystemExit(f"Token request failed HTTP {exc.code}:\n{detail}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach {token_url}: {exc.reason}")


# --- FHIR ------------------------------------------------------------------

def fhir_get(base_url: str, path: str, token: str) -> dict:
    request = urllib.request.Request(f"{base_url}{path}", method="GET")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        # Not truncated: Epic returns an OperationOutcome whose *last* issue is
        # usually the fatal one saying what it actually requires, so cutting the
        # body short hides the only useful sentence in it.
        return {"_http_error": exc.code, "_detail": exc.read().decode("utf-8", errors="replace")}
    except urllib.error.URLError as exc:
        return {"_http_error": "network", "_detail": str(exc.reason)}


def _print_operation_outcome(body: str) -> None:
    """Epic explains a rejected search in an OperationOutcome. Printing each
    issue with its severity makes the fatal one obvious - it is the one that
    says what the server actually requires."""
    try:
        outcome = json.loads(body)
    except ValueError:
        print(f"  {body[:800]}", file=sys.stderr)
        return
    for issue in outcome.get("issue", []):
        severity = issue.get("severity", "?")
        text = (issue.get("details") or {}).get("text") or issue.get("diagnostics") or ""
        where = ", ".join(issue.get("expression") or issue.get("location") or [])
        print(f"    [{severity}] {text}{f'  ({where})' if where else ''}", file=sys.stderr)


def search_encounters(base_url: str, token: str, query: str, max_pages: int = 20) -> list[dict]:
    """Follow Bundle.link[next] until Epic stops paging."""
    entries: list[dict] = []
    path = f"/Encounter?{query}"
    for _ in range(max_pages):
        bundle = fhir_get(base_url, path, token)
        if "_http_error" in bundle:
            print(f"  Encounter search returned {bundle['_http_error']}", file=sys.stderr)
            _print_operation_outcome(bundle["_detail"])
            return entries
        entries.extend(e.get("resource", {}) for e in bundle.get("entry", []) or [])
        next_url = next((l.get("url") for l in bundle.get("link", []) if l.get("relation") == "next"), None)
        if not next_url:
            break
        # Epic returns an absolute next link; keep only the part after the base.
        path = next_url[len(base_url):] if next_url.startswith(base_url) else next_url
    return entries


# --- Census ----------------------------------------------------------------

def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None


def to_hourly_census(encounters: list[dict], hours: int = 24 * 14) -> list[dict]:
    """One row per hour: how many inpatient encounters were open at that hour.

    This is the bit that has no FHIR field of its own. An encounter occupies a
    bed for every hour between period.start and period.end, so occupancy at
    hour T is the number of encounters spanning T.
    """
    spans = []
    for encounter in encounters:
        period = encounter.get("period") or {}
        start = _parse(period.get("start"))
        if start is None:
            continue
        spans.append((start, _parse(period.get("end"))))
    if not spans:
        return []

    earliest = min(start for start, _ in spans)
    latest = max((end or start for start, end in spans), default=earliest)
    # Cap the window so a single open-ended encounter cannot generate years of
    # hourly rows.
    total_hours = min(hours, int((latest - earliest).total_seconds() // 3600) + 1)

    rows = []
    for offset in range(max(total_hours, 1)):
        moment = earliest + timedelta(hours=offset)
        occupied = sum(1 for start, end in spans if start <= moment and (end is None or end > moment))
        rows.append({
            "business_date": moment.date().isoformat(),
            "hour_of_day": moment.hour,
            "occupied_beds": occupied,
        })
    return rows


# --- Main ------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Epic sandbox encounters and derive hourly census.")
    parser.add_argument("--query", help="Override the Encounter search query string.")
    parser.add_argument("--out", help="Write hourly census rows to this CSV.")
    parser.add_argument("--raw-out", help="Dump the raw Encounter resources here.")
    args = parser.parse_args()

    env_path = load_env_file()
    print(f"Loaded {env_path}" if env_path else "No .env found - using environment only.")

    client_id = _env("EPIC_CLIENT_ID")
    if not client_id or client_id.startswith("paste_"):
        print("\nEPIC_CLIENT_ID is not set in .env.", file=sys.stderr)
        print("Register at https://fhir.epic.com (Backend Systems app), upload", file=sys.stderr)
        print("epic_public_cert.pem, then copy the NON-PRODUCTION client id here.", file=sys.stderr)
        return 1

    base_url = _env("EPIC_FHIR_BASE") or DEFAULT_FHIR_BASE
    token_url = _env("EPIC_TOKEN_URL") or DEFAULT_TOKEN_URL
    key_path = Path(_env("EPIC_PRIVATE_KEY") or (Path(__file__).resolve().parent / "epic_private_key.pem"))

    print(f"Token endpoint: {token_url}")
    token = get_access_token(client_id, token_url, key_path)
    print(f"  got an access token ({len(token)} chars)")

    query = args.query or _env("EPIC_ENCOUNTER_QUERY") or "class=IMP&_count=100"
    print(f"Searching: /Encounter?{query}")
    encounters = search_encounters(base_url, token, query)
    print(f"  {len(encounters)} encounter(s) returned")
    if not encounters:
        print("\nNo encounters came back. Epic's sandbox usually requires a patient")
        print("context for Encounter searches - try a patient-scoped query, e.g.")
        print('  EPIC_ENCOUNTER_QUERY=patient=erXuFYUfucBZaryVksYEcMg3')
        return 0

    states = Counter(e.get("status", "?") for e in encounters)
    classes = Counter((e.get("class") or {}).get("code", "?") for e in encounters)
    print(f"  statuses: {dict(states)}")
    print(f"  classes:  {dict(classes)}")

    raw_path = args.raw_out or _env("EPIC_RAW_JSON")
    if raw_path:
        Path(raw_path).write_text(json.dumps(encounters, indent=2), encoding="utf-8")
        print(f"  wrote {raw_path}")

    rows = to_hourly_census(encounters)
    print(f"  {len(rows)} hourly census row(s) derived")
    if not rows:
        print("  (no encounter carried a period.start, so occupancy cannot be derived)")
        return 0

    out_path = args.out or _env("EPIC_OUTPUT_CSV")
    if out_path:
        with open(out_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"  wrote {out_path}")
        return 0

    # Summarise before previewing. The first 24 hours are often all zero - an
    # encounter that ended leaves empty hours behind it - so a naive head() of
    # the rows looks like the derivation failed when it did not.
    occupied = [row for row in rows if row["occupied_beds"] > 0]
    peak = max((row["occupied_beds"] for row in rows), default=0)
    print(f"  {len(occupied)} of {len(rows)} hour(s) had at least one bed occupied, peak {peak}")

    print()
    print(f"{'business_date':>14} {'hour_of_day':>12} {'occupied_beds':>14}")
    # Show hours that actually had occupancy; fall back to the head when none do.
    for row in (occupied or rows)[:24]:
        print(f"{row['business_date']:>14} {row['hour_of_day']:>12} {row['occupied_beds']:>14}")
    remaining = len(occupied or rows) - 24
    if remaining > 0:
        print(f"... {remaining} more occupied hour(s). Set EPIC_OUTPUT_CSV in .env to write them all.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
