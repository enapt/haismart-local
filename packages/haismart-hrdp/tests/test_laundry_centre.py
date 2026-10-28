"""A twin washer + dryer (class 0504) -- the first appliance here to split its state across TWO status
reports, and the first non-AC whose report length collides with an air-conditioner family's.

`fixtures/laundry_0504.json` is a real HWD140-BD14LCGNU1 laundry centre, captured over the LAN by the
integration's own diagnostics: the dryer's ``6D01`` report (165 B, running Ai Dry), the washer's
``6D02`` report (225 B, idle after a finished cycle), and Haier's cloud shadow read at the same
moment. The cloud is the independent witness: every field the map places is checked against it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from haismart_hrdp.appliance import ApplianceKind, kind_for
from haismart_hrdp.device_model import model_for
from haismart_hrdp.features import declared_attribute_names
from haismart_hrdp.uss import epp_command

CAPTURE = json.loads((Path(__file__).parent / "fixtures" / "laundry_0504.json").read_text("utf-8"))
TYPEID = CAPTURE["typeid"]
FRAMES = {name: bytes.fromhex(hex_) for name, hex_ in CAPTURE["frames"].items()}
CLOUD = CAPTURE["reported_values_now"]
DECLARED = frozenset(declared_attribute_names(CAPTURE["digital_model"]))


def _agrees(value: object, cloud: str) -> bool:
    """The cloud shadow is all strings: ``"true"``, ``"470"``, ``"0.00"``."""
    if isinstance(value, bool):
        return cloud == ("true" if value else "false")
    try:
        return float(value) == float(cloud)
    except (TypeError, ValueError):
        return str(value) == cloud


def test_it_is_identified_as_laundry_from_its_typeid() -> None:
    assert TYPEID[16:20] == "0504"
    assert kind_for(TYPEID) is ApplianceKind.LAUNDRY


def test_its_cloud_label_alone_does_not_make_a_0501_washer_laundry() -> None:
    """⛔ "Roller Washer" is what the cloud calls this unit, and very likely other drums too. A 0501
    front loader has generic controls today; a label must not quietly make it read-only."""
    washer_0501 = "201c51890c31c30805010021800239584d000000000000000000000000000140"
    assert kind_for(washer_0501, "Roller Washer") is ApplianceKind.OTHER


def test_the_dryer_and_the_washer_each_answer_their_own_status_command() -> None:
    assert epp_command(FRAMES["6d01_dryer_running"]).hex() == "6d01"
    assert epp_command(FRAMES["6d02_washer_idle"]).hex() == "6d02"


#: The dryer's report is one word shorter than its map's extent, so `placeable_limit` withholds the
#: fields past the first omitted word. The cloud agrees with what those words hold, but one capture
#: is not the evidence that rule asks for, so they stay withheld until more captures exist.
_WITHHELD_6D01 = {
    "dryerAirWashMode", "dryerDryMode", "dryerEndDisplayDuration", "dryerWeight",
    "dryerWindForceLevel",
}


@pytest.mark.parametrize(
    ("frame", "status_cmd", "withheld"),
    [("6d01_dryer_running", "6D01", _WITHHELD_6D01), ("6d02_washer_idle", "6D02", set())],
)
def test_every_placed_field_agrees_with_the_cloud(
    frame: str, status_cmd: str, withheld: set[str]
) -> None:
    """Not a handful of fields: every one the map places in that report, against the cloud."""
    model = model_for(TYPEID)
    assert model is not None
    # cae_type 13 is a 20-byte text block (the local programme names), which `decode` leaves out.
    placed = {f.name for f in model.fields_for(status_cmd) if f.cae_type != 13}
    state = model.decode(FRAMES[frame], status_cmd=status_cmd, only=DECLARED)
    assert placed and set(state) == (placed & DECLARED) - withheld
    disagree = {k: (v, CLOUD[k]) for k, v in state.items() if not _agrees(v, CLOUD[k])}
    assert not disagree, disagree


def test_read_with_the_dryers_positions_the_washer_report_is_wrong() -> None:
    """Why the command matters: the 6D01 map over a 6D02 report is a confident wrong answer."""
    model = model_for(TYPEID)
    assert model is not None
    misread = model.decode(FRAMES["6d02_washer_idle"], only=DECLARED)
    assert misread.get("dryerRemainingDryTime") != int(CLOUD["dryerRemainingDryTime"])


def test_the_dryer_report_moves_between_idle_and_running() -> None:
    model = model_for(TYPEID)
    assert model is not None
    idle = model.decode(FRAMES["6d01_dryer_idle"], only=DECLARED)
    running = model.decode(FRAMES["6d01_dryer_running"], only=DECLARED)
    assert (idle["dryerRunningMode"], running["dryerRunningMode"]) == (2, 1)     # paused -> start
    assert (idle["dryerCyclePhase"], running["dryerCyclePhase"]) == (0, 8)       # standby -> sensing
    assert idle["dryerDoorStatus"] is True and running["dryerDoorLockStatus"] is True


# --- labels -----------------------------------------------------------------------------------

_CJK = re.compile(r"[　-鿿＀-￯]")


def _laundry_specs():
    from haismart_hrdp.entity_spec import specs_for

    model = model_for(TYPEID)
    assert model is not None
    return specs_for(
        model, CAPTURE["digital_model"]["attributes"], status_cmd=("6D01", "6D02", "7D01")
    )


def test_no_state_this_unit_can_show_is_left_in_chinese() -> None:
    left = {
        f"{spec.attribute}={value}": label
        for spec in _laundry_specs()
        for value, label in spec.options
        if _CJK.search(label)
    }
    assert not left, left


def test_no_two_values_of_one_attribute_share_a_label() -> None:
    """Home Assistant dedupes an enum's options, so a shared label would hide a state."""
    clashes = {
        spec.attribute: labels
        for spec in _laundry_specs()
        if len(labels := [label for _, label in spec.options]) != len(set(labels))
    }
    assert not clashes, clashes


def test_the_end_of_cycle_states_keep_the_labels_automations_use() -> None:
    options = {spec.attribute: dict(spec.options) for spec in _laundry_specs()}
    assert options["dryerCyclePhase"]["6"] == "Finished"
    assert options["dryerCyclePhase"]["7"] == "Anti-crease"
    assert options["dryerMessage"]["2"] == "Drying finished"
    assert options["laundryCyclePhase"]["14"] == "Finished"
    assert options["washerMessage"]["1"] == "Wash finished"
    assert options["washerMessage"]["2"] == "Wash and dry finished"
    assert options["dryerUnifiedProgramSettings"]["56"] == "AI Dry"   # what the app shows


def test_laundry_labels_never_rename_another_class_s_states() -> None:
    """⛔ The same words on any other appliance keep the label they had before this class."""
    from haismart_hrdp.entity_spec import enum_label
    from haismart_hrdp.laundry_labels import laundry_label

    assert laundry_label("0501", "laundryCyclePhase", "结束") is None
    assert laundry_label(None, "runningMode", "启动") is None
    assert enum_label(1, "启动") == "启动"
