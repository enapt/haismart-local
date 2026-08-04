"""Core data types for the haismart-hrdp library.

The one live model type is :class:`AttributeProfile` — the per-model "cool vs 1 vs COOL" knowledge
that maps a device's STD enum values to the normalized tokens the library exposes. It is
defaults are overridable
per model, so real digital-model data slots in as configuration rather than code edits.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

# Haier's STD ("standard") enum code -> normalized token.
#
# These codes come from a Haier-WIDE space, not a per-model allocation. The tell is the gaps: a
# cooling-only model lists operationMode 0/1/2 and then jumps to 6 for fan-only, skipping 3/4/5. If
# each model numbered its own modes they would be contiguous. So the right way to read a digital
# model is "which of the global codes does this unit declare", not "what do its descriptions say".
#
# Only codes seen in real digital models are listed. operationMode 3 and 5 are deliberately ABSENT:
# they exist in the space but nothing here has observed them, and an unmapped code is dropped with a
# log line rather than guessed (a mode we cannot name simply doesn't appear in the entity).
STD_OPERATION_MODE: Mapping[str, str] = {
    "0": "auto",      # 智能/自动/舒适
    "1": "cool",      # 制冷
    "2": "dry",       # 除湿
    "4": "heat",      # 制热
    "6": "fan_only",  # 送风
}
STD_WIND_SPEED: Mapping[str, str] = {
    "1": "high",    # 高
    "2": "medium",  # 中
    "3": "low",     # 低
    "5": "auto",    # 自动
}


@dataclass(frozen=True)
class AttributeProfile:
    """Per-model STD attribute names + enum maps.

    This is the single home for the "cool vs 1 vs COOL" knowledge. STD enum values map to a small
    set of normalized tokens the library exposes; the HA integration maps those to HA climate.
    """

    power_attr: str = "onOffStatus"
    mode_attr: str = "operationMode"
    target_temp_attr: str = "targetTemperature"
    indoor_temp_attr: str = "indoorTemperature"
    humidity_attr: str = "indoorHumidity"
    fan_attr: str = "windSpeed"

    power_on_value: str = "true"
    power_off_value: str = "false"

    # STD value -> normalized token. The defaults MUST be keyed by the numeric STD codes, because
    # that is what `parse_full_status` produces (``str(byte >> 5)``). They used to be keyed by words
    # ("cool", "dehumidify", "wind"), which meant a profile that fell back to these defaults could
    # never match anything the decoder emitted: `normalized_mode("1")` returned None for every input,
    # so the climate entity showed no mode and no fan while still advertising both.
    mode_values: Mapping[str, str] = field(default_factory=lambda: dict(STD_OPERATION_MODE))
    fan_values: Mapping[str, str] = field(default_factory=lambda: dict(STD_WIND_SPEED))

    min_temp: float = 16.0
    max_temp: float = 30.0
    temp_step: float = 1.0

    # True when `mode_values` reflects what THIS unit actually supports (derived from its digital
    # model, or a hand-verified per-model profile). False for the generic STD fallback, which lists
    # every code the protocol defines so that DECODING a reported mode always works — but must not be
    # read as a capability list. A caller building a UI control should offer the full set only when
    # this is True, and otherwise stick to modes every AC has; see the note on `heat` in the HA
    # climate entity. Decoding is unaffected either way.
    modes_authoritative: bool = False

    def normalized_mode(self, std_value: str | None) -> str | None:
        if std_value is None:
            return None
        return self.mode_values.get(std_value)

    def std_mode(self, normalized: str) -> str | None:
        for std, norm in self.mode_values.items():
            if norm == normalized:
                return std
        return None

    def normalized_fan(self, std_value: str | None) -> str | None:
        if std_value is None:
            return None
        return self.fan_values.get(std_value)

    def std_fan(self, normalized: str) -> str | None:
        for std, norm in self.fan_values.items():
            if norm == normalized:
                return std
        return None
