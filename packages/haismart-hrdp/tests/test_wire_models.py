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
# Empty as of the ext46 write retarget: the two former exceptions (extended-46
# windDirectionVertical/windSpeed) used to write the shared-frame slots at group-set w1/w2 -- which
# on this twin-tower family are the LEFT TOWER -- and read back at report w25/w26. They now write
# group-set words 6/7, the appliance's own fields in the inserted block, which DO satisfy the
# relation (write w6 -> report w25, write w7 -> report w26). See
# `test_ext46_writes_the_appliance_vane_not_the_tower`.
_WRITE_READ_EXCEPTIONS: set[tuple[str, str]] = set()


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

    Writes now go at the appliance's own positions in the inserted block (group-set words 6/7 =
    report w25/w26), not the shared-frame slots -- see
    ``test_ext46_writes_the_appliance_vane_not_the_tower`` for why. Whether the appliance acts on
    them is a question only a write answers, but the readback is at the same position, so it is
    checkable.
    """
    from haismart_hrdp.wire_models import EXTENDED46

    assert "wind_speed" in EXTENDED46.fields
    assert "swing_vertical" in EXTENDED46.fields
    assert "windSpeed" in EXTENDED46.write_fields
    assert "windDirectionVertical" in EXTENDED46.write_fields
    # The horizontal axis stays out: nothing in this family's report reads it back, and a control
    # that writes what it cannot read is the defect this suite already guards above.
    assert "windDirectionHorizontal" not in EXTENDED46.write_fields


def test_ext46_writes_the_appliance_vane_not_the_tower() -> None:
    """The vane/fan writes target the appliance's own fields, in the inserted block -- not the
    shared-frame slots, which on this twin-tower family are the LEFT TOWER.

    Three independent lines settle where they go, none needing hardware:

    * the write positions satisfy the universal write<->read relation against the capture-confirmed
      read map: group-set word 6 -> report w25 (where ``swing_vertical`` reads), word 7 -> report
      w26 (where ``wind_speed`` reads). Bits match too.
    * the frame reaches them: ``word_count`` covers group-set word 7.
    * they are NOT at the shared single-flow slots (w1.b0 / w2.b8), because on this family the
      vendor's own group-set order puts ``windDirectionVerticalL`` / ``windSpeedL`` (the towers)
      there -- see ``test_ext46_shared_slots_are_the_towers_in_the_published_order``.
    """
    from haismart_hrdp.wire_models import EXTENDED46 as m

    v, f = m.write_fields["windDirectionVertical"], m.write_fields["windSpeed"]
    # frame is long enough to hold the fan at group-set word 7
    assert m.word_count >= 7
    # write word -> report word, against the capture-confirmed read positions
    assert m.write_base_word + v.word - 1 == m.fields["swing_vertical"].word == 25
    assert m.write_base_word + f.word - 1 == m.fields["wind_speed"].word == 26
    assert (v.bit, v.length) == (m.fields["swing_vertical"].bit, m.fields["swing_vertical"].length)
    assert (f.bit, f.length) == (m.fields["wind_speed"].bit, m.fields["wind_speed"].length)
    # and NOT the shared-frame slots (those are the towers here)
    assert (v.word, v.bit) != (1, 0) and (f.word, f.bit) != (2, 8)


# --- families that keep a different attribute at a shared-frame position -------------------------

TWIN_TOWER = "2008610800820324021200118017740000000000000000000000000000000040"
CLASSIC = "2008610800820324021200118012560000000000000000000000000000000040"


def test_a_twin_tower_family_refuses_the_fields_whose_bits_it_reuses():
    """The group-set is packed by POSITION, so a family that keeps a different attribute at one of
    the shared frame's positions must not be sent the shared attribute -- it would start the wrong
    function rather than fail.

    Measured across every published product: these families put their LEFT TOWER's vane and fan
    where a single-flow unit puts the appliance's, and `sterilizationSwitch` where the shared frame
    puts `selfCleaningStatus`. Unanimous across every member of each family.
    """
    from haismart_hrdp.family_write import displaced_write_fields, write_overrides

    displaced = displaced_write_fields(TWIN_TOWER)
    assert "windDirectionVertical" in displaced
    assert "windSpeed" in displaced
    # the one that matters most: our self-clean button would command sterilization
    assert "selfCleaningStatus" in displaced

    overrides = write_overrides(TWIN_TOWER)
    assert overrides["windDirectionVerticalL"] == (1, 0, 4)
    assert overrides["windDirectionVerticalR"] == (1, 4, 4)
    assert overrides["windSpeedL"] == (2, 8, 3)
    assert overrides["sterilizationSwitch"] == (5, 4, 1)


def test_a_family_with_no_departure_refuses_nothing():
    """Almost every family uses the shared frame unchanged, and must lose no control over this."""
    from haismart_hrdp.family_write import displaced_write_fields

    assert displaced_write_fields(CLASSIC) == frozenset()
    assert displaced_write_fields(None) == frozenset()
    assert displaced_write_fields("an appliance we have never met") == frozenset()


def test_a_field_retargeted_away_from_the_reused_slot_is_not_displaced():
    """A reuse is a fact about a POSITION, not a name -- the check must be against the bits the
    write would actually land on.

    extended-46 is the family this distinguishes: its shared vane/fan slots belong to the towers,
    but its own write map moved the appliance's vane and fan into the append region (words 6/7),
    which touches no reused bit. Refusing those by NAME is what silently re-withdrew that family's
    fan and swing in v0.48.0 (issue #6) after v0.47.0 had restored them.
    """
    from haismart_hrdp.family_write import displaced_at

    # the retargeted positions touch nothing the family reuses
    assert displaced_at(TWIN_TOWER, "windDirectionVertical", 6, 0, 4) is False
    assert displaced_at(TWIN_TOWER, "windSpeed", 7, 9, 3) is False
    # a write that WOULD land on a reused slot is still refused
    assert displaced_at(TWIN_TOWER, "windDirectionVertical", 1, 0, 4) is True
    assert displaced_at(TWIN_TOWER, "windSpeed", 2, 8, 3) is True
    assert displaced_at(TWIN_TOWER, "selfCleaningStatus", 5, 4, 1) is True
    # overlap counts, not just an identical start -- one shared bit runs the wrong function
    assert displaced_at(TWIN_TOWER, "windDirectionVertical", 1, 2, 1) is True
    # a family with no departure refuses nothing, wherever the write lands
    assert displaced_at(CLASSIC, "windSpeed", 2, 8, 3) is False
    assert displaced_at(None, "windSpeed", 2, 8, 3) is False


def test_the_newer_spelling_at_the_older_names_position_is_not_displaced_at_that_position():
    """The alias rule carries over to the position-aware check: `tenDegreeHeatingStatus` at
    (3, 8, 1) is `10degreeHeatingStatus` under another name, so writing the older name there is the
    same function, not a collision."""
    from haismart_hrdp.family_write import WRITE_OVERRIDES, displaced_at

    renamed = [u for u, o in WRITE_OVERRIDES.items() if "tenDegreeHeatingStatus" in o]
    assert renamed
    for uplus in renamed:
        assert displaced_at(uplus, "10degreeHeatingStatus", 3, 8, 1) is False


def test_no_registered_family_write_map_lands_on_a_bit_its_family_reuses():
    """Registry-wide invariant: a registered family's own write map must never drive a bit its
    published family gives to a different attribute. This is what licenses offering a control on a
    registered family whenever its map carries the field -- the map has already been kept clear of
    the family's reused positions (extended-46's retarget to words 6/7 being the case in point)."""
    from haismart_hrdp.family_write import displaced_at
    from haismart_hrdp.wire_models import WIRE_MODELS

    checked = 0
    for wm in WIRE_MODELS:
        for uplus in wm.uplus_ids:
            for name, wf in wm.write_fields.items():
                assert not displaced_at(uplus, name, wf.word, wf.bit, wf.length), (
                    f"{wm.family}: {name} at w{wf.word}.b{wf.bit} collides with a reused bit"
                )
                checked += 1
    assert checked, "expected at least one registered write field to check"


def test_the_same_function_under_a_newer_spelling_is_not_a_displacement():
    """`tenDegreeHeatingStatus` sits exactly where the shared frame puts `10degreeHeatingStatus`.

    That is one attribute with two spellings, not a reused bit, so nothing may be refused for it --
    otherwise a rename would silently cost those units a control.
    """
    from haismart_hrdp.family_write import ALIASES, WRITE_OVERRIDES, displaced_write_fields

    renamed = [u for u, o in WRITE_OVERRIDES.items() if "tenDegreeHeatingStatus" in o]
    assert renamed, "expected at least one family using the newer spelling"
    assert ALIASES["tenDegreeHeatingStatus"] == "10degreeHeatingStatus"
    for uplus in renamed:
        assert "10degreeHeatingStatus" not in displaced_write_fields(uplus)


def test_every_recorded_departure_is_a_real_departure():
    """No entry may merely restate the shared frame -- that would be noise carrying risk."""
    from haismart_hrdp.canonical_map import CANONICAL_WRITE
    from haismart_hrdp.family_write import WRITE_OVERRIDES

    shared = {n: (f.word, f.bit, f.length) for n, f in CANONICAL_WRITE.items()}
    for uplus, overrides in WRITE_OVERRIDES.items():
        assert overrides, f"{uplus} has an empty override map"
        for name, pos in overrides.items():
            assert shared.get(name) != pos, f"{uplus}:{name} restates the shared frame"


def test_ext36_write_table_restates_the_published_frame():
    """`_EXT36_WRITE` is typed by hand (it predates `CANONICAL_WRITE`), but every position in it is
    a claim about the published group-set frame, which does not displace between families. Pin the
    two together so a regenerated map cannot silently diverge from the table.

    `ecoMode` is the one exemption: no published model positions it (its place came from cycling a
    real unit through its levels), so the frame has nothing to pin it to. The order-derived panel
    controls (``PANEL_EXTRA_POSITIONS``) are pinned to their own source instead of the frame."""
    from haismart_hrdp.canonical_map import CANONICAL_WRITE
    from haismart_hrdp.panel import PANEL_EXTRA_POSITIONS
    from haismart_hrdp.wire_models import _EXT36_WRITE

    for name, wf in _EXT36_WRITE.items():
        if name == "ecoMode":
            assert name not in CANONICAL_WRITE
            continue
        if name in PANEL_EXTRA_POSITIONS:                       # order-derived, not in the frame
            assert (wf.word, wf.bit, wf.length) == PANEL_EXTRA_POSITIONS[name], name
            continue
        cf = CANONICAL_WRITE[name]
        assert (wf.word, wf.bit, wf.length) == (cf.word, cf.bit, cf.length), name


def test_compact_family_resolves_by_the_identifier_all_its_products_share():
    """The compact family's 509 catalogue products all carry one 32-character identifier — the
    family itself — and the registration must match what the shipped bundle says, so an appliance
    announcing it resolves before its first report instead of waiting for a 117-byte length match."""
    import gzip
    import json
    from pathlib import Path

    from haismart_hrdp import model_rules
    from haismart_hrdp.wire_models import COMPACT12, select_wire_model

    (family_id,) = COMPACT12.uplus_ids
    assert select_wire_model(0, family_id) is COMPACT12   # id alone, no plausible length
    bundle = json.loads(gzip.decompress(Path(model_rules.RULES_PATH).read_bytes()))
    members = bundle["by_uplus_id"][family_id]
    assert len(members) >= 509
    assert all(bundle["models"][code]["uplus_id"] == family_id for code in members)


def test_grsetdac_families_carry_the_frame_panel_controls():
    """Every grSetDAC family (extended-36, extended-46) offers the panel's frame-positioned controls
    at the same invariant positions, so the app's control surface reaches them too — not just the
    classic family. Compact-12 uses a different group command and layout, so it does NOT get them
    from the frame (its own controls come from its own map)."""
    from haismart_hrdp.canonical_map import CANONICAL_WRITE
    from haismart_hrdp.panel import PANEL_CONTROLS
    from haismart_hrdp.wire_models import COMPACT12, EXTENDED36, EXTENDED46

    frame_panel = {n for n in PANEL_CONTROLS if n in CANONICAL_WRITE}
    assert frame_panel, "expected some panel controls positioned by the frame"
    for wm in (EXTENDED36, EXTENDED46):
        for name in frame_panel:
            assert name in wm.write_fields, f"{wm.family} missing panel control {name}"
            wf = wm.write_fields[name]
            cf = CANONICAL_WRITE[name]
            assert (wf.word, wf.bit, wf.length) == (cf.word, cf.bit, cf.length), name
    # compact-12 is a different group command / layout — not extended by the shared frame.
    # ⚠️ The invariant is about POSITION, not about the name. This family may well control an
    # attribute the frame also positions -- it publishes its own group-command line and
    # `humanSensingStatus` is on it -- but it must reach it at ITS OWN position, never inherit the
    # frame's. Asserting on names alone would forbid a control the vendor's own description
    # authorises, which is the mistake `family_write.displaced_at` exists to avoid on the write path.
    for name in frame_panel & set(COMPACT12.write_fields):
        wf, cf = COMPACT12.write_fields[name], CANONICAL_WRITE[name]
        assert (wf.word, wf.bit, wf.length) != (cf.word, cf.bit, cf.length), (
            f"compact-12 places {name} at the shared frame's position -- it must come from its own "
            f"published map, not be inherited"
        )


def test_compact_single_parameter_controls_write_by_command_and_read_back():
    """Compact-12 controls its optional toggles one parameter at a time (not through the group set):
    the on/off EPP command carries the value, and state reads back from the toggle's own bit. This
    is how the app reaches electric-heat and fresh air on that family."""
    from haismart_hrdp.wire_models import COMPACT12

    sp = COMPACT12.single_param_fields
    assert "electricHeatingStatus" in sp and "freshAirStatus" in sp
    # the command carries the value; there is no data payload
    assert sp["electricHeatingStatus"].command(1) == b"\x4d\x05"   # 开电 (on)
    assert sp["electricHeatingStatus"].command(0) == b"\x4d\x04"   # 关电 (off)
    assert sp["freshAirStatus"].command(1) == b"\x4d\x1f"
    # health and self-clean, from the same published records
    assert sp["healthMode"].command(1) == b"\x4d\x09"              # 开康 (on)
    assert sp["healthMode"].command(0) == b"\x4d\x08"              # 关康 (off)
    assert sp["selfCleaningStatus"].command(1) == b"\x4d\x26"      # 开自 (start)
    assert sp["selfCleaningStatus"].command(0) is None             # start-only: no off command

    # read-back: set electric-heat's bit (w9.b1) in a report and confirm single_param_value sees it
    report = bytearray(117)
    off = 92 + (9 - 1) * 2                                          # word 9
    report[off + 1] = 0b10                                         # low byte, bit 1 set
    assert COMPACT12.single_param_value(bytes(report), "electricHeatingStatus") == 1
    report[off + 1] = 0
    assert COMPACT12.single_param_value(bytes(report), "electricHeatingStatus") == 0
    # health reads back from w9.b3, self-clean from w9.b2 — the bits their records state
    report[off + 1] = 0b1000
    assert COMPACT12.single_param_value(bytes(report), "healthMode") == 1
    report[off + 1] = 0b0100
    assert COMPACT12.single_param_value(bytes(report), "selfCleaningStatus") == 1


def test_compact_single_param_frame_is_a_bare_command_no_payload():
    """The single-parameter frame is the on/off command with no data — like smartair2's 4d02/4d03
    power. Distinct from the group-set frame (4d5f + a full word block)."""
    from haismart_hrdp.uss import build_epp_frame

    frame = build_epp_frame(0x01, b"\x4d\x05", b"")
    assert frame[:2] == b"\xff\xff" and frame[10:12] == b"\x4d\x05"
    assert (frame[2] + sum(frame[3:-1])) & 0xFF == frame[-1]       # checksum holds


def test_a_twin_tower_order_is_not_offered_the_horizontal_vane_frame_position() -> None:
    """The order gate closes the hole the bit-reuse table cannot see: same name, moved position.

    Every twin-tower family publishes the appliance's own vane, fan AND horizontal vane in the
    appended tail of its group-set order, past the frame's words. The vane and fan were already
    refused (their frame slots hold the towers, which the reuse table records) -- but nothing else
    was ever placed at the horizontal vane's slot, so the reuse table is structurally blind there
    and the frame position was still offered. On that hardware it writes tower/auxiliary bits.
    The product's own order is the evidence: a name it lists after the frame's last word is not at
    the frame's position, whatever the name.
    """
    from haismart_hrdp.wire_models import frame_write_fields

    # the head of a real 108-product twin-tower family's order (condensed), with the appliance's
    # vane / horizontal vane / fan in the appended tail exactly as published
    order = (
        "targetTemperature", "windDirectionVerticalR", "windDirectionVerticalL",
        "operationMode", "windSpeedL", "screenDisplayStatus", "silentSleepStatus",
        "muteStatus", "rapidMode", "electricHeatingStatus", "healthMode", "onOffStatus",
        "humanSensingStatus", "energySavingStatus", "lightStatus", "sterilizationSwitch",
        "freshAirStatus",
        # -- appended tail --
        "windSpeedR", "windDirectionHorizontalR",
        "windDirectionVertical", "windDirectionHorizontal", "windSpeed",
    )
    fields = frame_write_fields(order, TWIN_TOWER)

    # the moved trio is refused -- horizontal by the order gate, vane and fan doubly (reuse + order)
    assert "windDirectionHorizontal" not in fields
    assert "windDirectionVertical" not in fields
    assert "windSpeed" not in fields
    # the corroborated head keeps its controls: this is a gate, not a retreat
    for kept in ("targetTemperature", "operationMode", "onOffStatus", "muteStatus",
                 "freshAirStatus", "lightStatus", "energySavingStatus"):
        assert kept in fields, kept


def test_an_order_the_frame_cannot_explain_offers_no_writes_at_all() -> None:
    """Two families (30 products) publish a group-set order unrelated to the shared frame --
    rank-correlation with the frame's positions is near zero, so it is not the frame with a few
    moved names, it is some other layout. Writing any frame position there is a guess, and a
    guessed group-set runs wrong functions silently. The whole write path must stay closed until
    someone with the hardware supplies evidence; the read path is unaffected (report layouts are
    verified against the report itself, and the read frame is not the write frame)."""
    from haismart_hrdp.wire_models import frame_write_fields

    # the published order of the 12-product 1850 family, verbatim
    order = (
        "targetTemperature", "windDirectionHorizontal", "windAvoidance",
        "windDirectionVertical", "healthMode", "electricHeatingStatus", "onOffStatus",
        "aiSwitch", "energySavingStatus", "operationMode", "silentSleepStatus", "lightStatus",
        "humanSensingStatus", "uvSterilizationSwitch", "mouldProof", "preventHeatstroke",
        "preventSupercooling", "freshAirStatus", "freshWindSpeed", "selfSweepingStatus",
        "cleanningMode", "targetHumidity", "windSpeed", "rapidMode", "muteStatus",
        "screenDisplayStatus", "echoStatus", "drying", "constDehumidificationStatus",
        "warnStatus",
    )
    assert frame_write_fields(order, "2008610800820324021200118018500000000000000000000000000000000040") == {}
    # and with no uPlusId at all, the order alone still refuses -- the evidence is the order
    assert frame_write_fields(order, None) == {}
