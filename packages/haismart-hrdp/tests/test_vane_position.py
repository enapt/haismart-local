"""A vane is a POSITION, and reducing it to "is it sweeping" throws the position away.

`vane_v_sweeping`/`vane_h_sweeping` answer the question a climate entity's swing control asks, and
that answer is lossy in a way that matters: a vane parked at a real stop and a vane held closed both
come back `False`. The codes below are the three status reports attached to haismart-local issue #12
by the owner of a 133-byte central cabinet, plus two from a second cabinet of the same identifier
with one axis set sweeping from the phone app.
"""
from __future__ import annotations

import pytest

from haismart_hrdp.wire_models import (
    related_model_named,
    vane_code,
    vane_model_code,
    vane_position_name,
    vane_v_sweeping,
)

UPLUS = "201c10c7088081000d1205464544850000009cd68e692c104e2a333eab95d140"


def _report(payload: str) -> bytes:
    body = bytes.fromhex(payload.replace(" ", ""))
    blob = bytearray(133)
    blob[2:4] = b"\x27\x15"
    blob[92:92 + len(body)] = body
    return bytes(blob)


# up-down parked at its second stop, left-right sweeping
OFF = _report("09 02 22 00 02 00 14 07 00 00 00 00 00 00 00 03 02 03 32 32 5F 80 00 03")
# both axes closed
COOL22 = _report("06 00 23 00 02 01 14 00 00 00 00 00 00 00 00 03 02 03 32 32 5F 80 00 03")
# up-down sweeping (wire 0x0c), left-right closed
V_AUTO = _report("09 0C 22 00 02 01 14 00 00 00 00 00 00 00 00 03 02 03 30 32 5E 80 00 03")

MODEL = related_model_named("related-19+4@25", 133, uplus_id=UPLUS)

#: What this product's own model publishes for the up-down axis: ten stops, `0` fixed and `8` auto.
DECLARED_V = frozenset({0, 1, 2, 3, 4, 5, 6, 7, 8, 9})
VERTICAL = "windDirectionVertical"
HORIZONTAL = "windDirectionHorizontal"


def test_the_boolean_cannot_tell_a_parked_vane_from_a_closed_one() -> None:
    """The defect, stated as the thing that is indistinguishable."""
    assert vane_v_sweeping(vane_code(MODEL, OFF, "swing_vertical")) is False
    assert vane_v_sweeping(vane_code(MODEL, COOL22, "swing_vertical")) is False
    # ...yet the appliance is reporting two different things.
    assert vane_code(MODEL, OFF, "swing_vertical") == 2
    assert vane_code(MODEL, COOL22, "swing_vertical") == 0


@pytest.mark.parametrize(
    ("blob", "wire", "model_code"),
    [(OFF, 2, 2), (COOL22, 0, 0), (V_AUTO, 0x0C, 8)],
)
def test_the_up_down_position_survives_the_translation(blob, wire, model_code) -> None:
    """Vertical is the axis whose wire and model code spaces differ: `0x0c` on the wire is the
    model's `8`. Reporting the wire number to someone reading their own manual would be wrong."""
    assert vane_code(MODEL, blob, "swing_vertical") == wire
    assert vane_model_code(MODEL, blob, "swing_vertical") == model_code


def test_the_left_right_axis_needs_no_translation() -> None:
    assert vane_model_code(MODEL, OFF, "swing_horizontal") == 7      # its model's "position 8 (auto)"
    assert vane_model_code(MODEL, COOL22, "swing_horizontal") == 0   # "position 1 (fixed)"


def test_the_stops_the_vendor_names_are_named_rather_than_numbered() -> None:
    """Health airflow is a comfort preset, not a place along the sweep, and the vendor's own panel
    dictionary names it so. Numbering it says the wrong thing about what it does -- and because the
    two health stops sit at codes 1 and 3, *between* the ordinary positions, counting them pushed
    every later stop one place along."""
    named = {c: vane_position_name(c, DECLARED_V, 0, 8, VERTICAL) for c in sorted(DECLARED_V)}
    assert named[0] == "fixed"
    assert named[8] == "auto"
    assert named[1] == "health_up"
    assert named[3] == "health_down"
    assert named[9] == "auto_2"


def test_the_numbered_stops_reproduce_the_numbers_the_vendor_PRINTS() -> None:
    """The check that the naming above is right rather than merely tidier. This appliance's own
    published stops are described 上下摆位置一 through 五 at codes 2, 4, 5, 6, 7 -- so those are the
    five that must come back as positions one through five. Before the health stops were named,
    code 2 was reported as "position 2" to someone whose manual calls it position one."""
    named = {c: vane_position_name(c, DECLARED_V, 0, 8, VERTICAL) for c in sorted(DECLARED_V)}
    assert [named[c] for c in (2, 4, 5, 6, 7)] == [f"position_{n}" for n in range(1, 6)]


def test_the_same_code_is_not_the_same_stop_on_the_other_axis() -> None:
    """9 is a second automatic sweep up-down and the right-half sweep left-right, so the table has
    to be keyed by axis. Getting this wrong would name a real stop after a different one."""
    assert vane_position_name(9, {0, 8, 9}, 0, 8, VERTICAL) == "auto_2"
    assert vane_position_name(9, {0, 7, 9}, 0, 7, HORIZONTAL) == "right_half_auto"


def test_an_unknown_axis_numbers_every_stop() -> None:
    """Omitting the axis is the honest fallback: with no table to say which stops are special,
    counting them all is what the old behaviour did and is still right for an axis of plain
    positions. It must not silently apply one axis's table to another."""
    assert vane_position_name(1, DECLARED_V, 0, 8) == "position_1"


def test_the_axis_this_appliance_reports_is_the_one_it_was_set_to() -> None:
    """End to end on the two captures whose states were written down: up-down sweeping in one,
    left-right sweeping in the other."""
    assert vane_position_name(
        vane_model_code(MODEL, V_AUTO, "swing_vertical"), DECLARED_V, 0, 8, VERTICAL) == "auto"
    assert vane_position_name(
        vane_model_code(MODEL, OFF, "swing_vertical"), DECLARED_V, 0, 8, VERTICAL) == "position_1"


def test_an_axis_the_layout_does_not_place_reads_nothing_rather_than_zero() -> None:
    stripped = related_model_named("related-19", 133, uplus_id=UPLUS)
    assert vane_code(stripped, OFF, "no_such_axis") is None
