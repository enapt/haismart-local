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

# attribute name (as the device declares it) -> our stable key / translation slug.
OPTIONAL_BOOL_FEATURES: Mapping[str, str] = {
    "electricHeatingStatus": "electric_heating",
    "freshAirStatus": "fresh_air",
    "10degreeHeatingStatus": "keep_warm_10c",
    "lightStatus": "ambient_light",
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


def _attribute_names(model) -> set[str]:
    """The attribute names a device declares, from any shape the model turns up in: a digital model
    ``{"attributes": [...]}``, that ``attributes`` list itself (dicts or a name->spec map), or a bare
    collection of names."""
    if not model:
        return set()
    if isinstance(model, Mapping) and "attributes" in model:
        model = model["attributes"]
    if isinstance(model, Mapping):
        return {str(n) for n in model}
    names: set[str] = set()
    for a in model:
        name = a.get("name") if isinstance(a, Mapping) else a
        if name:
            names.add(str(name))
    return names


def declared_bool_features(model) -> frozenset[str]:
    """The optional boolean features a device declares, from its digital model."""
    return frozenset(OPTIONAL_BOOL_FEATURES) & _attribute_names(model)


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
