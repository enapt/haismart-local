"""Fetch Haier's published byte map for a device class that is not in the shipped bundle.

The integration ships the map for 165 device classes, which is what the catalogue on hand covers —
not what exists. A device whose class is missing would otherwise get no entities at all, so it is
fetched once at setup and cached on the config entry.

**The call is unauthenticated** and keyed by the full 64-hex uPlusId, which the appliance announces
for itself over the key-free discovery channel. So this works for a device added without an account,
and it discloses nothing about the user: the typeid identifies a product line, not a unit.

    GET standardcfm.haigeek.com/hardwareconfig/config/getDownUrlByFormat
        ?typeid=<64-hex>&formatver=V3&servicename=SDK&servicekey=<the SDK's own key>
      -> {"data": [{"f_url", "f_md5", "f_version"}]}   then GET f_url -> the config JSON
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode

from .cloud import Request, Response, _httpx_transport

_LOGGER = logging.getLogger(__name__)

CONFIG_HOST = "https://standardcfm.haigeek.com"
CONFIG_PATH = "/hardwareconfig/config/getDownUrlByFormat"
# The SDK's own service key, read out of `liball-in-one.so`. It is a constant shipped in every copy
# of Haier's app, not a secret and not a per-user credential.
SERVICE_KEY = "1234567890abcdefghigklmnopqrstuv"
# V3 covers the current families and V2 the older ones. Tried in order; a class answers to one.
FORMATS = ("V3", "V2")

Transport = Callable[[Request], Awaitable[Response]]


async def async_fetch_device_config(
    typeid: str, *, transport: Transport | None = None, timeout: float = 15.0
) -> dict[str, Any] | None:
    """Haier's configFile for ``typeid``, or ``None`` if the service has nothing for it.

    ``None`` for every failure, deliberately: this runs during setup of an appliance that is
    otherwise working, and a vendor CDN being unreachable must not stop it. The caller retries on
    the next start.
    """
    send = transport or _httpx_transport
    if not typeid or len(typeid) != 64:
        return None
    for formatver in FORMATS:
        query = urlencode({
            "typeid": typeid, "formatver": formatver,
            "servicename": "SDK", "servicekey": SERVICE_KEY,
        })
        try:
            listing = await send(Request("GET", f"{CONFIG_HOST}{CONFIG_PATH}?{query}", {}, ""))
            if listing.status != 200:
                continue
            entries = (json.loads(listing.text) or {}).get("data") or []
            if not entries:
                continue
            entry = entries[0]
            body = await send(Request("GET", entry["f_url"], {}, ""))
            if body.status != 200:
                continue
            # The service states the file's md5. A truncated or substituted body would otherwise
            # become a byte map, and a wrong byte map is confidently wrong readings.
            if entry.get("f_md5") and hashlib.md5(
                body.text.encode(), usedforsecurity=False
            ).hexdigest() != entry["f_md5"]:
                _LOGGER.warning("device config for %s failed its published md5", typeid)
                continue
            return json.loads(body.text)
        except Exception as err:  # noqa: BLE001 - never fail an appliance's setup over this
            _LOGGER.debug("device config fetch for %s (%s) failed: %s", typeid, formatver, err)
    return None
