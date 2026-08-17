"""Deriving wire positions from the order a device publishes its own group-set in.

A device's constraintfile carries ``groupCommands[].attrNameList`` -- the attributes its group-set
command writes. That list is not arbitrary: it is ordered by **word ascending, then bit descending**,
which is to say it *is* the wire layout, enumerated. Checked against every position we have measured
on real hardware (16 anchors spanning four words): the order matches exactly, with no violations.

Why that matters. A byte map is published only for some models, and a unit whose own identifier is
not among them has no map to look up -- our own units are such a case, and the manufacturer's own
software simply does without a local decode for them. But the constraintfile is fetched *per
device*, and every device has one. So the ordering is available for hardware no map covers, which is
precisely where it is needed.

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
from dataclasses import dataclass

__all__ = [
    "Ambiguity",
    "Placement",
    "Position",
    "order_key",
    "order_violations",
    "consistent_with_frame",
    "bracket_unplaced",
    "nearest_bundled_profile",
    "solve_positions",
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


def consistent_with_frame(
    attr_names: Sequence[str], known: Mapping[str, Position]
) -> frozenset[str] | None:
    """The known-position names this order corroborates -- or ``None`` when it refutes the frame.

    :func:`order_violations` reports that a contradiction exists; this decides what to do about
    each name, because the two realistic shapes of contradiction call for different answers:

    * **An appended tail.** A family that moved a handful of attributes lists them *after* the
      original frame -- extended-46 and its twin-tower relatives put the appliance's own vane, fan
      and horizontal vane past the towers, in words the shared frame does not reach. The head of
      the order still matches the frame exactly, so the head's names are corroborated and only the
      moved names are dropped.
    * **No relation at all.** A family whose order cannot be reconciled with the frame anywhere is
      not an instance of it, and no position taken from the frame can be trusted there. That is
      ``None``: the caller must offer nothing rather than pick survivors from a premise the order
      as a whole has refuted.

    Mechanically: the longest run of names whose positions are monotonic in published order
    (:func:`order_key`) is the frame-consistent backbone. A name is corroborated only when **every**
    such longest run keeps it -- two names that could each be the misplaced one of a pair are both
    dropped, because choosing between them would be a guess and a guessed write position runs the
    wrong function instead of failing. And the appended-tail shape is required for partial trust:
    if any dropped name sits *before* the last corroborated one, the disagreement is structural,
    not appended, and the whole order refutes the frame.

    An empty ``known`` yields an empty set -- nothing corroborated, nothing refuted.
    """
    placed = [(name, known[name]) for name in attr_names if name in known]
    if not placed:
        return frozenset()
    keys = [order_key(pos) for _, pos in placed]
    n = len(placed)
    ending = [1] * n      # longest monotonic run ending at i
    starting = [1] * n    # longest monotonic run starting at i
    for i in range(n):
        for j in range(i):
            if keys[j] <= keys[i]:
                ending[i] = max(ending[i], ending[j] + 1)
    for i in reversed(range(n)):
        for j in range(i + 1, n):
            if keys[i] <= keys[j]:
                starting[i] = max(starting[i], starting[j] + 1)
    longest = max(ending[i] + starting[i] - 1 for i in range(n))
    on_backbone = [i for i in range(n) if ending[i] + starting[i] - 1 == longest]
    at_rank: dict[int, int] = {}
    for i in on_backbone:
        at_rank[ending[i]] = at_rank.get(ending[i], 0) + 1
    corroborated = {i for i in on_backbone if at_rank[ending[i]] == 1}
    dropped = [i for i in range(n) if i not in corroborated]
    if dropped and corroborated:
        last = max(corroborated)
        if any(i < last for i in dropped):
            return None
    elif dropped:
        return None
    return frozenset(placed[i][0] for i in corroborated)


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

    Identifiers that share a long prefix belong to the same product family, differing only in a
    trailing per-model serial, and a family shares one layout -- so a device whose own identifier is
    published nowhere can still be decoded from a relative's map. Ours shares 26 characters with two
    published profiles and matches neither exactly.

    ⚠️ **This is our heuristic, not the manufacturer's.** Their own lookup opens the identifier as a
    filename, once, and gives up: no retry, no alternate name, no nearest match. A device it cannot
    find that way simply gets no local decode and is rendered from cloud-reported values instead.
    What licenses reading a relative's map is not that anyone else does it -- it is that every
    published model for this appliance class is the same map at a whole-word offset, so a family
    member's layout is the family's layout.

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


@dataclass(frozen=True)
class Placement:
    """A field's derived position: ``word``/``bit``/``length``, matching the published maps."""

    word: int
    bit: int
    length: int


@dataclass(frozen=True)
class Ambiguity:
    """A field the order brackets but does not pin down, and by how much it falls short.

    ``spare_bits`` is the room left over once every field in the run has taken its stated width.
    Zero means the run packs exactly and would have been solved; anything above zero means the
    frame reserves bits somewhere inside the run, and where they sit is not recoverable from the
    order alone. Resolving one is a matter of one more anchor, not more inference.
    """

    name: str
    after: Placement | None
    before: Placement | None
    spare_bits: int | None


def _to_index(word: int, bit: int, length: int, word_bits: int) -> int:
    """Position as a most-significant-first scan index, which is the order fields are published in."""
    return word * word_bits + word_bits - bit - length


def _from_index(index: int, length: int, word_bits: int) -> Placement:
    word, offset = divmod(index, word_bits)
    return Placement(word, word_bits - offset - length, length)


def solve_positions(
    attr_names: Sequence[str],
    anchors: Mapping[str, tuple[int, int, int]],
    widths: Mapping[str, int],
    *,
    word_bits: int = 16,
) -> tuple[dict[str, Placement], list[Ambiguity]]:
    """Place the fields a map does not cover, from the order the device publishes them in.

    The published order is the wire order, so between two fields whose positions are known, every
    field listed between them lies between them -- in that order, with no gaps of its own choosing.
    That turns a run of unknowns into arithmetic: their widths must fit the bits the two anchors
    leave, and where the fit is exact there is precisely one way to lay them out.

    Where the fit is *not* exact the run is reported as ambiguous instead of placed. The frame
    reserves bits -- our own units leave one spare above ``selfCleaning56Status`` and four in the
    rental block -- and a reserved bit is invisible to this arithmetic: the run could be packed
    against either anchor or split anywhere between. A guess would not fail loudly, it would decode,
    which is the worst way to be wrong about a byte map. One further anchor collapses a run
    completely, and anchors are cheap: a read of a unit in a known state produces them.

    ``anchors`` and ``widths`` are ``{name: (word, bit, length)}`` and ``{name: length}``; a name in
    neither is bracketed with ``spare_bits`` unknown. Returns the placements derived here -- anchors
    are not echoed back -- and every ambiguity, in wire order.
    """
    placed: dict[str, Placement] = {}
    ambiguous: list[Ambiguity] = []
    run: list[str] = []
    cursor: int | None = None          # first free index after the last anchor
    previous: Placement | None = None

    def flush(next_anchor: Placement | None, next_index: int | None) -> None:
        if not run:
            return
        sized = [(n, widths.get(n)) for n in run]
        room = None if (cursor is None or next_index is None) else next_index - cursor
        needed = sum(w for _, w in sized if w is not None)
        # An exact fit is the only case with one answer: every field in the run takes its width,
        # in order, leaving nothing over to hide a reserved bit in.
        if room is not None and all(w is not None for _, w in sized) and needed == room:
            at = cursor or 0
            for name, width in sized:
                assert width is not None
                if at % word_bits + width > word_bits:      # would straddle a word; not a layout
                    break
                placed[name] = _from_index(at, width, word_bits)
                at += width
            else:
                return
            for name, _ in sized:                            # straddled: nothing in the run stands
                placed.pop(name, None)
        spare = None if room is None else room - needed
        for name, _ in sized:
            ambiguous.append(Ambiguity(name, previous, next_anchor, spare))

    for name in attr_names:
        if name in anchors:
            word, bit, length = anchors[name]
            index = _to_index(word, bit, length, word_bits)
            here = Placement(word, bit, length)
            flush(here, index)
            run = []
            cursor = index + length
            previous = here
        else:
            run.append(name)
    flush(None, None)
    return placed, ambiguous
