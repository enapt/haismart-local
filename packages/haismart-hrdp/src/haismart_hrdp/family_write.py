"""Where a product family's group-set frame departs from the shared one.

The group-set frame is otherwise invariant: every published air-conditioner device type places the
same 39 attributes at the same word, bit and width, with **no** displacement between families (see
:mod:`haismart_hrdp.canonical_map`, ``CANONICAL_WRITE``). A handful of families nonetheless put a
*different attribute* at one of those positions -- a twin-tower cabinet writes its **left tower's**
vane and fan where a single-flow unit writes the appliance's, and some later models reuse two flag
bits for other functions.

That matters because a group-set is packed by position. Sending "swing on" to a family that keeps
``windDirectionVerticalL`` at that nibble moves one tower, and sending "self-clean" to a family that
keeps ``sterilizationSwitch`` at that bit starts a **different cycle entirely**. So the affected
fields are refused rather than sent to the wrong function.

Derived from the published models: for every product that publishes a group-set command, its ordered
attribute list is anchored on the shared frame and the gaps solved by exact fit. Every deviation
below is **unanimous across every member of its family** -- no family disagrees with itself -- which
is what makes it safe to key on the identifier an appliance announces for itself.

⚠️ Positions here are **group-set** words, not report words. A family converts between them with its
own base word (``20 + canonical displacement``).
"""
from __future__ import annotations

from collections.abc import Mapping

__all__ = ["WRITE_OVERRIDES", "ALIASES", "write_overrides", "displaced_write_fields"]

#: ``{uPlusId: {attribute: (word, bit, length)}}`` -- group-set positions this family uses that the
#: shared frame does not give that attribute.
WRITE_OVERRIDES: Mapping[str, Mapping[str, tuple[int, int, int]]] = {
    # 108 published products in this family
    "2008610800820324021200118013300000000000000000000000000000000040": {
        "sterilizationSwitch": (5, 4, 1),
        "windDirectionVerticalL": (1, 0, 4),
        "windDirectionVerticalR": (1, 4, 4),
        "windSpeedL": (2, 8, 3),
    },
    # 44 published products in this family
    "2008610800820324021200118017740000000000000000000000000000000040": {
        "sterilizationSwitch": (5, 4, 1),
        "windDirectionVerticalL": (1, 0, 4),
        "windDirectionVerticalR": (1, 4, 4),
        "windSpeedL": (2, 8, 3),
    },
    # 37 published products in this family
    "2008610800820324021200118018900000000000000000000000000000000040": {
        "drying": (5, 13, 1),
        "generatorMode": (4, 3, 3),
        "manualDefrosting": (5, 12, 1),
        "mouldProof": (5, 14, 1),
        "preventHeatstroke": (5, 15, 1),
    },
    # 29 published products in this family
    "2008610800820324021200118016750000000000000000000000000000000040": {
        "drying": (5, 13, 1),
        "generatorMode": (4, 3, 3),
        "manualDefrosting": (5, 12, 1),
        "mouldProof": (5, 14, 1),
        "preventHeatstroke": (5, 15, 1),
    },
    # 17 published products in this family
    "20086108008203240d2100118019160000000000000000000000000000000040": {
        "careMode": (2, 11, 2),
        "drying": (5, 13, 1),
        "manualDefrosting": (5, 12, 1),
        "mouldProof": (5, 14, 1),
        "preventHeatstroke": (5, 15, 1),
        "tenDegreeHeatingStatus": (3, 8, 1),
    },
    # 5 published products in this family
    "2008610800820324021200118015970000000000000000000000000000000040": {
        "generatorMode": (4, 3, 3),
    },
    # 5 published products in this family
    "2008610800820324031200118017370000000000000000000000000000000040": {
        "sterilizationSwitch": (5, 4, 1),
        "windDirectionVerticalL": (1, 0, 4),
        "windDirectionVerticalR": (1, 4, 4),
        "windSpeedL": (2, 8, 3),
    },
    # 2 published products in this family
    "2008610800820324021400000000000000000000000000000000000000000040": {
        "windDirectionVerticalL": (1, 0, 4),
        "windDirectionVerticalR": (1, 4, 4),
    },
    # 2 published products in this family
    "20086108008203240214b1fa7e03d700000046e4f3fc6a77178e84b94da30040": {
        "windDirectionVerticalL": (1, 0, 4),
        "windDirectionVerticalR": (1, 4, 4),
    },
    # 2 published products in this family
    "20086108008203240d2100118018944800000000000000000000000000000040": {
        "tenDegreeHeatingStatus": (3, 8, 1),
        "windDirectionVerticalL": (1, 0, 4),
        "windDirectionVerticalR": (1, 4, 4),
    },
    # 1 published products in this family
    "2008610800820324031200118020404200000000000000000000000000000040": {
        "sterilizationSwitch": (5, 4, 1),
        "windDirectionVerticalL": (1, 0, 4),
        "windDirectionVerticalR": (1, 4, 4),
        "windSpeedL": (2, 8, 3),
    },
    # 1 published products in this family
    "20086108008203240d2101518006484700000000000000000000000000000040": {
        "tenDegreeHeatingStatus": (3, 8, 1),
        "windDirectionVerticalL": (1, 0, 4),
        "windDirectionVerticalR": (1, 4, 4),
        "windSpeedL": (2, 8, 3),
    },
}

#: Pairs that are the same function under two spellings. A family using the newer name at the older
#: name's position has not moved anything, so nothing is refused.
ALIASES: Mapping[str, str] = {
    "tenDegreeHeatingStatus": "10degreeHeatingStatus",
}


def write_overrides(uplus_id: str | None) -> Mapping[str, tuple[int, int, int]]:
    """This family's departures from the shared group-set frame, or ``{}`` for a family with none
    (which is almost all of them) and for an appliance that has not named itself."""
    return WRITE_OVERRIDES.get(uplus_id or "", {})


def displaced_write_fields(uplus_id: str | None) -> frozenset[str]:
    """Shared-frame attributes this family keeps a **different** attribute at.

    Writing one of these would pack the requested value into a bit that does something else on this
    hardware, so the caller must refuse it. An alias pair is not a displacement.
    """
    from .canonical_map import CANONICAL_WRITE

    overrides = write_overrides(uplus_id)
    if not overrides:
        return frozenset()
    taken: dict[tuple[int, int, int], set[str]] = {}
    for name, pos in overrides.items():
        taken.setdefault(tuple(pos), set()).add(name)
    out: set[str] = set()
    for name, field in CANONICAL_WRITE.items():
        here = taken.get((field.word, field.bit, field.length))
        if not here:
            continue
        if all(ALIASES.get(other) == name for other in here):
            continue                      # same function, newer spelling
        out.add(name)
    return frozenset(out)
