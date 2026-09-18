"""Generate the RSA key pair Epic's backend OAuth flow needs.

Epic does not issue a client secret for backend (server-to-server) apps. You
prove identity by signing a JWT with a private key, and Epic verifies it with a
public certificate you upload when registering the app.

    pip install cryptography
    python make_keys.py

Writes two files next to this script:

    epic_private_key.pem   SECRET. Stays on your machine. Signs the JWT.
    epic_public_cert.pem   Upload THIS one to fhir.epic.com when registering.

Epic accepts a base64-encoded X.509 certificate, which is what this produces.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
except ImportError:
    print("This needs the 'cryptography' package:\n    pip install cryptography", file=sys.stderr)
    raise SystemExit(1)

HERE = Path(__file__).resolve().parent
PRIVATE_KEY_PATH = HERE / "epic_private_key.pem"
PUBLIC_CERT_PATH = HERE / "epic_public_cert.pem"

# Epic's backend OAuth requires RS384-signed JWTs, and a 2048-bit RSA key is
# the minimum they accept.
KEY_SIZE = 2048
CERT_VALID_DAYS = 3650


def main() -> int:
    if PRIVATE_KEY_PATH.exists():
        print(f"{PRIVATE_KEY_PATH.name} already exists.")
        print("Delete it first if you really want new keys - regenerating means")
        print("re-uploading the certificate to Epic and your current client stops working.")
        return 1

    print("Generating a 2048-bit RSA key pair ...")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=KEY_SIZE)

    PRIVATE_KEY_PATH.write_bytes(private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        # Unencrypted: the signing code has to read it unattended. That is why
        # it must never leave this machine or reach a git repository.
        encryption_algorithm=serialization.NoEncryption(),
    ))

    # Epic registers a certificate rather than a bare public key, so the public
    # half is wrapped in a self-signed X.509. Self-signed is fine - Epic only
    # uses it to hold your public key, never to verify a chain of trust.
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "sodexo-labor-forecasting"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Sodexo Healthcare POC"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=CERT_VALID_DAYS))
        .sign(private_key, hashes.SHA256())
    )
    PUBLIC_CERT_PATH.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))

    print()
    print(f"  {PRIVATE_KEY_PATH.name}   SECRET - keep local, never commit")
    print(f"  {PUBLIC_CERT_PATH.name}   upload this one to Epic")
    print()
    print("Next:")
    print("  1. https://fhir.epic.com -> sign in -> Build Apps -> Create")
    print("  2. Application Audience: 'Backend Systems'")
    print("  3. Add the FHIR resources you need: Encounter.Read, Patient.Read, Location.Read")
    print(f"  4. Upload {PUBLIC_CERT_PATH.name} as the public key")
    print("  5. Save, accept the terms, and copy the NON-PRODUCTION Client ID")
    print("  6. Put that Client ID in .env as EPIC_CLIENT_ID")
    print()
    print("Epic can take up to ~60 minutes to propagate a new client ID to the")
    print("sandbox. A 400 'invalid_client' straight after registering usually")
    print("means it has not synced yet, not that anything is wrong.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
