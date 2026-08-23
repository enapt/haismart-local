"""Layouts resolved from the closest published relative.

An appliance whose own model was never published still announces an identifier, and the published
models sharing that identifier's leading characters describe the same attributes at one of a small
number of whole-word offsets. These tests pin what that shortlist may and may not conclude.
"""
from __future__ import annotations

import pytest
from test_uss import STATUS_117_OFF, STATUS_125

from haismart_hrdp import decode_related
from haismart_hrdp.canonical_map import DISPLACEMENTS, PROFILE_DISPLACEMENTS
from haismart_hrdp.wire_models import (
    _RELATED_PREFIX_MIN,
    displacement_candidates,
    related_model_named,
    related_wire_model,
    related_wire_models,
)

# The identifier our own units announce. Its closest published relatives are two models that share
# 26 leading characters and disagree about the offset -- which is the case worth testing, because it
# is the common one and the one that cannot be settled from the identifier alone.
OUR_UPLUS_ID = "2008610800820324021200118012560000000000000000000000000000000040"


def test_the_per_profile_table_agrees_with_the_histogram() -> None:
    """The two tables are generated from one pass over the models; neither may drift."""
    counted: dict[int, int] = {}
    for displacement in PROFILE_DISPLACEMENTS.values():
        counted[displacement] = counted.get(displacement, 0) + 1
    assert counted == dict(DISPLACEMENTS)


def test_every_published_profile_states_a_known_displacement() -> None:
    assert set(PROFILE_DISPLACEMENTS.values()) == set(DISPLACEMENTS)


def test_our_own_identifier_shortlists_both_of_its_relatives() -> None:
    """Two relatives, disagreeing by exactly the span before the climate block."""
    assert set(displacement_candidates(OUR_UPLUS_ID)) == {-19, 0}


def test_a_stranger_shortlists_nothing() -> None:
    """Sharing no meaningful prefix is not a relationship, and must not produce a guess."""
    assert displacement_candidates("9" * 64) == ()
    assert displacement_candidates(None) == ()
    assert displacement_candidates("") == ()


def test_a_shared_product_class_alone_is_not_a_relationship() -> None:
    """The leading characters are a product class, and a class is explicitly not a layout."""
    a_profile = next(iter(PROFILE_DISPLACEMENTS))
    just_under = a_profile[: _RELATED_PREFIX_MIN - 1] + "z" * (65 - _RELATED_PREFIX_MIN)
    assert displacement_candidates(just_under) == ()


def test_a_related_layout_reproduces_the_hardware_verified_decoder() -> None:
    """The whole claim, checked against a real report: resolving the offset from the identifier
    alone yields exactly what the family's own confirmed decoder yields."""
    from haismart_hrdp import parse_full_status

    resolved = decode_related(STATUS_125, OUR_UPLUS_ID)
    assert resolved is not None
    confirmed = parse_full_status(STATUS_125)
    shared = set(resolved) & set(confirmed)
    assert shared >= {"power", "target_temperature", "current_temperature", "outdoor_temperature"}
    assert {k: resolved[k] for k in shared} == {k: confirmed[k] for k in shared}


def test_the_wrong_relative_is_refused_rather_than_returned_empty() -> None:
    """The offset that is wrong by nineteen words reads past the end of a shorter report, so every
    field comes back absent -- and a decode holding no readings passes a plausibility check on the
    readings it does not have. Absence must not read as agreement.

    The refusal now comes from ``WireModel.decode`` itself rather than from this caller, so every
    family gets it: a registered one claimed by uPlusId used to accept any short frame the same way.
    """
    assert related_wire_model(len(STATUS_125), 0).decode(STATUS_125) is None
    assert decode_related(STATUS_125, OUR_UPLUS_ID)["layout"] == "related-19"


def test_a_related_layout_never_claims_a_write_path() -> None:
    """Positions come from the map; no capture has confirmed them on this appliance, and a group-set
    writes a whole block at once. It may report, and must not command."""
    for wm in related_wire_models(125, OUR_UPLUS_ID):
        assert wm.writable is False
        assert wm.group_cmd is None
        assert wm.write_fields == {}


def test_a_related_layout_places_nothing_beyond_the_core_block() -> None:
    """``canonical_displacement`` stays unset, so the further attributes a device declares are not
    placed off an offset that no report has confirmed field for field."""
    for wm in related_wire_models(125, OUR_UPLUS_ID):
        assert wm.canonical_displacement is None
        assert wm.model_fields(["lockStatus", "indoorHumidity"], 125) == {}


def test_a_registered_family_is_not_displaced_by_a_relative() -> None:
    """A report a known family claims keeps that family's decode: this only ever fills a gap."""
    from haismart_hrdp import parse_full_status, select_wire_model

    assert select_wire_model(len(STATUS_117_OFF)) is not None
    decoded = parse_full_status(STATUS_117_OFF, uplus_id=OUR_UPLUS_ID)
    assert decoded["layout"] == "compact12"


@pytest.mark.parametrize("junk", [b"", b"\x00" * 40, b"\xff" * 200])
def test_junk_resolves_to_nothing(junk: bytes) -> None:
    assert decode_related(junk, OUR_UPLUS_ID) is None


# --- control on a layout resolved from a relative -------------------------------------------------

# The settings a real appliance publishes its group-set as carrying, in the order it publishes them.
OUR_ORDER = (
    "targetTemperature", "windDirectionVertical", "operationMode", "specialMode", "windSpeed",
    "energySavePeriod", "selfCleaning56Status", "tempUnit", "pmvStatus", "intelligenceStatus",
    "halfDegreeSettingStatus", "screenDisplayStatus", "10degreeHeatingStatus", "echoStatus",
    "lockStatus", "silentSleepStatus", "muteStatus", "rapidMode", "electricHeatingStatus",
    "healthMode", "onOffStatus", "targetHumidity", "humanSensingStatus", "windDirectionHorizontal",
    "cloudFilterChangeFlag", "cleaningTimeStatus", "energySavingStatus", "lightStatus",
    "selfCleaningStatus", "ch2oCleaningStatus", "pm2p5CleaningStatus", "humidificationStatus",
    "freshAirStatus",
)
TWIN_TOWER = "2008610800820324021200118017740000000000000000000000000000000040"


def test_a_related_layout_stays_read_only_without_the_appliances_own_group_set_list():
    """No list, no control. The frame says where a setting goes; only the appliance's own published
    list says whether it HAS that setting, and writing one it does not carry puts a value in a word
    its firmware uses for something else."""
    model = related_wire_model(127, -19)
    assert model.writable is False
    assert model.group_cmd is None
    assert model.write_fields == {}


def test_a_related_layout_becomes_commandable_once_the_list_is_known():
    model = related_wire_model(127, -19, order=OUR_ORDER)
    assert model.writable is True
    assert model.group_cmd == b"\x60\x01"
    assert "targetTemperature" in model.write_fields
    assert "onOffStatus" in model.write_fields


@pytest.mark.parametrize("displacement,length", [(-19, 127), (0, 165)])
def test_the_base_word_is_twenty_plus_the_displacement(displacement, length):
    """Not a per-family constant anyone fitted: the climate block begins at map word 20 and the
    group-set is those words lifted out, so the report word its first word lands on is 20 + the
    displacement. Checked against both offsets the published models use."""
    model = related_wire_model(length, displacement, order=OUR_ORDER)
    assert model.write_base_word == 20 + displacement


def test_a_family_that_reuses_the_frames_bits_loses_exactly_those_controls():
    """The three the twin-tower families keep a different attribute at -- and nothing else."""
    plain = set(related_wire_model(209, 0, order=OUR_ORDER).write_fields)
    twin = set(related_wire_model(209, 0, order=OUR_ORDER, uplus_id=TWIN_TOWER).write_fields)
    assert plain - twin == {"windDirectionVertical", "windSpeed", "selfCleaningStatus"}
    # everything else survives, so this is a gate and not a retreat
    assert {"targetTemperature", "operationMode", "onOffStatus", "muteStatus"} <= twin


def test_a_setpoint_encoded_on_a_related_layout_lands_where_the_frame_says():
    """End to end on a REAL report: seed the group-set from it, change one setting, and check the
    bytes moved at the position the published frame gives -- and nowhere else."""
    model = related_wire_model(len(STATUS_125), -19, order=OUR_ORDER)
    baseline = model.baseline_words(STATUS_125)
    assert len(baseline) == 10                      # five 16-bit words

    encoded = model.encode_control(baseline, {"targetTemperature": 25 - 16})
    assert len(encoded) == len(baseline)
    differing = [i for i, (a, b) in enumerate(zip(baseline, encoded, strict=True)) if a != b]
    # targetTemperature is the frame's word 1 bit 8, i.e. the HIGH byte of the first word
    assert differing == [0]
    assert encoded[0] == 25 - 16

    # and the value reads back through the family's own accessor
    assert model.current_write_value(STATUS_125[:92] + bytes(encoded) + STATUS_125[102:],
                                     "targetTemperature") == 25 - 16


def test_the_encoder_still_refuses_a_setting_the_appliance_does_not_publish():
    """The list is a gate in both directions: a frame position is not a licence to write it."""
    short = tuple(n for n in OUR_ORDER if n != "windDirectionHorizontal")
    model = related_wire_model(127, -19, order=short)
    assert "windDirectionHorizontal" not in model.write_fields
    with pytest.raises(KeyError):
        model.encode_control(model.baseline_words(STATUS_125), {"windDirectionHorizontal": 7})


# --- an appliance related to nothing (issue #11, the window air conditioners) ----------------

#: HW-10VCQ33-W, product AD0P34E00 -- a Philippine window unit, uPlusId class 3912. It shares only
#: SIXTEEN characters with the nearest published model, diverging inside the device type, which is
#: the boundary `_RELATED_PREFIX_MIN` exists to refuse. So it has no relative to inherit an offset
#: from and, before this, decoded to nothing at all.
WINDOW_UPLUS_ID = "201c120024000810391286e28c62e450083e48910b475b0921da284d3b25e440"

#: Its published group-set order, from the shipped rules bundle (33 names).
WINDOW_ORDER = (
    "targetTemperature", "windDirectionVertical", "operationMode", "specialMode", "windSpeed",
    "energySavePeriod", "energySave", "tempUnit", "pmvStatus", "intelligenceStatus",
    "halfDegreeSettingStatus", "screenDisplayStatus", "10degreeHeatingStatus", "echoStatus",
    "lockStatus", "silentSleepStatus", "muteStatus", "rapidMode", "electricHeatingStatus",
    "healthMode", "onOffStatus", "targetHumidity", "humanSensingStatus", "windDirectionHorizontal",
    "trdlSeting", "sabbathStatus", "energySavingStatus", "lightStatus", "selfCleaningStatus",
    "ch2oCleaningStatus", "pm2p5CleaningStatus", "humidificationStatus", "freshAirStatus",
)

#: The three reports attached to issue #11. 109 bytes: eight attribute words and the checksum, i.e.
#: the published map's words 20..27 and nothing after them.
WINDOW_OFF = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000000000000000000000000000000000000000000001dffff1a0000000000"
    "00066d010800a33c0000140000003600008000003f"
)
WINDOW_COOL_22_LOW = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000000000000000000000000000000000000000000001dffff1a0000000000"
    "00066d010600233c000114000000380000800000c0"
)
WINDOW_COOL_22_HIGH = bytes.fromhex(
    "00002715000000004e5601000003020000040100000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000000000000000000000000000000000000000000001dffff1a0000000000"
    "00066d010600213c000114000000380000800000be"
)


def test_an_appliance_with_no_relative_resolves_its_offset_from_the_report():
    """Issue #11. No published model shares enough of this identifier to rank as a relative, so the
    old shortlist was EMPTY and the report decoded to nothing. The offsets are still only two, and
    the report itself tells them apart: at 0 every climate word lies past the end of a 109-byte
    report, so nothing is placed at all."""
    from haismart_hrdp.wire_models import displacement_candidates, related_shortlist_is_ranked

    assert displacement_candidates(WINDOW_UPLUS_ID) == ()      # no relative, as before
    assert related_shortlist_is_ranked(WINDOW_UPLUS_ID) is False

    state = decode_related(WINDOW_COOL_22_LOW, WINDOW_UPLUS_ID, order=WINDOW_ORDER)
    assert state is not None
    assert state["layout"] == "related-19"
    assert state["power"] is True
    assert state["target_temperature"] == 22.0     # the stated setpoint
    assert state["current_temperature"] == 28.0
    assert state["wind_speed"] == "3"              # 低风 low, the stated fan speed
    assert state["operation_mode"] == "1"          # 制冷 cool, the stated mode


def test_the_window_reports_agree_with_every_state_their_reporter_stated():
    off = decode_related(WINDOW_OFF, WINDOW_UPLUS_ID, order=WINDOW_ORDER)
    high = decode_related(WINDOW_COOL_22_HIGH, WINDOW_UPLUS_ID, order=WINDOW_ORDER)
    assert off is not None and high is not None
    assert off["power"] is False and high["power"] is True
    assert high["wind_speed"] == "1"               # 高风 high
    # This unit declares no outdoor probe at all, and reads its sentinel zero rather than -64 C.
    assert off.get("outdoor_temperature") is None
    # It cannot heat, and says so itself -- which agrees with its published mode list (cool /
    # energy-saving / fan, no 制热). Two independent sources, so the offset is not merely plausible.
    assert off["heat_capable"] is False


def test_the_energy_saving_mode_the_window_units_publish_is_decoded():
    """`节能模式(窗机)` is operationMode 5. It was absent from the wire map's code set, so a unit
    sitting in it decoded with NO operationMode -- which reads downstream as "the appliance did not
    report a mode" rather than "we do not know this code"."""
    off = decode_related(WINDOW_OFF, WINDOW_UPLUS_ID, order=WINDOW_ORDER)
    assert off is not None
    assert off["operation_mode"] == "5"


def test_an_unidentified_or_frameless_appliance_keeps_the_partial_decode():
    """The fallback is not a free-for-all: it needs the appliance's own name AND its product's
    published frame. Without either, the report must fall through to the partial decode, whose
    `layout: unknown` flag is how an unsupported model gets reported in the first place."""
    assert decode_related(WINDOW_COOL_22_LOW, None, order=WINDOW_ORDER) is None
    assert decode_related(WINDOW_COOL_22_LOW, WINDOW_UPLUS_ID, order=None) is None
    assert decode_related(WINDOW_COOL_22_LOW, WINDOW_UPLUS_ID, order=()) is None


def test_a_relatives_ranking_still_wins_where_there_is_one():
    """The fallback must not disturb an appliance that HAS a relative: the shortlist is still the
    ranked one, and its first fit is still the answer."""
    from haismart_hrdp.wire_models import (
        displacement_candidates,
        related_shortlist_is_ranked,
        related_wire_models,
    )

    assert related_shortlist_is_ranked(OUR_UPLUS_ID) is True
    ranked = displacement_candidates(OUR_UPLUS_ID)
    assert ranked                       # relatives found -- the ranked shortlist, not the fallback
    assert tuple(wm.family for wm in related_wire_models(125, OUR_UPLUS_ID)) == tuple(
        f"related{d:+d}" for d in ranked
    )


def test_the_window_unit_can_be_commanded_through_its_published_frame():
    """Reading it is half the job. Its order is published, so the frame places every setting it
    carries -- and a control must land in the right byte and touch nothing else."""
    wm = related_model_named(
        "related-19", len(WINDOW_COOL_22_LOW), order=WINDOW_ORDER, uplus_id=WINDOW_UPLUS_ID
    )
    assert wm is not None and wm.writable
    assert wm.write_base_word == 1        # 20 + (-19)
    base = wm.baseline_words(WINDOW_COOL_22_LOW)

    def changed(**kw):
        out = wm.encode_control(base, kw)
        return [i for i, (a, b) in enumerate(zip(base, out, strict=True)) if a != b], out

    where, out = changed(targetTemperature=24 - 16)
    assert where == [0] and out[0] == 8
    where, _ = changed(windSpeed=5)
    assert where == [2]
    where, _ = changed(onOffStatus=0)
    assert where == [5]
    # ...including the energy-saving mode, which the frame's code set used to refuse outright.
    out = wm.encode_control(base, {"operationMode": 5})
    assert wm.current_write_value(WINDOW_COOL_22_LOW, "operationMode") == 1
    assert (out[2] >> 5) & 0x07 == 5


def test_every_published_operation_mode_code_is_decodable():
    """The wire map's code set is a FILTER, not a translation -- it is the identity -- so a code
    missing from it does not decode wrong, it vanishes. Enumerated from the published catalogue
    (1,451 products) so it cannot drift back:

        0 智能/自动/舒适 · 1 制冷 · 2 除湿 · 3 健康除湿 · 4 制热 · 5 节能模式(窗机) · 6 送风

    Code 5 is the one that was missing, and it is the whole of issue #11's second half.
    """
    from haismart_hrdp.wire_models import _EXT36_MODE, _FRAME_WRITE_SPEC

    published = {0, 1, 2, 3, 4, 5, 6}
    assert published <= set(_EXT36_MODE), "a published mode code that would decode to nothing"
    # identity: on every family that is the published map at a displacement, EPP value == STD code
    assert all(int(k) == int(v) for k, v in _EXT36_MODE.items())
    writable = _FRAME_WRITE_SPEC["operationMode"]["std_to_epp"]
    assert published <= set(writable), "a mode the frame could read but never write back"
    assert all(k == v for k, v in writable.items())
    # ...and every one of them fits the frame's 3-bit operationMode field.
    assert max(writable.values()) < 8


def test_every_product_with_no_relative_but_a_published_frame_is_reachable():
    """The set v0.52.0 exists for, pinned against the shipped bundle.

    Twenty-eight published products have no registered family and no relative close enough to rank —
    four window units (issue #11), four twin-tower wall units, and **twenty central-air cabinets**.
    Every one of them publishes a group-set order, and every one of those orders is corroborated by
    the shared frame, so every one is reachable the moment its first report arrives.

    This is a guard, not a discovery: tightening any of the four write gates would take these
    products back to read-only without a single existing test noticing.
    """
    import gzip
    import json

    from haismart_hrdp.model_rules import RULES_PATH
    from haismart_hrdp.wire_models import WIRE_MODELS, frame_write_fields

    models = json.loads(gzip.open(RULES_PATH, "rt").read())["models"]
    registered = {u for wm in WIRE_MODELS for u in wm.uplus_ids}

    unreachable_before = [
        (pc, r) for pc, r in models.items()
        if r.get("uplus_id") not in registered
        and not displacement_candidates(r.get("uplus_id"))
        and r.get("group_set_order")
    ]
    assert len(unreachable_before) == 28
    for pc, r in unreachable_before:
        assert frame_write_fields(r["group_set_order"], r["uplus_id"]), pc

    # ...and they are three device classes, not one. `0d` in particular is NOT one thing: the
    # central-air category splits into `0d12` (no group command at all) and `0d21` (the ordinary
    # shared frame), and a third of the category is already a registered family.
    classes = {r["uplus_id"][16:20] for _, r in unreachable_before}
    assert classes == {"3912", "0214", "0d21"}


def test_the_central_air_category_is_three_architectures_not_one():
    """`docs/FUTURE_WORK.md` used to record the central-air models as "out of scope, not a hole",
    which was true of one device class and read as if it were true of the category. It is not:
    of 235 published central-air products, 28 are a registered family that reads and controls
    today, and 20 more publish the ordinary shared frame."""
    import gzip
    import json

    from haismart_hrdp.model_rules import RULES_PATH
    from haismart_hrdp.wire_models import WIRE_MODELS

    models = json.loads(gzip.open(RULES_PATH, "rt").read())["models"]
    registered = {u for wm in WIRE_MODELS for u in wm.uplus_ids}
    by_class: dict[str, list[str]] = {}
    for pc, r in models.items():
        by_class.setdefault(r["uplus_id"][16:20], []).append(pc)

    # `0d12` — no group command of any name, so no frame and no control path from published data.
    assert len(by_class["0d12"]) == 187
    assert not any(models[pc].get("group_set_order") for pc in by_class["0d12"])
    # ...and they are only TWO identifiers, so two reports would place all 187.
    assert len({models[pc]["uplus_id"] for pc in by_class["0d12"]}) == 2

    # `0d21` — the ordinary group set, and a different device type despite the shared `0d`.
    assert len(by_class["0d21"]) == 20
    assert all(models[pc].get("group_set_order") for pc in by_class["0d21"])

    # `8080` — already registered (the compact family), i.e. central-air that works today.
    assert all(models[pc]["uplus_id"] in registered for pc in by_class["8080"])
