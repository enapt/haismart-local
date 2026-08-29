"""The 133-byte central cabinet: a report carrying words the published map does not describe.

Issue #12's appliance is a ``0d12`` ceiling cabinet. Its setpoint, mode, fan and power all read
correctly at the classic -19 offset, and its room temperature does not: four words the published map
knows nothing about sit between the settable block and the sensors, so ``indoorTemperature`` landed
inside them and read zero. The layout was rejected on that one field, no wire model claimed the
report, and control fell through to a group-set path this appliance's firmware refuses outright.

The three reports below are the ones attached to that issue, in states their owner set from the
unit's own wall panel and wrote down: off; cooling to 22 with the fan low; fan-only with the fan
high. They are the evidence for everything asserted here.
"""
from __future__ import annotations

from haismart_hrdp import decode_related, parse_full_status
from haismart_hrdp.wire_models import (
    RELATED_INSERT_PIVOT,
    insert_corroborated_by_actype,
    related_family_name,
    related_insert_models,
    related_model_named,
    related_wire_models,
)

#: Issue #12's appliance. The first twenty characters name the device class (``0d12``, the central
#: cabinets); the identifier as a whole is shared by 162 published products.
CABINET_UPLUS_ID = "201c10c7088081000d1205464544850000009cd68e692c104e2a333eab95d140"

#: What that appliance's own model declares: nine attributes, and an ``operationMode`` listing
#: smart, cool, dry and fan-only. **No heat code**, so it is a cooling-only unit -- which is the fact
#: the corroboration gate below tests the wire against.
CABINET_MODES = frozenset({0, 1, 2, 6})
CABINET_MODEL = {
    "attributes": [
        {"name": "operationMode", "valueRange": {"type": "LIST", "dataList": [
            {"data": str(c)} for c in sorted(CABINET_MODES)]}},
    ]
}

STATUS_133_OFF = bytes.fromhex(
    "00002715000000004e560100000302000004010000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000035ffff32000000000000066d0109022200020014070000000000000003"
    "020332325f800003000000000000000000000000000000003e"
)

STATUS_133_COOL22 = bytes.fromhex(
    "00002715000000004e560100000302000004010000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000035ffff32000000000000066d0106002300020114000000000000000003"
    "020332325f8000030000000000000000000000000000000034"
)

STATUS_133_FAN_ONLY = bytes.fromhex(
    "00002715000000004e560100000302000004010000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000035ffff32000000000000066d010600c100020114000000000000000003"
    "020332325f80000f00000000000000000000000000000000de"
)

#: What the owner set each unit to, from its wall panel. The room read 25 C on the panel throughout.
STATES = (
    (STATUS_133_OFF, False, 25.0, "1", "2"),
    (STATUS_133_COOL22, True, 22.0, "1", "3"),
    (STATUS_133_FAN_ONLY, True, 22.0, "6", "1"),
)


def _decode(report: bytes) -> dict | None:
    return decode_related(report, CABINET_UPLUS_ID, None, declared_modes=CABINET_MODES)


def test_the_report_resolves_to_the_map_with_four_words_inserted() -> None:
    """The layout is the published map at -19 with four words inserted at the usual pivot.

    Confirmed to FAIL before the insert fallback existed: every candidate was a flat offset, and no
    flat offset places this report's room temperature.
    """
    for report, *_ in STATES:
        decoded = _decode(report)
        assert decoded is not None, "no layout claimed the report"
        assert decoded["layout"] == related_family_name(-19, (RELATED_INSERT_PIVOT, 4))


def test_every_labelled_state_reads_back_as_its_owner_set_it() -> None:
    """Power, setpoint, mode and fan against the states written down, and the room against the panel."""
    for report, power, setpoint, mode, fan in STATES:
        decoded = _decode(report)
        assert decoded is not None
        assert decoded["power"] is power
        assert decoded["target_temperature"] == setpoint
        assert decoded["operation_mode"] == mode
        assert decoded["wind_speed"] == fan
        # The panel read 25 C during all three captures, and the outdoor probe 31 C.
        assert decoded["current_temperature"] == 25.0
        assert decoded["outdoor_temperature"] == 31.0
        # A healthy unit, and one that is cooling-only -- both of which the layout has to reproduce.
        assert decoded["error_code"] == 0
        assert decoded["heat_capable"] is False


def test_the_left_right_vane_is_read_back_at_all() -> None:
    """The horizontal axis was missing from the related layout's fields entirely.

    This appliance declares both axes and moves both. Its off capture was taken with the left-right
    vane on auto and the other two with it parked, so the axis is not merely present but SEEN to
    change -- which is what a swing control is read back from. Confirmed to FAIL before
    ``swing_horizontal`` was added to the related layout's keys: the key was absent from every
    decode, so the axis looked dead on every appliance resolved this way.
    """
    swings = [_decode(report)["swing_horizontal"] for report, *_ in STATES]
    assert swings == [True, False, False]


def test_plausibility_alone_does_not_settle_the_insert_count() -> None:
    """⚠️ THE REASON THIS NEEDS A GATE AT ALL, pinned so nobody removes it as belt-and-braces.

    The rule that settles a flat displacement -- try every candidate, keep it only if exactly one
    places the core block plausibly -- does NOT settle a count. A wrong count does not read off the
    end of the report; it lands the sensors on other real fields, which are perfectly plausible
    numbers. Three counts place this report, and two of them are wrong.
    """
    placed = [
        model.family
        for model in related_insert_models(len(STATUS_133_COOL22), CABINET_UPLUS_ID)
        if (decoded := model.decode(STATUS_133_COOL22, None)) is not None
        and decoded.get("current_temperature") is not None
    ]
    assert len(placed) > 1, "if only one count ever placed, the gate below would be unnecessary"


def test_the_declared_modes_are_what_separate_them() -> None:
    """The gate is two independent published facts agreeing, not a band on what looks sensible.

    ``acType`` is a bit the appliance sets one word past the room temperature; the device's model
    lists the modes it supports. A cooling-only unit must read cooling-only. Only the true count
    manages it -- the other two land ``acType`` on some other field and claim a heat pump.
    """
    accepted = [
        model.family
        for model in related_insert_models(len(STATUS_133_COOL22), CABINET_UPLUS_ID)
        if (decoded := model.decode(STATUS_133_COOL22, None)) is not None
        and decoded.get("current_temperature") is not None
        and insert_corroborated_by_actype(decoded, CABINET_MODES)
    ]
    assert accepted == [related_family_name(-19, (RELATED_INSERT_PIVOT, 4))]


def test_the_gate_is_keyed_on_the_declaration_and_not_on_the_answer() -> None:
    """Falsification, both ways.

    Told the same report belongs to a unit that declares a heat mode, the gate must reject the
    layout that is actually right and accept the two that are wrong -- because it is testing the
    declaration, not remembering the answer. Two survivors then fail the "exactly one" rule, so the
    appliance keeps the partial decode rather than being given a layout on a coin toss.
    """
    heat_pump = CABINET_MODES | {4}
    accepted = [
        model.family
        for model in related_insert_models(len(STATUS_133_COOL22), CABINET_UPLUS_ID)
        if (decoded := model.decode(STATUS_133_COOL22, None)) is not None
        and decoded.get("current_temperature") is not None
        and insert_corroborated_by_actype(decoded, heat_pump)
    ]
    assert related_family_name(-19, (RELATED_INSERT_PIVOT, 4)) not in accepted
    assert len(accepted) > 1

    # ⚠️ The gate's falsifiability is what the two assertions above pin, and it is unchanged. What
    # HAS changed is that `decode_related` no longer rests on it alone: for a lineage whose report
    # stops where the map stops, the frame length fixes the count outright
    # (`RELATED_INSERT_BASE_LENGTH`), and arithmetic is not a coin toss. That matters because the
    # flag can only ever confirm a COOLING-ONLY unit -- its informative value is 1, and a candidate
    # read at the wrong offset lands on a zero byte, which decodes as "heat pump". Two of the three
    # cabinets this project holds reports for are heat pumps, and both were refused until the
    # length rule answered for them (`CANONICAL_WIRE_MAP.md` §AO).
    assert decode_related(
        STATUS_133_COOL22, CABINET_UPLUS_ID, None, declared_modes=heat_pump
    )["layout"] == related_family_name(-19, (RELATED_INSERT_PIVOT, 4))


def test_an_appliance_that_declares_nothing_gets_no_inserted_layout() -> None:
    """With nothing to corroborate against, an insert is a guess. Keep today's behaviour instead."""
    for modes in (None, frozenset()):
        assert decode_related(
            STATUS_133_COOL22, CABINET_UPLUS_ID, None, declared_modes=modes
        ) is None


def test_the_inserted_layout_is_only_reached_when_no_flat_offset_fits() -> None:
    """The guarantee that no appliance working today is disturbed.

    An inserted layout can read a report a flat one also reads, so offering both at once would turn
    a report with one fit into a report with two -- and two fits means none. The fallback is reached
    only after every flat candidate has failed.
    """
    flat = related_wire_models(len(STATUS_133_COOL22), CABINET_UPLUS_ID)
    assert flat, "the shortlist itself is unchanged"
    assert all(
        model.decode(STATUS_133_COOL22, None) is None
        or model.decode(STATUS_133_COOL22, None).get("current_temperature") is None
        for model in flat
    ), "a flat offset fitting would mean the fallback is never consulted for this report"


def test_the_layout_name_carries_its_insert_and_rebuilds_exactly() -> None:
    """The decode reports its choice only as a name, and control rebuilds the model from it.

    A name that lost the insert would rebuild the flat layout -- reading the report correctly and
    then commanding the appliance four words out. An unparseable suffix must refuse rather than fall
    back to flat.
    """
    name = related_family_name(-19, (RELATED_INSERT_PIVOT, 4))
    assert name == "related-19+4@25"
    rebuilt = related_model_named(name, len(STATUS_133_COOL22), uplus_id=CABINET_UPLUS_ID)
    assert rebuilt is not None
    assert rebuilt.decode(STATUS_133_COOL22, None) == _decode(STATUS_133_COOL22)
    for broken in ("related-19+4", "related-19@25", "related-19+x@25", "relatedX"):
        assert related_model_named(broken, 133, uplus_id=CABINET_UPLUS_ID) is None


def test_control_is_offered_and_every_control_reads_back() -> None:
    """What the whole fix is for: this class is commandable one parameter at a time, and was not.

    Its firmware refuses the group set, so it publishes no group command and gets none here -- what
    it gets is a per-attribute channel, each control read back from its own position in the report.
    """
    model = related_model_named(
        related_family_name(-19, (RELATED_INSERT_PIVOT, 4)), 133, uplus_id=CABINET_UPLUS_ID
    )
    assert model is not None
    assert model.writable is True
    assert model.group_cmd is None, "this class's firmware refuses the group set"
    assert model.value_param_fields, "so it must be commanded one parameter at a time"
    for name in model.value_param_fields:
        for report, *_ in STATES:
            assert model.value_param_value(report, name) is not None
    # The four the labelled states pin, in the order off / cool 22 / fan-only.
    reads = {
        name: [model.value_param_value(report, name) for report, *_ in STATES]
        for name in ("onOffStatus", "targetTemperature", "operationMode", "windSpeed")
    }
    assert reads == {
        "onOffStatus": [0, 1, 1],
        "targetTemperature": [9, 6, 6],      # EPP is C - 16, so 25 / 22 / 22
        "operationMode": [1, 1, 6],
        "windSpeed": [2, 3, 1],
    }


def test_the_whole_read_path_resolves_it_not_just_the_resolver() -> None:
    """End to end through ``parse_full_status``, which is what the coordinator actually calls."""
    state = parse_full_status(
        STATUS_133_COOL22, None, CABINET_MODEL, uplus_id=CABINET_UPLUS_ID, order=None
    )
    assert not state.get("partial"), "the partial decode is what this appliance was stuck on"
    assert state["layout"] == related_family_name(-19, (RELATED_INSERT_PIVOT, 4))
    assert state["writable"] is True
    assert state["current_temperature"] == 25.0


def test_the_frame_length_fixes_the_insert_without_any_corroboration() -> None:
    """The count is arithmetic, not a judgement, for a lineage that ends where the map ends.

    `RELATED_INSERT_BASE_LENGTH` says the -19 lineage's report is 125 bytes with no inserted block,
    and the classic family calibrates that: its 127-byte rental member is the +1 case, which is
    exactly what `_CLASSIC_PROBE.length_inserts` already records. Two bytes per word, so a 133-byte
    report is +4 and can be nothing else.

    ★ This matters because `acType` cannot answer for every appliance. Its informative value is 1
    (单冷, cooling only); a candidate read at the wrong offset lands on one of the many zero bytes a
    report carries, and zero decodes as 冷暖 -- heat pump. So the flag singles out a cooling-only
    unit and is silent for a heat pump, and two of the three cabinets this project holds reports for
    are heat pumps.
    """
    from haismart_hrdp.wire_models import RELATED_INSERT_BASE_LENGTH

    assert RELATED_INSERT_BASE_LENGTH["0d12"] == (-19, 125)
    assert 125 + 2 * 4 == len(STATUS_133_COOL22), "133 bytes is the base plus four words"

    # Told the appliance is a heat pump -- the case `acType` cannot decide -- the length still does.
    heat_pump = CABINET_MODES | {4}
    for modes in (CABINET_MODES, heat_pump):
        decoded = decode_related(STATUS_133_COOL22, CABINET_UPLUS_ID, None, declared_modes=modes)
        assert decoded is not None
        assert decoded["layout"] == related_family_name(-19, (RELATED_INSERT_PIVOT, 4))
        assert decoded["current_temperature"] == 25.0


def test_the_length_rule_declines_the_families_it_was_not_measured_on() -> None:
    """⚠️ A base length is a claim that the report ENDS where the map does, and it is false for
    extended-46: its 209-byte report carries words past everything the map describes, so the same
    arithmetic would imply +22 where the true insert is +10. Displacement 0 is therefore absent from
    the table, and must stay absent until someone measures it."""
    from haismart_hrdp.wire_models import RELATED_INSERT_BASE_LENGTH

    assert set(RELATED_INSERT_BASE_LENGTH) == {"0d12"}
    # ⚠️ And it is keyed on the CLASS, not the displacement: a second 133-byte map exists (a 4-bit
    # setpoint at w1.b12, sensors at w5/w6) and length alone would hand it this family's placement.
    assert all(isinstance(k, str) for k in RELATED_INSERT_BASE_LENGTH)
