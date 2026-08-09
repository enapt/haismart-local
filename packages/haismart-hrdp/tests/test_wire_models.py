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


def test_the_write_frame_is_a_slice_of_the_report() -> None:
    """`write_base_word + write_word - 1` is the report word a written bit reads back at.

    This is what places the extended-46 toggles, so it is asserted rather than assumed. Checked on
    the fields whose report positions were established independently of it -- if the relation ever
    stops holding, the positions derived from it are no longer supported.
    """
    for wm in WIRE_MODELS:
        for name, token in _WRITE_TO_READ.items():
            wf, rf = wm.write_fields.get(name), wm.fields.get(token)
            if wf is None or rf is None or wf.length != rf.length:
                continue
            assert rf.word == wm.write_base_word + wf.word - 1, (
                f"{wm.family}: {name} writes w{wf.word} but reads at w{rf.word}, which is not "
                f"write_base_word ({wm.write_base_word}) + {wf.word} - 1"
            )
            assert rf.bit == wf.bit, f"{wm.family}: {name} bit moved between write and read"
