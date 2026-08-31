"""Self-signed certificate generation for the local Cync server.

Cync device firmware does not verify the server certificate (it connects to
whatever cm.gelighting.com resolves to and does not pin), so a self-signed
cert is sufficient. Generated once and cached in the HA storage dir.
"""
from __future__ import annotations

import datetime
import logging
from pathlib import Path

_LOGGER = logging.getLogger(__name__)


def ensure_certificate(cert_path: str, key_path: str) -> bool:
    """Create a self-signed cert/key pair if not already present.

    Returns True if a usable cert+key exist afterwards, False on failure.
    """
    cert_file = Path(cert_path)
    key_file = Path(key_path)

    if cert_file.exists() and key_file.exists():
        return True

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError as err:
        # cryptography ships with Home Assistant core, so this should not
        # happen; log clearly if it ever does.
        _LOGGER.error("cryptography not available, cannot generate cert: %s", err)
        return False

    try:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        subject = issuer = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, "cm.gelighting.com"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Cync Lights Local"),
            ]
        )

        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(
                x509.SubjectAlternativeName(
                    [
                        x509.DNSName("cm.gelighting.com"),
                        x509.DNSName("*.gelighting.com"),
                    ]
                ),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )

        cert_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        _LOGGER.info("Generated self-signed cert for local Cync server")
        return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Failed to generate local server certificate: %s", err)
        return False
