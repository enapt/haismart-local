"""The shipped rules bundle, and the reason it is not keyed the convenient way."""

import json

from haismart_hrdp.model_rules import (
    known_products,
    products_for_uplus_id,
    rules_for_product,
)

OUR_UPLUS_ID = "2008610800820324021200118012560000000000000000000000000000000040"


def test_our_own_model_carries_the_counts_the_published_model_states() -> None:
    """Every section is present at the size the published model gives -- 6, 10, 52, 39, 25.

    Sizes, not contents. The bundle is deliberately **not** section-for-section identical to what
    the cloud returns: the manufacturer's fault descriptions and lock explanations are stripped and
    the reason wording is this project's own, because none of that prose was ever read. What has to
    survive is the structure the decode and the availability logic index into, which is what these
    counts stand for. A change here means the bundle drifted from the published model, not that the
    numbers need updating.
    """
    rules = rules_for_product("AAC1UKZ01")
    assert rules is not None
    assert rules["model"] == "HSU-24VRRA03TF"
    assert len(rules["modifiers"]) == 6
    assert len(rules["constraints"]) == 10
    assert len(rules["alarms"]) == 52
    assert len(rules["attributes"]) == 39
    # attributes keep the published shape, `invisible` included: that flag is what separates a
    # generic model over-declaring a product line from the features this unit really has, and
    # nothing else publishes it.
    assert sum(1 for a in rules["attributes"] if a.get("invisible")) == 25
    assert set(rules["invalid_reasons"]) >= {"50001", "50002"}


def test_bundle_covers_the_published_line_and_refuses_the_unknown() -> None:
    # Every air conditioner published in any of the 100 regions the setup form offers. It was 171
    # for a long time -- which was one region's catalogue, the endpoint being scoped by the country
    # code an account signed in with, and every sweep here having used the same account.
    assert len(known_products()) == 1435
    assert rules_for_product("NOSUCHCODE") is None
    assert rules_for_product(None) is None


def test_uplus_id_narrows_to_a_family_but_cannot_choose_within_it() -> None:
    """Why the bundle is keyed by product and not by the id a unit actually announces.

    Our uPlusId covers 186 products. If rules were keyed on it, one of those rule sets would have to
    stand for all of them -- and they genuinely differ, so a unit would be locked or unlocked on
    evidence about different hardware. This test pins the disagreement so the shortcut stays closed.
    (It was 23 while the bundle held one region's catalogue; the identifier did not change, the
    coverage did.)
    """
    family = products_for_uplus_id(OUR_UPLUS_ID)
    assert "AAC1UKZ01" in family
    assert len(family) == 186

    shapes = {
        (len(r["modifiers"]), len(r["constraints"]))
        for code in family
        if (r := rules_for_product(code)) and "modifiers" in r
    }
    assert len(shapes) > 1, "members disagree; a single family-wide rule set would be wrong"

    modifiers = [
        {json.dumps(m, sort_keys=True) for m in (rules_for_product(c) or {}).get("modifiers", [])}
        for c in family
    ]
    assert not set.intersection(*modifiers), "not one modifier is shared by every member"


def test_unknown_uplus_id_yields_no_family() -> None:
    assert products_for_uplus_id("deadbeef") == []
    assert products_for_uplus_id(None) == []


def test_family_rules_are_correct_whichever_model_it_turns_out_to_be() -> None:
    """Where the model cannot be known, apply what every candidate agrees on.

    A unit announces its family, not its model, and many of our family's members are locally
    indistinguishable -- same declared attributes, same visible set -- while still carrying
    different rules. So no observation can pick one, and the honest floor is the agreed subset.

    The floor is lower than it was: with one region's catalogue every fault name was common to every
    member of every family, and across all regions it is 99% of them, with one family agreeing on no
    lock explanation at all. What the test pins is the property that makes the floor *safe* rather
    than its height -- nothing is kept that any member contradicts.
    """
    from haismart_hrdp.model_rules import (
        family_rules,
        products_for_uplus_id,
        rules_for_product,
    )

    uplus = "2008610800820324021200118012560000000000000000000000000000000040"
    agreed = family_rules(uplus)
    members = [rules_for_product(p) for p in products_for_uplus_id(uplus)]
    assert len(members) == 186

    # every rule kept must appear in every member -- that is what makes it safe to apply blind
    for section in ("alarms", "invalid_reasons", "constraints", "modifiers"):
        for rule in agreed[section]:
            for member in members:
                assert rule in (member.get(section) or []), (
                    f"{section} rule kept that member {member.get('model')} does not have"
                )

    # the part users actually see survives in full
    assert len(agreed["alarms"]) == 52
    assert len(agreed["invalid_reasons"]) == 9
    # and the conservative direction on features: invisible if ANY member says so, so a control is
    # never offered for hardware some member of the family lacks
    invisible = {a["name"] for a in agreed["attributes"] if a.get("invisible")}
    for member in members:
        for attr in member["attributes"]:
            if attr.get("invisible"):
                assert attr["name"] in invisible


def test_family_rules_gives_a_single_model_family_its_own_rules() -> None:
    """No intersection to take when there is nothing to intersect with."""
    from haismart_hrdp.model_rules import (
        _bundle,
        family_rules,
        products_for_uplus_id,
        rules_for_product,
    )

    solo = next(
        (u for u in _bundle()["by_uplus_id"] if len(products_for_uplus_id(u)) == 1), None
    )
    assert solo, "expected at least one single-model family"
    assert family_rules(solo) == rules_for_product(products_for_uplus_id(solo)[0])
    assert family_rules("nonexistent") is None
