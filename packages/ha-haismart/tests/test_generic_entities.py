"""Every generated entity, of every shipped device class, against Home Assistant's own rules.

There is no reporter for most of these appliances, so nobody will tell us that a sensor on a cooker
hood was rejected at write time. Home Assistant validates a device class against its unit AND
against its state class, and refuses the state when they disagree — so this walks all 165 bundled
maps and checks every spec the classifier produces against Home Assistant's own constants rather
than against a table copied out of them.

⚠️ Every field is treated as declared, which no real device does — so this is an UPPER BOUND on what
anyone sees, and deliberately so: it exercises combinations no single appliance would.
"""
from __future__ import annotations

import collections

import pytest
from haismart_hrdp.device_model import known_typeids, model_for
from haismart_hrdp.entity_spec import Control, EntitySpec, specs_for
from homeassistant.components.number import NumberDeviceClass
from homeassistant.components.number.const import DEVICE_CLASS_UNITS as NUMBER_UNITS
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.sensor.const import (
    DEVICE_CLASS_STATE_CLASSES,
)
from homeassistant.components.sensor.const import (
    DEVICE_CLASS_UNITS as SENSOR_UNITS,
)
from homeassistant.const import CONCENTRATION_MICROGRAMS_PER_CUBIC_METER

from custom_components.haismart.generic import (
    device_class_for,
    state_class_for,
    unit_for,
)

ALL_TYPEIDS = sorted(known_typeids())


def _all_specs():
    for typeid in ALL_TYPEIDS:
        model = model_for(typeid)
        assert model is not None
        specs = specs_for(
            model,
            [{"name": f.name} for f in model.fields],
            writable=[f.name for f in model.writable_fields()],
        )
        for spec in specs:
            yield typeid, model, spec


def test_no_sensor_pairs_a_device_class_with_a_unit_home_assistant_refuses() -> None:
    """`temperature` accepts °C, K and °F and nothing else; `pm25` only µg/m³, and so on.

    Checked against `DEVICE_CLASS_UNITS` itself, so a Home Assistant release that tightens a rule
    fails here rather than in somebody's log.
    """
    bad = [
        f"{model.device_class} {spec.attribute}: {dc.value} + {unit!r}"
        for _, model, spec in _all_specs()
        if (dc := device_class_for(spec)) is not None
        and (allowed := SENSOR_UNITS.get(dc)) is not None
        and (unit := unit_for(spec)) not in allowed
    ]
    assert not bad, bad[:10]


def test_units_are_home_assistants_own_spelling_not_a_literal() -> None:
    """A unit we publish must be what Home Assistant validates against, character for character.

    ⛔ This exists because Home Assistant CHANGED the micro sign between releases:

        2025.1.4  CONCENTRATION_MICROGRAMS_PER_CUBIC_METER = 'µg/m³'  U+00B5 MICRO SIGN
        2026.2.3  CONCENTRATION_MICROGRAMS_PER_CUBIC_METER = 'μg/m³'  U+03BC GREEK SMALL LETTER MU

    The two are indistinguishable on screen, so a hardcoded literal passes review, passes a local
    test run, and is rejected on the other release with nothing to see. The test above catches it
    only when the installed Home Assistant happens to be the newer one -- which no developer here
    had. This one catches it on either, by asserting the value came from Home Assistant rather than
    from us.
    """
    ug = CONCENTRATION_MICROGRAMS_PER_CUBIC_METER
    other_mu = ug.translate(str.maketrans({"\u00b5": "\u03bc", "\u03bc": "\u00b5"}))
    assert other_mu != ug, "both spellings must differ, or this test proves nothing"

    # Whichever spelling the byte map produced, what we publish is Home Assistant's own.
    for spelling in (ug, other_mu):
        spec = EntitySpec(
            attribute="x", control=Control.SENSOR, name="X", writable=False, unit=spelling
        )
        assert unit_for(spec) == ug, f"{spelling!r} was published as-is instead of HA's constant"

    # And it really is accepted by the table the other test checks.
    assert ug in SENSOR_UNITS[SensorDeviceClass.PM25]


def test_no_sensor_pairs_a_device_class_with_a_state_class_home_assistant_refuses() -> None:
    """The pairing that was wrong 203 times before this test existed.

    `volume` is a meter total and accepts only `total`/`total_increasing`; a tank's contents is
    `volume_storage`, which accepts only `measurement`. Derived independently they are each
    plausible and jointly invalid, and Home Assistant refuses the state at write time.
    """
    bad = [
        f"{model.device_class} {spec.attribute}: {dc.value} + {sc.value}"
        for _, model, spec in _all_specs()
        if (dc := device_class_for(spec)) is not None
        and (sc := state_class_for(spec)) is not None
        and (allowed := DEVICE_CLASS_STATE_CLASSES.get(dc)) is not None
        and sc not in allowed
    ]
    assert not bad, bad[:10]


def test_no_number_pairs_a_device_class_with_a_unit_home_assistant_refuses() -> None:
    """The number platform has its own table, and it is not the sensor one."""
    bad = []
    for _, model, spec in _all_specs():
        if spec.control is not Control.NUMBER:
            continue
        dc = device_class_for(spec)
        if dc is None:
            continue
        try:
            number_class = NumberDeviceClass(dc.value)
        except ValueError:
            bad.append(f"{model.device_class} {spec.attribute}: no NumberDeviceClass {dc.value}")
            continue
        allowed = NUMBER_UNITS.get(number_class)
        if allowed is not None and (unit := unit_for(spec)) not in allowed:
            bad.append(f"{model.device_class} {spec.attribute}: {dc.value} + {unit!r}")
    assert not bad, bad[:10]


def test_an_ambiguous_unit_is_never_given_a_device_class_by_the_unit_alone() -> None:
    """⛔ µg/m³ is PM2.5, PM10 *and* formaldehyde; ppm is CO₂, CO, methane, smoke and ions.

    Labelling by unit alone called a formaldehyde probe "PM2.5" and a carbon-monoxide probe "CO₂" —
    a wrong fact about a safety sensor, which is the worst kind to publish. Where the name does not
    settle it, the reading keeps its unit and gets no class.
    """
    by_attribute = {spec.attribute: spec for _, _, spec in _all_specs()}
    assert by_attribute["indoorPM2p5Value"].device_class == "pm25"
    assert by_attribute["ch2oValue"].device_class == "volatile_organic_compounds"
    assert by_attribute["co2Value"].device_class == "carbon_dioxide"
    assert by_attribute["coValue"].device_class == "carbon_monoxide"
    assert by_attribute["ch4Value"].device_class is None      # methane: ppm, no class for it
    # Litres are water used, hot water remaining, and gas burned. Only one of those is `water`.
    assert by_attribute["totalWaterUsed"].device_class == "water"
    assert by_attribute["totalUseGasL"].device_class == "volume"
    assert by_attribute["remainingHotWater"].device_class == "volume_storage"


def test_every_entity_has_a_unique_id_within_its_device() -> None:
    """Two entities sharing a unique id is a setup failure, not a cosmetic problem."""
    for typeid in ALL_TYPEIDS:
        model = model_for(typeid)
        specs = specs_for(
            model,
            [{"name": f.name} for f in model.fields],
            writable=[f.name for f in model.writable_fields()],
        )
        duplicates = [k for k, n in collections.Counter(s.key for s in specs).items() if n > 1]
        assert not duplicates, f"{model.device_class} {typeid}: {duplicates}"


@pytest.mark.parametrize("typeid", ALL_TYPEIDS)
def test_every_control_is_well_formed(typeid: str) -> None:
    """A control that cannot be used is worse than one that is missing.

    A select with one option, a number whose range is a single value or inverted, two options
    sharing a label — each renders as a control and then does nothing useful.
    """
    model = model_for(typeid)
    assert model is not None
    specs = specs_for(
        model,
        [{"name": f.name} for f in model.fields],
        writable=[f.name for f in model.writable_fields()],
    )
    for spec in specs:
        if spec.control is Control.SELECT:
            labels = [label for _, label in spec.options]
            assert len(labels) > 1, f"{spec.attribute}: a select with {len(labels)} options"
            assert len(set(labels)) == len(labels), f"{spec.attribute}: duplicate labels"
        if spec.control is Control.NUMBER:
            assert spec.minimum is not None and spec.maximum is not None, spec.attribute
            assert spec.minimum < spec.maximum, f"{spec.attribute}: {spec.minimum}..{spec.maximum}"
            assert spec.step, f"{spec.attribute}: step {spec.step!r}"
        if spec.sources:
            assert len(spec.sources) == len(spec.source_labels), spec.attribute


@pytest.mark.parametrize("typeid", ALL_TYPEIDS)
def test_every_writable_spec_can_actually_be_encoded(typeid: str) -> None:
    """A control the encoder would refuse is a control that fails the first time it is used.

    Every switch, select and number offered is written through `encode_write`, so every value it
    offers must survive that. Checked at both ends of a number's range and for every option of a
    select — which is the whole of what the user can ask for.
    """
    model = model_for(typeid)
    assert model is not None
    specs = specs_for(
        model,
        [{"name": f.name} for f in model.fields],
        writable=[f.name for f in model.writable_fields()],
    )
    for spec in specs:
        if spec.control is Control.SWITCH:
            for value in (True, False):
                model.encode_write(spec.attribute, value)
        elif spec.control is Control.SELECT:
            for value, _ in spec.options:
                model.encode_write(spec.attribute, value)
        elif spec.control is Control.NUMBER:
            for value in (spec.minimum, spec.maximum):
                model.encode_write(spec.attribute, value)
