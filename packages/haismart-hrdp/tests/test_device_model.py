"""The manufacturer's byte map decodes real hardware — including a class nobody here has captured.

Two kinds of check, deliberately:

* **Against ground truth.** A heat-pump water heater's report, decoded from Haier's own configFile
  and compared to what the cloud reported for the same unit in the same diagnostics download. It is
  the strongest evidence available short of hardware, and it is a class this package had never
  decoded — the point being that nothing about the decoder is AC-shaped.
* **Across the whole bundle.** Properties every one of the 164 shipped maps must satisfy. A bundle
  is added to by regenerating a file, and a regenerated file cannot be reviewed into correctness.

⛔ What these do NOT establish: any write beyond the single confirmed one (a ``2001`` water
heater's ``targetTemperature``/``5D01``, accepted by real hardware 2026-09-14 — issue #13; every
other non-AC write is still unexercised), the
``Bigdata``/``7D01`` frame on a non-AC class (never captured), or that a map is right for a unit of
some other family. The parent tree's ``tools/re/configfile_decode.py --selftest`` carries the wider
comparison against the stored AC captures, which are too large to vendor here.
"""
from __future__ import annotations

import pytest

from haismart_hrdp.device_model import (
    ATTR_BASE,
    absent_probe,
    device_classes,
    known_typeids,
    model_for,
    read_field,
)

# --- issue #13: a heat-pump water heater (Taiwan), product code GK0GXZE0J ------------------------
# Two of the reporter's four controlled diagnostics downloads: the baseline, and the one where they
# switched the unit to dual-source/instant heat. `..._CLOUD` is that capture's own
# `digital_model.reported_values_now` — Haier's account of the same instant, which is what makes
# this a comparison rather than a plausibility check.
WH_TYPEID = "201c120000118674200100418007574800000000000000000000000000000040"

WH_BASELINE = bytes.fromhex(
    "00002715000000004e560100000302000004010000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000057ffff54000000000000066d013112160b"
    "000303e800c8000000000000140000140000000000002222000006000000000052c55900000000000c2a030000000000"
    "0000000000000000000000000000000000000003000000"
)
WH_BASELINE_CLOUD = {
    "currentTemperature": "49", "dualHeaterMode": "false", "heatModeMaxTemp": "1",
    "oddHotWater": "3", "onOffStatus": "true", "pumpModeMaxTemp": "1",
    "resn1CycleStatus": "true", "resn1Result": "true", "resn1RunningStatus": "false",
    "resn1Temperature": "50", "resn1TimeHH": "0", "resn1TimeMM": "0",
    "resn2CycleStatus": "true", "resn2Result": "true", "resn2RunningStatus": "false",
    "resn2Temperature": "50", "resn2TimeHH": "0", "resn2TimeMM": "0",
    "runningMode": "2", "targetTemperature": "48", "time": "22:11",
    "valley1StartTimeHH": "0", "valley1StartTimeMM": "0", "valley1StopTimeHH": "6",
    "valley1StopTimeMM": "0", "workStatus": "1",
}

WH_DUAL_SOURCE = bytes.fromhex(
    "00002715000000004e560100000302000004010000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000057ffff54000000000000066d0132121617"
    "000403e800c80000000000002d00002d0000000000002222000006000000000050c55900000000000c2a030000000000"
    "000000000000000000000000000000000000004300007e"
)
WH_DUAL_SOURCE_CLOUD = {
    "currentTemperature": "50", "dualHeaterMode": "true", "heatModeMaxTemp": "1",
    "oddHotWater": "4", "onOffStatus": "true", "pumpModeMaxTemp": "1",
    "resn1CycleStatus": "true", "resn1Result": "true", "resn1RunningStatus": "false",
    "resn1Temperature": "75", "resn1TimeHH": "0", "resn1TimeMM": "0",
    "resn2CycleStatus": "true", "resn2Result": "true", "resn2RunningStatus": "false",
    "resn2Temperature": "75", "resn2TimeHH": "0", "resn2TimeMM": "0",
    "runningMode": "2", "targetTemperature": "48", "time": "22:23",
    "valley1StartTimeHH": "0", "valley1StartTimeMM": "0", "valley1StopTimeHH": "6",
    "valley1StopTimeMM": "0", "workStatus": "1",
}

_CAPTURES = [
    pytest.param(WH_BASELINE, WH_BASELINE_CLOUD, id="baseline"),
    pytest.param(WH_DUAL_SOURCE, WH_DUAL_SOURCE_CLOUD, id="dual-source"),
]


def _same(decoded: object, published: object) -> bool:
    """Compare across JSON/Python spellings: true/True, 48/48.0, "2"/2.

    Symmetric on purpose. It was written against the cloud, whose values are all strings, and the
    first caller that handed it two Python values crashed on `bool.lower()` — a comparison helper
    that raises rather than answers is worse than one that is merely wrong.
    """
    if isinstance(decoded, bool) or isinstance(published, bool):
        return str(decoded).lower() == str(published).lower()
    try:
        return abs(float(decoded) - float(published)) < 1e-9   # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(decoded) == str(published)


@pytest.mark.parametrize(("report", "published"), _CAPTURES)
def test_water_heater_decodes_exactly_what_the_cloud_reported(
    report: bytes, published: dict[str, str]
) -> None:
    """Every attribute the cloud reported, from the manufacturer's map alone.

    Not a subset: the assertion is over the cloud's whole set, because choosing which attributes to
    compare is how a decoder passes while being wrong about the ones nobody looked at. That is not
    hypothetical here — an earlier hand-check of nine chosen attributes passed while `time` was
    being decoded as `None`.
    """
    model = model_for(WH_TYPEID)
    assert model is not None, "the bundle must carry issue #13's typeid"
    decoded = model.decode(report, only=frozenset(published))

    missing = sorted(set(published) - set(decoded))
    wrong = sorted(
        (name, decoded[name], value)
        for name, value in published.items()
        if name in decoded and not _same(decoded[name], value)
    )
    assert not missing, f"decoded nothing for {missing}"
    assert not wrong, f"disagreed with the cloud on {wrong}"


def test_work_status_is_the_field_the_reporter_could_not_pin() -> None:
    """`workStatus` 1 = keep-warm, 2 = heating — issue #13's one unresolved byte.

    The reporter pinned every other field by diffing four captures and said outright that this one
    was in the digital model but not located. Haier's map puts it at word 36 bit 7, and it reads
    keep-warm on the baseline. Pinned here so a bundle regeneration cannot quietly move it.
    """
    model = model_for(WH_TYPEID)
    assert model is not None
    field = model.field("workStatus")
    assert field is not None
    assert (field.word, field.bit, field.length) == (36, 7, 1)
    assert model.decode(WH_BASELINE, only=frozenset({"workStatus"}))["workStatus"] == 1


def test_the_water_heater_publishes_single_parameter_write_ids() -> None:
    """Its control path is `5Dxx` — the mechanism the `0d12` cabinets already ship.

    Reads alone would leave issue #13 half-answered: the reporter's complaint is that commands are
    disabled. ⛔ This asserts what the manufacturer PUBLISHES, not that any of it works — no write
    has ever been sent to this unit, and the first one must be self-verifying against a read-back.
    """
    model = model_for(WH_TYPEID)
    assert model is not None
    ids = {field.name: field.epp_cmd for field in model.writable_fields()}
    assert ids["onOffStatus"] == "5D00"
    assert ids["targetTemperature"] == "5D01"
    assert ids["runningMode"] == "5D04"
    assert ids["dualHeaterMode"] == "5D05"


def test_writes_encode_to_the_published_command_and_value() -> None:
    """`5Dxx` + a big-endian 16-bit value, and the value is the inverse of the read scaling.

    55 C on a field published as `raw + 30` must go out as 25, not 55. Getting that backwards is
    silent: the appliance accepts a well-formed command carrying the wrong number.
    """
    model = model_for(WH_TYPEID)
    assert model is not None
    assert model.encode_write("targetTemperature", 55) == (b"\x5d\x01", b"\x00\x19")
    assert model.encode_write("onOffStatus", True) == (b"\x5d\x00", b"\x00\x01")
    assert model.encode_write("dualHeaterMode", True) == (b"\x5d\x05", b"\x00\x01")
    # An enum goes out as its EPP value, not the std code the model publishes: 中温保温 is std 19,
    # epp 6, and the two are not the same number for eight of this attribute's nineteen values.
    assert model.encode_write("runningMode", 19) == (b"\x5d\x04", b"\x00\x06")


@pytest.mark.parametrize(
    ("name", "value", "why"),
    [
        ("targetTemperature", 200, "outside the published range"),
        ("targetTemperature", -5, "outside the published range"),
        ("runningMode", 99, "not a value this attribute publishes"),
        ("currentTemperature", 50, "read-only: no write id is published"),
        ("time", "01:02", "a composite is not written this way"),
        ("noSuchAttribute", 1, "not an attribute of this class"),
    ],
)
def test_a_write_refuses_anything_the_map_does_not_name(name: str, value, why: str) -> None:
    """Control may only ever emit a mapped attribute with a supported value.

    A value the appliance does not recognise is at best discarded and at worst lands in a
    neighbouring field, and neither reports itself.
    """
    model = model_for(WH_TYPEID)
    assert model is not None
    with pytest.raises((ValueError, KeyError)):
        model.encode_write(name, value)


def test_a_written_value_reads_back_at_the_same_position() -> None:
    """The read and the write must be the same field, or a control shows an echo of itself.

    Asserted as a round trip on the real captures: what the encoder would send for the setpoint the
    unit is actually at must be the raw value sitting in the report.
    """
    model = model_for(WH_TYPEID)
    assert model is not None
    field = model.field("targetTemperature")
    assert field is not None
    live = model.decode(WH_BASELINE, only=frozenset({"targetTemperature"}))["targetTemperature"]
    assert live == 48
    _, payload = model.encode_write("targetTemperature", live)
    assert int.from_bytes(payload, "big") == read_field(
        WH_BASELINE, field.word, field.bit, field.length
    )


def test_composite_fields_decode_as_their_parts() -> None:
    """caeType 3/4/5 store a part descriptor where an enum stores `eppValue`.

    Read as an enum a composite silently yields `None` — no exception, no wrong number, just a
    field that quietly never appears. That is exactly how it got shipped past a hand-check, so the
    distinction is asserted rather than trusted.
    """
    model = model_for(WH_TYPEID)
    assert model is not None
    field = model.field("time")
    assert field is not None and field.is_composite and not field.is_enum
    assert field.read(WH_BASELINE) == "22:11"
    assert field.read(WH_DUAL_SOURCE) == "22:23"


def test_a_device_model_carries_its_class_and_its_alarms() -> None:
    model = model_for(WH_TYPEID)
    assert model is not None
    assert model.device_class == "2001"
    names = dict(model.alarms)
    assert "leakageAlarm" in names and "tempExceedAlarm" in names


def test_an_unknown_typeid_decodes_nothing_rather_than_guessing() -> None:
    """A near-miss typeid is a different device. There is no fallback here on purpose."""
    assert model_for(None) is None
    assert model_for("") is None
    assert model_for("0" * 64) is None
    # One hex digit away from a typeid we DO carry, and still not it.
    assert model_for(WH_TYPEID[:-1] + "f") is None


# --- properties every shipped map must satisfy --------------------------------------------------

def test_the_bundle_covers_more_than_air_conditioners() -> None:
    """The premise of supporting every appliance: the maps are already here, across many classes.

    Pinned low enough not to be brittle, high enough to fail if the bundle is regenerated from a
    narrowed source. The AC classes and issue #13's must each be present by name.
    """
    classes = device_classes()
    assert len(known_typeids()) >= 160
    assert len(classes) >= 30
    assert {"0212", "0d12"} <= classes, "the AC classes this project ships must be carried"
    assert "2001" in classes, "issue #13's heat-pump water heater class"


@pytest.mark.parametrize("typeid", sorted(known_typeids()))
def test_every_field_in_every_map_is_readable_and_typed(typeid: str) -> None:
    """Structural invariants across all 164 maps, ~20k fields.

    A position that cannot be read, or a `variants` shape no rule handles, is a decoder that returns
    `None` for a field a user expects — the quiet failure mode this whole module is exposed to.
    """
    model = model_for(typeid)
    assert model is not None
    assert model.device_class == typeid[16:20]
    for field in model.fields:
        assert field.length > 0 and field.word >= 1 and 0 <= field.bit <= 15, field
        # caeType is the discriminator for what `variants` means; an unhandled combination would
        # decode to a raw integer that means nothing, so every field must match a known row.
        if field.cae_type in (1, 6):
            assert isinstance(field.variants, dict) and ("k" in field.variants
                                                         or "c" in field.variants), field
        elif field.cae_type == 2:
            assert isinstance(field.variants, list) and field.variants, field
            assert "eppValue" in field.variants[0], field
        elif field.cae_type in (3, 4, 5):
            assert field.is_composite and isinstance(field.variants, list), field
            assert all("startWord" in part for part in field.variants), field
        elif field.cae_type == 13:
            assert not field.variants, field
        else:  # pragma: no cover - a new caeType must be classified, not silently accepted
            pytest.fail(f"{typeid} {field.name}: unclassified caeType {field.cae_type!r}")


def test_reading_past_the_end_of_a_report_returns_none_rather_than_raising() -> None:
    """A short frame — an ack, or a reply to a query the unit does not implement — must not crash.

    The AC path learned this the hard way: a 93-byte reply was once claimed as a status report and
    became the baseline for the next control command.
    """
    short = b"\x00\x00\x27\x15" + b"\x00" * 40
    assert read_field(short, 1, 0, 8) is None
    assert read_field(short, 900, 0, 8) is None
    model = model_for(WH_TYPEID)
    assert model is not None
    assert model.decode(short) == {}


def test_word_geometry_matches_the_ac_path() -> None:
    """Word N starts at byte 92 + 2*(N-1), big-endian — the same array `uss.py` reads.

    That the water heater decodes at the SAME base as the air conditioners is the finding this
    module rests on; if it ever stops being true, everything above is coincidence.
    """
    assert ATTR_BASE == 92
    data = bytearray(200)
    data[ATTR_BASE], data[ATTR_BASE + 1] = 0xAB, 0xCD
    assert read_field(bytes(data), 1, 0, 16) == 0xABCD
    assert read_field(bytes(data), 1, 8, 8) == 0xAB
    assert read_field(bytes(data), 1, 0, 8) == 0xCD


def test_an_absent_probe_reads_as_absent_not_as_minus_sixty_four() -> None:
    """The rule `uss._sensor_temp` exists for, carried across to the published maps.

    A unit without an outdoor probe reports raw 0, which `raw * 1 + (-64)` turns into a confident
    -64 C. As a MEASUREMENT that lands in long-term statistics, one fabricated reading permanently
    skews a user's history — so this is not cosmetic.
    """
    ac = model_for("2008610800820324021200118006915900000000000000000000000000000040")
    assert ac is not None, "the classic wall-unit family must be carried"
    outdoor = ac.field("outdoorTemperature")
    assert outdoor is not None and outdoor.unit == "℃" and not outdoor.writable

    report = bytearray(b"\x00" * 200)
    assert absent_probe(outdoor, bytes(report)), "raw 0 is the absent-probe sentinel"
    assert "outdoorTemperature" not in ac.decode(bytes(report))
    # ...while a SETPOINT at raw 0 is a real 16 C and must survive. Note this family publishes its
    # own setpoint as `writable: false`, which is why the rule cannot key on that flag.
    target = ac.field("targetTemperature")
    assert target is not None and not target.writable
    assert not absent_probe(target, bytes(report))
    assert ac.decode(bytes(report)).get("targetTemperature") == 16.0


def test_the_air_conditioner_plausibility_band_does_not_reject_other_appliances() -> None:
    """A 75 C reservation temperature is real on a water heater and implausible on an AC.

    `wire_models._PLAUSIBLE_SENSOR_C` is (-30, 70) — correct for air conditioners and wrong the moment the
    appliance is not one. Carrying it across would have silently dropped two attributes the cloud
    reported in issue #13's fourth capture, which is how a decoder ends up confidently incomplete.
    The manufacturer's own per-field bounds are used instead.
    """
    model = model_for(WH_TYPEID)
    assert model is not None
    field = model.field("resn1Temperature")
    assert field is not None and field.bounds() == (30.0, 80.0)
    assert not absent_probe(field, WH_DUAL_SOURCE)
    assert model.decode(WH_DUAL_SOURCE)["resn1Temperature"] == 75


def test_a_declaration_gate_is_honoured() -> None:
    """Only what a device declares becomes state.

    The class map lists every attribute the PLATFORM can carry; a device declares a subset. Entities
    built from the map alone are phantoms — 0 of 187 `0d12` products declare an outdoor probe and
    all seven real cabinets have one, so the gate cuts both ways and must be the caller's choice.
    """
    model = model_for(WH_TYPEID)
    assert model is not None
    everything = model.decode(WH_BASELINE)
    gated = model.decode(WH_BASELINE, only=frozenset({"targetTemperature", "workStatus"}))
    assert set(gated) == {"targetTemperature", "workStatus"}
    assert len(everything) > len(gated)


# --- the two decoders, checked against each other -------------------------------------------------

@pytest.mark.parametrize(
    ("typeid", "length", "family"),
    [
        # The owner's own units, and the other family whose shipped layout is FIXED.
        ("2008610800820324021200118012560000000000000000000000000000000040", 127, "classic"),
        ("2008610800820324021200118006915900000000000000000000000000000040", 165, "extended-36"),
        # ⛔ The `0d12` cabinet (133 B) is NOT here, and the reason is worth stating: it has neither
        # a confirmed layout-table entry nor a wire model, so its shipped path DERIVES the layout
        # from the report and scores candidate displacements against the data. Fed noise it scores
        # differently, which is a property of the probe and not a disagreement about the map — the
        # two decoders agree on all four of its real captures, which is what
        # `tools/re/configfile_decode.py --selftest` checks.
    ],
)
def test_the_byte_map_and_the_hand_derived_decoder_agree_on_random_frames(
    typeid: str, length: int, family: str
) -> None:
    """Two independent implementations, compared across randomised input.

    The air-conditioner decoder was derived by hand from captures over months; the byte-map decoder
    reads Haier's published positions and knows nothing about it. Twelve stored captures already
    show they agree on real reports — this shows they agree on reports nobody has seen, which is the
    case that matters when a new family arrives.

    ⚠️ **One divergence is expected and is not a bug in either.** The hand-derived decoder applies a
    physical plausibility band to a *sensor* reading (`wire_models._PLAUSIBLE_SENSOR_C`,
    −30…70 °C, confirmed on air-conditioner hardware) and drops anything outside it. The published
    map states only the field's declared range, which for `outdoorTemperature` is −64…191 — the span of
    the byte, not a
    temperature anything reaches. So a garbage byte reads as `None` on one side and as 169 °C on the
    other. The byte-map decoder will not invent a band it cannot source: a water heater's reserve
    goes to 80 °C and an oven far higher, and borrowing the air conditioner's band is exactly the
    mistake that dropped a real 75 °C reading earlier. What is asserted instead is that wherever
    BOTH produce a value, the values are identical.

    Randomised rather than exhaustive, and seeded so a failure is reproducible.
    """
    import random

    from haismart_hrdp import parse_full_status, profile_for

    model = model_for(typeid)
    assert model is not None
    profile = profile_for("AAC1UKZ01")
    pairs = [
        ("power", "onOffStatus"),
        ("target_temperature", "targetTemperature"),
        ("current_temperature", "indoorTemperature"),
        ("outdoor_temperature", "outdoorTemperature"),
        ("operation_mode", "operationMode"),
        ("wind_speed", "windSpeed"),
    ]
    # Keep this family's own indoor probe plausible, or the hand-derived decoder vetoes the frame
    # and a vetoed frame compares nothing. Read from the map rather than hardcoded, so the test
    # follows a family whose indoor temperature sits at a different word.
    indoor = model.field("indoorTemperature")
    assert indoor is not None
    indoor_byte = ATTR_BASE + 2 * (indoor.word - 1)

    random.seed(7)
    disagreements: list[str] = []
    one_sided = 0
    compared = 0
    for _ in range(120):
        data = bytearray(length)
        data[2:4] = b"\x27\x15"
        for index in range(92, length):
            data[index] = random.randrange(256)
        data[92] = random.randrange(0, 15)                   # a setpoint code in range
        data[indoor_byte] = random.randrange(20, 80)         # a plausible indoor reading
        state = parse_full_status(bytes(data), profile, None, uplus_id=typeid)
        if not state or state.get("partial"):
            continue
        decoded = model.decode(bytes(data))
        for ours, theirs in pairs:
            if state.get(ours) is None or decoded.get(theirs) is None:
                # One side dropped it. That is the plausibility band at work and is asserted
                # separately below, not smuggled in here as an agreement.
                one_sided += 1
                continue
            compared += 1
            if not _same(decoded[theirs], state[ours]):
                disagreements.append(f"{ours}={state[ours]!r} vs {theirs}={decoded[theirs]!r}")
    assert compared > 50, f"{family}: only {compared} comparisons -- the frames were all vetoed"
    assert not disagreements, f"{family}: {disagreements[:5]}"


def test_the_one_expected_divergence_is_the_plausibility_band_and_nothing_else() -> None:
    """Named rather than left as a silent difference between two decoders.

    A reading the hand-derived decoder drops as physically implausible is one the byte map happily
    publishes, because the map's declared range for `outdoorTemperature` is the span of the byte.
    ⛔ This is a real limit of a published map used on its own, and it is recorded here so the next
    person to compare the two finds the answer instead of the question.
    """
    from haismart_hrdp import parse_full_status, profile_for

    typeid = "2008610800820324021200118012560000000000000000000000000000000040"
    model = model_for(typeid)
    assert model is not None
    outdoor = model.field("outdoorTemperature")
    assert outdoor is not None
    assert outdoor.bounds() == (-64.0, 191.0), "the byte's span, not a temperature"

    data = bytearray(127)
    data[2:4] = b"\x27\x15"
    data[ATTR_BASE + 2 * (model.field("indoorTemperature").word - 1)] = 50     # 25 °C
    data[ATTR_BASE + 2 * (outdoor.word - 1)] = 233                            # 169 °C
    state = parse_full_status(bytes(data), profile_for("AAC1UKZ01"), None, uplus_id=typeid)
    decoded = model.decode(bytes(data))

    assert state.get("outdoor_temperature") is None, "the hand-derived decoder vetoes it"
    assert decoded["outdoorTemperature"] == 169, "the map's own range permits it"
    # ...and the sentinel rule still catches the case that actually occurs in the field, which is a
    # unit with no outdoor probe reporting zero.
    data[ATTR_BASE + 2 * (outdoor.word - 1)] = 0
    assert "outdoorTemperature" not in model.decode(bytes(data))
