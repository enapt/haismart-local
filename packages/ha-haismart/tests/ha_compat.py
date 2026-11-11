"""Home Assistant test helpers, from whichever test package matches the installed core.

Home Assistant publishes its test fixtures as ``pytest-homeassistant`` from 2026.11 on; earlier
cores pair with ``pytest-homeassistant-custom-component``. Both expose the same helpers under
``common``. ``DhcpServiceInfo`` lives in ``helpers.service_info.dhcp`` from 2025.2 on, and the
DHCP component no longer re-exports it. Tests import these names from here so that one suite runs
against every core CI tests.
"""
from __future__ import annotations

try:  # Home Assistant 2026.11+
    from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
except ImportError:
    from pytest_homeassistant_custom_component.common import (  # type: ignore[no-redef]
        MockConfigEntry,
        async_fire_time_changed,
    )

try:  # Home Assistant 2025.2+
    from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
except ImportError:  # pragma: no cover - Home Assistant < 2025.2
    from homeassistant.components.dhcp import DhcpServiceInfo  # type: ignore[no-redef]

__all__ = ["DhcpServiceInfo", "MockConfigEntry", "async_fire_time_changed"]
