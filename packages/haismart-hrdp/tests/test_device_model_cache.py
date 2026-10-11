"""The DeviceModel fast paths answer exactly what the plain scans they replaced answered."""
from __future__ import annotations

import random

import pytest

from haismart_hrdp.device_model import STATUS_ALL, STATUS_BIGDATA, known_typeids, model_for, read_field


def _read_field_bitwise(data, word, bit, length, *, base):
    """The original bit-by-bit reader, kept verbatim as the oracle."""
    value = 0
    for index in range(length):
        source_word, source_bit = word, bit + index
        while source_bit > 15:
            source_bit -= 16
            source_word -= 1
        offset = base + 2 * (source_word - 1)
        if source_word < 1 or offset + 1 >= len(data):
            return None
        if ((data[offset] << 8 | data[offset + 1]) >> source_bit) & 1:
            value |= 1 << index
    return value


def test_read_field_matches_the_bitwise_reader_everywhere() -> None:
    rng = random.Random(7)
    for _ in range(20000):
        base = rng.choice((0, 12, 92))
        data = rng.randbytes(rng.randint(0, base + 24))
        word, bit, length = rng.randint(-1, 14), rng.randint(0, 40), rng.randint(0, 40)
        assert read_field(data, word, bit, length, base=base) == _read_field_bitwise(
            data, word, bit, length, base=base
        ), (len(data), word, bit, length, base)


def _first_omitted_scan(model, status_cmd):
    covered: set[int] = set()
    for f in model.fields:
        if f.status_cmd == status_cmd:
            covered.update(range(f.word, f.last_word + 1))
    extent = max((f.last_word for f in model.fields if f.status_cmd == status_cmd), default=0)
    run_start = None
    for word in range(1, extent + 1):
        if word in covered:
            if run_start is not None and word - run_start >= 2:
                return run_start
            run_start = None
        elif run_start is None:
            run_start = word
    return run_start


@pytest.mark.parametrize("typeid", sorted(known_typeids())[::7])
def test_indexed_lookups_match_the_scans(typeid: str) -> None:
    model = model_for(typeid)
    for f in model.fields:
        assert model.field(f.name) is next(g for g in model.fields if g.name == f.name)
    assert model.field("no-such-attribute") is None
    for cmd in (STATUS_ALL, STATUS_BIGDATA, "XXXX"):
        assert model.fields_for(cmd) == tuple(f for f in model.fields if f.status_cmd == cmd)
        assert model.extent(cmd) == max(
            (f.last_word for f in model.fields if f.status_cmd == cmd), default=0
        )
        assert model.first_omitted_word(cmd) == _first_omitted_scan(model, cmd)
