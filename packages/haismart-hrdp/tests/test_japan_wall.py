"""The Japanese wall units (`日本挂2024` / `日本挂2025`): a family with a frame of its own.

Issue #19's `JAA-MX225AK` sent a 111-byte report no hand-built family describes. Read through the
classic family's fallback it showed a 58 C setpoint and a unit that was off while it was running,
and control was refused. The manufacturer's map for its identifier states both the report and the
write frame, and they agree with each other position for position; these tests hold the family to
that map, and its decode to the manufacturer's own cloud record of the same unit.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from haismart_hrdp.device_model import model_for
from haismart_hrdp.features import (
    OPTIONAL_BOOL_FEATURES,
    OPTIONAL_ENUM_FEATURES,
    OPTIONAL_NUMERIC_READINGS,
)
from haismart_hrdp.uss import build_epp_frame, parse_full_status
from haismart_hrdp.wire_models import (
    _JAPAN_WALL_FAN,
    _JAPAN_WALL_MODE,
    _JAPAN_WALL_VANE_H,
    _JAPAN_WALL_VANE_V,
    JAPAN_WALL,
    JAPAN_WALL_TYPEIDS,
    VANE_V_MODEL_TO_EPP,
    select_wire_model,
    vane_model_code,
)

JP_2024 = "2008610800820324021200118018500000000000000000000000000000000040"

#: Issue #19's status report, as its diagnostics download kept it. Climate block: words 1-4 =
#: `2a08 2104 0000 0200`; sensors at words 8-9 = `283c 4e00`.
REPORT = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000000000000000000000000000000000000001fffff1c000000000000066d012a08"
    "210400000200000000000000283c4e009b"
)
assert len(REPORT) == 111

#: The manufacturer's cloud record of the same unit, fetched while that report was current
#: (`reported_values_now` in the same download). Never used to build the map.
CLOUD = {
    "onOffStatus": "true", "targetTemperature": "21.0", "indoorTemperature": "20.0",
    "outdoorTemperature": "14", "indoorHumidity": "60", "operationMode": "1", "windSpeed": "5",
    "windDirectionVertical": "6", "windDirectionHorizontal": "0", "healthMode": "false",
    "silentSleepStatus": "false", "rapidMode": "false", "muteStatus": "false",
    "screenDisplayStatus": "true", "windAvoidance": "false", "electricHeatingStatus": "false",
    "energySavingStatus": "false", "lightStatus": "false", "humanSensingStatus": "0",
    "uvSterilizationSwitch": "false", "mouldProof": "true", "preventHeatstroke": "false",
    "preventSupercooling": "false", "freshAirStatus": "false", "echoStatus": "false",
    "drying": "false", "constDehumidificationStatus": "false", "localFilterChangeFlag": "false",
}

#: Our key -> the published attribute it reads.
ATTRIBUTE = {
    "power": "onOffStatus", "target_temperature": "targetTemperature",
    "current_temperature": "indoorTemperature", "outdoor_temperature": "outdoorTemperature",
    "operation_mode": "operationMode", "wind_speed": "windSpeed",
    "swing_vertical": "windDirectionVertical", "swing_horizontal": "windDirectionHorizontal",
    "health": "healthMode", "sleep": "silentSleepStatus", "strong": "rapidMode",
    "quiet": "muteStatus", "lamp": "screenDisplayStatus", "last_changed_by": "opSrc",
}

_GRSETDAC = json.loads(
    (Path(__file__).parent / "fixtures" / "japan_wall_grsetdac.json").read_text(encoding="utf-8")
)


def _as_published(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer() and value < 0:
        return str(int(value))
    return str(value)


def test_the_report_decodes_to_the_manufacturers_cloud_record() -> None:
    state = parse_full_status(REPORT, uplus_id=JP_2024)
    assert state["layout"] == "japan_wall" and state["writable"] is True
    assert "partial" not in state

    assert state["power"] is True
    assert state["target_temperature"] == float(CLOUD["targetTemperature"])
    assert state["current_temperature"] == float(CLOUD["indoorTemperature"])
    assert state["outdoor_temperature"] == float(CLOUD["outdoorTemperature"])
    assert state["operation_mode"] == CLOUD["operationMode"]
    assert state["wind_speed"] == CLOUD["windSpeed"]
    for key in ("health", "sleep", "strong", "quiet", "lamp"):
        assert _as_published(state[key]) == CLOUD[ATTRIBUTE[key]], key
    # Parked at stop 6 (position four) and at the fixed left-right stop: neither is sweeping, and the
    # positions are the ones the cloud names.
    assert state["swing_vertical"] is False and state["swing_horizontal"] is False
    assert vane_model_code(JAPAN_WALL, REPORT, "swing_vertical") == int(
        CLOUD["windDirectionVertical"]
    )
    assert vane_model_code(JAPAN_WALL, REPORT, "swing_horizontal") == int(
        CLOUD["windDirectionHorizontal"]
    )


def test_every_own_field_agrees_with_the_cloud_record() -> None:
    placed = JAPAN_WALL.model_fields(sorted(JAPAN_WALL.own_fields), len(REPORT))
    assert set(placed) == set(JAPAN_WALL.own_fields)
    for name, field in placed.items():
        assert _as_published(field.read(REPORT)) == CLOUD[name], name


def test_the_classic_fallback_is_what_produced_the_reported_symptoms() -> None:
    """The reporter's 58 C and 'off': the same bytes read with no identifier, i.e. as before."""
    state = parse_full_status(REPORT)
    assert state.get("layout") == "unknown" and state.get("partial") is True
    assert state["target_temperature"] == 58.0
    assert state["power"] is False


@pytest.mark.parametrize("typeid", sorted(JAPAN_WALL_TYPEIDS))
def test_japan_wall_matches_the_published_map(typeid: str) -> None:
    model = model_for(typeid)
    assert model is not None

    def position(name: str) -> tuple[int, int, int]:
        field = model.field(name)
        assert field is not None, name
        return field.word, field.bit, field.length

    for key, wf in JAPAN_WALL.fields.items():
        assert (wf.word, wf.bit, wf.length) == position(ATTRIBUTE[key]), key
        variants = model.field(ATTRIBUTE[key]).variants
        if isinstance(variants, dict):          # a scaled number: the scale is the map's too
            assert (wf.k, wf.c) == (variants["k"], variants["c"]), key

    for name, wf in JAPAN_WALL.own_fields.items():
        assert (wf.word, wf.bit, wf.length) == position(name), name

    # ...and nothing the optional readers know is left out. An omission here is a declared probe or
    # feature that silently never appears.
    known = set(OPTIONAL_BOOL_FEATURES) | set(OPTIONAL_NUMERIC_READINGS) | set(OPTIONAL_ENUM_FEATURES)
    published = {f.name for f in model.fields_for()}
    assert (published & known) - set(JAPAN_WALL.own_fields) - set(ATTRIBUTE.values()) == set()

    for name, wf in JAPAN_WALL.write_fields.items():
        assert (wf.word, wf.bit, wf.length) == position(name), name


@pytest.mark.parametrize("typeid", sorted(JAPAN_WALL_TYPEIDS))
def test_the_write_frame_is_the_published_one(typeid: str) -> None:
    published = _GRSETDAC[typeid]["grSetDAC"]
    assert bytes.fromhex(published["eppCmd"]) == JAPAN_WALL.group_cmd
    variants = {v["name"]: (v["startWord"], v["startBit"], v["length"]) for v in published["variants"]}
    # The frame is the published span, and it starts at the report's own word 1.
    assert JAPAN_WALL.word_count == max(word for word, _bit, _len in variants.values())
    assert JAPAN_WALL.write_base_word == 1
    for name, wf in JAPAN_WALL.write_fields.items():
        assert variants[name] == (wf.word, wf.bit, wf.length), name

    # The report and the write frame state the same place for every settable attribute, which is
    # what lets the group set be seeded from the report and read back where it was written.
    model = model_for(typeid)
    assert model is not None
    for name, at in variants.items():
        field = model.field(name)
        assert field is not None and (field.word, field.bit, field.length) == at, name


@pytest.mark.parametrize("typeid", sorted(JAPAN_WALL_TYPEIDS))
def test_the_code_tables_are_the_published_ones(typeid: str) -> None:
    model = model_for(typeid)
    assert model is not None

    def std_to_epp(name: str) -> dict[int, int]:
        return {int(v["stdValue"]): int(v["eppValue"]) for v in model.field(name).variants}

    assert dict(_JAPAN_WALL_MODE) == std_to_epp("operationMode")
    assert dict(_JAPAN_WALL_FAN) == std_to_epp("windSpeed")
    assert {s: w for w, s in _JAPAN_WALL_VANE_V.items()} == std_to_epp("windDirectionVertical")
    assert {s: w for w, s in _JAPAN_WALL_VANE_H.items()} == std_to_epp("windDirectionHorizontal")


def test_japan_wall_up_down_stops_agree_with_the_shared_table() -> None:
    """The vane select translates a published stop through the SHARED table. On this family that is
    only safe because every stop the two tables both name lands on the same wire code; the family's
    own extras are its two half-range sweeps, which the shared table cannot express and so are never
    offered. A regenerated map that moved one of them fails here rather than misplacing the vane."""
    family = {s: w for w, s in _JAPAN_WALL_VANE_V.items()}
    common = set(family) & set(VANE_V_MODEL_TO_EPP)
    assert common and all(family[s] == VANE_V_MODEL_TO_EPP[s] for s in common)
    assert set(family) - set(VANE_V_MODEL_TO_EPP) == {12, 13}


def test_the_left_right_axis_is_written_only_at_its_ends() -> None:
    """Its stops are not the shared identity (wire 1 is published stop 3), so the stops are not
    offered and a write can only mean fixed or sweeping."""
    assert "windDirectionHorizontal" not in JAPAN_WALL.position_fields
    words = JAPAN_WALL.baseline_words(REPORT)
    on = JAPAN_WALL.encode_control(words, {"windDirectionHorizontal": 7})
    off = JAPAN_WALL.encode_control(on, {"windDirectionHorizontal": 0})
    assert (int.from_bytes(on[0:2], "big") >> 5) & 0x7 == 7
    assert off == bytes(words)
    assert vane_model_code(JAPAN_WALL, REPORT[:92] + on + REPORT[100:], "swing_horizontal") == 7


#: (attribute, value in the caller's representation, the state key it reads back as, expected).
WRITES = [
    ("onOffStatus", 0, "power", False),
    ("targetTemperature", 6, "target_temperature", 22.0),     # 22 C as the caller hands it, °C - 16
    ("targetTemperature", 14, "target_temperature", 30.0),
    ("operationMode", 4, "operation_mode", "4"),
    ("operationMode", 6, "operation_mode", "6"),
    ("windSpeed", 1, "wind_speed", "1"),
    ("windSpeed", 8, "wind_speed", "8"),
    ("windDirectionVertical", 0x0C, "swing_vertical", True),
    ("windDirectionHorizontal", 7, "swing_horizontal", True),
    ("healthMode", 1, "health", True),
    ("silentSleepStatus", 1, "sleep", True),
    ("rapidMode", 1, "strong", True),
    ("muteStatus", 1, "quiet", True),
    ("screenDisplayStatus", 0, "lamp", False),
]


@pytest.mark.parametrize(("name", "value", "key", "expected"), WRITES)
def test_a_write_reads_back_where_it_was_written_and_moves_nothing_else(
    name: str, value: int, key: str, expected
) -> None:
    words = JAPAN_WALL.baseline_words(REPORT)
    written = JAPAN_WALL.encode_control(words, {name: value})
    after = REPORT[:92] + written + REPORT[92 + len(written):]
    assert parse_full_status(after, uplus_id=JP_2024)[key] == expected

    wf = JAPAN_WALL.write_fields[name]
    mask = ((1 << wf.length) - 1) << wf.bit
    for word in range(JAPAN_WALL.word_count):
        before_w = int.from_bytes(words[2 * word:2 * word + 2], "big")
        after_w = int.from_bytes(written[2 * word:2 * word + 2], "big")
        allowed = mask if word == wf.word - 1 else 0
        assert (before_w ^ after_w) & ~allowed == 0, f"{name} disturbed word {word + 1}"


def test_the_group_set_is_four_words_under_6001() -> None:
    words = JAPAN_WALL.baseline_words(REPORT)
    assert bytes(words) == bytes.fromhex("2a08210400000200")
    frame = build_epp_frame(0x01, JAPAN_WALL.group_cmd, JAPAN_WALL.encode_control(words, {}))
    assert frame == bytes.fromhex("ffff120000000000000160012a08210400000200cd")


@pytest.mark.parametrize(
    ("name", "value"),
    [("targetTemperature", 15), ("targetTemperature", -1), ("windSpeed", 0), ("operationMode", 3)],
)
def test_the_encoder_refuses_what_the_family_cannot_express(name: str, value: int) -> None:
    with pytest.raises(ValueError):
        JAPAN_WALL.encode_control(JAPAN_WALL.baseline_words(REPORT), {name: value})


def test_the_family_is_keyed_on_its_identifiers_and_never_on_the_length() -> None:
    assert select_wire_model(111, JP_2024) is JAPAN_WALL
    assert select_wire_model(111, None) is None
    assert select_wire_model(111, "2008610800820324021200118012560000000000000000000000000000000040") is None
    # Without the identifier the report stays an unrecognised layout, exactly as before.
    assert parse_full_status(REPORT).get("layout") == "unknown"
