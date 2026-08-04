"""HTTP transport for the cloud client, backed by Home Assistant's shared httpx client.

The extractor's own default transport would otherwise construct an ``httpx.AsyncClient`` itself, and
building a client loads the CA bundle from disk — blocking I/O that HA detects and reports
("blocking call to load_verify_locations inside the event loop"). HA already owns a client whose
SSL context was created off-loop at startup, so we hand that to the library instead: no blocking
call, and cloud requests share HA's connection pool and settings.

Every place that talks to Haier's REST API (config flow sign-in, the coordinator's token refresh)
must pass ``transport=async_cloud_transport(hass)``. The localKey gateway fetch is unaffected — it
runs in an executor already.
"""
from __future__ import annotations

import logging

from haismart_extractor.cloud import Transport, httpx_transport
from homeassistant.core import HomeAssistant, callback

_LOGGER = logging.getLogger(__name__)


@callback
def async_cloud_transport(hass: HomeAssistant) -> Transport | None:
    """A Transport over HA's shared httpx client, or ``None`` to let the library use its own.

    ``None`` is a safe fallback rather than an error: the library builds its client off-loop too, so
    the only loss is HA's pooling/settings. Returning it keeps an unexpected HA-internal change from
    breaking sign-in outright.
    """
    try:
        from homeassistant.helpers.httpx_client import get_async_client
    except ImportError:  # pragma: no cover - helper has existed for many releases
        _LOGGER.debug("HA httpx helper unavailable; using the library's own client")
        return None
    return httpx_transport(get_async_client(hass))
