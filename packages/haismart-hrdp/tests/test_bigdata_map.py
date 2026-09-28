"""The published telemetry map's field reads."""
from haismart_hrdp.bigdata_map import BIGDATA_MAPS
from haismart_hrdp.uss import read_bigdata_field


def _field(span: int, name: str):
    return next(f for f in BIGDATA_MAPS[span] if f.name == name)


def _payload(span: int, words: dict[int, int]) -> bytes:
    out = bytearray(2 * span)
    for word, value in words.items():
        out[2 * (word - 1):2 * word] = value.to_bytes(2, "big")
    return bytes(out)


def test_a_32_bit_counter_takes_its_high_half_from_the_word_before() -> None:
    """The WireField convention: significance grows backwards, so w34 holds the high half of w35."""
    field = _field(43, "totalElectricityUsed")
    assert read_bigdata_field(field, _payload(43, {34: 0x0001, 35: 0x0002})) == 0x0001_0002


def test_a_counter_reading_zero_is_absent_not_zero() -> None:
    """A register the firmware never fills reads 0 forever; a permanent 0 Wh is worse than nothing."""
    assert read_bigdata_field(_field(43, "totalElectricityUsed"), _payload(43, {})) is None
    assert read_bigdata_field(_field(23, "totalElectricityUsed"), _payload(23, {})) is None


def test_single_word_fields_read_as_before() -> None:
    power = _field(43, "power")
    assert read_bigdata_field(power, _payload(43, {37: 1234})) == 1234
    assert read_bigdata_field(power, _payload(43, {})) == 0            # a gauge, not a counter: 0 W is real
    current = _field(43, "compressorCurrent")
    assert read_bigdata_field(current, _payload(43, {41: 57})) == 5.7
    coil = _field(43, "indoorCoilerTemperature")
    assert read_bigdata_field(coil, _payload(43, {38: 90 << 8})) == 25.0


def test_a_field_past_the_end_of_the_payload_is_none() -> None:
    assert read_bigdata_field(_field(43, "expansionValveOpenDegree"), b"\x00" * 84) is None
