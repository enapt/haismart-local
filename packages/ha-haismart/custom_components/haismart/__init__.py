"""The Haismart integration — fully-local uSS control of Haier ACs (no cloud, no MQTT)."""
from __future__ import annotations

# HACS/vendored build: bundled helper libs live in ./vendor (no pip step needed). This runs
# before any submodule import, so their top-level `from haismart_hrdp import ...` resolve.
# ruff: noqa: E402 - the sys.path shim below must precede the submodule imports by design.
import os as _os
import sys as _sys
import logging as _logging

_vendor = _os.path.join(_os.path.dirname(__file__), "vendor")
if _vendor not in _sys.path:
    _sys.path.insert(0, _vendor)

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import DOMAIN, PLATFORMS
from .coordinator import HaismartConfigEntry, HaismartCoordinator

_LOGGER = _logging.getLogger(__name__)

# Services are registered once per HA run, not per entry (a second entry would otherwise
# overwrite the first's registrations and leave a dangling handler after it unloads).
_SERVICES_REGISTERED = f"{DOMAIN}_services_registered"

SET_CLOUD_ATTRIBUTE = "set_cloud_attribute"
GET_CLOUD_ATTRIBUTE = "get_cloud_attribute"

_SERVICE_FIELDS = {
    vol.Required("device_id"): cv.string,
    vol.Required("attribute"): cv.string,
}


def _coordinator_for_device(
    hass: HomeAssistant, device_id: str
) -> HaismartCoordinator | None:
    """The coordinator whose device matches ``device_id`` (case-insensitive)."""
    device_id = device_id.upper()
    for entry in hass.config_entries.async_entries(DOMAIN):
        coordinator = entry.runtime_data
        if coordinator is not None and coordinator.device_id.upper() == device_id:
            return coordinator
    return None


def _find_coordinator(hass: HomeAssistant, call: ServiceCall) -> HaismartCoordinator:
    coordinator = _coordinator_for_device(hass, call.data["device_id"])
    if coordinator is None:
        raise HomeAssistantError(f"No haismart device with id {call.data['device_id']!r}")
    return coordinator


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register the cloud-control services (idempotent)."""
    if hass.data.get(_SERVICES_REGISTERED):
        return
    hass.data[_SERVICES_REGISTERED] = True

    async def _set_cloud_attribute(hass: HomeAssistant, call: ServiceCall) -> None:
        coordinator = _find_coordinator(hass, call)
        await coordinator.async_cloud_set_attribute(
            call.data["attribute"], call.data["value"]
        )

    async def _get_cloud_attribute(hass: HomeAssistant, call: ServiceCall) -> None:
        coordinator = _find_coordinator(hass, call)
        call.response = await coordinator.async_cloud_get_attribute(call.data["attribute"])

    hass.services.async_register(
        DOMAIN, SET_CLOUD_ATTRIBUTE, _set_cloud_attribute,
        vol.Schema({**_SERVICE_FIELDS, vol.Required("value"): cv.match_all}),
    )
    hass.services.async_register(
        DOMAIN, GET_CLOUD_ATTRIBUTE, _get_cloud_attribute,
        vol.Schema(_SERVICE_FIELDS), supports_response=SupportsResponse.ONLY,
    )


async def async_setup_entry(hass: HomeAssistant, entry: HaismartConfigEntry) -> bool:
    coordinator = HaismartCoordinator(hass, entry)
    if coordinator.host:
        await coordinator.async_config_entry_first_refresh()
    else:
        # Added without a LAN IP: local polling is skipped and the device may legitimately be
        # offline for the cloud (a washer that is simply switched off). Do not fail setup in an
        # endless retry loop -- set up anyway and let the entities show as unavailable until the
        # device comes online; the first successful cloud read brings them alive.
        try:
            await coordinator.async_config_entry_first_refresh()
        except (UpdateFailed, ConfigEntryNotReady) as err:
            _LOGGER.info(
                "%s: added cloud-only and currently offline for the cloud (%s); "
                "it will come online automatically",
                entry.title, err,
            )

    # A successful first read means the stored key works, so clear any stale-localKey repair left
    # over from a rotation (e.g. after a manual reauth, which reloads the entry).
    coordinator.clear_stale_localkey_issue()

    # Entries set up before the model rules were fetched hold a model with none in it, which leaves
    # the integration offering controls the unit discards. Top it up once. Normally in the
    # background -- it is a cloud round trip and nothing should wait on it -- but for an entry that
    # also predates the model carrying its `invisible_attributes`, wait for it: the optional-feature
    # entities are created next, and without that flag they would be built for features the generic
    # model over-declares (which read a permanent, meaningless off) rather than the ones the unit
    # actually has. A fresh onboarding already has the flag, so it never waits.
    if coordinator.needs_invisible_topup:
        await coordinator.async_fetch_model_rules()
    else:
        entry.async_create_background_task(
            hass, coordinator.async_fetch_model_rules(), "haismart model rules"
        )

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await _async_register_services(hass)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: HaismartConfigEntry) -> None:
    """Reload when the OPTIONS change (poll interval) -- and only then.

    Update listeners fire on any entry change, data included, and the coordinator writes to
    ``entry.data`` at runtime: a rotated localKey, a uPlusId learned from the device, a DHCP move
    it followed. Reloading on those would tear the integration down and rebuild it in response to a
    change it had just made itself, dropping every entity for a moment each time.
    """
    coordinator = entry.runtime_data
    if entry.options == coordinator.options:
        return
    coordinator.options = dict(entry.options)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HaismartConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
