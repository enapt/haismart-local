"""The Haismart local integration — fully-local uSS control of Haier ACs (no cloud, no MQTT)."""
from __future__ import annotations

# HACS/vendored build: bundled helper libs live in ./vendor (no pip step needed). This runs
# before any submodule import, so their top-level `from haismart_hrdp import ...` resolve.
# ruff: noqa: E402 - the sys.path shim below must precede the submodule imports by design.
import os as _os
import sys as _sys

_vendor = _os.path.join(_os.path.dirname(__file__), "vendor")
if _vendor not in _sys.path:
    _sys.path.insert(0, _vendor)

import asyncio
import contextlib

from homeassistant.core import HomeAssistant

from .const import IDENTITY_TOPUP_TIMEOUT, PLATFORMS
from .coordinator import HaismartConfigEntry, HaismartCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: HaismartConfigEntry) -> bool:
    coordinator = HaismartCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

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
    # An entry added through an account before its product code was kept does not store one. The
    # places where that could pick the wrong model already guard against it -- the profile comes
    # from the device's own model, and the rules lookup refuses a defaulted code -- so this is not
    # a correctness fix. It is that nothing can be looked up by a code that is missing: the shipped
    # rules cannot complete what the fetched copy leaves empty, and a report names a model the unit
    # may not be. The account is signed in and its device list has always carried this, so tell the
    # entry rather than ask anyone to re-add a working appliance. Awaited because what it learns
    # decides which rules are read immediately below.
    if coordinator.needs_identity_topup:
        # Bounded: an unreachable network teaches it nothing, so without a limit every restart
        # would pay the full HTTP timeout for a lookup that is only ever an improvement.
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(IDENTITY_TOPUP_TIMEOUT):
                await coordinator.async_topup_identity()

    if coordinator.needs_invisible_topup:
        await coordinator.async_fetch_model_rules()
    else:
        entry.async_create_background_task(
            hass, coordinator.async_fetch_model_rules(), "haismart model rules"
        )

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
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
