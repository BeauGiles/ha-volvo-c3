"""Remove personal data from a Volvo snapshot before it is put in a diagnostics download.

Pure Python (no Home Assistant imports) so it can be tested on its own.
"""

from __future__ import annotations

from typing import Any

# Whole values replaced when the key is exactly one of these (lower case).
_REDACT_KEYS = {
    "vin", "id", "refresh_token", "dpop_private_key_pem", "id_token", "app_installation_id",
    "registrationplate", "registration_plate", "latitude", "longitude", "altitude", "heading",
    "batterypackserialnumber", "plugandchargepcid", "visualid", "nickname", "streetaddress", "streetname", "streetnumber", "postalcode", "city", "name", "usernotes", "notes",
}
REDACTED = "**REDACTED**"


def redact(value: Any, *, vin: str | None = None, secrets: tuple[str, ...] = ()) -> Any:
    """A copy of ``value`` with sensitive keys blanked, and the VIN and ``secrets`` removed from every string.

    ``secrets`` catches identifiers in raw replies, where keys are only field numbers (``unknown_3``).
    """
    if isinstance(value, dict):
        return {
            k: REDACTED if str(k).lower() in _REDACT_KEYS else redact(v, vin=vin, secrets=secrets)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v, vin=vin, secrets=secrets) for v in value]
    if isinstance(value, str):
        if vin and vin in value:
            value = value.replace(vin, "<VIN>")
        for secret in secrets:
            if secret and len(secret) >= 4 and secret in value:
                value = value.replace(secret, REDACTED)
    return value
