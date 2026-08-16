"""The app's control surface, as data — which attributes it renders as controls, and how.

The vendor app decides what to offer with a documentary rule, not by probing hardware. Its own panel
code resolves a feature as ``device declares the attribute ∧ it is not invisible ∧ the panel has a
widget for it`` (plus an occasional typeid gate). So the set of controls the app offers for a device
is computable from data we hold — the digital model (declared attributes + ``invisible`` flags) and
the panel's widget table — with no capture and no unit. This module is that widget table.

It is the authorising layer above the wire map: :mod:`haismart_hrdp.canonical_map` says *where* an
attribute is written, this says *whether the app offers a control for it at all*. An attribute in the
map but absent here is one the app can encode but never renders (``echoStatus`` is the type case — in
the write frame, model-writable, and the app shows no widget for it, so we don't either).

Deliberately NOT here, though the device model declares them writable: ``echoStatus`` (no widget;
hardware discards it), ``heatAccumulationStatus``, ``humidificationStatus``, ``intelligenceStatus``
(no widget in the panel action set), and ``10degreeHeatingStatus`` (the 10 °C keep-warm — the
authoritative panel renders NO widget for it, confirmed against the current SEA panel bundle; it was
briefly offered here on the same misreading the gate exists to prevent, and is now read-only, as the
app leaves it). Presence in the model is not a control; a panel widget is.

Positions come from :data:`~haismart_hrdp.canonical_map.CANONICAL_WRITE` (the invariant group-set
frame, identical across every published air-conditioner device type). The controls listed here are
exactly those the frame positions, so a caller can offer any of them on any family without a
per-attribute capture. Controls the app renders whose position is *not* in the frame (the w5
order-derived block — ``mouldProof``/``drying``/… — and the dual-airflow ``*L``/``*R`` set) are
tracked in ``docs/FUTURE_WORK.md`` and are added here as their positions are wired in.
"""
from __future__ import annotations

from collections.abc import Mapping

#: Boolean panel controls (rendered as switches), by attribute name -> stable slug / translation key.
#: Every one is positioned by the invariant write frame (``CANONICAL_WRITE``), verified by the test
#: in ``test_panel.py``, so it needs no family-specific placement.
PANEL_BOOL_CONTROLS: Mapping[str, str] = {
    "electricHeatingStatus": "electric_heating",
    "freshAirStatus": "fresh_air",
    "lightStatus": "ambient_light",
    # The boolean energy-save toggle (distinct from the multi-level `generatorMode` "eco" ladder,
    # which keeps its own select). The panel renders it with the plain declared-and-not-invisible
    # gate, and the invariant frame positions it at w5.b6 — a position no family reuses.
    "energySavingStatus": "energy_saving",
    # Positioned not by the invariant frame but by the published group-set ORDER — each placed
    # unanimously across the 83 products that declare it (exact-fit against the full frame as
    # anchors), reproducing the positions in ``PANEL_EXTRA_POSITIONS``. See item 5 of FUTURE_WORK.
    "mouldProof": "mould_proof",
    "drying": "drying",
    "preventHeatstroke": "prevent_heatstroke",
}

#: Positions for panel controls the invariant frame (``CANONICAL_WRITE``) does NOT carry, derived
#: from the published group-set order (word, bit, length). Kept here rather than in ``canonical_map``
#: because that file is generated from the bundled profiles, which predate these attributes; each was
#: confirmed unanimous across every product that declares it (83 each). The write/read layers merge
#: these with the frame positions. Only add one here once its order placement is unanimous — a wrong
#: write position decodes silently.
PANEL_EXTRA_POSITIONS: Mapping[str, tuple[int, int, int]] = {
    "mouldProof": (5, 14, 1),
    "drying": (5, 13, 1),
    "preventHeatstroke": (5, 15, 1),
}

#: Multi-state panel controls (rendered as selects): attribute -> (slug, {wire value: state token}).
#: The state tokens and their wire values are the vendor's own, read from the model's enum
#: descriptions (NOT guessed); a wire value not in the map is dropped rather than shown as a code.
#:
#: ⚠️ ``freshWindSpeed`` is deliberately NOT here. The authoritative panel offers FIVE values —
#: close(0), low(1), high(2), rated(3), mid(4) — and writes them by NAMED ATTRIBUTE, not through the
#: group set; the invariant frame gives it only a **2-bit** slot (w4.b4/2, holds 0..3), which cannot
#: hold value 4 (mid). So it cannot be written faithfully through our group-set path, and it stays
#: withdrawn until either its real frame width or a named-attribute write channel is available. (An
#: earlier version guessed {0:off,1:low,2:medium,3:high}; the panel's own value list settles it —
#: value 2 is HIGH, value 4 is mid, and there is no "off/medium/high" ordering to assume. Read the
#: listed enum, don't guess.)
PANEL_ENUM_CONTROLS: Mapping[str, tuple[str, Mapping[int, str]]] = {
    "humanSensingStatus": ("human_sensing", {0: "off", 1: "avoid", 2: "follow", 3: "on"}),
}

#: Every attribute this module classifies as a panel control (bool or enum).
PANEL_CONTROLS: frozenset[str] = frozenset(PANEL_BOOL_CONTROLS) | frozenset(PANEL_ENUM_CONTROLS)


def declared_panel_controls(model) -> frozenset[str]:
    """The panel controls a device declares and does not mark invisible — the app's own gate,
    restricted to the controls this module classifies.

    This is `device declares the attribute ∧ it is not invisible` — two of the three inputs the app
    uses; the third (a panel widget exists) is :data:`PANEL_CONTROLS` itself. Empty unless the model's
    real feature set is known (the ``invisible_attributes`` key is present), because a generic model
    over-declares and only the invisible flags say which attributes a unit actually has. A caller
    still has to confirm the family can *write* the field's position (``coordinator.supports_field``);
    this answers only "would the app offer a control for it".
    """
    from .features import _attribute_names, _known_feature_set

    if not _known_feature_set(model):
        return frozenset()
    return PANEL_CONTROLS & _attribute_names(model)
