"""The Haismart local integration — fully-local uSS control of Haier ACs (no cloud, no MQTT)."""
from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .coordinator import HaismartConfigEntry, HaismartCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: HaismartConfigEntry) -> bool:
    coordinator = HaismartCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    # A successful first read means the stored key works, so clear any stale-localKey repair left
    # over from a rotation (e.g. after a manual reauth, which reloads the entry).
    coordinator.clear_stale_localkey_issue()

    # Entries set up before the model rules were fetched hold a model with none in it, which leaves
    # the integration offering controls the unit discards. Top it up once, in the background: it is
    # a cloud round trip and nothing here should wait on it.
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
