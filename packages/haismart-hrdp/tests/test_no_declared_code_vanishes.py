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


def test_a_provisional_id_is_offered_only_where_the_appliance_can_settle_it() -> None:
    """An id nobody has watched being accepted is offered only if the same attribute reads back.

    That is what makes offering it honest rather than hopeful: the appliance adjudicates its own
    registry, once, and an id that does not take is retired instead of being sent again. So the
    invariant is not "is it observed" but "can this be checked" -- every provisional attribute must
    have a published position to read it back from, and no id may be both settled and provisional.
    """
    for klass, unconfirmed in wm.PROVISIONAL_SINGLE_PARAM_IDS.items():
        settled = wm.SINGLE_PARAM_IDS.get(klass, {})
        assert not set(unconfirmed) & set(settled), "an id cannot be both settled and provisional"
        for name, param_id in unconfirmed.items():
            assert 0 < param_id < 0x100
            assert name in CANONICAL, f"{name} has no published position to read it back from"


def test_the_vertical_vane_id_is_the_only_one_its_bracket_leaves_free() -> None:
    """The second, independent reason to believe 0x03 -- reached before any hardware confirmed it.

    An owner has since moved both axes, so the id is observed now; this is kept because it is the
    argument that justified sending the command in the first place, and because a later map that
    moved either anchor would quietly withdraw it.

    In the published wire order this attribute is the ONLY one the class declares between two
    OBSERVED ids, and one id is free in that span. Written down as a check because it is the whole
    argument: if a later map moves either anchor, or another attribute lands between them, the
    bracket stops forcing anything and this fails rather than quietly going on being quoted.
    """
    ids = wm.SINGLE_PARAM_IDS["0d12"]
    lo, hi = ids["targetTemperature"], ids["operationMode"]
    vane = CANONICAL["windDirectionVertical"]
    span = [n for n, f in CANONICAL.items()
            if (CANONICAL["targetTemperature"].word, -CANONICAL["targetTemperature"].bit)
            < (f.word, -f.bit)
            < (CANONICAL["operationMode"].word, -CANONICAL["operationMode"].bit)]
    assert span == ["windDirectionVertical"], span
    assert list(range(lo + 1, hi)) == [ids[span[0]]]
    assert vane.word  # the position that makes the read-back check possible


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


def test_a_value_no_field_can_hold_vetoes_a_layout_candidate() -> None:
    """A published value space is a legal-range test, and a candidate outside it is wrong.

    ``errCode`` is an alarm's position plus one, matched against all 51 published entries with zero
    mismatches, so a report claiming a higher code is not reporting a fault -- it is being read in
    the wrong place. This is what the recorded invariant list means by "wrong regardless of score".
    """
    assert not wm.structural_violations({"error_code": 0})
    assert not wm.structural_violations({"error_code": 51})
    assert wm.structural_violations({"error_code": 52})
    assert wm.structural_violations({"error_code": 95})
    # Absent is not a violation: a family that does not place the field says nothing about it.
    assert not wm.structural_violations({})


def test_the_veto_is_not_applied_where_ambiguity_is_the_safety_net() -> None:
    """⚠️ Pins a NON-obvious placement decision, so nobody 'tidies it up' by applying it everywhere.

    The layout prober ranks candidates for a person to read, so removing impossible ones there is a
    straight improvement. The inserted-layout gate is different: it ACTS on a single survivor, and
    the protection against a wrong answer is that two candidates survive and the report is refused.
    Vetoing an impossible candidate there can leave a merely-wrong one alone in the field.

    Measured on the reports this was derived from: told (inconsistently) that the appliance declares
    heat, the wrong count 3 is impossible and the wrong count 5 is not -- so with a veto the wrong
    one would stand alone and be accepted, and without it two stand and nothing is.
    """
    from test_inserted_layouts import CABINET_UPLUS_ID, STATUS_133_COOL22

    heat = frozenset({0, 1, 2, 4, 6})
    survivors = []
    for model in wm.related_insert_models(len(STATUS_133_COOL22), CABINET_UPLUS_ID):
        decoded = model.decode(STATUS_133_COOL22, None)
        if decoded is None or not all(k in decoded for k in wm._RELATED_REQUIRED):
            continue
        if wm.insert_corroborated_by_actype(decoded, heat):
            survivors.append((model.family, bool(wm.structural_violations(decoded))))
    # Two survive the corroboration; exactly one of them is also structurally impossible.
    assert len(survivors) == 2, survivors
    assert sum(1 for _, vetoed in survivors if vetoed) == 1
    # The veto is still NOT applied here, and the reasoning above still holds for it: on a survivor
    # count, removing an impossible candidate can leave a merely-wrong one alone in the field.
    #
    # ⚠️ What resolves this report is neither the veto nor the survivor count. The frame LENGTH fixes
    # the insert outright for a lineage whose report stops where the map stops -- 125 B base, 2
    # bytes per inserted word, so a 133-byte report is +4 and nothing else. Arithmetic does not need
    # a safety net, and it answers for the heat-pump cabinets `acType` is structurally silent about
    # (`CANONICAL_WIRE_MAP.md` §AO). The ambiguity above is what the gate would fall back to if the
    # base length for this lineage were ever withdrawn.
    assert wm.decode_related(
        STATUS_133_COOL22, CABINET_UPLUS_ID, None, declared_modes=heat
    )["layout"].endswith("+4@25")
