"""Rules that hold across every report family, rather than facts about one of them.

A family is added by writing a table, and a table cannot be reviewed into correctness -- so what
must be true of all of them belongs here, where the next one is checked without anybody remembering
to.
"""
from __future__ import annotations

from haismart_hrdp.wire_models import WIRE_MODELS

# --- a family that writes a setting must read it back -------------------------------------------

# Model attribute name -> the token the read map uses for the same setting. Built from the families
# that carry both, so it states the correspondence rather than guessing at it.
_WRITE_TO_READ = {
    "onOffStatus": "power",
    "healthMode": "health",
    "rapidMode": "strong",
    "muteStatus": "quiet",
    "silentSleepStatus": "sleep",
    "screenDisplayStatus": "lamp",
    "targetTemperature": "target_temperature",
    "operationMode": "operation_mode",
    "windSpeed": "wind_speed",
    "windDirectionVertical": "swing_vertical",
    "windDirectionHorizontal": "swing_horizontal",
    "selfCleaningStatus": "self_cleaning",
}

# `ecoMode` is deliberately absent from the table above. It is written on extended-36 and has no
# plain boolean read token, being a multi-level control that the eco select resolves separately --
# so listing it here would report a gap that is not one.


def test_no_family_offers_a_control_it_cannot_read_back() -> None:
    """A write-only control is worse than a missing one, and this has now happened twice.

    On extended-36 it surfaced as "cannot enable Rapid or Silent Sleep": the writes were fine and
    the next poll simply overwrote the switch, because nothing read the setting back. It was fixed
    there and the same audit was owed across the other families and not done -- so extended-46
    shipped five switches that could be written, had no state to show, and sat unavailable.

    The rule is what is asserted, not the one family that broke it, because the next family added
    will not be checked by hand either.
    """
    offenders: dict[str, list[str]] = {}
    for wm in WIRE_MODELS:
        missing = [
            name for name in wm.write_fields
            if (token := _WRITE_TO_READ.get(name)) and token not in wm.fields
        ]
        if missing:
            offenders[wm.family] = sorted(missing)
    assert not offenders, (
        "these families can write a setting they never read back, so the control would sit "
        f"unavailable: {offenders}"
    )


# Measured departures from the relation below: (family, field) pairs where a written bit does NOT
# read back at `write_base_word + write_word - 1`, each with the evidence that put it elsewhere.
#
# Both are extended-46, both are in the ten-word block that family inserts, and both were checked
# against one file whose cloud record is fresh (see `test_the_209_family_reads_the_appliance_vane`).
# Neither weakens what the relation places elsewhere: on this family it holds for words 1..3 as
# WORDS -- setpoint, mode and the entire boolean block -- and those toggles were separately
# confirmed 6/6 against that same record.
_WRITE_READ_EXCEPTIONS = {
    ("extended46", "windDirectionVertical"),   # writes w1.b0, reads report w25 (map's w20 reads 0)
    ("extended46", "windSpeed"),               # writes w2.b8, reads report w26.b9 (map's w21 = 6)
}


def test_the_write_frame_is_a_slice_of_the_report() -> None:
    """`write_base_word + write_word - 1` is the report word a written bit reads back at.

    This is what places the extended-46 toggles, so it is asserted rather than assumed. Checked on
    the fields whose report positions were established independently of it -- if the relation ever
    stops holding, the positions derived from it are no longer supported.

    ⚠️ It is a HEURISTIC, not a law, and the exceptions above are why it is stated that way: an
    appliance may take a setting in the group-set and report it somewhere else entirely. Reasoning
    from this relation is what withheld two working controls for two releases.
    """
    seen: set[tuple[str, str]] = set()
    for wm in WIRE_MODELS:
        for name, token in _WRITE_TO_READ.items():
            wf, rf = wm.write_fields.get(name), wm.fields.get(token)
            if wf is None or rf is None or wf.length != rf.length:
                continue
            if (wm.family, name) in _WRITE_READ_EXCEPTIONS:
                seen.add((wm.family, name))
                assert rf.word != wm.write_base_word + wf.word - 1, (
                    f"{wm.family}: {name} now DOES follow the relation -- delete its exception "
                    "rather than leaving a stale one here"
                )
                continue
            assert rf.word == wm.write_base_word + wf.word - 1, (
                f"{wm.family}: {name} writes w{wf.word} but reads at w{rf.word}, which is not "
                f"write_base_word ({wm.write_base_word}) + {wf.word} - 1"
            )
            assert rf.bit == wf.bit, f"{wm.family}: {name} bit moved between write and read"
    assert seen == _WRITE_READ_EXCEPTIONS, (
        f"exceptions listed for fields no family writes and reads: {_WRITE_READ_EXCEPTIONS - seen}"
    )


# --- the 209-byte family is a piecewise displacement, not a typed table -------------------------


def test_the_insert_pivot_is_stated_once() -> None:
    """The helper that builds the fields and the model's own rule must agree for every word.

    The pivot appears in two places out of necessity -- the fields are built while the model is
    being constructed -- so the risk is that one is edited and the other is not, which would put the
    device's declared attributes somewhere the hand-checked fields are not.
    """
    from haismart_hrdp.wire_models import EXTENDED46, _ext46_word

    for word in range(1, 60):
        assert _ext46_word(word) == EXTENDED46.canonical_word(word), f"disagree at w{word}"


def test_the_generated_map_reproduces_every_verified_position() -> None:
    """Generation must reproduce what captures established, or it is not the same map.

    These positions were each confirmed against real reports -- several against the manufacturer's
    own record of the same attributes -- so they are the fixed point the derivation has to hit. If
    the published map ever moves under us, this is what says so, rather than the readings quietly
    changing on somebody's dashboard.
    """
    from haismart_hrdp.wire_models import EXTENDED46

    expected = {
        "target_temperature": (20, 8, 8), "operation_mode": (21, 13, 3), "power": (22, 0, 1),
        "health": (22, 1, 1), "strong": (22, 3, 1), "quiet": (22, 4, 1),
        "sleep": (22, 5, 1), "lamp": (22, 9, 1),
        # The two the published map names but does not place HERE: they answer from the inserted
        # block, against a cloud record that agrees with this report on everything else.
        "swing_vertical": (25, 0, 4), "wind_speed": (26, 9, 3),
        "current_temperature": (35, 8, 8), "heat_capable": (36, 7, 1),
        "outdoor_temperature": (36, 8, 8), "last_changed_by": (37, 0, 2),
        "error_code": (37, 8, 8), "energy_wh": (45, 0, 32),
    }
    got = {k: (f.word, f.bit, f.length) for k, f in EXTENDED46.fields.items()}
    assert got == expected


def test_the_half_degree_setpoint_is_kept_against_the_map() -> None:
    """⚠️ Deliberate departure. Do not "correct" this to what the published map says.

    The map encodes a setpoint the classic way, as degrees above 16. This family sends half-degrees
    from zero, which is what its captures show. Taking the scaling from the map -- on a field whose
    *position* the map gets right -- would read 24 °C as 40 °C. Position from the map, scaling from
    a reading.
    """
    from haismart_hrdp.canonical_map import CANONICAL
    from haismart_hrdp.wire_models import EXTENDED46

    field = EXTENDED46.fields["target_temperature"]
    published = CANONICAL["targetTemperature"]
    assert field.word == published.word + 0, "the position still comes from the map"
    assert (field.k, field.c) == (0.5, 0.0)
    assert (published.k, published.c) != (0.5, 0.0), (
        "the map now agrees with this family, so the override and this test are obsolete"
    )


def test_an_inserted_block_no_longer_blocks_reading_declared_attributes() -> None:
    """A family with an insert is placeable in two pieces, and used to be treated as unplaceable.

    Saying "no single displacement fits" and stopping cost this family every attribute its own
    device declares, and with it the optional-feature entities -- three symptoms reported as
    separate faults, one cause.
    """
    from haismart_hrdp.wire_models import EXTENDED46

    declared = ["lockStatus", "indoorHumidity", "echoStatus", "freshAirStatus"]
    placed = EXTENDED46.model_fields(declared, 209)
    assert placed, "an insert must not mean nothing can be placed"
    # below the pivot: where the map puts it. from the pivot up: pushed along by the insert.
    from haismart_hrdp.canonical_map import CANONICAL
    for name, field in placed.items():
        c = CANONICAL[name]
        assert field.word == c.word + (10 if c.word >= 25 else 0)


def test_the_209_family_reads_and_writes_its_fan_and_up_down_vane() -> None:
    """The appliance's fan and vane answer from the INSERTED BLOCK, not from the map's own words.

    Both were withdrawn once, on the reading that the block is a dual-airflow cabinet's per-tower
    controls. The document that withdrew them refutes it: in the one file whose cloud record is
    fresh -- setpoint, indoor temperature, power and all six word-22 toggles agreeing with the
    report bit for bit -- w25 reads 2 and w26.b9 reads 1, which are that record's
    ``windDirectionVertical`` and ``windSpeed``. Its per-tower attributes are published in the same
    record as 0 / 0 and 3 / 5. A tower register cannot read the appliance's value.

    Writes go at the published positions (w1.b0, w2.b8), which every air-conditioner device type
    states identically. Whether the appliance acts on them there is a question only a write
    answers -- and now can be answered by the owner, because the readback is restored.
    """
    from haismart_hrdp.wire_models import EXTENDED46

    assert "wind_speed" in EXTENDED46.fields
    assert "swing_vertical" in EXTENDED46.fields
    assert "windSpeed" in EXTENDED46.write_fields
    assert "windDirectionVertical" in EXTENDED46.write_fields
    # The horizontal axis stays out: nothing in this family's report reads it back, and a control
    # that writes what it cannot read is the defect this suite already guards above.
    assert "windDirectionHorizontal" not in EXTENDED46.write_fields
