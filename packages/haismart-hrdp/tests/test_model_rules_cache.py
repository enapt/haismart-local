"""`family_rules` / `product_for_model` are memoised: callers must not be able to poison the memo."""
from __future__ import annotations

from haismart_hrdp import model_rules
from haismart_hrdp.model_rules import family_rules, product_for_model

FAMILY = "2008610800820324021200118012560000000000000000000000000000000040"


def test_mutating_a_family_result_does_not_leak_into_the_next_call() -> None:
    first = family_rules(FAMILY)
    pristine = family_rules(FAMILY)
    assert first == pristine and first is not pristine
    first["alarms"].clear()
    first["attributes"][0]["name"] = "poisoned"
    first["invalid_reasons"]["x"] = "y"
    assert family_rules(FAMILY) == pristine


def test_a_replaced_bundle_is_not_answered_from_the_old_one(monkeypatch) -> None:
    assert family_rules(FAMILY) is not None
    assert product_for_model("HSU-24VRRA03TF") == "AAC1UKZ01"
    empty = {"models": {}, "by_uplus_id": {}}
    monkeypatch.setattr(model_rules, "_bundle", lambda: empty)
    monkeypatch.setattr(model_rules, "_by_model", lambda: {})
    assert family_rules(FAMILY) is None
    assert product_for_model("HSU-24VRRA03TF") is None
