"""What kind of appliance a device is — and, as much, what happens when we do not know.

The failure this guards against is not an exotic one: it is the integration's default behaviour
until now, which was to treat every device as an air conditioner because every device had been one.
"""
from __future__ import annotations

import pytest

from haismart_hrdp.appliance import CLASS_KINDS, ApplianceKind, class_of, kind_for
from haismart_hrdp.device_model import device_classes, known_typeids, model_for

WATER_HEATER = "201c120000118674200100418007574800000000000000000000000000000040"   # issue #13
CLASSIC_AC = "2008610800820324021200118006915900000000000000000000000000000040"
CABINET_AC = "201c10c7088081000d1205464544850000009cd68e692c104e2a333eab95d140"     # issue #12


def test_the_issue_13_water_heater_is_not_an_air_conditioner() -> None:
    """The whole of the report: `2001` is 热泵热水器, whatever the cloud calls it."""
    assert kind_for(WATER_HEATER) is ApplianceKind.WATER_HEATER
    assert class_of(WATER_HEATER) == "2001"


def test_the_cloud_category_cannot_override_the_typeid() -> None:
    """Issue #13's device is filed by Haier under `A048 Pump`, and the typeid still decides.

    The label is marketing-facing and ambiguous — a pump is also a circulation pump or a pool pump —
    so it is consulted only where the class field says nothing.
    """
    assert kind_for(WATER_HEATER, "Pump") is ApplianceKind.WATER_HEATER
    assert kind_for(CLASSIC_AC, "Refrigerator") is ApplianceKind.AIR_CONDITIONER
    # ...and on its own, "Pump" is NOT enough to conclude water heater.
    assert kind_for(None, "Pump") is ApplianceKind.OTHER


def test_the_shipped_air_conditioners_stay_air_conditioners() -> None:
    """No existing install may change kind. These are the families the integration ships today."""
    assert kind_for(CLASSIC_AC) is ApplianceKind.AIR_CONDITIONER
    assert kind_for(CABINET_AC) is ApplianceKind.AIR_CONDITIONER


@pytest.mark.parametrize(
    ("app_type", "expected"),
    [
        ("Wall Mounted", ApplianceKind.AIR_CONDITIONER),
        ("Floor Standing", ApplianceKind.AIR_CONDITIONER),
        ("Central Ac", ApplianceKind.AIR_CONDITIONER),
        ("Window AC", ApplianceKind.AIR_CONDITIONER),
        ("  central ac  ", ApplianceKind.AIR_CONDITIONER),
        ("Electric Water Heater", ApplianceKind.WATER_HEATER),
        ("Refrigerator", ApplianceKind.OTHER),
        ("Robot Vacuum", ApplianceKind.OTHER),
        ("", ApplianceKind.OTHER),
    ],
)
def test_the_cloud_category_is_the_fallback_when_the_class_is_unknown(
    app_type: str, expected: ApplianceKind
) -> None:
    assert kind_for(None, app_type) is expected


@pytest.mark.parametrize(
    "uplus_id",
    [None, "", "short", "0" * 64, "201c1200000000000000" + "0" * 44],
)
def test_an_absent_or_empty_typeid_resolves_to_other_rather_than_to_a_guess(uplus_id) -> None:
    """An all-zero uPlusId is how a unit says "not reported" — it is not a device class."""
    assert class_of(uplus_id) is None
    assert kind_for(uplus_id) is ApplianceKind.OTHER


def test_an_unmapped_class_is_other_and_never_silently_an_air_conditioner() -> None:
    """Refrigerators, washers, hoods and hobs are each a real kind we have not built.

    Answering OTHER is what lets the caller decline to build a thermostat for a fridge. Answering
    AIR_CONDITIONER would reproduce issue #13 for every one of them.
    """
    for device_class in ("0121", "0501", "0901", "1d01", "3e01", "2101"):
        assert kind_for(f"{'0' * 16}{device_class}{'0' * 44}") is ApplianceKind.OTHER


def test_every_mapped_class_is_one_the_byte_map_bundle_can_actually_decode() -> None:
    """A kind we claim to support but cannot decode is a promise the integration cannot keep."""
    carried = device_classes()
    missing = sorted(set(CLASS_KINDS) - carried)
    assert not missing, f"mapped to a kind but absent from the byte-map bundle: {missing}"


def test_every_mapped_class_has_a_typeid_whose_map_names_the_appliance() -> None:
    """The evidence for each row is Haier's own name for that class. Assert it is really there.

    A comment claiming `2001` is 热泵热水器 is worth nothing if a bundle regeneration changes what
    `2001` contains; this reads the name back out of the shipped bundle.
    """
    seen: dict[str, str] = {}
    for typeid in known_typeids():
        model = model_for(typeid)
        assert model is not None
        if model.device_class in CLASS_KINDS and model.name:
            seen.setdefault(model.device_class, model.name)
    assert set(seen) == set(CLASS_KINDS), f"no named map for {sorted(set(CLASS_KINDS) - set(seen))}"
    assert "热泵热水器" in seen["2001"] or "热泵" in seen["2001"]
    assert "空调" in seen["0211"]
