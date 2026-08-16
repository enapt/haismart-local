"""The user-facing boolean features an air conditioner may expose, beyond the dozen a family map
names by hand.

Each is an attribute a device's digital model may declare as a **group-set-writable boolean**
(``writeType=G``, a ``false``/``true`` code list) -- the optional comfort and air-treatment
functions a unit either has or does not. This module surfaces them **read-only**: a device that
declares one has the feature, its position comes from :mod:`haismart_hrdp.canonical_map`, and its
value is the bit at that position -- no capture per attribute. Writing them is a separate matter (a
group-set applies the whole word block, so a write needs its own confirmation); this is observability
only.

The set is deliberately the ones NOT already surfaced as dedicated controls (health, strong, quiet,
sleep, lamp, eco, self-clean) -- those keep their hand-built entities.
"""
from __future__ import annotations

from collections.abc import Mapping

from .canonical_map import CANONICAL

# attribute name (as the device declares it) -> our stable key / translation slug.
OPTIONAL_BOOL_FEATURES: Mapping[str, str] = {
    "electricHeatingStatus": "electric_heating",
    "freshAirStatus": "fresh_air",
    "10degreeHeatingStatus": "keep_warm_10c",
    "lightStatus": "ambient_light",
    "energySavingStatus": "energy_saving",
    "intelligenceStatus": "intelligent",
    "echoStatus": "buzzer_silent",           # set = buzzer stays silent (per the device model)
    "mouldProof": "mould_proof",
    "drying": "drying",
    "constDehumidificationStatus": "constant_dehumidify",
    "preventHeatstroke": "prevent_heatstroke",
    "preventSupercooling": "prevent_supercooling",
    "pvPowerSavingMode": "pv_saving",
    "uvSterilizationSwitch": "uv_sterilize",
    "windAvoidance": "wind_avoidance",
    "humidificationStatus": "humidification",
    "heatAccumulationStatus": "heat_accumulation",
}


# Optional MULTI-STATE features: attribute -> (slug, {wire value: state}). Read-only, like the
# booleans -- a select would write, and a group-set write needs its own confirmation.
OPTIONAL_ENUM_FEATURES: Mapping[str, tuple[str, Mapping[int, str]]] = {
    "humanSensingStatus": ("human_sensing", {0: "off", 1: "avoid", 2: "follow", 3: "on"}),
}


# Optional NUMERIC readings: attribute -> (slug, largest valid value). The air-quality suite a unit
# may carry (PM2.5 probes, CO2/formaldehyde/VOC sensing) plus the humidity probe, read from the
# status report at the published-map positions, gated exactly like the booleans: the device declares
# the attribute and does not mark it invisible.
#
# The bound is the maximum the published models themselves state for the attribute (every AC profile
# agrees on each), and a raw value above it is a sentinel or a misread, never a measurement.
# **Zero is absent, not a reading**: a unit without the probe leaves the register at 0 for its whole
# service life (every capture of every family so far), and a permanent 0 ug/m3 in someone's
# statistics is a fabricated number. A real probe in habitable air does not rest at exactly 0 for
# any of these quantities -- CO2 in particular never reads below ~400 ppm anywhere near a building.
OPTIONAL_NUMERIC_READINGS: Mapping[str, tuple[str, int]] = {
    "indoorPM2p5Value": ("indoor_pm25", 4095),
    "outdoorPM2p5Value": ("outdoor_pm25", 4095),
    "ch2oValue": ("formaldehyde", 10_000),
    "vocValue": ("voc_level", 1023),      # a unitless index (the models publish no unit for it)
    "co2Value": ("co2", 10_000),
    "indoorHumidity": ("humidity", 100),
}


def _attribute_names(model) -> set[str]:
    """The attribute names a device actually has: the ones it declares, minus the ones its model
    marks ``invisible``.

    A generic model over-declares -- it lists every attribute the product line might have, and marks
    the ones a given unit lacks ``invisible`` (they then report a constant zero). Surfacing an
    invisible attribute would be an entity that reads a permanent, meaningless off. So they are
    removed here, from any shape the model turns up in: a digital model ``{"attributes": [...],
    "invisible_attributes": [...]}``, that ``attributes`` list itself, or a bare collection of names.
    """
    if not model:
        return set()
    invisible: set[str] = set()
    if isinstance(model, Mapping):
        invisible = {str(n) for n in model.get("invisible_attributes") or ()}
        attrs = model["attributes"] if "attributes" in model else model
    else:
        attrs = model
    if isinstance(attrs, Mapping):
        names = {str(n) for n in attrs}
    else:
        names = set()
        for a in attrs:
            n = a.get("name") if isinstance(a, Mapping) else a
            if n is not None:            # an entry with no name, not one named "None"
                names.add(str(n))
    return {n for n in names if n} - invisible


# Only features the canonical map can place: a declared attribute the map does not carry cannot be
# read off any report, so surfacing it would be an entity that never has a value. The map covers 8
# of the boolean set; the rest (mould-proof, drying, UV, PV, ...) wait on a position.
_PLACEABLE_BOOL = frozenset(n for n in OPTIONAL_BOOL_FEATURES if n in CANONICAL)
_PLACEABLE_ENUM = frozenset(n for n in OPTIONAL_ENUM_FEATURES if n in CANONICAL)
_PLACEABLE_NUMERIC = frozenset(n for n in OPTIONAL_NUMERIC_READINGS if n in CANONICAL)


def _known_feature_set(model) -> bool:
    """Whether a model carries the ``invisible_attributes`` key -- present (even empty) means we know
    which attributes this unit actually has; absent means we do NOT, so no optional-feature entities
    are offered rather than risk surfacing ones the generic model over-declares. A bare list/set of
    names (no digital model) is treated as known -- the caller vouched for it (tests, direct use)."""
    return not isinstance(model, Mapping) or "invisible_attributes" in model


def declared_attribute_names(model) -> frozenset[str]:
    """Every attribute the model declares and does not mark ``invisible`` — empty when the unit's
    real feature set is unknown (see :func:`_known_feature_set`), never a guess. The generic form
    of the gates below, for callers deciding about attributes outside the curated tables (a
    single-parameter control is offered only to units that declare its attribute)."""
    if not _known_feature_set(model):
        return frozenset()
    return frozenset(_attribute_names(model))


def declared_bool_features(model) -> frozenset[str]:
    """The optional boolean features a device declares AND the map can place -- empty unless we know
    the unit's real feature set (see :func:`_known_feature_set`)."""
    if not _known_feature_set(model):
        return frozenset()
    return _PLACEABLE_BOOL & _attribute_names(model)


def declared_enum_features(model) -> frozenset[str]:
    """The optional multi-state features a device declares AND the map can place -- same gate."""
    if not _known_feature_set(model):
        return frozenset()
    return _PLACEABLE_ENUM & _attribute_names(model)


def declared_numeric_readings(model) -> frozenset[str]:
    """The optional numeric readings a device declares AND the map can place -- same gate."""
    if not _known_feature_set(model):
        return frozenset()
    return _PLACEABLE_NUMERIC & _attribute_names(model)


def read_numeric_readings(wire_model, declared, blob: bytes) -> dict[str, int]:
    """Read the declared numeric air-quality/humidity values out of ``blob``.

    Same map-and-position basis as :func:`read_bool_features`. A value of zero is the register of a
    probe the unit does not have (absent, not a measurement), and one above the published maximum is
    a sentinel; both are dropped rather than reported.
    """
    names = declared_numeric_readings(declared)
    if not names:
        return {}
    out: dict[str, int] = {}
    for name, field in wire_model.model_fields(sorted(names), len(blob)).items():
        _slug, bound = OPTIONAL_NUMERIC_READINGS[name]
        value = field.read(blob)
        if isinstance(value, int) and not isinstance(value, bool) and 0 < value <= bound:
            out[name] = value
    return out


def read_enum_features(wire_model, declared, blob: bytes) -> dict[str, str]:
    """Read the declared multi-state features out of ``blob`` as their labelled state.

    Same map-and-position basis as :func:`read_bool_features`; the raw value is looked up in the
    attribute's state map, and a value the map does not name is dropped rather than shown as a code.
    """
    names = declared_enum_features(declared)
    if not names:
        return {}
    out: dict[str, str] = {}
    for name, field in wire_model.model_fields(sorted(names), len(blob)).items():
        states = OPTIONAL_ENUM_FEATURES[name][1]
        value = field.read(blob)
        if isinstance(value, int) and value in states:
            out[name] = states[value]
    return out


def read_bool_features(wire_model, declared, blob: bytes) -> dict[str, bool]:
    """Read the declared optional boolean features out of ``blob`` at their published-map positions.

    ``wire_model`` is the family's model (its :meth:`WireModel.model_fields` returns nothing unless
    the family has a *confirmed* whole-word displacement, which is the safety gate -- a family whose
    map is not pinned yields no features rather than a guess). Only ``bool`` results are kept.
    """
    names = declared_bool_features(declared)
    if not names:
        return {}
    out: dict[str, bool] = {}
    for name, field in wire_model.model_fields(sorted(names), len(blob)).items():
        value = field.read(blob)
        if isinstance(value, bool):
            out[name] = value
    return out
