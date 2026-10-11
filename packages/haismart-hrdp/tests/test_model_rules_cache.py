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


def test_the_memo_is_bounded() -> None:
    """Model numbers are typed by people; an unbounded memo would keep every one for the process."""
    for i in range(300):
        product_for_model(f"NOT-A-MODEL-{i}")
    assert model_rules._product_for_model.cache_info().currsize <= 256
