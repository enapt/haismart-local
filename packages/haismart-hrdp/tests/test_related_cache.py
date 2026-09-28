"""Related-layout construction is memoised, and a memoised layout cannot be edited by a caller."""
from __future__ import annotations

import pytest

from haismart_hrdp import wire_models
from haismart_hrdp.wire_models import decode_related, related_wire_model

CABINET_UPLUS_ID = "201c10c7088081000d1205464544850000009cd68e692c104e2a333eab95d140"


def test_the_same_inputs_return_the_same_frozen_layout() -> None:
    a = related_wire_model(133, -19, order=["onOffStatus"], uplus_id=CABINET_UPLUS_ID, insert=(25, 4))
    b = related_wire_model(133, -19, order=("onOffStatus",), uplus_id=CABINET_UPLUS_ID, insert=(25, 4))
    assert a is b
    for mapping in (a.fields, a.write_fields, a.value_param_fields):
        with pytest.raises(TypeError):
            mapping["x"] = None     # shared between every caller, so it must refuse edits


def test_a_decode_builds_the_inserted_candidates_once(monkeypatch) -> None:
    """A report no flat offset fits used to build every inserted candidate twice per decode."""
    calls = []
    real = wire_models.related_insert_models

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(wire_models, "related_insert_models", counting)
    decode_related(bytes(133), CABINET_UPLUS_ID, None, declared_modes=(1, 2))
    assert len(calls) == 1
