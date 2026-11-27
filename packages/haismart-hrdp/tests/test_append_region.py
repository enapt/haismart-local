"""A twin-tower family writes its APPLIANCE's own vane and fan in the append region.

The shared frame's vane and fan slots belong to those cabinets' **left tower**, so writing there
moves the wrong flow -- which is why ``displaced_write_fields`` refuses them. Extended-46 recovers
the controls from its own registered map, where the append-region positions are capture-confirmed.
Families that publish the *same* order but are registered to no wire family had nowhere to be
offered from and lost swing and fan speed entirely; ``TAIL_POSITIONS`` is where they get them.
"""
from __future__ import annotations

import pytest

from haismart_hrdp import model_rules
from haismart_hrdp.family_write import TAIL_POSITIONS, displaced_write_fields
from haismart_hrdp.wire_models import (
    _EXT46_WRITE,
    frame_write_fields,
    related_wire_model,
)

# The confirmed family: extended-46, whose append-region positions read back at report words 25/26.
CONFIRMED_FAMILY = "20086108008203240212001180177400"
CONFIRMED_PRODUCT = "AAAHD5007"
ANCHORS = ("windDirectionVertical", "windSpeed")


def _order(product: str) -> list[str]:
    rules = model_rules.rules_for_product(product) or {}
    for command in rules.get("groupCommands") or ():
        if command.get("name") == "grSetDAC":
            return [str(n) for n in command.get("attrNameList") or ()]
    raise AssertionError(f"{product} publishes no grSetDAC order")


def _uplus(product: str) -> str:
    return str((model_rules.rules_for_product(product) or {})["uplus_id"])


@pytest.mark.parametrize("family", sorted(TAIL_POSITIONS))
def test_an_appended_vane_and_fan_are_offered_from_the_append_region(family: str) -> None:
    """The whole point: these products get swing and fan speed, at the appended positions."""
    product = model_rules.products_for_uplus_id(family + "0" * 30 + "40")[0]
    offered = frame_write_fields(_order(product), _uplus(product))
    for name in ANCHORS:
        assert name in offered, f"{family} lost {name}"
        field = offered[name]
        assert (field.word, field.bit, field.length) == TAIL_POSITIONS[family][name]
        assert field.word > 5, "an appended field must sit past the frame's five words"


@pytest.mark.parametrize("family", sorted(TAIL_POSITIONS))
def test_an_appended_field_is_not_refused_under_its_own_name(family: str) -> None:
    """A reuse is a fact about a POSITION, not a name -- the v0.50.1 regression, restated.

    These families keep the left tower at the shared vane/fan slots, so both names are in the
    name-keyed refusal set. The field is nonetheless written somewhere that set never describes,
    and refusing it there costs the appliance its two most-used controls.
    """
    product = model_rules.products_for_uplus_id(family + "0" * 30 + "40")[0]
    refused = displaced_write_fields(_uplus(product))
    assert set(ANCHORS) <= refused, "precondition: the shared slots are the tower's"
    assert set(ANCHORS) <= set(frame_write_fields(_order(product), _uplus(product)))


@pytest.mark.parametrize("family", sorted(TAIL_POSITIONS))
def test_the_op_runs_far_enough_to_carry_an_appended_field(family: str) -> None:
    """``word_count = 5`` stopping the frame before word 6 is what made extended-46's vane
    unreachable (v0.47.0). A frame that does not reach the field cannot write it."""
    product = model_rules.products_for_uplus_id(family + "0" * 30 + "40")[0]
    model = related_wire_model(209, 0, order=_order(product), uplus_id=_uplus(product))
    assert model.word_count >= max(w for w, _, _ in TAIL_POSITIONS[family].values())


@pytest.mark.parametrize("family", sorted(TAIL_POSITIONS))
def test_a_listed_family_publishes_the_CONFIRMED_family_s_order_through_its_anchors(
    family: str,
) -> None:
    """The evidence for the transfer, kept where it cannot rot.

    A position is only carried over from the confirmed family when this family's published order is
    identical to it *through the anchors* -- same attributes, same indices -- because the packing
    that puts those anchors on those bits is the order itself. Adding a family to
    ``TAIL_POSITIONS`` without that agreement fails here.
    """
    confirmed = _order(CONFIRMED_PRODUCT)
    product = model_rules.products_for_uplus_id(family + "0" * 30 + "40")[0]
    order = _order(product)
    last = max(confirmed.index(name) for name in ANCHORS)
    assert order[: last + 1] == confirmed[: last + 1], (
        f"{family} diverges from the confirmed order before its anchors"
    )


@pytest.mark.parametrize("family", sorted(TAIL_POSITIONS))
def test_a_listed_position_is_the_confirmed_family_s_own(family: str) -> None:
    """Nothing here is derived: each position is the one extended-46 was confirmed at."""
    for name, position in TAIL_POSITIONS[family].items():
        confirmed = _EXT46_WRITE[name]
        assert (confirmed.word, confirmed.bit, confirmed.length) == position


def _report_length(uplus: str) -> int:
    """A full status report's length by the product's own map: base 92, two bytes a word, checksum."""
    from haismart_hrdp.device_model import model_for

    words = max(f.word for f in model_for(uplus).fields if (f.status_cmd or "").upper() == "6D01")
    return 92 + 2 * words + 1


@pytest.mark.parametrize("family", sorted(TAIL_POSITIONS))
def test_a_listed_family_writes_its_fan_with_its_own_map_s_codes(family: str) -> None:
    """Through the model each family's report ACTUALLY selects. Each listed family's own byte map
    puts the fan at report word 26 bit 8, three bits, high 2 / medium 4 / low 6 / auto 0 --
    extended-46's exactly. The 209-byte family (``…133000…``, 108 products) is matched to
    extended-46 itself by its length; only the 231-byte one (``…204042…``) takes a related layout,
    where the tail position applies -- with extended-46's encoding, not the shared frame's identity
    table, which sent auto as 5 one bit up (high, with ``oxgyenSupplyMode`` on)."""
    from haismart_hrdp.device_model import model_for
    from haismart_hrdp.wire_models import select_wire_model

    uplus = family + "0" * 30 + "40"
    haier = next(f for f in model_for(uplus).fields
                 if f.name == "windSpeed" and f.status_cmd == "6D01")
    published = {v["stdValue"]: v["eppValue"] for v in haier.variants}
    product = model_rules.products_for_uplus_id(uplus)[0]
    length = _report_length(uplus)
    # The map's climate block starts at word 20 on both, so a related layout sits at displacement 0.
    model = select_wire_model(length, uplus) or related_wire_model(
        length, 0, order=_order(product), uplus_id=_uplus(product)
    )
    fan = model.write_fields["windSpeed"]
    assert (model.write_base_word + fan.word - 1, fan.bit, fan.length) == (
        haier.word, haier.bit, haier.length
    )
    # every product of both families declares exactly these four speeds
    assert {std: fan.std_to_epp[std] for std in (1, 2, 3, 5)} == {
        std: published[std] for std in (1, 2, 3, 5)
    }


def test_which_listed_family_actually_uses_the_tail_positions() -> None:
    """Measured, because the record once said all 109 products did: the 209-byte family's reports
    select extended-46 by length (its read included), and only the one 231-byte product decodes as a
    related layout."""
    from haismart_hrdp.wire_models import EXTENDED46, select_wire_model

    by_length = {
        family: select_wire_model(_report_length(family + "0" * 30 + "40"), family + "0" * 30 + "40")
        for family in TAIL_POSITIONS
    }
    assert by_length == {
        "20086108008203240212001180133000": EXTENDED46,
        "20086108008203240312001180204042": None,
    }


def test_the_confirmed_family_is_not_itself_listed() -> None:
    """Extended-46 carries these positions in its registered map; listing it too would be two
    sources for one fact, and they could drift apart."""
    assert CONFIRMED_FAMILY not in TAIL_POSITIONS


def test_a_single_flow_family_still_writes_the_shared_slots() -> None:
    """The shared frame is untouched: a unit whose vane really is at w1.b0 keeps it there."""
    product = "AAC1UKZ01"
    offered = frame_write_fields(_order(product), _uplus(product))
    assert (offered["windDirectionVertical"].word, offered["windDirectionVertical"].bit) == (1, 0)
    assert (offered["windSpeed"].word, offered["windSpeed"].bit) == (2, 8)
