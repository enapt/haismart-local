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
