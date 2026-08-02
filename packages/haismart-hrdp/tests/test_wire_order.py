"""The published group-set order, checked against hardware-measured positions."""

from haismart_hrdp.wire_order import (
    bracket_unplaced,
    nearest_bundled_profile,
    order_violations,
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

    That is how the vendor app renders a full panel for a unit whose model it does not bundle -- and
    why exact-match comparison wrongly concludes the unit is unknown. The tie is real: only the
    report length separates the two candidates, so this function must not pretend to break it.
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
