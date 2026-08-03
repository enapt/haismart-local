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

import asyncio
import logging

from haismart_hrdp import udiscovery
from homeassistant.core import HomeAssistant

from .const import HAIER_OUIS

_LOGGER = logging.getLogger(__name__)

BROADCAST_TIMEOUT = 3.0


async def async_resolve_host_arp(device_id: str) -> str | None:
    """Map the deviceId (= MAC) to a LAN IP via aiodiscover's ARP scan (HA's DHCP mechanism)."""
    target = device_id.replace(":", "").lower()
    try:
        from aiodiscover import DiscoverHosts

        hosts = await DiscoverHosts().async_discover()
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


async def async_scan_for_appliances(
    hass: HomeAssistant, *, timeout: float = BROADCAST_TIMEOUT
) -> list[udiscovery.DeviceInfo]:
    """Every Haier appliance answering on this network, found without a key or an account.

    Two steps, cheap then precise. Home Assistant already knows every MAC on the subnet -- it runs
    an ARP scan for its own DHCP discovery -- so the candidates are simply the hosts whose MAC
    begins with one of the manufacturer's registered prefixes. Each of those is then *asked*
    whether it is one of these appliances, which costs one UDP datagram and returns its device ID,
    its wire-model identifier and whether it can still reach the vendor's servers.

    That second step is what makes this safe to act on. An OUI match alone is a guess -- the same
    prefix covers fridges and washing machines -- whereas an answer to the query is the appliance
    identifying itself.

    Falls back to a broadcast when the ARP scan finds nothing to ask, since a unit on a different
    subnet or behind a router that hides its neighbours can still answer one. Never raises: this
    runs while someone is waiting on a form, and an empty list simply means they type an address.
    """
    candidates: list[str] = []
    try:
        from aiodiscover import DiscoverHosts

        for host in await DiscoverHosts().async_discover():
            mac = str(host.get("macaddress", "")).replace(":", "").upper()
            if mac.startswith(HAIER_OUIS) and host.get("ip"):
                candidates.append(str(host["ip"]))
    except Exception as err:  # noqa: BLE001 - best effort; aiodiscover ships with `dhcp`
        _LOGGER.debug("ARP scan unavailable: %s", err)

    found: list[udiscovery.DeviceInfo] = []
    if candidates:
        replies = await asyncio.gather(
            *(udiscovery.async_query(ip, timeout=timeout) for ip in candidates),
            return_exceptions=True,
        )
        found = [r for r in replies if isinstance(r, udiscovery.DeviceInfo)]
    if found:
        return found

    try:
        return await hass.async_add_executor_job(
            lambda: udiscovery.discover(timeout=timeout)
        )
    except OSError as err:
        _LOGGER.debug("broadcast discovery failed: %s", err)
        return []
