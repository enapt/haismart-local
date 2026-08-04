"""Button to start the AC's self-clean cycle.

Self-clean is a one-shot *trigger*, not a toggle: the cycle runs to completion and there is no OFF
command — the device model declares a start and no stop, and pressing it again while it runs is
ignored. So it is a Button, not a switch. Pressing it sends ``selfCleaningStatus=1`` through the
confirmed grSetDAC group-set path; the library refuses the field on any family that has not placed
it, so the button is only created where control of it is real.

Live-confirmed on the classic family — with the unit on, in a non-auto mode and not sleeping, the
one bit read back set and the unit's own panel showed "CL". Offered on extended-36 from the shared
write frame (same group command, zero displacement) to be confirmed there.
"""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import HaismartConfigEntry, HaismartCoordinator
from .entity import HaismartEntity

_SELF_CLEAN_FIELD = "selfCleaningStatus"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaismartConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    # Only where this unit's report family can actually write the flag. Same rule the switches
    # follow: a button that fires an op the family cannot place would silently do nothing.
    if coordinator.supports_field(_SELF_CLEAN_FIELD):
        async_add_entities([HaismartSelfCleanButton(coordinator)])


class HaismartSelfCleanButton(HaismartEntity, ButtonEntity):
    """Starts a self-clean cycle. One-shot: it cannot be cancelled once running."""

    _attr_translation_key = "start_self_clean"

    def __init__(self, coordinator: HaismartCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_start_self_clean"

    @property
    def available(self) -> bool:
        """Greyed out when the unit's own model refuses the write.

        The model's modifiers lock self-clean while the unit is off, in auto mode, sleeping, or
        faulted — the exact states the hardware would drop the op in — and ``locked_fields`` already
        evaluates them. So the button disables itself in those states rather than fire an op that
        does nothing.
        """
        return (
            super().available
            and _SELF_CLEAN_FIELD not in self.coordinator.locked_fields
        )

    async def async_press(self) -> None:
        await self.coordinator.async_send_control({_SELF_CLEAN_FIELD: 1})
