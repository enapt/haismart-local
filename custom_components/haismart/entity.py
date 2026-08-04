"""Base entity wiring device info + coordinator for Haismart entities."""
from __future__ import annotations

import re

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
            # Empty host = cloud-only entry (no LAN address), which has no configuration URL;
            # a blank "http://" is rejected by the HA device registry and kills entity creation.
            configuration_url=f"http://{coordinator.host}" if coordinator.host else None,
        )
