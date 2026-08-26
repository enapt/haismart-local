"""The shipped rules bundle, and the reason it is not keyed the convenient way."""

import json

from haismart_hrdp.model_rules import (
    _bundle,
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
    # Every air conditioner published in any region, in any of the four categories the manufacturer
    # files them under. The count has been wrong twice, each time because a sweep parameter was
    # mistaken for a property of the data: 171 was ONE REGION's catalogue (the listing is scoped by
    # the country code an account signs in with), and 1435 was three CATEGORY codes chosen by hand,
    # which omitted window air conditioners entirely.
    #
    # So this asserts a floor and the two things that were actually wrong, not an exact number --
    # a number that only a re-sweep can change is a test of the sweep, not of the bundle.
    products = known_products()
    assert len(products) >= 1451
    # window air conditioners: the category the hand-written filter missed
    assert "AD0RF0E00" in products
    # a central unit from the brand the same filter dropped
    assert "AE2S01Q00" in products
    assert rules_for_product("NOSUCHCODE") is None
    assert rules_for_product(None) is None


def test_every_product_is_reachable_through_its_own_family() -> None:
    """The family index is derived from the products, so it must never lag behind them.

    It did. The index is stored alongside the entries rather than computed from them, and a merge
    that added products rewrote the entries while leaving the index as it was -- so sixteen
    products carried a `uplus_id` that led nowhere. Two of the resulting families were absent
    entirely, window air conditioners among them.

    That is worse than a missing lookup in two ways. The model shortlist is narrowed by family, so
    those products could never be offered to the owner of one; and `family_rules` keeps what every
    member agrees on, which means an unindexed member's disagreement was not counted -- the index
    going stale quietly loosens a check whose whole purpose is to be conservative.
    """
    bundle = _bundle()
    indexed = {code for codes in bundle["by_uplus_id"].values() for code in codes}
    expected = {c for c, e in bundle["models"].items() if e.get("uplus_id")}
    assert indexed == expected, "the family index disagrees with the entries it is built from"

    # and every entry is filed under the family it actually names
    for uplus, codes in bundle["by_uplus_id"].items():
        for code in codes:
            assert bundle["models"][code]["uplus_id"] == uplus

    # the two families the stale index had lost, named so a regression is legible
    assert products_for_uplus_id(
        "2008610800820324391200118019024500000000000000000000000000000040"
    ) == ["AD0RF0E00", "AD0RG0E00"]


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


def test_family_agreed_lock_explanations_keep_their_sentences() -> None:
    """``invalid_reasons`` is a mapping (code -> sentence), and the family floor must stay one.

    The intersection helper iterates each section, and iterating a mapping yields bare keys -- so
    the agreed rules once shipped this section as a **list of codes** with every sentence dropped,
    and ``lock_reasons`` (which formats the mapping) crashed at entity setup on any install that
    fell back to family rules. Agreement is on the codes -- the code is the fact, the sentence is
    presentation -- and the wording comes from the first rulebook that carries it.
    """
    from haismart_hrdp.model_rules import (
        family_rules,
        products_for_uplus_id,
        rules_for_product,
    )

    uplus = "2008610800820324021200118017740000000000000000000000000000000040"
    agreed = family_rules(uplus)
    reasons = agreed["invalid_reasons"]
    assert isinstance(reasons, dict) and reasons
    members = [rules_for_product(p) for p in products_for_uplus_id(uplus)]
    for code, sentence in reasons.items():
        assert sentence, f"code {code} kept with its sentence dropped"
        assert all(code in (m.get("invalid_reasons") or {}) for m in members)


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


def test_a_model_number_shared_by_products_that_disagree_resolves_to_nothing() -> None:
    """A number on a label is not a unique key, and a tie must not be broken by luck.

    Across one region's catalogue every model number named exactly one product, and this module said
    so. Across every region, 21 numbers name two or three -- and 15 of those sets disagree about
    their rules, so the dict that used to hold one code per number was silently choosing a rulebook.
    Where the candidates agree the answer is still an answer; where they differ there is none, and
    the family fallback covers it.
    """
    from haismart_hrdp.model_rules import _by_model, product_for_model, rules_for_product

    shared = {m: c for m, c in _by_model().items() if len(c) > 1}
    assert shared, "fixture assumes the bundle spans regions, where numbers do collide"

    def shape(code: str) -> str:
        r = rules_for_product(code) or {}
        return json.dumps({s: r.get(s) for s in
                           ("modifiers", "constraints", "alarms", "invalid_reasons")}, sort_keys=True)

    refused = agreed = 0
    for number, codes in shared.items():
        answer = product_for_model(number)
        if len({shape(c) for c in codes}) == 1:
            assert answer in codes, "candidates agree, so either is the same answer"
            agreed += 1
        else:
            assert answer is None, f"{number} names {codes}, which disagree -- no answer to give"
            refused += 1
    assert refused and agreed, (refused, agreed)

    # an unambiguous number still resolves, which is the ordinary case
    assert product_for_model("HSU-24VRRA03TF") == "AAC1UKZ01"


def test_the_bundle_hands_back_the_group_set_order_in_the_shape_that_is_read():
    """The order positions the settings no shared map places, so it has to REACH `declared_order`.

    The bundle stores it flat (`group_set_order`); everything downstream reads `groupCommands`. A
    flat key would sit in the bundle unread -- a fix in a path that never runs -- so the lookup
    translates it, and this asserts the translation rather than the storage.
    """
    from haismart_hrdp import declared_order, rules_for_product

    rules = rules_for_product("AAC1UKZ01")
    assert rules is not None
    assert "group_set_order" not in rules, "the flat key must not leak downstream"
    order = declared_order(rules)
    assert order, "declared_order must see the bundled order"
    assert order[0] == "targetTemperature"
    assert "onOffStatus" in order


def test_the_bundled_order_is_shipped_for_every_product_that_publishes_one():
    """Coverage, asserted -- it was 18 of 1435 while the section carrying it was being discarded."""
    from haismart_hrdp import declared_order, known_products, rules_for_product

    with_order = sum(1 for pc in known_products() if declared_order(rules_for_product(pc)))
    assert with_order > 1200, f"only {with_order} products carry a group-set order"


def test_a_product_with_no_group_set_reports_no_order():
    """The families that publish no group-set command must not acquire a phantom one."""
    from haismart_hrdp import declared_order, known_products, rules_for_product

    without = [pc for pc in known_products() if not declared_order(rules_for_product(pc))]
    assert without, "expected the single-parameter lineage to have no group-set order"
    for pc in without[:20]:
        assert declared_order(rules_for_product(pc)) == ()


def test_no_shipped_lock_reason_is_left_in_the_source_language() -> None:
    """Every explanation a user can be shown is in English.

    52% of them were not: the wording only ever covered the `500xx` reason-code space, so the 700
    products whose codes live in the low space (`0`..`21`) shipped the vendor's Chinese straight
    through. An untranslated sentence is worse than a missing one -- a missing reason shows nothing,
    an untranslated one shows a user text they cannot read and looks like a bug in the integration.

    ⚠️ There is no vendor English to fall back on: these sentences appear nowhere in the app (checked
    across the fully-unpacked APK with a positive control), so the wording is this project's own and
    a newly swept product can reintroduce the source language. That is what this guards.
    """
    from haismart_hrdp.model_rules import known_products, rules_for_product

    def cjk(text: str) -> bool:
        return any("一" <= ch <= "鿿" for ch in str(text))

    offenders = {
        code: [v for v in (rules_for_product(code) or {}).get("invalid_reasons", {}).values()
               if cjk(v)]
        for code in known_products()
    }
    offenders = {c: v for c, v in offenders.items() if v}
    assert not offenders, (
        f"{len(offenders)} product(s) ship an untranslated lock reason, e.g. "
        f"{next(iter(offenders.items()))}"
    )


def test_a_reason_code_is_not_a_global_key() -> None:
    """The same code means different things on different products, so nothing may key on it alone.

    Measured on the published corpus: code `1` is "not allowed in the current state" on 509 products
    and "this function is not supported" on 300; code `2` is "cannot adjust temperature" or "the
    control command failed"; code `4` is "not allowed in intelligent mode" or "device fault". Any
    code that carries an English sentence across products would show a wrong explanation -- this
    pins the fact so the shortcut is never taken.
    """
    from haismart_hrdp.model_rules import known_products, rules_for_product

    meanings: dict[str, set[str]] = {}
    for code in known_products():
        for key, text in ((rules_for_product(code) or {}).get("invalid_reasons") or {}).items():
            meanings.setdefault(key, set()).add(text)
    multi = {k: v for k, v in meanings.items() if len(v) > 1}
    assert multi, "expected at least one reason code to carry more than one meaning"
    assert "1" in multi, f"code 1 should be ambiguous across products, got {meanings.get('1')}"
