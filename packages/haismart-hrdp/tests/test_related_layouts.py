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
    readings it does not have. Absence must not read as agreement."""
    wrong = related_wire_model(len(STATUS_125), 0).decode(STATUS_125)
    assert wrong is not None                      # nothing implausible was read...
    assert "target_temperature" not in wrong      # ...because nothing was read at all
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
