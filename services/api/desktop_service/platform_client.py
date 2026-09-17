"""Client for the Instance platform's internal charge API (SPEC v0.2: pay per action, no balance).

Cubicle asks for a charge when someone needs runtime, shows the payer the platform's payment sheet, and
does the work once the charge is paid. An unpriced SKU comes back free, which is how a deployment with
no prices set behaves: everything runs and nothing is charged.

Every call is server to server with the service secret. Nothing here is reachable from a browser or from
a workspace API key.
"""

import logging

import httpx

from .config import settings

log = logging.getLogger(__name__)
TIMEOUT = 10.0


class PlatformError(RuntimeError):
    """The platform could not be reached or answered with an error."""


def configured():
    s = settings()
    return bool(s.platform_url and s.platform_service_token)


def _client():
    s = settings()
    return httpx.Client(
        base_url=s.platform_url.rstrip("/"),
        headers={"Authorization": "Bearer " + s.platform_service_token},
        timeout=TIMEOUT,
    )


def _request(method, path, **kwargs):
    if not configured():
        raise PlatformError("The platform service is not configured")
    try:
        with _client() as client:
            response = client.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        raise PlatformError(f"Platform unreachable: {type(exc).__name__}") from None
    if response.status_code >= 400:
        detail = ""
        try:
            detail = response.json().get("error", {}).get("code", "")
        except ValueError:
            pass
        raise PlatformError(f"Platform returned {response.status_code} {detail}".strip())
    return response.json()


_price_cache = {"at": 0.0, "value": {}}
PRICE_TTL = 60.0


def prices(refresh=False):
    """SKU to unit price in micro-USDC. Cached briefly; an empty map means nothing is priced."""
    import time

    if not refresh and time.monotonic() - _price_cache["at"] < PRICE_TTL:
        return _price_cache["value"]
    rows = _request("GET", "/internal/v1/prices").get("prices", [])
    value = {row["sku"]: row.get("unitPriceMicro") for row in rows if row.get("sku")}
    _price_cache.update(at=time.monotonic(), value=value)
    return value


def price_for(sku):
    """None when the SKU has no price, which the platform defines as free."""
    return prices().get(sku)


def create_charge(
    sku, subject, idempotency_key, units=1, description=None, organization_id=None, expires_in_seconds=None
):
    """Create or replay a charge. Returns {"free": True} for an unpriced SKU, else the charge envelope."""
    body = {"sku": sku, "subject": subject, "units": units}
    if description:
        body["description"] = description
    if organization_id:
        body["organizationId"] = organization_id
    if expires_in_seconds:
        body["expiresInSeconds"] = expires_in_seconds
    return _request("POST", "/internal/v1/charges", json=body, headers={"Idempotency-Key": idempotency_key})


def get_charge(charge_id):
    return _request("GET", f"/internal/v1/charges/{charge_id}")


def charge_for_subject(subject):
    """The latest charge for one of our subjects, so a retry finds an existing payment."""
    body = _request("GET", "/internal/v1/charges", params={"subject": subject})
    if isinstance(body, dict) and "charge" in body:
        return body["charge"]
    if isinstance(body, dict) and "charges" in body:
        charges = body["charges"]
        return charges[0] if charges else None
    return body or None
