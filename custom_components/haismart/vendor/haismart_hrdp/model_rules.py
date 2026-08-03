"""Published model rules for every AC the region publishes, shipped rather than fetched.

The rules a unit is governed by -- which controls lock when, what a fault code is called, which
writes drag siblings along -- are published per model. Fetching them needs an account, and an
account answers only for its *own* devices, so an install with no cloud credentials, or a bug report
about hardware nobody here owns, got nothing and the lock/co-command machinery sat inert. This
bundle removes that dependency for the 171 published air conditioners.

**Keyed by product code, because rules are a property of the product, not of the family.** That is
worth stating because the obvious alternative is wrong: uPlusId is what a unit announces on the LAN
without a key, so keying on it would be far more convenient. But it does not hold. Of the twelve
uPlusId families here, five contain members whose rule sets differ, and in the family our own units
belong to -- 23 products -- **not one modifier is common to all of them**. Keying rules by uPlusId
would hand a device a sibling's rulebook, which is the same defect that once let a two-model account
give one AC the other's constraints.

So :func:`products_for_uplus_id` narrows, and does not decide. A uPlusId identifies the family; the
caller supplies the product code, or asks. What a uPlusId *does* key reliably is the byte map -- see
:mod:`haismart_hrdp.wire_order` -- because layout is shared across a family where rules are not.
"""

from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = [
    "rules_for_product",
    "products_for_uplus_id",
    "models_for_uplus_id",
    "product_for_model",
    "family_rules",
    "known_products",
    "RULES_PATH",
]

RULES_PATH = Path(__file__).with_name("model_rules.json.gz")


@lru_cache(maxsize=1)
def _bundle() -> dict[str, Any]:
    with gzip.open(RULES_PATH, "rt", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def _by_model() -> dict[str, str]:
    """``{MODEL NUMBER: product code}``, built from the bundle rather than stored in it.

    Upper-cased on both sides so a number copied off a label matches regardless of how it was
    typed. Model numbers are unique across the published set, so this cannot collide.
    """
    return {
        entry["model"].upper(): code
        for code, entry in _bundle()["models"].items()
        if entry.get("model")
    }


def known_products() -> frozenset[str]:
    """Every product code the bundle covers."""
    return frozenset(_bundle()["models"])


def rules_for_product(product_code: str | None) -> dict[str, Any] | None:
    """Published rules for a product code, or ``None`` if it is not covered.

    The result carries the sections a device shadow never does -- ``modifiers``, ``constraints``,
    ``alarms``, ``invalid_reasons``, ``invisible_attributes`` -- in the same shape the cloud path
    returns, so it drops straight into ``merge_rules`` with nothing downstream needing to know which
    source it came from.
    """
    if not product_code:
        return None
    entry = _bundle()["models"].get(product_code)
    return dict(entry) if entry is not None else None


def products_for_uplus_id(uplus_id: str | None) -> list[str]:
    """Product codes sharing a uPlusId -- a candidate list, deliberately not a choice.

    A unit tells us its uPlusId over discovery, with no key and no account, and that is as far as
    the wire gets us: 23 products answer to ours. Where they agree this is still useful (they share
    an attribute set, so a caller can take the intersection safely); where they disagree -- and on
    rules they do -- somebody has to pick, which in practice means asking the owner which model they
    have. Returned sorted so the order is stable enough to show in a picker.
    """
    if not uplus_id:
        return []
    return list(_bundle()["by_uplus_id"].get(uplus_id, []))


def models_for_uplus_id(uplus_id: str | None) -> dict[str, str]:
    """``{model number: product code}`` for the products sharing a uPlusId.

    The picker form of :func:`products_for_uplus_id`. A product code is an opaque token nobody can
    check (`AAC1UKZ01`), while a model number is printed on the appliance -- so asking "which of
    these is yours" only works if the question is asked in model numbers. A unit hands over its
    uPlusId on discovery for free, which narrows the 171 published models to a couple of dozen, and
    that is short enough to choose from.

    Model numbers are unique across the whole published set, so the mapping never collides.
    """
    out = {}
    for product_code in products_for_uplus_id(uplus_id):
        model = (rules_for_product(product_code) or {}).get("model")
        if model:
            out[model] = product_code
    return out


def product_for_model(model: str | None) -> str | None:
    """The product code for a model number as printed on the appliance, or ``None``.

    All 171 published model numbers are distinct, so this needs no other identifier to disambiguate
    -- which is what lets an install with no account resolve the rules for its own unit from a
    number the owner can read off the label.
    """
    if not model:
        return None
    return _by_model().get(model.strip().upper())


def family_rules(uplus_id: str | None) -> dict[str, Any] | None:
    """Only the rules every model in a family agrees on -- correct without knowing which model.

    A unit announces its family and not its model, and where an account can be asked that gap is
    closed for free. Where it cannot -- a hand-made entry from a saved key -- something has to give,
    and the choice is not between "the right rules" and "no rules": it is between *asking someone to
    guess* and *applying only what holds whichever model it turns out to be*.

    That second option is worth far more than it sounds, because the disagreement is concentrated:
    across every multi-model family published, **every alarm and every lock explanation is common to
    all members** (698/698 and 54/54). So fault names -- the part a user actually sees, and the part
    that turns an unexplained failure into a service code -- need no model at all. Only the
    conditional-availability rules genuinely vary (26% common), and those degrade safely: a rule
    nobody disagrees about cannot lock the wrong control, and a missing rule locks nothing.

    Attributes are merged the conservative way round: an attribute any member marks ``invisible``
    is marked invisible here. Optional-feature entities are built from that flag, and offering a
    control for hardware a unit does not have is the one failure mode this layer exists to prevent.

    Returns ``None`` when the family is unknown, and the single model's rules when it has only one.
    """
    products = products_for_uplus_id(uplus_id)
    if not products:
        return None
    if len(products) == 1:
        return rules_for_product(products[0])
    rules = [r for r in (rules_for_product(p) for p in products) if r is not None]
    if not rules:
        return None

    def agreed(section: str) -> list[Any]:
        sets = [
            {json.dumps(item, sort_keys=True) for item in (r.get(section) or ())} for r in rules
        ]
        return [json.loads(item) for item in sorted(set.intersection(*sets))] if sets else []

    invisible = {
        a["name"]
        for r in rules
        for a in (r.get("attributes") or ())
        if a.get("name") and a.get("invisible")
    }
    attributes = [
        {**a, **({"invisible": True} if a.get("name") in invisible else {})}
        for a in (rules[0].get("attributes") or ())
    ]
    return {
        "uplus_id": uplus_id,
        "attributes": attributes,
        "alarms": agreed("alarms"),
        "invalid_reasons": agreed("invalid_reasons"),
        "constraints": agreed("constraints"),
        "modifiers": agreed("modifiers"),
    }
