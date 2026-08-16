"""The panel control surface — the app's documentary authorisation, reproduced."""
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
