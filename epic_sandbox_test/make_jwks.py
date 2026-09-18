"""Turn epic_private_key.pem into the JWKS document Epic fetches.

Epic's app registration now asks for a "Non-Production JWK Set URL" rather than
a certificate upload: you host a JSON Web Key Set at a public HTTPS URL, and
Epic reads your public key from it to verify the JWTs you sign.

    python make_jwks.py

Writes jwks.json next to this script. Only the PUBLIC half of the key goes in
it - the file is safe to publish, which is the whole point. The private key
never leaves your machine.

Where to host it (it just has to be public HTTPS returning this JSON):
  - GitHub: commit jwks.json to a public repo, enable Pages, use that URL
  - GitHub Gist: create a public gist, use the "Raw" URL
  - Any static host: S3, Cloudflare Pages, Netlify

Then paste the URL into Epic's "Non-Production JWK Set URL" field.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

try:
    from cryptography.hazmat.primitives import serialization
except ImportError:
    print("This needs the 'cryptography' package:\n    pip install cryptography", file=sys.stderr)
    raise SystemExit(1)

HERE = Path(__file__).resolve().parent
PRIVATE_KEY_PATH = HERE / "epic_private_key.pem"
JWKS_PATH = HERE / "jwks.json"


def _b64url_uint(value: int) -> str:
    """JWK encodes RSA numbers as base64url of their big-endian bytes, with no
    padding and no leading zero byte."""
    raw = value.to_bytes((value.bit_length() + 7) // 8, byteorder="big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def main() -> int:
    if not PRIVATE_KEY_PATH.is_file():
        print(f"{PRIVATE_KEY_PATH.name} not found. Run make_keys.py first.", file=sys.stderr)
        return 1

    private_key = serialization.load_pem_private_key(PRIVATE_KEY_PATH.read_bytes(), password=None)
    numbers = private_key.public_key().public_numbers()

    modulus = _b64url_uint(numbers.n)
    exponent = _b64url_uint(numbers.e)
    # A stable id derived from the key itself, so regenerating the JWKS from the
    # same key always produces the same kid.
    kid = hashlib.sha256(f"{modulus}{exponent}".encode()).hexdigest()[:16]

    jwks = {
        "keys": [{
            "kty": "RSA",
            "kid": kid,
            "use": "sig",
            # Must match the algorithm epic_fetch.py signs with.
            "alg": "RS384",
            "n": modulus,
            "e": exponent,
        }]
    }
    JWKS_PATH.write_text(json.dumps(jwks, indent=2), encoding="utf-8")

    print(f"Wrote {JWKS_PATH.name}  (kid={kid})")
    print("This file contains only the PUBLIC key - safe to publish.")
    print()
    print(JWKS_PATH.read_text(encoding="utf-8"))
    print("Next:")
    print("  1. Host this file at a public HTTPS URL (public gist -> Raw URL is quickest)")
    print("  2. Paste that URL into Epic's 'Non-Production JWK Set URL' field")
    print("  3. Save the app, then run: python epic_fetch.py")
    print()
    print("Epic must be able to fetch the URL anonymously, and it has to return")
    print("this JSON as the response body - not an HTML page wrapping it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
