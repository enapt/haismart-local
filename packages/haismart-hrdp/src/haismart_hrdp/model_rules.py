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
    "preload",
    "RULES_PATH",
]

RULES_PATH = Path(__file__).with_name("model_rules.json.gz")


@lru_cache(maxsize=1)
def _bundle() -> dict[str, Any]:
    with gzip.open(RULES_PATH, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def preload() -> None:
    """Warm the bundled-rules caches so the first lookup does not read from disk.

    The bundle is a gzip file opened once (every lookup here is ``lru_cache``d). A host that reads
    the rules on its event loop — Home Assistant does, in the coordinator's constructor — should
    call this from an executor first, so that one-off decompression happens off the loop rather than
    blocking it. A no-op after the first call.
    """
    _bundle()
    _by_model()


@lru_cache(maxsize=1)
def _by_model() -> dict[str, list[str]]:
    """``{MODEL NUMBER: [product codes]}``, built from the bundle rather than stored in it.

    Upper-cased on both sides so a number copied off a label matches regardless of how it was typed.

    ⚠️ **A model number is not unique.** It was across one region's 171 products, and this said so;
    across all 1435 there are 21 numbers carried by two or three products each, and 15 of those
    disagree about their rules. A ``{number: code}`` dict silently kept whichever came last, which
    is a coin toss between rule sets -- the exact failure this layer exists to prevent. So the
    candidates are all kept, and :func:`product_for_model` decides what a tie means.
    """
    out: dict[str, list[str]] = {}
    for code, entry in _bundle()["models"].items():
        if entry.get("model"):
            out.setdefault(entry["model"].upper(), []).append(code)
    return out


def known_products() -> frozenset[str]:
    """Every product code the bundle covers."""
    return frozenset(_bundle()["models"])


def rules_for_product(product_code: str | None) -> dict[str, Any] | None:
    """Published rules for a product code, or ``None`` if it is not covered.

    The result carries the sections a device shadow never does -- ``modifiers``, ``constraints``,
    ``alarms``, ``invalid_reasons``, ``invisible_attributes`` -- in the same shape the cloud path
    returns, so it drops straight into ``merge_rules`` with nothing downstream needing to know which
    source it came from.

    ★ That includes the **group-set order**, which the bundle stores flat as ``group_set_order`` and
    which is handed back here in the ``groupCommands`` shape the rest of this library already reads
    (:func:`~haismart_hrdp.device_rules.declared_order`). It is the ordered list of settings a
    product's group-set command carries, and the order *is* the wire order -- so a unit with no
    account still gets the one thing that positions the settings no shared map places.

    ⚠️ Storing it and not translating it would have been a fix in a path that never runs: the
    merge copies ``groupCommands`` and nothing else, so a flat key would sit in the bundle unread.
    """
    if not product_code:
        return None
    entry = _bundle()["models"].get(product_code)
    if entry is None:
        return None
    out = dict(entry)
    order = out.pop("group_set_order", None)
    if order and not out.get("groupCommands"):
        out["groupCommands"] = [{"name": "grSetDAC", "attrNameList": list(order)}]
    return out


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


def models_for_uplus_id(uplus_id: str | None, zone: str | None = None) -> dict[str, str]:
    """``{model number: product code}`` for the products sharing a uPlusId.

    The picker form of :func:`products_for_uplus_id`. A product code is an opaque token nobody can
    check (`AAC1UKZ01`), while a model number is printed on the appliance -- so asking "which of
    these is yours" only works if the question is asked in model numbers.

    ⚠️ **A uPlusId alone no longer narrows this to a shortlist.** It did when the bundle held one
    region's catalogue: ours came to 23 products, which is choosable. Across every region the same
    identifier reaches 186, which is a list nobody reads.

    ``zone`` -- the owner's dialling code, which onboarding already collects -- cuts it back to what
    is actually published where they are, offline and with no lookup, because the sweep records which
    regions publish each product. A zone that matches nothing falls back to the whole family rather
    than offering an empty list: the region lists are a snapshot, and an appliance in front of
    someone outranks a catalogue that has not heard of it.

    Model numbers are unique across the whole published set, so the mapping never collides.
    """
    out: dict[str, str] = {}
    in_zone: dict[str, str] = {}
    for product_code in products_for_uplus_id(uplus_id):
        entry = rules_for_product(product_code) or {}
        model = entry.get("model")
        if not model:
            continue
        out[model] = product_code
        if zone and zone in (entry.get("zones") or ()):
            in_zone[model] = product_code
    return in_zone or out


def product_for_model(model: str | None) -> str | None:
    """The product code for a model number as printed on the appliance, or ``None``.

    This is what lets an install with no account resolve its own unit's rules from a number its
    owner can read off the label.

    ``None`` when the number is unknown **or ambiguous in a way that matters**: 21 numbers name more
    than one product, and where those products disagree about their rules there is no answer to give
    -- picking one would apply a rulebook on the strength of a tie. Where they agree, the tie is not
    a tie and the first is returned.

    Refusing is not the end of the road: the appliance still announces its family, and
    :func:`family_rules` applies what every candidate in it agrees on. That is the same trade made
    for a unit whose model is unknown altogether, and it is why refusing here is cheap.
    """
    if not model:
        return None
    codes = _by_model().get(model.strip().upper()) or []
    if len(codes) == 1:
        return codes[0]
    if not codes:
        return None
    sections = ("modifiers", "constraints", "alarms", "invalid_reasons")
    shapes = {
        json.dumps({s: (rules_for_product(c) or {}).get(s) for s in sections}, sort_keys=True)
        for c in codes
    }
    return codes[0] if len(shapes) == 1 else None


def family_rules(uplus_id: str | None) -> dict[str, Any] | None:
    """Only the rules every model in a family agrees on -- correct without knowing which model.

    A unit announces its family and not its model, and where an account can be asked that gap is
    closed for free. Where it cannot -- a hand-made entry from a saved key -- something has to give,
    and the choice is not between "the right rules" and "no rules": it is between *asking someone to
    guess* and *applying only what holds whichever model it turns out to be*.

    That second option is worth more than it sounds, because the disagreement is concentrated in the
    conditional rules rather than in what a user reads. Measured across every multi-model family in
    this bundle: **alarms 99% common (1393/1410), lock explanations 93% (117/126)**, constraints 21%
    and modifiers 9%. So fault names -- the part that turns an unexplained failure into a service
    code -- arrive very nearly in full with no model at all, while conditional availability thins
    out, and thinning out is safe: a rule nobody disagrees about cannot lock the wrong control, and a
    missing rule locks nothing.

    ⚠️ Those first two figures were **100%** when this bundle held one region's 171 products, and
    that is how they were first written down here. Widening it to every region's 1435 dropped them,
    and one family now agrees on no lock explanation at all -- so "every alarm name is common" is no
    longer true, and a claim measured on one corpus should not be quoted for a larger one. Re-measure
    with ``tools/re/check_family_intersections.py`` after any change to the bundle.

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

    def agreed_reasons() -> dict[str, str]:
        # ``invalid_reasons`` is a MAPPING (code -> sentence), unlike the list sections above, and
        # iterating a mapping yields bare keys -- which is how this section once shipped as a list
        # of codes with every sentence dropped, and ``lock_reasons`` crashes on a list. The code is
        # the fact and the sentence is presentation, so agreement is on the codes; the wording
        # comes from the first rulebook that carries each one.
        maps = [dict(r.get("invalid_reasons") or {}) for r in rules]
        common = set.intersection(*(set(m) for m in maps)) if maps else set()
        return {code: next(m[code] for m in maps if code in m) for code in sorted(common)}

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
        "invalid_reasons": agreed_reasons(),
        "constraints": agreed("constraints"),
        "modifiers": agreed("modifiers"),
    }
