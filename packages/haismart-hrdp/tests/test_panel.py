"""The panel control surface — the app's documentary authorisation, reproduced."""
import pytest

from haismart_hrdp import (
    PANEL_BOOL_CONTROLS,
    PANEL_CONTROLS,
    declared_panel_controls,
)
from haismart_hrdp.canonical_map import CANONICAL_WRITE
from haismart_hrdp.uss import GRSETDAC_FIELDS


def test_every_panel_control_is_positioned_and_encodable():
    """The controls this module offers must all be placeable without a capture — either by the
    invariant frame, or by the published order (``PANEL_EXTRA_POSITIONS``, each unanimous). A control
    with no established position has no business here. All must be encodable (in GRSETDAC_FIELDS)."""
    from haismart_hrdp.panel import PANEL_EXTRA_POSITIONS

    for name in PANEL_CONTROLS:
        assert name in CANONICAL_WRITE or name in PANEL_EXTRA_POSITIONS, (
            f"{name} has no established write position"
        )
        assert name in GRSETDAC_FIELDS, f"{name} is not encodable"


def test_echostatus_is_not_a_panel_control():
    """The load-bearing exclusion: echoStatus is in the write frame and model-writable, but the app
    renders no widget for it and hardware discards the write. It must NOT be offered."""
    assert "echoStatus" in CANONICAL_WRITE
    assert "echoStatus" not in PANEL_CONTROLS
    assert "echoStatus" not in GRSETDAC_FIELDS


def test_declared_panel_controls_is_declared_minus_invisible():
    """The app's gate: a control is offered iff the device declares the attribute and it is not
    invisible. A generic over-declaring model with no invisible flags offers nothing (we don't know
    its real feature set)."""
    # a unit that declares electric heating and fresh air, with fresh air marked absent (invisible)
    model = {
        "attributes": [{"name": "electricHeatingStatus"}, {"name": "freshAirStatus"},
                       {"name": "echoStatus"}],
        "invisible_attributes": ["freshAirStatus"],
    }
    offered = declared_panel_controls(model)
    assert "electricHeatingStatus" in offered          # declared, visible, a panel control
    assert "freshAirStatus" not in offered             # declared but invisible
    assert "echoStatus" not in offered                 # declared, visible, but NOT a panel control
    # no invisible_attributes key -> feature set unknown -> nothing offered
    assert declared_panel_controls({"attributes": [{"name": "electricHeatingStatus"}]}) == frozenset()


def test_panel_bool_controls_exclude_the_read_only_features():
    """Attributes the model marks writable but the app shows no widget for stay read-only, never
    switches: echoStatus, and the status-only ones."""
    # 10degreeHeatingStatus is the notable one: it IS in the write frame (so it looks encodable) but
    # the authoritative panel renders no widget for it, so it is read-only like echoStatus.
    for read_only in ("echoStatus", "heatAccumulationStatus", "humidificationStatus",
                      "intelligenceStatus", "10degreeHeatingStatus"):
        assert read_only not in PANEL_BOOL_CONTROLS


def test_each_withheld_order_position_still_has_its_reason():
    """The five derived-but-withheld positions, re-measured against the shipped model bundle.

    Each was derived the same way the shipped ``PANEL_EXTRA_POSITIONS`` were -- unanimously, from
    the products' own published group-set order -- and each is held back for a reason that is a
    *measurement*, not a caution. Measurements expire: a catalogue re-sweep can make an attribute
    visible, or move a product off a read-only family. So the reasons are checked here rather than
    remembered, and this test failing is good news -- it means one of them can now be surfaced.
    """
    from haismart_hrdp.canonical_map import CANONICAL
    from haismart_hrdp.model_rules import _bundle
    from haismart_hrdp.panel import WITHHELD_ORDER_POSITIONS
    from haismart_hrdp.wire_models import frame_write_fields

    models = _bundle()["models"]

    def visible(entry) -> set[str]:
        return {a["name"] for a in entry.get("attributes") or () if not a.get("invisible")}

    def declared(entry) -> set[str]:
        return {a["name"] for a in entry.get("attributes") or ()}

    checked = set()
    for name, ((word, bit, _length), reason) in WITHHELD_ORDER_POSITIONS.items():
        shows_it = [e for e in models.values() if name in visible(e)]
        if reason == "invisible-everywhere":
            # nothing to surface: every product that declares it says this unit does not have it
            assert not shows_it, f"{name} is now visible on {len(shows_it)} products"
            assert any(name in declared(e) for e in models.values()), (
                f"{name} is not declared at all any more -- the entry is stale"
            )
        elif reason == "contested":
            # the shared map places another attribute at the same word and bit; the products
            # declaring this one overwhelmingly declare that one too, so a placement under this
            # name would be reading the other attribute's bits on most of them.
            rival = [
                other for other, c in CANONICAL.items()
                if other != name and c.word == word + 19 and c.bit == bit
            ]
            assert rival, f"{name}: nothing else is placed at w{word + 19}.b{bit} any more"
            with_rival = [e for e in models.values()
                          if name in declared(e) and set(rival) & declared(e)]
            declares_it = [e for e in models.values() if name in declared(e)]
            assert len(with_rival) > len(declares_it) / 2, (
                f"{name} no longer travels with {rival} on most products"
            )
        elif reason == "read-only-family":
            # the only units that could show it are ones this project already refuses to command,
            # because their published order refutes the shared frame -- which is the very frame the
            # position was derived against.
            assert shows_it, f"{name} is visible nowhere; its reason should be invisible-everywhere"
            for entry in shows_it:
                assert not frame_write_fields(
                    entry.get("group_set_order"), entry.get("uplus_id")
                ), f"{name}: {entry.get('model')} now accepts frame writes"
        else:                                             # pragma: no cover - guards the vocabulary
            raise AssertionError(f"unknown withholding reason {reason!r}")
        checked.add(name)
    assert checked == set(WITHHELD_ORDER_POSITIONS)


def test_compact12_writes_presence_at_its_own_published_position():
    """compact-12 places `humanSensingStatus` where its OWN profile puts it, with the two codes
    that profile names -- not the shared frame's four.

    The lineage's group-command line reads `20200H#2&9,12,1*00:00,03:01`: word 9, bit 12, one bit,
    STD 0 -> EPP 0 and STD 3 -> EPP 1. Two attributes on the same line already reproduce the shipped
    maps exactly (`20200D` is `operationMode`, `20200F` is `windSpeed`), which is what makes the
    reading of the format a measurement rather than an interpretation.

    ⚠️ The shared frame gives this attribute a TWO-bit slot carrying off/avoid/follow/on. Here it is
    one bit and only the ends exist, so `avoid` and `follow` must be REFUSED rather than silently
    truncated into the neighbouring bit.
    """
    from haismart_hrdp.wire_models import COMPACT12

    wf = COMPACT12.write_fields["humanSensingStatus"]
    assert (wf.word, wf.bit, wf.length) == (9, 12, 1)
    assert wf.std_to_epp == {0: 0, 3: 1}

    # It writes the bit its own READ map already publishes, so the state reads back where it was
    # written -- the write<->read relation every family here is held to.
    assert COMPACT12.fields["human_sensing"].word == wf.word
    assert COMPACT12.fields["human_sensing"].bit == wf.bit

    baseline = bytes.fromhex("001d003b000000000000000300000000000000000000000b")
    on = COMPACT12.encode_control(baseline, {"humanSensingStatus": 3})
    assert [i for i, (a, b) in enumerate(zip(baseline, on, strict=True)) if a != b] == [16]  # w9 high byte
    assert on[16] & 0x10                                                        # bit 12
    assert COMPACT12.encode_control(on, {"humanSensingStatus": 0}) == baseline

    for unsupported in (1, 2):          # avoid / follow: no code for them on this lineage
        with pytest.raises(ValueError):
            COMPACT12.encode_control(baseline, {"humanSensingStatus": unsupported})


def test_compact12_reads_presence_back_as_the_code_it_writes():
    """The value read back is in the same representation the encoder accepts, so the control shows
    the appliance's real state: raw bit set -> STD 3, clear -> STD 0."""
    from haismart_hrdp.wire_models import COMPACT12
    from tests.test_uss import STATUS_117_OFF

    assert COMPACT12.current_write_value(STATUS_117_OFF, "humanSensingStatus") == 0
    lit = bytearray(STATUS_117_OFF)
    lit[92 + (9 - 1) * 2] |= 0x10                    # report word 9, bit 12
    assert COMPACT12.current_write_value(bytes(lit), "humanSensingStatus") == 3
    assert COMPACT12.decode(bytes(lit))["human_sensing"] is True
