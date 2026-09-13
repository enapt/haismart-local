"""A washing machine, from prior art — the second appliance class, and the one that found a hazard.

`captures/prior-art/haier-esphome-37-HaierWasherUARTData.txt` is an esphome `uart_debug` tap on the
board↔module wire of a Haier HW90-B14959U1 front loader, recovered from the esphome-haier issue
tracker. It is not ours and nobody here owns the appliance, which is the point: supporting every
appliance the app does cannot wait for a reporter per category.

Two things it establishes that the water heater could not:

* the same published map decodes a **UART** frame as well as a LAN one — only the word array's base
  differs (12 vs 92), which is a property of the transport;
* ⛔ **a map can describe a longer report than a firmware sends**, and past the reserved block it
  omits, every field is at an unknown offset. This capture is exactly that case, and it is why
  :meth:`DeviceModel.placeable_limit` exists.
"""
from __future__ import annotations

import pytest

from haismart_hrdp.device_model import model_for

# 201c51890c31c308 **0501** ... — the washing-machine class. Read out of the capture's own `71`
# reply (the 32-byte TYPEID the module returns when the board asks), then fetched from Haier.
WASHER = "201c51890c31c30805010021800239584d000000000000000000000000000140"

# A raw board↔module frame: FF FF · len · addr[6] · type(06) · cmd(6D01) · attributes · checksum.
# The attribute array therefore starts at byte 12, not 92.
UART_BASE = 12

WASHER_IDLE = bytes.fromhex(
    "ffff7a400000000000066d01440a0100000801021e00000a000a00000000018b00000000018100028500286e00000000"
    "008c00000000000000018201000000000000000000000000000000000000000065636f34305f36300000000000000000"
    "00000000304d4c4674374871304e544533413d3d0000000000000000cd"
)

WASHER_RUNNING = bytes.fromhex(
    "ffff7a400000000000066d01380a0100001901003900000b000b0000000001a400000000019500028500141900000000"
    "0250000000000000000182010000000000000000000000000000000001000000736d6172745f6c6f63616c0000000000"
    "000000003173653732382b300000000000000000000000000000000036"
)


def test_a_washing_machine_decodes_from_the_same_published_map() -> None:
    """No washer-specific code exists anywhere in this package. The map is the whole decoder."""
    model = model_for(WASHER)
    assert model is not None
    assert model.device_class == "0501"
    assert "单滚筒" in (model.name or "")            # 单滚筒 = single-drum front loader

    state = model.decode(WASHER_IDLE, base=UART_BASE)
    # Every one of these is a real washing machine reading, and none of them could be a coincidence
    # of a wrong offset: a spin speed that is an exact multiple of 10 rpm, a wash temperature on the
    # dial, a countdown that is hours-and-minutes, and three cumulative counters that agree.
    assert state["spinSpeed"] == 1400
    assert state["washTemp"] == 40
    assert (state["remainingTimeHH"], state["remainingTimeMM"]) == (2, 30)
    assert state["totalElectricityUsed"] == pytest.approx(3.85)
    assert state["totalWaterUsed"] == 395
    assert state["totalWashCycle"] == state["currentWashCycle"] == 10
    assert state["onOffStatus"] is False
    assert state["doorLockStatus"] is False


def test_the_second_frame_moves_the_way_a_wash_does() -> None:
    """A decoder that returns the same answer whatever the bytes passes a one-frame test."""
    model = model_for(WASHER)
    assert model is not None
    idle = model.decode(WASHER_IDLE, base=UART_BASE)
    running = model.decode(WASHER_RUNNING, base=UART_BASE)

    assert idle["onOffStatus"] is False and running["onOffStatus"] is True
    # A different programme: 20 C at 800 rpm rather than 40 C at 1400.
    assert (running["washTemp"], running["spinSpeed"]) == (20, 800)
    # The counters only ever go up, and all three moved together for one completed cycle.
    assert running["totalWashCycle"] == idle["totalWashCycle"] + 1
    assert running["totalWaterUsed"] > idle["totalWaterUsed"]
    assert running["totalElectricityUsed"] > idle["totalElectricityUsed"]


def test_a_reserved_block_the_firmware_omits_makes_the_tail_unplaceable() -> None:
    """⛔ The hazard, and the reason a published map is not sufficient on its own.

    This washer's map declares fields at w1–w34, says nothing about w35–w43, then resumes at w44
    with two programme-name strings. The firmware does not send the reserved block: the strings are
    really at w35 and w45, nine words earlier. Placed where the map says, they read as zeros — and
    a neighbouring numeric field would have read as a plausible, wrong number.

    So the tail is refused. The 90 attributes below the block decode perfectly in the same frame,
    which is what makes this a limit worth drawing precisely rather than a reason to distrust the
    map.
    """
    model = model_for(WASHER)
    assert model is not None
    assert model.extent() == 63                       # what the map describes
    assert (len(WASHER_IDLE) - UART_BASE) // 2 == 56  # what the firmware sends
    assert model.first_omitted_word() == 35
    assert model.placeable_limit(len(WASHER_IDLE), base=UART_BASE) == 34

    state = model.decode(WASHER_IDLE, base=UART_BASE)
    assert "localProgName1" not in state and "localProgName2" not in state
    assert len(state) == 90


def test_a_full_length_report_places_everything() -> None:
    """The limit applies only when the report is actually short.

    Stated as a property rather than trusted: a frame long enough for the whole map has no reserved
    block to have been omitted, so nothing is refused.
    """
    model = model_for(WASHER)
    assert model is not None
    full = UART_BASE + 2 * model.extent() + 2
    assert model.placeable_limit(full, base=UART_BASE) is None


@pytest.mark.parametrize(
    ("typeid", "report_length", "why"),
    [
        # The appliances this integration decodes correctly today must not be restricted by the
        # rule. Each is SHORT of its map's extent -- by one word -- and each decodes in full,
        # because a one-word gap is padding every firmware sends, not a reserved block.
        ("201c120000118674200100418007574800000000000000000000000000000040", 167, "water heater"),
        ("201c10c7088081000d1205464544850000009cd68e692c104e2a333eab95d140", 133, "0d12 cabinet"),
        ("2008610800820324021200118006915900000000000000000000000000000040", 165, "ext-36 AC"),
    ],
)
def test_the_rule_does_not_fire_on_appliances_that_already_decode(
    typeid: str, report_length: int, why: str
) -> None:
    model = model_for(typeid)
    assert model is not None
    assert model.placeable_limit(report_length) is None, why


def test_a_fault_is_named_from_the_appliances_own_list_not_an_air_conditioners() -> None:
    """⛔ Fault 22 is `doorLockFail` on this washer and "Indoor PM2.5 sensor failure" on an AC.

    The shared table is the wording every published AIR CONDITIONER agrees on for positions 0..50,
    and it was consulted first for every appliance. A fault label is read by somebody deciding
    whether to call an engineer, so a confident wrong one is worse than an honest unknown.
    """
    from haismart_hrdp.uss import alarm_label

    model = model_for(WASHER)
    assert model is not None
    names = model.alarm_names()
    assert alarm_label(22, names, shared_table=False) == "doorLockFail"
    assert alarm_label(22, names) != "doorLockFail", "the AC table would have won"
    # A position this appliance does not name stays honest rather than borrowing a neighbour's.
    assert alarm_label(200, names, shared_table=False) == "Unknown fault 200"


def test_alarm_positions_are_sparse_so_declaration_order_would_misname_them() -> None:
    """Haier files each alarm with its POSITION, and the positions have gaps.

    This washer's run 2..66 with holes, so a list built in declaration order would name every fault
    after the first gap as its neighbour -- which is the failure mode this guards, not an absent
    label but a wrong one.
    """
    model = model_for(WASHER)
    assert model is not None
    positions = [pos for _, pos in model.alarms]
    assert min(positions) == 2, "the list does not start at 0"
    assert len(positions) < max(positions) + 1, "the positions are sparse"
    names = model.alarm_names()
    assert names[2] == "fanErr" and names[22] == "doorLockFail"
    assert names[0] == "" and names[1] == ""
