"""Can ONE decoder serve everything? — the shim that lets the question be answered, not argued.

`ac_view.ac_state` produces the same dictionary `parse_full_status` does, from Haier's published
byte map alone. Nothing decodes with it yet: it exists so the two can be compared field for field,
and so the part that is genuinely air-conditioner-specific — presentation, not decoding — is written
down on its own instead of being tangled through a per-family position table.

The wide comparison lives in the development tree (`tools/re/decoder_equivalence.py --shim`, which
has the captures): **38 air-conditioner captures, 633 fields identical, none different, and 8 the
byte map places that the hand map does not.** What is asserted here is the same property on the
frames this package can carry, plus the specific mistakes that comparison caught.
"""
from __future__ import annotations

import random

import pytest

from haismart_hrdp import parse_full_status, profile_for
from haismart_hrdp.ac_view import AC_WIRE_FIELDS, ac_state
from haismart_hrdp.device_model import ATTR_BASE, model_for

# The owner's own family, and the other whose shipped layout is fixed. (The `0d12` cabinet derives
# its layout from the data, so randomised frames make it choose differently — see test_device_model.)
FAMILIES = [
    ("2008610800820324021200118012560000000000000000000000000000000040", 127, "classic"),
    ("2008610800820324021200118006915900000000000000000000000000000040", 165, "extended-36"),
]
COMPARABLE = [*AC_WIRE_FIELDS, "swing_vertical", "swing_horizontal", "last_changed_by",
              "mode", "fan_mode"]


def _named(model, attribute: str) -> set[str]:
    """The STD codes this class's own map names for ``attribute``."""
    field = model.field(attribute)
    if field is None or not isinstance(field.variants, list):
        return set()
    return {str(e.get("stdValue")) for e in field.variants} | {
        str(e.get("eppValue")) for e in field.variants
    }


def _same(a, b) -> bool:
    if str(a).lower() == str(b).lower():
        return True
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return False


@pytest.mark.parametrize(("typeid", "length", "family"), FAMILIES)
def test_the_shim_reproduces_the_shipped_decoder_on_random_frames(
    typeid: str, length: int, family: str
) -> None:
    """Key for key, on frames nobody has seen — which is the case that decides whether a flip is safe.

    ⛔ A field the shim reads and the hand-derived map does not is NOT a failure: the byte map is
    more complete, and eight such fields exist in the stored captures. What must never happen is a
    field the shipped decoder produces going missing, or the two reading it to different values.
    """
    model = model_for(typeid)
    assert model is not None
    profile = profile_for("AAC1UKZ01")
    indoor = model.field("indoorTemperature")
    assert indoor is not None
    indoor_byte = ATTR_BASE + 2 * (indoor.word - 1)

    random.seed(11)
    different: list[str] = []
    lost: list[str] = []
    compared = 0
    for _ in range(120):
        data = bytearray(length)
        data[2:4] = b"\x27\x15"
        for index in range(92, length):
            data[index] = random.randrange(256)
        data[92] = random.randrange(0, 15)
        data[indoor_byte] = random.randrange(20, 80)
        # ⛔ Put a code the manufacturer's own table NAMES into each enum field. Pure noise almost
        # never does, and the two decoders differ on an unnamed code ON PURPOSE — asserted
        # separately below. Real hardware emits values its own model names, which is why all 38
        # stored captures agree; this makes the random frames realistic in the same way.
        for attribute in ("operationMode", "windSpeed", "windDirectionVertical"):
            field = model.field(attribute)
            if field is None or not isinstance(field.variants, list) or not field.variants:
                continue
            code = random.choice([e["eppValue"] for e in field.variants])
            offset = ATTR_BASE + 2 * (field.word - 1) + (0 if field.bit >= 8 else 1)
            if offset < len(data):
                shift = field.bit % 8
                mask = ((1 << field.length) - 1) << shift
                data[offset] = (data[offset] & ~mask & 0xFF) | ((code << shift) & mask)
        shipped = parse_full_status(bytes(data), profile, None, uplus_id=typeid)
        if not shipped or shipped.get("partial"):
            continue
        shim = ac_state(model, bytes(data), profile)
        for key in COMPARABLE:
            # A key the shipped decoder carries as `None` and the shim omits is the same statement.
            if key in shipped and shipped[key] is None:
                if shim.get(key) is not None:
                    different.append(f"{key}: shipped None vs {shim[key]!r}")
                continue
            if key in shipped and key not in shim:
                lost.append(f"{key}={shipped[key]!r}")
            elif key in shipped and key in shim:
                compared += 1
                if not _same(shipped[key], shim[key]):
                    different.append(f"{key}: {shipped[key]!r} vs {shim[key]!r}")
    assert compared > 150, f"{family}: only {compared} comparisons"
    assert not lost, f"{family}: the shim lost {lost[:5]}"
    assert not different, f"{family}: {different[:5]}"


def test_a_vane_is_read_RAW_because_the_sweep_test_is_written_against_the_epp_code() -> None:
    """⛔ The mistake the comparison caught, and it was silent.

    `DeviceModel.decode` applies the map's `variants`, which translates a vane's EPP code into the
    STD code the model publishes — and `vane_v_sweeping` is written against the EPP code
    (`wire_models.VANE_V_MODEL_TO_EPP` exists precisely because they differ). Handing it the
    translated value reported "not sweeping" for three captures that were sweeping.
    """
    from haismart_hrdp.wire_models import VANE_V_EPP_TO_MODEL, vane_v_sweeping

    epp_sweeping = next(e for e in VANE_V_EPP_TO_MODEL if vane_v_sweeping(e))
    std = VANE_V_EPP_TO_MODEL[epp_sweeping]
    assert std != epp_sweeping, "the premise: the two codes differ for a sweeping vane"
    assert not vane_v_sweeping(std), "...and the translated one reads as NOT sweeping"

    typeid, length, _ = FAMILIES[0]
    model = model_for(typeid)
    assert model is not None
    field = model.field("windDirectionVertical")
    assert field is not None
    data = bytearray(length)
    data[2:4] = b"\x27\x15"
    offset = ATTR_BASE + 2 * (field.word - 1) + (0 if field.bit >= 8 else 1)
    data[offset] = epp_sweeping << (field.bit % 8)
    data[ATTR_BASE + 2 * (model.field("indoorTemperature").word - 1)] = 50
    assert ac_state(model, bytes(data), profile_for("AAC1UKZ01")).get("swing_vertical") is True


def test_the_shim_applies_the_absent_probe_rule() -> None:
    """A map alone would publish a unit's missing outdoor probe as a confident −64 °C.

    That rule is `uss._sensor_temp`'s and it is part of what the air-conditioner layer knows, so the
    shim has to carry it or a flip would regress every unit without an outdoor sensor.
    """
    typeid, length, _ = FAMILIES[0]
    model = model_for(typeid)
    assert model is not None
    data = bytearray(length)
    data[2:4] = b"\x27\x15"
    data[ATTR_BASE + 2 * (model.field("indoorTemperature").word - 1)] = 50   # 25 °C
    state = ac_state(model, bytes(data), profile_for("AAC1UKZ01"))
    assert state["current_temperature"] == 25.0
    assert "outdoor_temperature" not in state, "raw 0 is a probe the unit does not have"


def test_an_unnamed_enum_code_is_dropped_rather_than_passed_through() -> None:
    """⚠️ A real difference between the two decoders, and the byte map's answer is the safer one.

    The hand-derived decoder passes a raw `operationMode` code straight out, whatever it is; the
    byte map consults the manufacturer's own variants table and drops a code that table does not
    name. On random bytes that happens constantly — which is why the randomised comparison above
    skips those frames — and on real hardware it does not: a unit emits values its own model names,
    and across all 38 stored air-conditioner captures the two never differed.

    Recorded rather than reconciled, because it is a decision a flip would have to make
    deliberately: showing `mode: 7` for a code nothing defines, or showing nothing.
    """
    typeid, length, _ = FAMILIES[0]
    model = model_for(typeid)
    assert model is not None
    field = model.field("operationMode")
    assert field is not None
    named = {e["eppValue"] for e in field.variants}
    unnamed = next(v for v in range(2 ** field.length) if v not in named)

    data = bytearray(length)
    data[2:4] = b"\x27\x15"
    data[ATTR_BASE + 2 * (model.field("indoorTemperature").word - 1)] = 50
    offset = ATTR_BASE + 2 * (field.word - 1) + (0 if field.bit >= 8 else 1)
    data[offset] = unnamed << (field.bit % 8)

    shipped = parse_full_status(bytes(data), profile_for("AAC1UKZ01"), None, uplus_id=typeid)
    shim = ac_state(model, bytes(data), profile_for("AAC1UKZ01"))
    assert shipped.get("operation_mode") == str(unnamed), "the hand decoder passes it through"
    assert "operation_mode" not in shim, "the byte map drops a code its own table does not name"


def test_the_shim_is_not_wired_into_the_decode_path_yet() -> None:
    """Stated as a test because it is the current design decision, not an oversight.

    The shim exists so the comparison can be made. Flipping the primary decoder touches 1,451
    working products and the capture corpus covers four families of twenty-six, so it is a decision
    with evidence behind it rather than a tidy-up — see `docs/MULTI_DEVICE_PLAN` §11.
    """
    import inspect

    from haismart_hrdp import uss

    assert "ac_view" not in inspect.getsource(uss), "uss.py must not depend on the shim yet"
