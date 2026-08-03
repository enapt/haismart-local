"""The published group-set order, checked against hardware-measured positions."""

from haismart_hrdp.canonical_map import CANONICAL_WRITE
from haismart_hrdp.wire_order import (
    Placement,
    bracket_unplaced,
    nearest_bundled_profile,
    order_violations,
    solve_positions,
)

# The order our own unit's constraintfile publishes for grSetDAC, verbatim.
ATTR_ORDER = [
    "targetTemperature", "windDirectionVertical", "operationMode", "specialMode", "windSpeed",
    "energySavePeriod", "selfCleaning56Status", "tempUnit", "pmvStatus", "intelligenceStatus",
    "halfDegreeSettingStatus", "screenDisplayStatus", "10degreeHeatingStatus", "echoStatus",
    "lockStatus", "silentSleepStatus", "muteStatus", "rapidMode", "electricHeatingStatus",
    "healthMode", "onOffStatus", "targetHumidity", "humanSensingStatus", "generatorMode",
    "windDirectionHorizontal", "useMode", "localCtrValid", "rentTimingStatus",
    "cloudFilterChangeFlag", "cleaningTimeStatus", "energySavingStatus", "lightStatus",
    "selfCleaningStatus", "ch2oCleaningStatus", "pm2p5CleaningStatus", "humidificationStatus",
    "freshAirStatus", "targetRentTime",
]

# Positions confirmed on real hardware -- the capture-confirmed grSetDAC map.
MEASURED = {
    "targetTemperature": (1, 8), "windDirectionVertical": (1, 0),
    "operationMode": (2, 13), "windSpeed": (2, 8),
    "selfCleaning56Status": (3, 15), "halfDegreeSettingStatus": (3, 10),
    "screenDisplayStatus": (3, 9), "echoStatus": (3, 7), "lockStatus": (3, 6),
    "silentSleepStatus": (3, 5), "muteStatus": (3, 4), "rapidMode": (3, 3),
    "electricHeatingStatus": (3, 2), "healthMode": (3, 1), "onOffStatus": (3, 0),
    "generatorMode": (4, 3),
}


def test_published_order_is_the_wire_order() -> None:
    """Every measured position agrees with the order the device publishes.

    Sixteen anchors across four words, no violations. This is what licenses reading the list as a
    layout at all; if it ever fails for a family, that family's brackets must not be trusted.
    """
    assert order_violations(ATTR_ORDER, MEASURED) == []


def test_order_predicts_the_extra_word_our_family_carries() -> None:
    """``targetRentTime`` is last in the list, and last on the wire.

    Our units carry one word past their nearest published relative, and which attribute occupies it
    was settled the hard way -- by experiment, against two frame lengths. The published order says
    the same thing for free: nothing follows it, and nothing measured sits after ``generatorMode``.
    """
    assert ATTR_ORDER[-1] == "targetRentTime"
    after, before = bracket_unplaced(ATTR_ORDER, MEASURED)["targetRentTime"]
    assert after == MEASURED["generatorMode"]
    assert before is None


def test_brackets_constrain_the_rental_attributes_without_guessing() -> None:
    """The rental attributes no published profile declares are still bounded by their neighbours."""
    brackets = bracket_unplaced(ATTR_ORDER, MEASURED)
    for name in ("useMode", "localCtrValid", "rentTimingStatus"):
        after, before = brackets[name]
        assert after == MEASURED["generatorMode"]   # they follow the last anchor
        assert before is None
    assert "onOffStatus" not in brackets            # measured attributes are never bracketed


def test_prefix_resolution_finds_our_relatives_and_admits_the_tie() -> None:
    """Our uPlusId matches no published profile exactly, and two share 26 characters.

    Which is why an exact-match comparison wrongly concludes the unit is unknown -- the shared
    leading characters identify the family, and a family shares one layout. Note this is a
    convenience we take and not a behaviour anyone else has: the manufacturer's lookup opens the
    identifier as a filename and gives up, leaving such a device with no local decode at all.

    The tie is real: only the report length separates the two candidates, so this function must not
    pretend to break it.
    """
    ours = "2008610800820324021200118012560000000000000000000000000000000040"
    published = [
        "2008610800820324021200118007264200000000000000000000000000000040",  # 0201201G, 16 words
        "2008610800820324021200118006915900000000000000000000000000000040",  # 02012036, 36 words
        "2008610800820324031200118011124100000000000000000000000000000040",  # 0301200n, a cabinet
        "00000000000000008080000000041410",                                  # unrelated family
    ]
    ranked = nearest_bundled_profile(ours, published)

    assert ours not in published                    # no exact match exists
    assert [shared for shared, _ in ranked[:2]] == [26, 26]
    assert ranked[2][0] == 17                       # the cabinet family falls away
    assert ranked[3][0] == 0                        # and an unrelated family shares nothing


# The published write frame, as `canonical_map` records it, plus the two fields no profile
# publishes but hardware settled: the eco ladder (measured by cycling a unit through its levels)
# and localCtrValid (bit 11 is the only high bit ever seen set on hardware, and the device's own
# published values report that attribute true while its neighbours are false).
_WRITE_ANCHORS = {
    n: (f.word, f.bit, f.length) for n, f in CANONICAL_WRITE.items()
} | {"generatorMode": (4, 3, 3), "localCtrValid": (5, 11, 1)}

# Widths for what remains: the shared/rental SKU's own fields, absent from every published profile.
_WIDTHS = {"useMode": 1, "rentTimingStatus": 1, "targetRentTime": 8}


def test_the_write_frame_and_hardware_between_them_leave_only_the_rental_fields() -> None:
    """33 of 38 fields come from the published write frame; two more from hardware; 3 remain.

    Worth separating, because "the published frame places 35" would be false and is the easy thing
    to say. ``generatorMode`` was placed by cycling a unit through its eco levels and ``localCtrValid``
    by reading a bit that is set while its neighbours are clear -- neither is published anywhere.

    Worth stating at all because the gap looks far larger when the wrong map is used as anchors: the
    *report* layout and the *write* layout are different frames, and only one of them answers here.
    What is left over is the shared-rental SKU's own vocabulary, which no published profile carries.
    """
    solved, ambiguous = solve_positions(ATTR_ORDER, _WRITE_ANCHORS, _WIDTHS)
    published = set(CANONICAL_WRITE) & set(ATTR_ORDER)

    assert len(published) == 33                                   # what the models actually state
    ordered = set(_WRITE_ANCHORS) & set(ATTR_ORDER)
    assert sorted(ordered - published) == ["generatorMode", "localCtrValid"]
    assert len(_WRITE_ANCHORS.keys() & set(ATTR_ORDER)) == 35     # published + measured
    assert {a.name for a in ambiguous} == {"useMode", "rentTimingStatus", "targetRentTime"}
    assert not solved            # nothing left over fits exactly; see the containment test below


def test_the_open_fields_cannot_disturb_anything_else() -> None:
    """Each unresolved field is fenced between known anchors, so the doubt goes no further.

    This is what makes the residue tolerable rather than a hole in the map. ``useMode`` sits in four
    bits between two placed fields and ``rentTimingStatus`` in two; wherever inside those windows
    they really are, every other field keeps the position the profile publishes. Only
    ``targetRentTime`` is open-ended, and it has its word to itself.

    They cannot be narrowed further from anything held here: all three read zero in every captured
    report, so a reserved bit and a false flag look identical. Settling them needs a unit in rental
    service, which these are not -- and nothing surfaces them, so it buys nothing.
    """
    _, ambiguous = solve_positions(ATTR_ORDER, _WRITE_ANCHORS, _WIDTHS)
    by_name = {a.name: a for a in ambiguous}

    assert by_name["useMode"].after == Placement(4, 0, 3)        # windDirectionHorizontal
    assert by_name["useMode"].before == Placement(5, 11, 1)      # localCtrValid
    assert by_name["rentTimingStatus"].after == Placement(5, 11, 1)
    assert by_name["rentTimingStatus"].before == Placement(5, 8, 1)   # cloudFilterChangeFlag
    assert by_name["targetRentTime"].before is None              # alone past the last anchor


# Widths from the universal map plus the value ranges the device publishes. The map covers 30 of
# the 38 ordered fields; the rest are the shared/rental SKU's own, which no published profile has.
_UNIVERSAL = {
    "targetTemperature": (1, 8, 8), "windDirectionVertical": (1, 0, 4),
    "operationMode": (2, 13, 3), "specialMode": (2, 11, 2), "windSpeed": (2, 8, 3),
    "energySavePeriod": (2, 0, 8), "tempUnit": (3, 13, 1), "pmvStatus": (3, 12, 1),
    "intelligenceStatus": (3, 11, 1), "halfDegreeSettingStatus": (3, 10, 1),
    "screenDisplayStatus": (3, 9, 1), "10degreeHeatingStatus": (3, 8, 1),
    "echoStatus": (3, 7, 1), "lockStatus": (3, 6, 1), "silentSleepStatus": (3, 5, 1),
    "muteStatus": (3, 4, 1), "rapidMode": (3, 3, 1), "electricHeatingStatus": (3, 2, 1),
    "healthMode": (3, 1, 1), "onOffStatus": (3, 0, 1), "targetHumidity": (4, 8, 8),
    "humanSensingStatus": (4, 6, 2), "windDirectionHorizontal": (4, 0, 3),
    "energySavingStatus": (5, 6, 1), "lightStatus": (5, 5, 1), "selfCleaningStatus": (5, 4, 1),
    "ch2oCleaningStatus": (5, 3, 1), "pm2p5CleaningStatus": (5, 2, 1),
    "humidificationStatus": (5, 1, 1), "freshAirStatus": (5, 0, 1),
}
_WIDTHS = {
    "selfCleaning56Status": 1, "generatorMode": 3, "useMode": 1, "localCtrValid": 1,
    "rentTimingStatus": 1, "cloudFilterChangeFlag": 1, "cleaningTimeStatus": 1,
    "targetRentTime": 8,
}


def test_solver_places_the_eco_field_from_its_neighbours() -> None:
    """Given its width, ``generatorMode``'s position falls out of the order and the neighbours.

    It sits between two mapped fields with exactly three bits between them and is three bits wide,
    so there is one way to lay it out. That it lands on w4.b3 is the check: the eco ladder was
    placed by cycling a real unit through its levels and watching the power draw, and the arithmetic
    reaches the same answer from the published order without seeing any of that.

    The width is supplied, not derived, and deliberately so. A sole unknown in a bounded run *looks*
    like it must be exactly as wide as the run, but that reasoning assumes the run reserves no bits
    -- the very assumption this module refuses to make everywhere else. So the position is derived
    and the width is an input.
    """
    solved, _ = solve_positions(ATTR_ORDER, _UNIVERSAL, _WIDTHS)

    assert solved["generatorMode"] == Placement(word=4, bit=3, length=3)


def test_solver_refuses_the_runs_the_frame_reserves_bits_in() -> None:
    """Where a run has room to spare, nothing in it is placed -- the spare bit could be anywhere.

    One bit above ``selfCleaning56Status`` and four in the rental block. A packing that assumes the
    fields sit flush against one anchor would be plausible and would decode; being wrong about that
    is how a byte map produces confident nonsense, so the run is reported rather than resolved.
    """
    solved, ambiguous = solve_positions(ATTR_ORDER, _UNIVERSAL, _WIDTHS)
    spare = {a.name: a.spare_bits for a in ambiguous}

    assert "selfCleaning56Status" not in solved
    assert spare["selfCleaning56Status"] == 1
    for name in ("useMode", "localCtrValid", "rentTimingStatus"):
        assert name not in solved
        assert spare[name] == 4


def test_one_more_anchor_shrinks_the_rental_block_without_closing_it() -> None:
    """Each anchor narrows the run it falls in; it does not necessarily finish it.

    ``localCtrValid`` is readable from a status report, and adding it cuts the spare room after it
    from four bits to one -- the three flags that follow are now known to within a single reserved
    bit. That is the shape of the whole method: ambiguity is measured in anchors and retires as they
    arrive, and it is honest about the last bit rather than rounding it away. Nothing new is
    *placed*, because one spare bit still admits more than one packing.
    """
    before = {a.name: a.spare_bits for a in solve_positions(ATTR_ORDER, _UNIVERSAL, _WIDTHS)[1]}
    solved, ambiguous = solve_positions(
        ATTR_ORDER, {**_UNIVERSAL, "localCtrValid": (5, 11, 1)}, _WIDTHS
    )
    after = {a.name: a.spare_bits for a in ambiguous}

    assert before["rentTimingStatus"] == 4 and after["rentTimingStatus"] == 1
    assert before["useMode"] == 4 and after["useMode"] == 3
    assert "localCtrValid" not in after            # it is an anchor now, not a question
    assert set(solved) == {"generatorMode"}        # narrower, but still not one answer


def test_the_trailing_field_is_bracketed_open_ended_not_invented() -> None:
    """``targetRentTime`` is last, so nothing bounds it from above and it is not placed.

    Which is right: the extra word our family carries was settled from frame lengths, not from the
    order, and the order alone genuinely cannot say how far past the last anchor a trailing field
    sits. What it does say -- that nothing follows it -- is the part that agreed with the experiment.
    """
    solved, ambiguous = solve_positions(ATTR_ORDER, _UNIVERSAL, _WIDTHS)
    trailing = next(a for a in ambiguous if a.name == "targetRentTime")

    assert "targetRentTime" not in solved
    assert trailing.before is None
    assert trailing.spare_bits is None
    assert trailing.after == Placement(word=5, bit=0, length=1)   # the last mapped field


def test_the_solver_recovers_a_layout_it_was_not_shown() -> None:
    """Round-trip: build a layout, hide some of it, and check what comes back is what was hidden.

    Every other test here checks the solver against positions this project already believed. That
    risks agreeing with itself -- the anchors, the widths and the expected answers all come from the
    same map. Here the layout is invented, so the only thing under test is the arithmetic: fields are
    packed into words, every other one is withheld, and the solver must reproduce the withheld ones
    exactly from its neighbours.

    Only the exactly-filled runs come back, which is the point. A run with room to spare stays open
    however the layout was built, because reserved bits are not recoverable from an ordering.
    """
    layout = {                       # invented, contiguous, no reserved bits
        "a": (1, 12, 4), "b": (1, 8, 4), "c": (1, 4, 4), "d": (1, 0, 4),
        "e": (2, 13, 3), "f": (2, 10, 3), "g": (2, 8, 2), "h": (2, 0, 8),
        "i": (3, 15, 1), "j": (3, 14, 1), "k": (3, 6, 8), "l": (3, 0, 6),
    }
    order = sorted(layout, key=lambda n: (layout[n][0], -layout[n][1]))
    hidden = {"b", "f", "j", "k"}
    anchors = {n: p for n, p in layout.items() if n not in hidden}
    widths = {n: layout[n][2] for n in hidden}

    solved, ambiguous = solve_positions(order, anchors, widths)

    assert order_violations(order, {n: p[:2] for n, p in layout.items()}) == []
    for name in hidden:
        word, bit, length = layout[name]
        assert solved[name] == Placement(word, bit, length), name
    assert not ambiguous            # a contiguous layout leaves nothing open
    assert set(solved) == hidden    # and it never re-places what it was given


def test_a_reserved_bit_stops_the_solver_recovering_the_run() -> None:
    """The same layout with one bit left spare: the run it touches must come back open, not wrong.

    This is the property that makes the solver safe to use on hardware nobody owns. It cannot see a
    reserved bit, so where one exists it must decline rather than shift everything along by one and
    produce a layout that decodes.
    """
    layout = {"a": (1, 12, 4), "b": (1, 8, 4), "c": (1, 0, 4)}    # bits 4-7 of word 1 unused
    order = ["a", "b", "c"]
    solved, ambiguous = solve_positions(order, {"a": layout["a"], "c": layout["c"]}, {"b": 4})

    assert "b" not in solved
    assert [a.name for a in ambiguous] == ["b"]
    assert ambiguous[0].spare_bits == 4
