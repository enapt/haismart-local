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
    # --- the maintenance and air-treatment statuses the panel renders no switch for ---
    # Measured against every published model rather than assumed: the figure after each name is how
    # many of the 1,451 products declare it AND do not mark it invisible, i.e. how many could ever
    # show it. None of them appears in any panel control descriptor, which is the vendor's own way
    # of saying "status, not switch" -- so they belong here and not in `panel.PANEL_BOOL_CONTROLS`.
    # Their false/true codes are 0/1 on every air-conditioner description that publishes a code
    # map (checked -- the one device class that inverts `lockStatus` is not an air conditioner).
    "localFilterChangeFlag": "filter_change",     # 197 -- the filter-change reminder
    "lockStatus": "control_lock",                 # 17  -- the panel's electronic lock
    "pm2p5CleaningStatus": "pm25_purify",         # 26
    "ch2oCleaningStatus": "formaldehyde_purify",  # 6
    "windSensingStatus": "wind_sensing",          # 5   -- sensing-driven even airflow
}


# Optional MULTI-STATE features: attribute -> (slug, {wire value: state}). Read-only, like the
# booleans -- a select would write, and a group-set write needs its own confirmation.
OPTIONAL_ENUM_FEATURES: Mapping[str, tuple[str, Mapping[int, str]]] = {
    "humanSensingStatus": ("human_sensing", {0: "off", 1: "avoid", 2: "follow", 3: "on"}),
    # The two four-step quality ladders, whose states are the vendor's own words (优/良/中/差) and
    # not an invented scale. Both occupy a two-bit field, and every air-conditioner description
    # publishing a code map for them lists 0..3 mapping to itself -- so the wire value IS the level.
    # (Two descriptions publish a six-value, three-bit `airQuality`; both belong to another
    # appliance class, and on the air-conditioner map the neighbouring attribute already occupies
    # the bit a third one would need. Check the class before borrowing a width.)
    "airQuality": ("air_quality", {0: "excellent", 1: "good", 2: "moderate", 3: "poor"}),
    "pm2p5Level": ("pm25_level", {0: "excellent", 1: "good", 2: "moderate", 3: "poor"}),
    # Occupancy, as the presence sensor reports it. **0 is not a state**: the model names it
    # 无此功能 -- "no such function" -- an in-band statement that this unit has no presence sensor
    # at all, exactly like the telemetry actuator states' "information not available". Leaving it
    # out of the map is what drops it, so a unit without the sensor reads unknown rather than
    # claiming an empty room.
    "sensingResult": ("occupancy", {1: "unoccupied", 2: "one_person", 3: "several_people"}),
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
    # The purifier board's accumulated running hours (the model publishes the unit: `h`, 0..65535).
    # A counter, so the zero rule reads the same way it does for the energy register: a unit whose
    # board has never run reports 0 and is indistinguishable from one that does not have the board,
    # and a permanent 0 h in someone's statistics is a fabricated number.
    "totalCleaningTime": ("purifier_hours", 65535),
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


#: Attributes a device CLASS demonstrably carries on the wire while its products systematically do
#: not declare them. A narrow, evidence-carrying exception to the declaration gate -- never a general
#: loosening, which is what stops phantom entities.
#:
#: ``0d12`` (187 commercial cabinets) is the measured case. Its products publish a minimal cloud
#: control surface -- **17 distinct attribute names across all 187**, enumerated -- while the board
#: emits the full shared frame. The proof that under-declaration is systematic on this class, rather
#: than a statement about the hardware, is `outdoorTemperature`: **0 of 187 declare an outdoor probe
#: and every cabinet observed has a working one** (25-33 °C in Bangkok, 11-16 °C in Europe), which
#: this integration already surfaces. Applying the declaration gate literally here would delete that
#: sensor too.
#:
#: For `humanSensingStatus` specifically, three independent sources agree the class carries it:
#:  * the **alarm table** publishes `humanSensingModuleErr` (人感模块故障) on **187 of 187** `0d12`
#:    products and on **none of the other 1,264** -- a class-exclusive fault, and a manufacturer does
#:    not publish one for a module the line cannot have;
#:  * the vendor's own **panel bundle** for these products embeds a device model naming
#:    `humanSensingStatus` 感人模式 with all four values;
#:  * the **wire**: of four cabinets of one model, with identical firmware, one reads 3 ("on") at the
#:    published position while its three siblings read 0.
#:
#: ⚠️ Zero is NOT surfaced for these (see :func:`read_enum_features`): on a declaring unit 0 is the
#: real state "off", but where the hardware itself is inferred, 0 cannot be told from "not fitted".
#: Attributes that CONTRADICT a class-carried one at the same bits, keyed by the carried name.
#: If the device declares any of these, the carried attribute is NOT read -- its bits belong to
#: something else on that product.
#:
#: ⛔ `humanSensingStatus` sits at w23.b6/2, and on `0d12` the four-sided vanes **substitute** for
#: `windDirectionHorizontal` across **w23.b0-b11** as four 3-bit fields (b0/b3/b6/b9). So on a
#: four-sided cassette **b6-b7 are the low two bits of `4SidesWindDirection3`**, and reading them as
#: presence would report a VANE POSITION as a presence mode -- a wrong value, not a missing one.
#: Measured: of 187 `0d12` products, **52 declare the four-sided vanes and 91 declare
#: `windDirectionHorizontal`** -- so the class is not one layout at w23 and a per-CLASS gate is not
#: enough. This is the bit-reuse hazard `family_write.WRITE_OVERRIDES` exists for, arriving on the
#: read path.
CARRIED_BLOCKED_BY: Mapping[str, frozenset[str]] = {
    "humanSensingStatus": frozenset({
        "4SidesWindDirection1", "4SidesWindDirection2",
        "4SidesWindDirection3", "4SidesWindDirection4",
    }),
}


CLASS_CARRIED_ENUM_FEATURES: Mapping[str, frozenset[str]] = {
    # ★ The presence feature is TWO halves and both belong here -- the vendor's own UI models it as a
    # setting plus a reading, and surfacing only the setting would report the mode while hiding what
    # the sensor sees:
    #   `humanSensingStatus` (w23.b6/2)  SETTING  0 off · 1 avoid · 2 follow · 3 on
    #   `sensingResult`      (w26.b4/2)  READING  0 no-such-function · 1 nobody · 2 one · 3 several
    # ⚠️ `sensingResult`'s 0 already means "no such function" and is dropped by its own state map, so
    # a cabinet without the sensor yields no entity whether or not this class carries it -- which is
    # what all seven observed cabinets do today. It costs nothing and lights up if one ever detects.
    "0d12": frozenset({"humanSensingStatus", "sensingResult"}),
}


def declared_enum_features(model, device_class: str | None = None) -> frozenset[str]:
    """The optional multi-state features a device declares AND the map can place -- same gate.

    ``device_class`` additionally admits the attributes its class is known to carry undeclared
    (:data:`CLASS_CARRIED_ENUM_FEATURES`). Omitted, behaviour is exactly as before.
    """
    carried = _PLACEABLE_ENUM & CLASS_CARRIED_ENUM_FEATURES.get((device_class or "").lower(), frozenset())
    declared = _attribute_names(model) if _known_feature_set(model) else frozenset()
    # Drop a carried attribute whose bits this product gives to something else (see
    # :data:`CARRIED_BLOCKED_BY`). Reading them anyway yields a wrong value, not an absent one.
    carried = frozenset(
        n for n in carried if not (CARRIED_BLOCKED_BY.get(n, frozenset()) & declared)
    )
    if not _known_feature_set(model):
        return carried
    return (_PLACEABLE_ENUM & declared) | carried


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


def read_enum_features(
    wire_model, declared, blob: bytes, device_class: str | None = None
) -> dict[str, str]:
    """Read the declared multi-state features out of ``blob`` as their labelled state.

    Same map-and-position basis as :func:`read_bool_features`; the raw value is looked up in the
    attribute's state map, and a value the map does not name is dropped rather than shown as a code.
    """
    names = declared_enum_features(declared, device_class)
    if not names:
        return {}
    # Where the hardware is inferred from the class rather than declared by the product, a zero
    # reading cannot be told from "not fitted" -- so it is dropped and the entity reads unknown,
    # the same call already made for `sensingResult`'s 无此功能 and for the absent-counter rule.
    inferred = _PLACEABLE_ENUM & CLASS_CARRIED_ENUM_FEATURES.get(
        (device_class or "").lower(), frozenset()
    )
    if _known_feature_set(declared):
        inferred -= _attribute_names(declared)
    out: dict[str, str] = {}
    for name, field in wire_model.model_fields(sorted(names), len(blob)).items():
        states = OPTIONAL_ENUM_FEATURES[name][1]
        value = field.read(blob)
        if not isinstance(value, int) or value not in states:
            continue
        if name in inferred and value == 0:
            continue
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
