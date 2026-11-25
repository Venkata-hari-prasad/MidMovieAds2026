"""Issue an offline signed license from an operator's machine fingerprint."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import uuid

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from reporting.terminal_ui import TerminalUI  # noqa: E402
from security.license_manager import FINGERPRINT_LENGTH, PRODUCT_ID  # noqa: E402

PRIVATE_KEY_PATH = (
    Path.home() / "AppData" / "Local" / "MidMovieAds2026" / "license-keys" / "issuer_private_key.pem"
)


def _urlsafe_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def issue_license(fingerprint: str, private_key_path: str | Path, output_path: str | Path) -> Path:
    """Create a product license signed by the offline issuer's Ed25519 private key."""
    normalized_fingerprint = fingerprint.strip().upper()
    if not re.fullmatch(rf"[0-9A-F]{{{FINGERPRINT_LENGTH}}}", normalized_fingerprint):
        raise ValueError(f"Fingerprint must be exactly {FINGERPRINT_LENGTH} hexadecimal characters.")
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError as exc:
        raise RuntimeError("The 'cryptography' package is required; install the project requirements.") from exc

    key_path = Path(private_key_path).expanduser()
    try:
        private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Unable to load issuer private key {key_path}: {exc}") from exc
    if not isinstance(private_key, Ed25519PrivateKey):
        raise RuntimeError(f"Issuer key is not an Ed25519 private key: {key_path}")

    payload = {
        "schema": 1,
        "product": PRODUCT_ID,
        "license_id": uuid.uuid4().hex,
        "fingerprint": normalized_fingerprint,
        "issued_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = private_key.sign(payload_bytes)
    token = f"MMA1.{_urlsafe_encode(payload_bytes)}.{_urlsafe_encode(signature)}\n"

    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(token, encoding="utf-8", newline="\n")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Issue a signed offline MidMovieAds-2026 license.")
    parser.add_argument("--fingerprint", required=True, help="64-character machine fingerprint from first-run activation.")
    parser.add_argument("--output", required=True, type=Path, help="Path for the license file to send to the operator.")
    parser.add_argument("--private-key", type=Path, default=PRIVATE_KEY_PATH,
                        help=f"Issuer private key path (default: {PRIVATE_KEY_PATH}).")
    args = parser.parse_args()
    ui = TerminalUI()
    try:
        output = issue_license(args.fingerprint, args.private_key, args.output)
    except (ValueError, RuntimeError) as exc:
        ui.error(f"LIC-ISSUE-001: {exc}")
        return 2
    ui.status(f"License issued successfully: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
