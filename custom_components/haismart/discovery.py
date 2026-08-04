"""Finding an AC's LAN address without the cloud.

Two mechanisms, tried in order of dependability:

1. **ARP / DHCP** (`aiodiscover`, the same machinery Home Assistant's own `dhcp` component uses).
   The uSDK deviceId *is* the Wi-Fi module's MAC, so a MAC->IP lookup identifies the unit wherever
   it has landed. This works on any network HA can see, which is why it goes first.
2. **A UDISCOVERY broadcast** as a backstop. It is the protocol's own answer to "who is out
   there", but broadcast is not dependable in practice -- plenty of access points filter or rate
   limit it, and units that answer a unicast query reliably can stay silent to a broadcast one.
   Useful when it works, never relied upon.

These modules move on DHCP, and a moved unit is indistinguishable from a dead one until something
goes looking for it, so this is worth doing properly rather than asking the user to fix a host by
hand.
"""
from __future__ import annotations

import logging

from haismart_hrdp import udiscovery
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

BROADCAST_TIMEOUT = 3.0


async def async_resolve_host_arp(device_id: str) -> str | None:
    """Map the deviceId (= MAC) to a LAN IP via aiodiscover's ARP scan (HA's DHCP mechanism)."""
    target = device_id.replace(":", "").lower()
    try:
        from aiodiscover import DiscoverHosts
        # Limit discovery to ARP/DHCP to avoid needing raw socket permissions for TC
        hosts = await DiscoverHosts(arp=True, dhcp=True, tc=False).async_discover()
    except Exception:  # noqa: BLE001 - best-effort; aiodiscover ships with the dhcp component
        return None
    for host in hosts:
        if str(host.get("macaddress", "")).replace(":", "").lower() == target:
            return host.get("ip")
    return None


async def async_find_host(hass: HomeAssistant, device_id: str) -> str | None:
    """This AC's current LAN address, or ``None`` if nothing on the network admits to being it.

    Never raises: callers use this on a failure path, where an exception would replace the error
    that actually matters.
    """
    if (ip := await async_resolve_host_arp(device_id)) is not None:
        return ip
    try:
        found = await hass.async_add_executor_job(
            lambda: udiscovery.discover(timeout=BROADCAST_TIMEOUT)
        )
    except OSError as err:
        _LOGGER.debug("broadcast discovery failed: %s", err)
        return None
    match = next((d for d in found if d.device_id == device_id), None)
    return match.host or None if match else None
