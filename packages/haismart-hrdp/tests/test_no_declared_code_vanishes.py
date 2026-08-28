"""A code the vendor publishes must not disappear on its way to the wire.

Every translation in this library maps the codes a device's model declares to the values its wire
field carries, and **every consumer of one filters against its keys**: a code the table does not
mention is not written wrong, it is silently dropped -- from the model-authorized set, from a
select's options, from a decode. So an incomplete table costs an appliance a function it has, and
costs it invisibly. That has now happened twice: ``operationMode`` 5 (the window units' economy
mode) vanished from a read map until issue #11, and the up-down vane's ``1``/``3``/``9`` vanished
from the write table until issue #12 -- 86 products, three stops each.

These tests are the standing guard. They do not ask whether a table looks complete; they compare it
against the vendor's own published code space and require every difference to be **named, with a
reason**, so a new omission fails while the justified ones stay justified.
"""
from __future__ import annotations

from haismart_hrdp import wire_models as wm
from haismart_hrdp.canonical_map import CANONICAL

#: Codes our translations deliberately do not carry, and why. Anything missing and NOT listed here
#: is the bug this module exists to catch. Every entry is a measurement with an expiry date, not a
#: permanent exemption.
JUSTIFIED_OMISSIONS: dict[str, dict[int, str]] = {
    # Nothing omitted. The table is now read FROM the published map, so it cannot fall behind it --
    # which is the point: the table that went stale was the one written out by hand.
    "windDirectionVertical": {},
    # The wire field is one bit wide and carries both codes the map publishes.
    "tempUnit": {},
}


def _published(name: str) -> set[int]:
    """The STD codes the published map states for ``name``."""
    return set((CANONICAL[name].enum or {}).values())


def test_every_published_code_table_is_covered_or_its_gaps_are_named() -> None:
    """Keyed on the MAP, not on a list written here.

    An attribute that gains a code table when the map is regenerated is covered from that moment,
    without anyone remembering to add it -- the assertion fails until its coverage is stated.
    """
    with_codes = {name for name, f in CANONICAL.items() if f.enum}
    assert with_codes == set(JUSTIFIED_OMISSIONS), (
        "the published map has a code table this guard does not cover: "
        f"{sorted(with_codes ^ set(JUSTIFIED_OMISSIONS))}"
    )
    ours = {"windDirectionVertical": set(wm.VANE_V_MODEL_TO_EPP), "tempUnit": {1, 2}}
    for name, carried in ours.items():
        missing = _published(name) - carried
        assert missing == set(JUSTIFIED_OMISSIONS[name]), (
            f"{name} drops published codes {sorted(missing)} with no recorded reason"
        )


def test_the_vane_table_still_agrees_with_the_stops_confirmed_on_hardware() -> None:
    """Taking the table from the map is safe only while the map agrees with what a unit reported.

    A real unit was stepped through every stop its app offers, one capture per stop. Those readings
    are kept separately so the map is CHECKED against an observation rather than trusted: if a
    regenerated map ever moved one of them, this fails instead of silently redefining what an
    appliance is told to do.
    """
    for std, epp in wm.VANE_V_CONFIRMED_ON_HARDWARE.items():
        assert wm.VANE_V_MODEL_TO_EPP[std] == epp, f"vane stop {std} moved to {epp}"
    # Reversible, or a position could be written and never read back.
    assert len(wm.VANE_V_EPP_TO_MODEL) == len(wm.VANE_V_MODEL_TO_EPP)


def test_the_vane_table_carries_the_codes_that_used_to_vanish() -> None:
    """The three stops issue #12's appliance declares and could not reach. Fails before the fix."""
    for std in (1, 3, 9):
        assert std in wm.VANE_V_MODEL_TO_EPP


def test_the_withheld_vane_ids_are_waiting_only_on_an_observation() -> None:
    """A withholding is a measurement, so it states what it waits for and is re-checked.

    The two central-cabinet vane ids are not shipped because nothing of that class has ever been
    seen to accept them -- NOT because the appliances lack the hardware. This pins the distinction:
    the map places both axes, so the only missing piece is one accept/refuse observation. Shipping
    an id means taking it out of the withheld table, and this is what makes that deliberate.
    """
    for klass, withheld in wm.WITHHELD_SINGLE_PARAM_IDS.items():
        shipped = wm.SINGLE_PARAM_IDS.get(klass, {})
        assert not set(withheld) & set(shipped), "an id cannot be both shipped and withheld"
        for name, (param_id, reason) in withheld.items():
            assert reason == "never observed accepted"
            assert 0 < param_id < 0x100
            assert name in CANONICAL, f"{name} has no published position to read it back from"


def test_a_group_set_is_never_packed_across_an_inserted_block() -> None:
    """A group-set is one contiguous slice of the report, so it cannot span words the map omits.

    The frame covers canonical words 20..19+word_count, so a five-word frame stops at w24 and clears
    a pivot at w25 -- which is why the one family that has an insert today would keep its group-set
    if it published an order at all. The guard exists for a frame that DOES reach the pivot: the
    append region already produces seven-word frames elsewhere, and one of those over an inserted
    layout would seed every word from the pivot on out of the wrong place and write it back there.

    Both halves are pinned, because a guard that fires when it should not is as wrong as one that
    never fires.
    """
    order = ("targetTemperature", "operationMode", "windSpeed", "onOffStatus")
    uplus = "2" * 64

    # Clears the real pivot: the frame ends one word short of it, so nothing is refused.
    clears = wm.related_wire_model(
        133, -19, order=order, uplus_id=uplus, insert=(wm.RELATED_INSERT_PIVOT, 4)
    )
    assert clears.write_fields, "a frame below the pivot must keep its group-set"

    # Reaches it: same frame, an insert that begins inside the words the frame packs.
    crosses = wm.related_wire_model(133, -19, order=order, uplus_id=uplus, insert=(22, 4))
    assert crosses.group_cmd is None
    assert not crosses.write_fields
    # Reads and the per-attribute channel are untouched -- refusing the group-set is not refusing
    # the appliance.
    assert crosses.fields
