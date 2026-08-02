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

__all__ = ["rules_for_product", "products_for_uplus_id", "known_products", "RULES_PATH"]

RULES_PATH = Path(__file__).with_name("model_rules.json.gz")


@lru_cache(maxsize=1)
def _bundle() -> dict[str, Any]:
    with gzip.open(RULES_PATH, "rt", encoding="utf-8") as handle:
        return json.load(handle)


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
