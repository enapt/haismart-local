"""Deriving wire positions from the order a device publishes its own group-set in.

A device's constraintfile carries ``groupCommands[].attrNameList`` -- the attributes its group-set
command writes. That list is not arbitrary: it is ordered by **word ascending, then bit descending**,
which is to say it *is* the wire layout, enumerated. Checked against every position we have measured
on real hardware (16 anchors spanning four words): the order matches exactly, with no violations.

Why that matters. A byte map is published only for the models bundled in the vendor app, and a unit
whose model is not bundled has no map to look up -- our own units are such a case. But the
constraintfile is fetched *per device*, by uPlusId, and every device has one. So the ordering is
available for hardware no map covers, which is precisely where it is needed.

The order alone does not give positions; widths do that, and a width cannot be read off an
attribute's value range (``targetTemperature`` spans 15 values and occupies 8 wire bits). What the
order does give is a **total ordering constraint**: between two attributes whose positions are known,
every attribute listed between them lies between them on the wire. Anchors come from a bundled
relative or from measurement, and the gaps resolve against them.

Independent check on our own units: the list ends at ``targetRentTime``, and the extra word our
family carries past its nearest bundled relative -- established by experiment, from frame lengths --
is ``targetRentTime`` at w6. The published order predicts it without being told.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

__all__ = [
    "Position",
    "order_key",
    "order_violations",
    "bracket_unplaced",
    "nearest_bundled_profile",
]

Position = tuple[int, int]
"""A ``(word, bit)`` pair. ``bit`` is the field's least significant bit, as everywhere else here."""


def order_key(pos: Position) -> tuple[int, int]:
    """Sort key putting positions in published order: word ascending, bit descending."""
    word, bit = pos
    return (word, -bit)


def order_violations(
    attr_names: Sequence[str], known: Mapping[str, Position]
) -> list[tuple[str, str]]:
    """Pairs of consecutive *known* attributes that contradict the published order.

    An empty result means the layout agrees with the order the device publishes. This is the check
    to run before trusting :func:`bracket_unplaced` on an unfamiliar family -- the ordering rule was
    verified on the classic family, and a family that departs from it should say so loudly rather
    than quietly yield wrong positions.
    """
    placed = [(n, known[n]) for n in attr_names if n in known]
    return [
        (placed[i][0], placed[i + 1][0])
        for i in range(len(placed) - 1)
        if order_key(placed[i][1]) > order_key(placed[i + 1][1])
    ]


def bracket_unplaced(
    attr_names: Sequence[str], known: Mapping[str, Position]
) -> dict[str, tuple[Position | None, Position | None]]:
    """For each attribute with no known position, the positions it must lie strictly between.

    Returns ``{name: (after, before)}`` in wire order -- ``after`` is the nearest preceding anchor
    and ``before`` the nearest following one, either being ``None`` at the ends of the list. A
    bracket is a constraint, not a placement: it narrows a candidate to a handful of bits, and
    something that observes the unit still has to choose among them. Deliberately no guess is made
    here, because a plausible position that is wrong is worse than none -- it decodes.
    """
    out: dict[str, tuple[Position | None, Position | None]] = {}
    for index, name in enumerate(attr_names):
        if name in known:
            continue
        after = next(
            (known[n] for n in reversed(attr_names[:index]) if n in known),
            None,
        )
        before = next((known[n] for n in attr_names[index + 1 :] if n in known), None)
        out[name] = (after, before)
    return out


def nearest_bundled_profile(uplus_id: str, candidates: Iterable[str]) -> list[tuple[int, str]]:
    """Rank published profile ids by how much of their uPlusId they share with ``uplus_id``.

    The vendor app resolves a device to a profile by **prefix**, not by exact match, which is how a
    unit whose full uPlusId appears nowhere still gets a working panel: the leading characters
    identify the family and only the trailing per-model serial differs. Ours shares 26 characters
    with two published profiles and matches neither exactly.

    Returns ``(shared_prefix_length, id)`` best first. A tie is normal and is not resolved here --
    our own unit ties at 26 between a 16-word and a 36-word profile, and only the report length
    tells them apart. Callers should treat this as candidate generation and let something that has
    seen a real frame decide.
    """
    ranked = []
    for candidate in candidates:
        shared = 0
        # strict=False on purpose: ids differ in length (32 hex for E++1.x, 64 for 2.x) and the
        # comparison is a prefix, so running out of one string simply ends the match.
        for a, b in zip(uplus_id, candidate, strict=False):
            if a != b:
                break
            shared += 1
        ranked.append((shared, candidate))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return ranked
