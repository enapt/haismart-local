"""Base entity wiring device info + coordinator for Haismart entities."""
from __future__ import annotations

import re

from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_BRAND, CONF_MODEL_NAME, DOMAIN, MANUFACTURER
from .coordinator import HaismartCoordinator

_MAC_ID = re.compile(r"^[0-9A-Fa-f]{12}$")


class HaismartEntity(CoordinatorEntity[HaismartCoordinator]):
    """Common base: attaches every entity to one HA device per AC."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HaismartCoordinator) -> None:
        super().__init__(coordinator)
        device_id = coordinator.device_id
        # on this hardware the uSDK deviceId IS the wifi module's MAC (e.g. A1B2C3D4E5F6)
        connections = (
            {(CONNECTION_NETWORK_MAC, format_mac(device_id))}
            if _MAC_ID.match(device_id)
            else set()
        )
        entry_data = coordinator.config_entry.data
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            connections=connections,
            # `brand`/`model` come from the cloud device list's extendedInfo when available, so the
            # device page shows "PRO X INV-42/3PH" rather than a raw product code like AACRL2E00.
            manufacturer=entry_data.get(CONF_BRAND) or MANUFACTURER,
            model=entry_data.get(CONF_MODEL_NAME) or coordinator.product_code,
            model_id=coordinator.product_code,
            name=coordinator.config_entry.title,
            # Reported by the AC over the key-free UDISCOVERY query; absent on units that don't
            # answer it, in which case HA simply shows no firmware version.
            sw_version=coordinator.firmware,
            configuration_url=f"http://{coordinator.host}",
        )

    def raise_if_locked(self, field: str) -> None:
        """Refuse a command the unit's own model says it would discard, saying why.

        These controls stay **available** while locked, rather than disappearing. A unit ignoring
        its economy setting in fan-only is a normal operating state, not a fault, and that is what
        an unavailable entity looks like — it also loses the reading and leaves a gap in the
        history for as long as the mode lasts. The setting is still readable throughout; only
        writing is refused.

        Refusing here rather than in the coordinator is deliberate. Commands are not gated
        centrally: a model marks almost everything unwritable while a unit is off, including the
        mode, and turning a unit on is exactly a write of the mode — which real hardware accepts. An
        entity knows which field it is and can refuse only for itself.

        The reason comes from the model, so it names the actual condition. Where a rule states none,
        the refusal still happens and says only that the unit will not accept it now — a missing
        explanation must never turn into a command that silently does nothing.
        """
        if field not in self.coordinator.locked_fields:
            return
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="control_rejected",
            translation_placeholders={
                "name": self.name or self.coordinator.config_entry.title,
                "error": self.coordinator.locked_reasons.get(field)
                or "not available in the unit's current state",
            },
        )
