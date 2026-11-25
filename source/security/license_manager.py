"""Offline machine-bound license verification for application entry points."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

PRODUCT_ID = "MidMovieAds-2026"
SOURCE_ROOT = Path(__file__).resolve().parents[1]
LICENSE_PATH = SOURCE_ROOT / "license.txt"
PUBLIC_KEY_PATH = Path(__file__).with_name("license_public_key.pem")
FINGERPRINT_LENGTH = 64

_POWERSHELL_FINGERPRINT_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$system = Get-CimInstance -ClassName Win32_ComputerSystemProduct | Select-Object -First 1
$bios = Get-CimInstance -ClassName Win32_BIOS | Select-Object -First 1
$board = Get-CimInstance -ClassName Win32_BaseBoard | Select-Object -First 1
[pscustomobject]@{
    system_uuid = $system.UUID
    bios_serial = $bios.SerialNumber
    baseboard_serial = $board.SerialNumber
} | ConvertTo-Json -Compress
"""

_INVALID_HARDWARE_VALUES = {
    "",
    "0",
    "00",
    "00000000",
    "0000000000000000",
    "00000000000000000000000000000000",
    "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
    "NONE",
    "UNKNOWN",
    "NOTSPECIFIED",
    "DEFAULTSTRING",
    "TOBEFILLEDBYOEM",
    "SYSTEMSERIALNUMBER",
    "NA",
}


@dataclass(frozen=True)
class LicenseCheckResult:
    valid: bool
    code: str
    message: str
    fingerprint: str | None = None


class FingerprintError(RuntimeError):
    """Raised when the machine's hardware identity cannot be read reliably."""


def _normalized_hardware_value(value: Any) -> str:
    normalized = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if (normalized in _INVALID_HARDWARE_VALUES
            or (normalized and set(normalized) <= {"0"})
            or (normalized and set(normalized) <= {"F"})):
        return ""
    return normalized


def get_machine_fingerprint() -> str:
    """Return a fixed-length SHA-256 fingerprint of the selected SMBIOS values."""
    if os.name != "nt":
        raise FingerprintError("Machine-bound activation is currently supported on Windows only.")
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
             _POWERSHELL_FINGERPRINT_SCRIPT],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=30,
        )
        identifiers = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        detail = getattr(exc, "stderr", None)
        raise FingerprintError(f"Unable to read Windows hardware identifiers: {detail or exc}") from exc
    if not isinstance(identifiers, dict):
        raise FingerprintError("Windows returned an invalid hardware-identifier response.")

    canonical: dict[str, str] = {
        "system_uuid": _normalized_hardware_value(identifiers.get("system_uuid")),
        "bios_serial": _normalized_hardware_value(identifiers.get("bios_serial")),
        "baseboard_serial": _normalized_hardware_value(identifiers.get("baseboard_serial")),
    }
    valid_count = sum(bool(value) for value in canonical.values())
    if valid_count < 2:
        raise FingerprintError(
            f"Only {valid_count}/3 usable hardware identifiers were reported; at least two are required."
        )
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest().upper()
    return digest


def _urlsafe_decode(value: str) -> bytes:
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def _load_public_key() -> Any:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise RuntimeError("The 'cryptography' package is required; install the project requirements.") from exc
    try:
        key = serialization.load_pem_public_key(PUBLIC_KEY_PATH.read_bytes())
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Unable to load the embedded license verification key: {exc}") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise RuntimeError("The embedded license verification key is not an Ed25519 public key.")
    return key


def check_license(license_path: str | Path = LICENSE_PATH) -> LicenseCheckResult:
    """Verify the signed license file and bind it to this computer."""
    try:
        fingerprint = get_machine_fingerprint()
    except FingerprintError as exc:
        return LicenseCheckResult(False, "LIC-003", str(exc))

    path = Path(license_path).expanduser()
    if not path.is_file():
        return LicenseCheckResult(
            False,
            "LIC-001",
            f"Activation is required. Send the machine fingerprint below and save the returned license as {path}.",
            fingerprint,
        )
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return LicenseCheckResult(False, "LIC-002", f"Unable to read the license file: {exc}", fingerprint)

    try:
        version, encoded_payload, encoded_signature = token.split(".")
        if version != "MMA1":
            raise ValueError("Unsupported license format.")
        payload_bytes = _urlsafe_decode(encoded_payload)
        signature = _urlsafe_decode(encoded_signature)
        payload = json.loads(payload_bytes.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("License payload must be a JSON object.")
        public_key = _load_public_key()
        public_key.verify(signature, payload_bytes)
        if payload.get("schema") != 1 or payload.get("product") != PRODUCT_ID:
            raise ValueError("License is for another product or has an unsupported schema.")
        if payload.get("fingerprint") != fingerprint:
            return LicenseCheckResult(
                False,
                "LIC-002",
                "This license belongs to a different machine. Contact the issuer for reactivation.",
                fingerprint,
            )
        if not isinstance(payload.get("license_id"), str) or not payload["license_id"].strip():
            raise ValueError("License ID is missing.")
    except ImportError as exc:
        return LicenseCheckResult(False, "LIC-900", str(exc), fingerprint)
    except RuntimeError as exc:
        return LicenseCheckResult(False, "LIC-900", str(exc), fingerprint)
    except Exception as exc:
        return LicenseCheckResult(
            False,
            "LIC-002",
            f"The license is invalid or does not match this installation: {exc}",
            fingerprint,
        )

    return LicenseCheckResult(True, "LIC-000", "License check passed.", fingerprint)
