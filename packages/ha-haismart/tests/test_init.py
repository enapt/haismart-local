"""Entry setup, coordinator read cycle, entity state, and localKey-rotation reauth."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from conftest import (
    heat_capable_digital_model,
    locking_digital_model,
    make_compact12_frame,
    make_extended36_frame,
    make_extended_frame,
    make_status_frame,
    vane_positions_digital_model,
)
from haismart_extractor import HaierCloud
from homeassistant.components.climate import ClimateEntityFeature
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.haismart.const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_LOCALKEY_VERSION,
    CONF_PRODUCT_CODE,
    CONF_SCAN_INTERVAL,
    CONF_UPLUS_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EXTENDED_MISSES,
    OUTDOOR_TEMP_MAX_AGE,
    REDISCOVER_COOLDOWN,
    TELEMETRY_MAX_AGE,
    UDISCOVERY_INTERVAL,
    UDISCOVERY_MISSES,
    UDISCOVERY_RETIRE_INTERVAL,
)

CLIMATE = "climate.downstairs_ac"
VANE_H = "select.downstairs_ac_left_right_vane"
VANE_V = "select.downstairs_ac_up_down_vane"


def _entry(**overrides) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Downstairs AC",
        unique_id="A1B2C3D4E5F6",
        data={
            CONF_HOST: "192.168.1.50",
            CONF_DEVICE_ID: "A1B2C3D4E5F6",
            CONF_LOCAL_KEY: "00112233445566778899aabbccddeeff",
            CONF_PRODUCT_CODE: "AAC1UKZ01",
            CONF_LOCALKEY_VERSION: 4,
            **overrides,
        },
    )


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _tick(hass: HomeAssistant, freezer) -> None:
    freezer.tick(timedelta(seconds=DEFAULT_SCAN_INTERVAL + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_setup_creates_entities_from_status(hass: HomeAssistant, mock_uss) -> None:
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    climate = hass.states.get(CLIMATE)
    assert climate is not None
    assert climate.state == "cool"
    assert climate.attributes["current_temperature"] == 26.5
    assert climate.attributes["temperature"] == 24.0
    assert climate.attributes["fan_mode"] == "auto"
    assert climate.attributes["swing_mode"] == "vertical"
    # both axes are independent fields on the wire but are presented as ONE conventional control
    assert climate.attributes["swing_modes"] == ["off", "vertical", "horizontal", "both"]
    assert climate.attributes["min_temp"] == 16.0
    assert climate.attributes["max_temp"] == 30.0
    assert climate.attributes["fan_modes"] == ["high", "medium", "low", "auto"]
    # OFF + the model's own enum order (cooling-only unit: no HEAT)
    assert climate.attributes["hvac_modes"] == ["off", "auto", "cool", "dry", "fan_only"]

    indoor = hass.states.get("sensor.downstairs_ac_indoor_temperature")
    outdoor = hass.states.get("sensor.downstairs_ac_outdoor_temperature")
    assert indoor is not None and float(indoor.state) == 26.5
    assert outdoor is not None and float(outdoor.state) == 33.0


async def test_extended_status_creates_power_sensors(hass: HomeAssistant, mock_uss) -> None:
    """A unit that answers the extended query gets power / current / frequency entities.

    Their names come from their device classes (Home Assistant translates those), so the entity ids
    are the device-class slugs rather than anything this integration names.
    """
    mock_uss.read.return_value = [make_status_frame(), make_extended_frame()]
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.supports_extended is True

    power = hass.states.get("sensor.downstairs_ac_power")
    assert power is not None and float(power.state) == 910.0
    assert power.attributes["device_class"] == "power"
    assert power.attributes["unit_of_measurement"] == "W"
    # MEASUREMENT is what puts it into long-term statistics, which the energy helper builds on
    assert power.attributes["state_class"] == "measurement"

    current = hass.states.get("sensor.downstairs_ac_current")
    assert current is not None and float(current.state) == 4.0
    frequency = hass.states.get("sensor.downstairs_ac_frequency")
    assert frequency is not None and float(frequency.state) == 43.0
    coil = hass.states.get("sensor.downstairs_ac_coil_temperature")
    assert coil is not None and float(coil.state) == 12.0
    discharge = hass.states.get("sensor.downstairs_ac_discharge_temperature")
    assert discharge is not None and float(discharge.state) == 58.0

    # These units measure, but they keep no running total: their cumulative register exists and
    # stays at zero for the unit's life, so the Energy sensor is unavailable rather than reporting a
    # permanent 0 kWh into the Energy dashboard.
    energy = hass.states.get("sensor.downstairs_ac_energy")
    assert energy is not None and energy.state == "unknown"

    # running-state binary sensors
    comp = hass.states.get("binary_sensor.downstairs_ac_compressor")
    assert comp is not None and comp.state == "on"
    fan = hass.states.get("binary_sensor.downstairs_ac_fan")
    assert fan is not None and fan.state == "on"

    # the ordinary status fields still decode from the same cycle
    assert hass.states.get(CLIMATE).state == "cool"


async def test_unit_without_extended_status_stops_asking(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """A unit that ignores every form of the extended query keeps working, and we stop asking.

    It takes EXTENDED_MISSES cycles per published form rather than one cycle in total: a single
    dropped reply must not be mistaken for a unit with no extended report, and silence to one form
    must not be mistaken for silence to the command, since one generation publishes it under a
    different frame type.

    The sensors are still created (so they appear if a firmware update ever answers) but report
    unknown rather than a made-up zero.
    """
    mock_uss.read.return_value = [make_status_frame()]        # status only, no extended report
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    coordinator = entry.runtime_data
    assert coordinator.supports_extended is None             # not concluded yet, one cycle in

    power = hass.states.get("sensor.downstairs_ac_power")
    assert power is not None and power.state == "unknown"

    from custom_components.haismart.coordinator import EXTENDED_STATUS_FRAME_TYPES

    for _ in range(EXTENDED_MISSES * len(EXTENDED_STATUS_FRAME_TYPES) - 1):
        await _tick(hass, freezer)
    assert coordinator.supports_extended is False

    # and the next poll must not ask again
    mock_uss.read.reset_mock()
    await _tick(hass, freezer)
    for call in mock_uss.read.await_args_list:
        assert call.kwargs.get("extra_request") is None


def _honest_read(*, answer_from_ask: int = 1, empty: dict | None = None):
    """A read side effect that returns an extended report ONLY on a cycle that asked for one.

    `mock_uss.read.return_value` cannot express that — it hands back the extended frame whether or
    not the coordinator appended the query — and that difference is the whole subject of the two
    tests below. ``answer_from_ask`` is the first ask that gets an answer (earlier ones dropped);
    ``empty``, if given, is a dict whose truthy ``["now"]`` makes a cycle decode nothing at all.
    """
    asks: list[bool] = []

    async def _read(*args, **kwargs):
        asked = kwargs.get("extra_request") is not None
        asks.append(asked)
        if empty is not None and empty.get("now"):
            return []
        frames = [make_status_frame()]
        if asked and sum(asks) >= answer_from_ask:
            frames.append(make_extended_frame())
        return frames

    _read.asks = asks
    return _read


async def test_one_missing_extended_reply_does_not_retire_the_query(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """A single cycle without an extended report must keep asking.

    Retiring on the first miss meant one dropped reply cost the unit its power, current, frequency,
    coil, discharge, compressor and fan entities until the entry was reloaded.
    """
    mock_uss.read.side_effect = _honest_read(answer_from_ask=2)  # the first reply is dropped
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    assert coordinator.supports_extended is None             # not written off after one miss

    await _tick(hass, freezer)                                # asked again, and answered this time
    assert coordinator.supports_extended is True
    power = hass.states.get("sensor.downstairs_ac_power")
    assert power is not None and float(power.state) == 910.0


async def test_empty_cycle_does_not_disprove_a_proven_extended_unit(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """A cycle that decodes nothing says nothing about the extended query.

    It is the localKey-rotation window or a dropped push, not the extra frame — so a unit that has
    already answered one keeps its telemetry: the query pauses for a cycle and is re-armed as soon
    as status decodes again.
    """
    outage = {"now": False}
    read = _honest_read(empty=outage)
    mock_uss.read.side_effect = read
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    assert coordinator.supports_extended is True

    outage["now"] = True                                      # nothing decodes this cycle
    await _tick(hass, freezer)
    assert coordinator.supports_extended is True              # still believed, only paused
    assert read.asks[-1] is True

    outage["now"] = False
    await _tick(hass, freezer)                                # plain read works again -> re-arm
    assert read.asks[-1] is False

    await _tick(hass, freezer)                                # asking again, and answered
    assert read.asks[-1] is True
    assert float(hass.states.get("sensor.downstairs_ac_power").state) == 910.0


async def test_powered_off_reports_hvac_off(hass: HomeAssistant, mock_uss) -> None:
    mock_uss.read.return_value = [make_status_frame(power=False)]
    await _setup(hass)
    assert hass.states.get(CLIMATE).state == "off"


async def test_compact12_family_decodes_and_controls_via_4d5f(
    hass: HomeAssistant, mock_uss
) -> None:
    """A non-classic wire family (117-byte compact-12, issue #4) decodes fully — climate + sensor
    populate — WITHOUT the unknown-layout repair, and control goes out as the family's own 4d5f
    group-set (setpoint packed at word 12, per its model's group-command spec)."""
    frame = make_compact12_frame(power=True, target_temp=22, indoor_temp=27, mode_epp=1, fan_epp=3)
    mock_uss.read.return_value = [frame]
    mock_uss.send.baseline = frame   # the AC's in-session push that seeds the group-set
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    climate = hass.states.get(CLIMATE)
    assert climate is not None and climate.state == "cool"
    assert climate.attributes["current_temperature"] == 27.0
    assert climate.attributes["temperature"] == 22.0
    # issue #4: this family has no writable presets, so the climate entity must build without a
    # preset control -- and without crashing. The preset_modes property reads _attr_preset_modes,
    # which HA's ClimateEntity gives no default, so it has to be assigned unconditionally.
    features = ClimateEntityFeature(climate.attributes["supported_features"])
    assert ClimateEntityFeature.PRESET_MODE not in features
    assert "preset_modes" not in climate.attributes

    coord = entry.runtime_data
    assert coord.unknown_layout is None            # a KNOWN family — no "new model" repair
    assert coord.read_only_layout is None          # writable family — control enabled

    await coord.async_send_control({"targetTemperature": 24 - 16})
    sent = mock_uss.send.last_frame
    # a 4d5f group-set frame, not the classic 6001
    assert sent[:2] == b"\xff\xff" and sent[10:12] == b"\x4d\x5f"
    words = sent[12:-1]
    assert len(words) == 24
    assert words[(12 - 1) * 2 + 1] == 24 - 16  # setpoint packed at word 12


async def test_self_clean_button_fires_one_bit_and_gates_on_state(
    hass: HomeAssistant, mock_uss
) -> None:
    """The self-clean button sends selfCleaningStatus as a one-bit grSetDAC group-set (issue #8).

    Live-confirmed on the classic family — with the unit on and not in auto/sleep the single bit
    landed and the unit's panel showed "CL". This pins the frame it sends (exactly word 5 bit 4,
    nothing else) and that the model's own modifiers gate it: off, and the button disappears from
    reach. It's a start-only trigger, so there is no "off" to test.
    """
    on = make_status_frame(power=True, mode_code=1)  # on, cooling — self-clean writable
    mock_uss.read.return_value = [on]
    mock_uss.send.baseline = on
    await _setup(hass)

    btn = "button.downstairs_ac_start_self_clean"
    state = hass.states.get(btn)
    assert state is not None and state.state != "unavailable"

    await hass.services.async_call("button", "press", {"entity_id": btn}, blocking=True)
    sent = mock_uss.send.last_frame
    assert sent[:2] == b"\xff\xff" and sent[10:12] == b"\x60\x01"  # classic grSetDAC
    data = sent[12:-1]
    base = on[92:104]
    changed = [i for i in range(len(base)) if base[i] != data[i]]
    assert changed == [9] and (data[9] ^ base[9]) == 0x10  # only word 5 bit 4 — selfCleaningStatus


async def test_self_clean_button_absent_where_the_family_cannot_write_it(
    hass: HomeAssistant, mock_uss
) -> None:
    """A family whose write map has no self-clean flag gets no button — the compact-12 case."""
    mock_uss.read.return_value = [make_compact12_frame()]
    await _setup(hass)
    assert hass.states.get("button.downstairs_ac_start_self_clean") is None


async def test_compact12_omits_the_controls_it_cannot_write(
    hass: HomeAssistant, mock_uss
) -> None:
    """A family whose write map has none of the secondary fields must not get their entities.

    They used to be created regardless, so a compact-12 unit showed five switches and an eco select
    that read `unknown` forever and raised the moment they were touched.
    """
    mock_uss.read.return_value = [make_compact12_frame()]
    await _setup(hass)

    assert hass.states.get(CLIMATE) is not None                  # the climate entity still works
    assert hass.states.get("switch.downstairs_ac_sleep") is None
    assert hass.states.get("switch.downstairs_ac_strong") is None
    assert hass.states.get("select.downstairs_ac_eco") is None


async def test_extended36_family_decodes_and_controls_from_word_20(
    hass: HomeAssistant, mock_uss
) -> None:
    """The 165-byte extended-36 family (issue #5): full decode plus control as a `6001` group-set
    whose baseline is sliced from report word 20. Before this family existed the classic partial
    decode read the leading media block and reported a 48 C setpoint on a unit that was off."""
    frame = make_extended36_frame(power=True, target_temp=22, indoor_temp=27.5, fan_code=1)
    mock_uss.read.return_value = [frame]
    mock_uss.send.baseline = frame
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    climate = hass.states.get(CLIMATE)
    assert climate is not None and climate.state == "cool"
    assert climate.attributes["current_temperature"] == 27.5
    assert climate.attributes["temperature"] == 22.0
    assert climate.attributes["fan_mode"] == "high"

    coord = entry.runtime_data
    assert coord.unknown_layout is None          # a KNOWN family — no "new model" repair
    assert coord.read_only_layout is None        # writable family — control enabled
    # the w22 boolean block is read back through the wire model, so the switches show real state
    assert coord.current_field("screenDisplayStatus") == 1
    assert coord.current_field("rapidMode") == 0
    assert hass.states.get("switch.downstairs_ac_display_light").state == "on"

    await coord.async_send_control({"targetTemperature": 24 - 16})
    sent = mock_uss.send.last_frame
    assert sent[:2] == b"\xff\xff" and sent[10:12] == b"\x60\x01"   # classic group command
    words = sent[12:-1]
    assert len(words) == 10                                        # five words, not the classic six
    assert words[0] == 24 - 16                                     # setpoint at word 1 b8
    assert words[2:] == frame[132:140]                             # words 2..5 preserved (w21..w24)


def _sent_field(send, name: str) -> int:
    """Decode a grSetDAC field out of the EPP frame the coordinator sent to async_send_op."""
    from haismart_hrdp import GRSETDAC_FIELDS

    frame = send.last_frame  # the grSetDAC frame build_frame produced (see conftest)
    assert frame[:2] == b"\xff\xff" and frame[10:12] == b"\x60\x01"  # a grSetDAC frame
    words = frame[12:-1]
    wi, shift, width = GRSETDAC_FIELDS[name]
    off = (wi - 1) * 2
    word = (words[off] << 8) | words[off + 1]
    return (word >> shift) & ((1 << width) - 1)


async def test_set_temperature_sends_grsetdac(hass: HomeAssistant, mock_uss) -> None:
    await _setup(hass)
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": CLIMATE, "temperature": 22}, blocking=True
    )
    assert mock_uss.send.await_count == 1
    assert _sent_field(mock_uss.send, "targetTemperature") == 6  # 22 - 16
    # a group-set: every other field is preserved from current state (baseline 24/cool/auto/on)
    assert _sent_field(mock_uss.send, "operationMode") == 1
    assert _sent_field(mock_uss.send, "windSpeed") == 5
    assert _sent_field(mock_uss.send, "onOffStatus") == 1


async def test_set_hvac_mode_off_then_dry(hass: HomeAssistant, mock_uss) -> None:
    await _setup(hass)
    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": CLIMATE, "hvac_mode": "off"}, blocking=True
    )
    assert _sent_field(mock_uss.send, "onOffStatus") == 0
    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": CLIMATE, "hvac_mode": "dry"}, blocking=True
    )
    assert _sent_field(mock_uss.send, "onOffStatus") == 1
    assert _sent_field(mock_uss.send, "operationMode") == 2  # dry


async def test_set_fan_mode_sends(hass: HomeAssistant, mock_uss) -> None:
    await _setup(hass)
    await hass.services.async_call(
        "climate", "set_fan_mode", {"entity_id": CLIMATE, "fan_mode": "high"}, blocking=True
    )
    assert _sent_field(mock_uss.send, "windSpeed") == 1


async def test_fan_only_mode_substitutes_concrete_fan(hass: HomeAssistant, mock_uss) -> None:
    """Regression: fan-only mode rejects fan=auto on this unit (the group-set is silently dropped).
    Entering fan-only while the fan is on auto must also send a concrete windSpeed,
    or the mode change does nothing."""
    await _setup(hass)  # baseline: cool, fan auto (make_status_frame default fan_code=5)
    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": CLIMATE, "hvac_mode": "fan_only"}, blocking=True
    )
    assert _sent_field(mock_uss.send, "operationMode") == 6   # fan_only
    assert _sent_field(mock_uss.send, "onOffStatus") == 1
    # low (3) substituted, NOT auto(5): low is what the unit's own model names for fan-only, and
    # what the unit sends itself when fan-only is selected
    assert _sent_field(mock_uss.send, "windSpeed") == 3


async def test_heat_mode_offered_and_sent_when_the_model_declares_it(
    hass: HomeAssistant, mock_uss
) -> None:
    """Heat works on a unit whose digital model declares it (issue #1).

    Our reference hardware is cooling-only, so heat is deliberately absent from the encoder's
    observed-value allowlist. A heat-pump AC's own model declares operationMode 4, and that is what
    authorizes both the entity offering HEAT and the group-set carrying it.
    """
    mock_uss.read.return_value = [make_status_frame(mode_code=4)]  # AC reports it's heating
    entry = _entry(digital_model=json.dumps(heat_capable_digital_model()))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    climate = hass.states.get(CLIMATE)
    assert climate.attributes["hvac_modes"] == [
        "off", "auto", "cool", "dry", "heat", "fan_only",
    ]
    assert climate.state == "heat"  # the report's mode code decodes back to heat

    mock_uss.send.baseline = make_status_frame(mode_code=1)  # currently cooling
    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": CLIMATE, "hvac_mode": "heat"}, blocking=True
    )
    assert _sent_field(mock_uss.send, "operationMode") == 4  # the model's own heat code
    assert _sent_field(mock_uss.send, "onOffStatus") == 1


async def test_heat_refused_on_a_unit_whose_model_excludes_it(
    hass: HomeAssistant, mock_uss
) -> None:
    """The flip side of the guard: a unit whose digital model does not list heat must not get it.

    Heat itself is hardware-confirmed now, so the ENCODER accepts code 4 unconditionally; what keeps
    it off a cooling-only unit is the model gate in the coordinator plus the mode list the entity
    builds from that same model.
    """
    import json as _json

    from custom_components.haismart.const import CONF_DIGITAL_MODEL

    cooling_only = _json.dumps({
        "attributes": [{
            "name": "operationMode", "writable": True,
            "valueRange": {"type": "LIST", "dataList": [
                {"data": "0", "desc": "智能/自动/舒适"}, {"data": "1", "desc": "制冷"},
                {"data": "2", "desc": "除湿"}, {"data": "6", "desc": "送风"},
            ]},
        }]
    })
    entry = _entry(**{CONF_DIGITAL_MODEL: cooling_only})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert "heat" not in hass.states.get(CLIMATE).attributes["hvac_modes"]
    with pytest.raises(HomeAssistantError):
        await entry.runtime_data.async_send_control({"operationMode": 4})
    assert mock_uss.send.last_frame is None  # the op frame was never even encoded


async def test_set_swing_mode_sends_toggle(hass: HomeAssistant, mock_uss) -> None:
    await _setup(hass)
    await hass.services.async_call(
        "climate", "set_swing_mode", {"entity_id": CLIMATE, "swing_mode": "off"}, blocking=True
    )
    assert _sent_field(mock_uss.send, "windDirectionVertical") == 0
    await hass.services.async_call(
        "climate", "set_swing_mode", {"entity_id": CLIMATE, "swing_mode": "vertical"}, blocking=True
    )
    assert _sent_field(mock_uss.send, "windDirectionVertical") == 0x0C


def _with_fields(frame: bytes, **fields: int) -> bytes:
    """A status frame with grSetDAC fields set, packed by the library rather than by hand here."""
    from haismart_hrdp import uss

    layout = uss.status_layout(frame)
    words = uss.grsetdac_baseline_from_status(frame)
    for name, value in fields.items():
        words = uss.set_grsetdac_field(words, name, value)
    out = bytearray(frame)
    out[layout.baseline] = words
    return bytes(out)


async def test_presets_are_offered_for_the_comfort_modes(
    hass: HomeAssistant, mock_uss
) -> None:
    """eco / sleep / boost belong on the thermostat, not only on separate switches — that is what
    makes them reachable from the climate card, a voice assistant and climate.set_preset_mode."""
    await _setup(hass)

    climate = hass.states.get(CLIMATE)
    assert climate.attributes["preset_modes"] == ["none", "eco", "sleep", "boost"]
    assert climate.attributes["preset_mode"] == "none"       # nothing set in the default frame


async def test_setting_a_preset_clears_the_others_in_one_group_set(
    hass: HomeAssistant, mock_uss
) -> None:
    """A preset is exclusive, and a group-set writes the whole attribute vector — so one op sets the
    chosen field and clears the rest, instead of three switch writes in three sessions."""
    await _setup(hass)
    mock_uss.send.baseline = _with_fields(make_status_frame(), ecoMode=7)  # eco L3 currently on

    await hass.services.async_call(
        "climate", "set_preset_mode", {"entity_id": CLIMATE, "preset_mode": "boost"}, blocking=True
    )
    assert mock_uss.send.await_count == 1                    # one session, not one per field
    assert _sent_field(mock_uss.send, "rapidMode") == 1
    assert _sent_field(mock_uss.send, "ecoMode") == 0
    assert _sent_field(mock_uss.send, "silentSleepStatus") == 0
    # and the rest of the state is preserved, as any group-set must
    assert _sent_field(mock_uss.send, "operationMode") == 1
    assert _sent_field(mock_uss.send, "onOffStatus") == 1

    await hass.services.async_call(
        "climate", "set_preset_mode", {"entity_id": CLIMATE, "preset_mode": "none"}, blocking=True
    )
    assert _sent_field(mock_uss.send, "rapidMode") == 0
    assert _sent_field(mock_uss.send, "ecoMode") == 0
    assert _sent_field(mock_uss.send, "silentSleepStatus") == 0


async def test_preset_reads_back_the_most_assertive_of_several(
    hass: HomeAssistant, mock_uss
) -> None:
    """The fields are independent on the wire and the switches write them one at a time, so a unit
    can have two on at once. Home Assistant needs one answer: the most assertive wins."""
    mock_uss.read.return_value = [_with_fields(make_status_frame(), ecoMode=5)]
    await _setup(hass)
    assert hass.states.get(CLIMATE).attributes["preset_mode"] == "eco"

    mock_uss.read.return_value = [
        _with_fields(make_status_frame(), ecoMode=5, silentSleepStatus=1)
    ]
    await hass.config_entries.async_reload(hass.config_entries.async_entries(DOMAIN)[0].entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(CLIMATE).attributes["preset_mode"] == "sleep"


async def test_presets_absent_on_a_family_that_cannot_write_them(
    hass: HomeAssistant, mock_uss
) -> None:
    """The compact-12 family's write map has none of these fields, so the control must not appear —
    an offered preset that can only raise is worse than no preset."""
    mock_uss.read.return_value = [make_compact12_frame()]
    await _setup(hass)

    climate = hass.states.get(CLIMATE)
    assert "preset_modes" not in climate.attributes
    assert "preset_mode" not in climate.attributes


async def test_horizontal_swing_moves_only_that_axis(hass: HomeAssistant, mock_uss) -> None:
    """The axis-at-a-time control must leave the other vane where the user put it.

    Through the four-way control alone, "start left-right swing" has to be spelled
    `swing_mode: both`, which also starts the up-down vane.
    """
    mock_uss.read.return_value = [make_status_frame(swing=True)]   # vertical swinging
    await _setup(hass)
    climate = hass.states.get(CLIMATE)
    assert climate.attributes["swing_horizontal_modes"] == ["off", "on"]
    assert climate.attributes["swing_horizontal_mode"] == "off"
    assert climate.attributes["swing_mode"] == "vertical"          # the old control is unchanged

    mock_uss.send.baseline = make_status_frame(swing=True)
    await hass.services.async_call(
        "climate",
        "set_swing_horizontal_mode",
        {"entity_id": CLIMATE, "swing_horizontal_mode": "on"},
        blocking=True,
    )
    assert _sent_field(mock_uss.send, "windDirectionHorizontal") == 0x07
    # the vertical nibble goes back exactly as the AC reported it (8 = the swinging flag), rather
    # than being rewritten to the 0x0c the encoder uses to turn it on
    # the vertical axis is carried through untouched -- 0x0c is the sweep code the fixture set
    assert _sent_field(mock_uss.send, "windDirectionVertical") == 0x0C


async def test_horizontal_swing_absent_when_the_family_omits_it(
    hass: HomeAssistant, mock_uss
) -> None:
    """extended-46 leaves windDirectionHorizontal out of its write map on purpose (the position is
    not settled), so the control must not be offered on that family."""
    from conftest import make_extended46_frame

    mock_uss.read.return_value = [make_extended46_frame()]
    await _setup(hass)

    climate = hass.states.get(CLIMATE)
    assert "swing_horizontal_modes" not in climate.attributes
    assert "swing_horizontal_mode" not in climate.attributes


async def test_switch_toggles_confirmed_bit(hass: HomeAssistant, mock_uss) -> None:
    await _setup(hass)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.downstairs_ac_sleep"}, blocking=True
    )
    assert _sent_field(mock_uss.send, "silentSleepStatus") == 1
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.downstairs_ac_strong"}, blocking=True
    )
    assert _sent_field(mock_uss.send, "rapidMode") == 0


async def test_eco_select_sends_level(hass: HomeAssistant, mock_uss) -> None:
    await _setup(hass)
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.downstairs_ac_eco", "option": "level2"}, blocking=True,
    )
    assert _sent_field(mock_uss.send, "ecoMode") == 6  # level2 -> code 6


async def test_extended36_family_covers_its_longer_report_too(
    hass: HomeAssistant, mock_uss
) -> None:
    """A 175-byte report is the same family with five words of counters on the end (issue #8).

    The reporting unit connected, decoded nothing, and raised the new-model repair. It must now come
    up as a fully decoded, controllable unit — the layout is known, so nothing about it is a repair.
    """
    frame = make_extended36_frame(
        length=175, power=True, target_temp=24, indoor_temp=26.0, power_w=1432, energy_wh=37022
    )
    mock_uss.read.return_value = [frame]
    mock_uss.send.baseline = frame
    entry = await _setup(hass)

    climate = hass.states.get(CLIMATE)
    assert climate.state == "cool"
    assert climate.attributes["current_temperature"] == 26.0
    assert climate.attributes["temperature"] == 24.0

    coord = entry.runtime_data
    assert coord.unknown_layout is None and coord.read_only_layout is None
    # this variant reports live power in the status frame itself, so the Power sensor works on a
    # unit that never answers the extended-status query the classic family's telemetry comes from
    assert float(hass.states.get("sensor.downstairs_ac_power").state) == 1432
    assert hass.states.get("sensor.downstairs_ac_current").state == "unknown"
    # and it keeps a cumulative total of its own, which the Energy dashboard can take directly:
    # counted in watt-hours by the unit, shown in kWh
    energy = hass.states.get("sensor.downstairs_ac_energy")
    assert float(energy.state) == 37.022
    assert energy.attributes["unit_of_measurement"] == "kWh"
    assert energy.attributes["state_class"] == "total_increasing"

    await coord.async_send_control({"targetTemperature": 25 - 16})
    sent = mock_uss.send.last_frame
    assert sent[:2] == b"\xff\xff" and sent[10:12] == b"\x60\x01"
    assert sent[12] == 25 - 16                      # setpoint at group-set word 1, from report w20


async def test_vane_positions_come_from_the_units_own_model(
    hass: HomeAssistant, mock_uss
) -> None:
    """The left-right vane is a position, not a flag, so where a unit's model publishes the stops
    they can be selected. Only the two ends have ever been seen written, so the model is what
    authorizes the rest — the same mechanism heat mode uses."""
    mock_uss.read.return_value = [make_status_frame(vane_h=4)]  # parked at position five
    entry = _entry(digital_model=json.dumps(vane_positions_digital_model()))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    vane = hass.states.get(VANE_H)
    assert vane.attributes["options"] == [
        "fixed", "position_1", "position_2", "position_3",
        "position_4", "position_5", "position_6", "auto",
    ]
    # positions are numbered by their place in the model's list, not by their code: this model lists
    # 1..6 between fixed and auto, so the reported code 4 is the fourth stop it offers
    assert vane.state == "position_4"
    # a parked vane is not a swinging one, and the climate control still says so
    assert hass.states.get(CLIMATE).attributes["swing_horizontal_mode"] == "off"

    await hass.services.async_call(
        "select", "select_option", {"entity_id": VANE_H, "option": "position_3"}, blocking=True,
    )
    assert _sent_field(mock_uss.send, "windDirectionHorizontal") == 3


async def test_vane_positions_not_offered_without_them(hass: HomeAssistant, mock_uss) -> None:
    """Two cases that must not get the entity: a unit whose model lists only the two ends (the
    swing control already expresses those), and one onboarded with no model at all (nothing then
    authorizes a position)."""
    entry = _entry(digital_model=json.dumps(vane_positions_digital_model(codes=(0, 7))))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(VANE_H) is None
    await hass.config_entries.async_unload(entry.entry_id)

    await _setup(hass)
    assert hass.states.get(VANE_H) is None


async def test_vane_positions_leave_out_a_code_the_field_cannot_hold(
    hass: HomeAssistant, mock_uss
) -> None:
    """The vane's field is three bits wide. A model listing something wider describes an attribute
    this field is not, so that code is left out rather than offered as an option that could only
    ever fail on the way to the unit."""
    entry = _entry(digital_model=json.dumps(vane_positions_digital_model(codes=(0, 4, 7, 9))))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(VANE_H).attributes["options"] == ["fixed", "position_1", "auto"]


async def test_vane_positions_not_offered_where_they_cannot_be_placed(
    hass: HomeAssistant, mock_uss
) -> None:
    """A family that packs a vane into a single bit cannot hold a position — it would arrive as
    "sweep" — so the entity must not appear there however many stops the model publishes."""
    mock_uss.read.return_value = [make_compact12_frame()]
    entry = _entry(digital_model=json.dumps(
        vane_positions_digital_model(vertical=(0, 2, 4, 5, 6, 8))
    ))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(CLIMATE) is not None                  # the unit still works
    assert hass.states.get(VANE_H) is None
    assert hass.states.get(VANE_V) is None


async def test_vane_positions_on_the_extended36_family(hass: HomeAssistant, mock_uss) -> None:
    """Both axes, on a family that keeps its climate block 19 words in (issue #8).

    The up-down axis is the one that needed settling: its model names stops 0, 2, 4, 5, 6, 8 while
    the unit works in 0, 2, 4, 6, 8, 12, so a position only reaches the wire correctly if the
    translation is applied. Auto lands on the same 0x0c the swing control has always sent.
    """
    frame = make_extended36_frame(length=175, power=True, target_temp=24, indoor_temp=26.0)
    mock_uss.read.return_value = [frame]
    mock_uss.send.baseline = frame
    entry = _entry(digital_model=json.dumps(
        vane_positions_digital_model(codes=(0, 3, 4, 5, 6, 7), vertical=(0, 2, 4, 5, 6, 8))
    ))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(VANE_V).attributes["options"] == [
        "fixed", "position_1", "position_2", "position_3", "position_4", "auto",
    ]
    assert hass.states.get(VANE_H).attributes["options"] == [
        "fixed", "position_1", "position_2", "position_3", "position_4", "auto",
    ]

    coord = entry.runtime_data
    # the model's third stop (code 5) is 6 on the wire, not 5
    await hass.services.async_call(
        "select", "select_option", {"entity_id": VANE_V, "option": "position_3"}, blocking=True,
    )
    words = mock_uss.send.last_frame[12:-1]
    assert words[1] & 0x0F == 6
    # and its auto is the 0x0c nibble, so the climate swing control still agrees with this entity
    await hass.services.async_call(
        "select", "select_option", {"entity_id": VANE_V, "option": "auto"}, blocking=True,
    )
    assert mock_uss.send.last_frame[12:-1][1] & 0x0F == 0x0C

    # the left-right axis needs no translation: the model's code is the wire value
    await hass.services.async_call(
        "select", "select_option", {"entity_id": VANE_H, "option": "position_2"}, blocking=True,
    )
    words = mock_uss.send.last_frame[12:-1]
    assert (words[6] << 8 | words[7]) & 0x07 == 4
    assert coord.unknown_layout is None


async def test_control_confirms_from_op_reply_without_extra_read(
    hass: HomeAssistant, mock_uss
) -> None:
    """The AC echoes its updated state on the op connection, so the coordinator confirms from that
    reply directly — the entity updates immediately and NO extra read cycle is issued (the group-set
    is seeded from the op's own in-session status push, not a separate read)."""
    await _setup(hass)
    reads_after_setup = mock_uss.read.await_count
    # the op reply carries the AC's updated full-status report (target now 26)
    mock_uss.send.return_value = [make_status_frame(target_temp=26)]
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": CLIMATE, "temperature": 26}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(CLIMATE).attributes["temperature"] == 26.0   # from the op reply
    assert mock_uss.read.await_count == reads_after_setup               # no separate read at all


async def test_control_seeds_from_in_session_push_not_stale_cache(
    hass: HomeAssistant, mock_uss
) -> None:
    """Regression (the 'setpoint won't stick' bug): a control group-set must be seeded from the AC's
    live in-session status push, not the cached ``last_raw_status``. Here the cache is stale
    (unit OFF) while the AC's push says it's really ON; a temp change must carry the fresh power
    bit, or it
    would silently turn the unit off. Assert the built op frame equals the fresh-seeded one."""
    from haismart_hrdp import uss

    entry = await _setup(hass)
    coordinator = entry.runtime_data
    stale = make_status_frame(power=False, target_temp=30)   # stale cache: OFF
    fresh = make_status_frame(power=True, target_temp=24)    # what the AC pushes in-session: ON
    coordinator.last_raw_status = stale
    mock_uss.send.baseline = fresh                            # the op-connection status push
    mock_uss.send.return_value = [make_status_frame(power=True, target_temp=25)]

    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": CLIMATE, "temperature": 25}, blocking=True
    )
    await hass.async_block_till_done()

    sent_frame = mock_uss.send.last_frame
    fresh_seeded = uss.grsetdac_op_frame(
        uss.set_grsetdac_field(
            uss.grsetdac_baseline_from_status(fresh), "targetTemperature", 25 - 16
        )
    )
    stale_seeded = uss.grsetdac_op_frame(
        uss.set_grsetdac_field(
            uss.grsetdac_baseline_from_status(stale), "targetTemperature", 25 - 16
        )
    )
    assert sent_frame == fresh_seeded  # seeded from the live in-session push (power ON preserved)
    assert sent_frame != stale_seeded       # NOT from the stale OFF cache


async def test_control_falls_back_to_read_when_reply_has_no_status(
    hass: HomeAssistant, mock_uss
) -> None:
    """If the op reply carries no decodable full-status report, confirm with a normal read cycle."""
    await _setup(hass)
    reads_after_setup = mock_uss.read.await_count
    mock_uss.send.return_value = []                                # nothing usable in the reply
    mock_uss.read.return_value = [make_status_frame(target_temp=26)]
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": CLIMATE, "temperature": 26}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(CLIMATE).attributes["temperature"] == 26.0
    # one read: the post-op fallback confirmation cycle (the baseline came from the op's own push)
    assert mock_uss.read.await_count == reads_after_setup + 1


async def test_concurrent_commands_never_share_the_session(
    hass: HomeAssistant, mock_uss
) -> None:
    """Two commands at once must not open two uSS sessions.

    Applying a scene fires its entities concurrently, so a scene that carries the thermostat *and*
    one of the switches sends two control ops with nothing in between. These units accept one
    connection at a time, and each op seeds its group-set from the status the AC pushes on its OWN
    connection — so an overlap does not half-apply, it REVERTS: the second baseline predates the
    first change and a group-set rewrites the whole attribute vector.
    """
    await _setup(hass)
    depth = peak = 0
    frames: list[bytes] = []

    async def _slow_op(*args, **kwargs):
        nonlocal depth, peak
        depth += 1
        peak = max(peak, depth)
        await asyncio.sleep(0.01)      # an unserialized second op would land inside this window
        frames.append(kwargs["build_frame"](mock_uss.send.baseline))
        depth -= 1
        return [make_status_frame()]

    mock_uss.send.side_effect = _slow_op
    await asyncio.gather(
        hass.services.async_call(
            "climate", "set_temperature", {"entity_id": CLIMATE, "temperature": 22}, blocking=True
        ),
        hass.services.async_call(
            "switch", "turn_on", {"entity_id": "switch.downstairs_ac_sleep"}, blocking=True
        ),
    )
    assert peak == 1            # one session at a time
    assert len(frames) == 2     # and neither command was dropped to get there


async def test_a_command_waits_for_the_poll_holding_the_session(
    hass: HomeAssistant, mock_uss
) -> None:
    """A command that lands mid-poll queues behind it instead of opening a second connection."""
    entry = await _setup(hass)
    order: list[str] = []
    reading = asyncio.Event()

    async def _slow_read(*args, **kwargs):
        order.append("read-start")
        reading.set()
        await asyncio.sleep(0.01)
        order.append("read-end")
        return [make_status_frame()]

    async def _op(*args, **kwargs):
        order.append("op")
        kwargs["build_frame"](mock_uss.send.baseline)
        return [make_status_frame(target_temp=22)]

    mock_uss.read.side_effect = _slow_read
    mock_uss.send.side_effect = _op
    poll = hass.async_create_task(entry.runtime_data.async_refresh())
    await reading.wait()
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": CLIMATE, "temperature": 22}, blocking=True
    )
    await poll
    assert order == ["read-start", "read-end", "op"]


async def test_control_keeps_the_telemetry_readings(hass: HomeAssistant, mock_uss) -> None:
    """A command must not blank the power/compressor entities.

    The op connection carries the AC's status echo but no extended report (that query belongs to a
    read cycle), so confirming from the echo alone left every telemetry entity `unknown` until the
    next poll — which the command itself had just pushed a full interval away. The last reading
    stands in instead.
    """
    mock_uss.read.return_value = [make_status_frame(), make_extended_frame()]
    await _setup(hass)
    assert float(hass.states.get("sensor.downstairs_ac_power").state) == 910.0

    mock_uss.send.return_value = [make_status_frame(target_temp=26)]   # status echo, no telemetry
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": CLIMATE, "temperature": 26}, blocking=True
    )
    await hass.async_block_till_done()

    assert hass.states.get(CLIMATE).attributes["temperature"] == 26.0   # the command took effect
    assert float(hass.states.get("sensor.downstairs_ac_power").state) == 910.0
    assert float(hass.states.get("sensor.downstairs_ac_current").state) == 4.0
    assert float(hass.states.get("sensor.downstairs_ac_frequency").state) == 43.0
    assert float(hass.states.get("sensor.downstairs_ac_coil_temperature").state) == 12.0
    assert hass.states.get("binary_sensor.downstairs_ac_compressor").state == "on"


async def test_switching_off_drops_the_stale_telemetry(hass: HomeAssistant, mock_uss) -> None:
    """Holding the previous reading stops at an on/off change: an AC that was drawing 910 W draws
    nothing once it is off, so the figures are dropped rather than held as a plausible lie."""
    mock_uss.read.return_value = [make_status_frame(), make_extended_frame()]
    await _setup(hass)
    assert float(hass.states.get("sensor.downstairs_ac_power").state) == 910.0

    mock_uss.send.return_value = [make_status_frame(power=False)]
    await hass.services.async_call(
        "climate", "turn_off", {"entity_id": CLIMATE}, blocking=True
    )
    await hass.async_block_till_done()

    assert hass.states.get(CLIMATE).state == "off"
    assert hass.states.get("sensor.downstairs_ac_power").state == "unknown"
    assert hass.states.get("binary_sensor.downstairs_ac_compressor").state == "unknown"


async def test_telemetry_survives_a_dropped_reply_then_expires(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """A read cycle whose extended reply does not arrive keeps the last reading too — but only for
    TELEMETRY_MAX_AGE, so a unit that has actually stopped reporting reads unknown rather than
    staying frozen on an old number."""
    mock_uss.read.return_value = [make_status_frame(), make_extended_frame()]
    await _setup(hass)

    mock_uss.read.return_value = [make_status_frame()]      # extended reply missing from now on
    await _tick(hass, freezer)
    assert float(hass.states.get("sensor.downstairs_ac_power").state) == 910.0

    freezer.tick(timedelta(seconds=TELEMETRY_MAX_AGE))
    await _tick(hass, freezer)
    assert hass.states.get("sensor.downstairs_ac_power").state == "unknown"
    assert hass.states.get(CLIMATE).state == "cool"        # the status itself still decodes


OUTDOOR = "sensor.downstairs_ac_outdoor_temperature"


async def test_a_parked_outdoor_reading_goes_unknown_once_the_unit_has_been_off(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """The outdoor probe is in the outdoor unit, which sleeps when the AC is off — so the indoor
    board repeats the last value it took, for as long as the unit stays off. Published as a
    MEASUREMENT it would write that number into long-term statistics as though it had been
    measured, so past OUTDOOR_TEMP_MAX_AGE it reads unknown instead."""
    mock_uss.read.return_value = [make_status_frame(outdoor_temp=33)]
    await _setup(hass)
    assert float(hass.states.get(OUTDOOR).state) == 33.0

    # Off, but only just: a recently parked reading is still broadly true and stands.
    mock_uss.read.return_value = [make_status_frame(power=False, outdoor_temp=33)]
    await _tick(hass, freezer)
    assert float(hass.states.get(OUTDOOR).state) == 33.0

    freezer.tick(timedelta(seconds=OUTDOOR_TEMP_MAX_AGE))
    await _tick(hass, freezer)
    assert hass.states.get(OUTDOOR).state == "unknown"
    # ...and only that reading: the indoor probe is on the indoor board, which stays awake.
    assert float(hass.states.get("sensor.downstairs_ac_indoor_temperature").state) == 26.5
    assert hass.states.get(CLIMATE).state == "off"


async def test_a_running_unit_never_has_its_outdoor_reading_suppressed(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """The bound is about a dormant probe, not about a value that looks too steady. An AC that runs
    all day in stable weather reports the same number for hours and every one of them is a real
    measurement — withholding those would hide the decode faults absence is meant to reveal."""
    mock_uss.read.return_value = [make_status_frame(outdoor_temp=33)]
    await _setup(hass)

    freezer.tick(timedelta(seconds=OUTDOOR_TEMP_MAX_AGE * 3))
    await _tick(hass, freezer)
    assert float(hass.states.get(OUTDOOR).state) == 33.0


async def test_an_off_unit_that_keeps_refreshing_its_outdoor_reading_keeps_the_sensor(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """Staleness while off is documented behaviour, not a law, so it is watched for rather than
    assumed: a unit that sends a *different* value while off is plainly still reading its probe, and
    saying so resets the clock. Only a value that has actually sat unchanged is dropped."""
    mock_uss.read.return_value = [make_status_frame(power=False, outdoor_temp=33)]
    await _setup(hass)

    for offset, expected in ((1, 32), (2, 31)):
        freezer.tick(timedelta(seconds=OUTDOOR_TEMP_MAX_AGE))
        mock_uss.read.return_value = [
            make_status_frame(power=False, outdoor_temp=33 - offset)
        ]
        await _tick(hass, freezer)
        assert float(hass.states.get(OUTDOOR).state) == float(expected)


async def test_the_outdoor_bound_raises_nothing_and_warns_about_nothing(
    hass: HomeAssistant, mock_uss, freezer, caplog
) -> None:
    """A switched-off air conditioner is ordinary. Blanking the reading must not look like a fault:
    no repair, no warning in the log, and every other entity untouched."""
    from homeassistant.helpers import issue_registry as ir

    mock_uss.read.return_value = [make_status_frame(outdoor_temp=33)]
    await _setup(hass)
    mock_uss.read.return_value = [make_status_frame(power=False, outdoor_temp=33)]
    before = set(ir.async_get(hass).issues)
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        freezer.tick(timedelta(seconds=OUTDOOR_TEMP_MAX_AGE))
        await _tick(hass, freezer)

    assert hass.states.get(OUTDOOR).state == "unknown"
    # Scoped to this integration on purpose: jumping the clock makes asyncio grumble about a task
    # that took half an hour of frozen time, which says nothing about the code under test.
    assert not [
        r for r in caplog.records
        if r.levelno >= logging.WARNING and r.name.startswith("custom_components.haismart")
    ]
    # Nothing NEW: this entry already carries the rotation warning, which has nothing to do with a
    # parked probe. What matters is that going unknown adds no repair of its own.
    assert set(ir.async_get(hass).issues) == before
    # unknown, never unavailable: the entity is working and the value is simply not known.
    assert hass.states.get(OUTDOOR).state != "unavailable"


async def test_setup_retries_when_unreachable(hass: HomeAssistant, mock_uss) -> None:
    mock_uss.read.side_effect = OSError("connection refused")
    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_a_brief_outage_holds_the_reading_and_a_longer_one_does_not(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """A dropped read is not news; a unit that has stopped answering is.

    These modules take one session at a time and close it after ~17 s regardless, so a lost reply is
    ordinary — and taking every entity to `unavailable` for one of them reads as an integration
    erring constantly on a site whose Wi-Fi is rough (issue #6). The last reading stands in for
    STATUS_MISSES_HELD cycles, then the failure surfaces as it always did.
    """
    from custom_components.haismart.const import STATUS_MISSES_HELD

    await _setup(hass)
    assert hass.states.get(CLIMATE).state == "cool"

    mock_uss.read.side_effect = OSError("host down")
    for _ in range(STATUS_MISSES_HELD):
        await _tick(hass, freezer)
        assert hass.states.get(CLIMATE).state == "cool"    # held, not blanked

    await _tick(hass, freezer)
    assert hass.states.get(CLIMATE).state == "unavailable"

    mock_uss.read.side_effect = None
    await _tick(hass, freezer)
    assert hass.states.get(CLIMATE).state == "cool"


async def test_the_hold_expires_on_the_clock_as_well_as_the_count(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """A slow poll must not hold a stale reading for as long as its interval makes two cycles.

    The count alone would let a five-minute poll publish a reading a quarter of an hour old, so the
    hold is bounded by time too and whichever bound comes first ends it.
    """
    from custom_components.haismart.const import STATUS_HOLD_MAX_AGE

    await _setup(hass)
    mock_uss.read.side_effect = OSError("host down")

    await _tick(hass, freezer)
    assert hass.states.get(CLIMATE).state == "cool"

    freezer.tick(timedelta(seconds=STATUS_HOLD_MAX_AGE))
    await _tick(hass, freezer)
    assert hass.states.get(CLIMATE).state == "unavailable"


async def test_localkey_rotation_triggers_reauth(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """Empty read cycles + a newer key version on the AC -> ConfigEntryAuthFailed -> reauth."""
    entry = await _setup(hass)

    mock_uss.read.return_value = []
    mock_uss.read.side_effect = None
    mock_uss.probe.return_value = 5  # AC rotated: stored v4, AC says v5
    await _tick(hass, freezer)  # miss 1 — no probe yet
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    await _tick(hass, freezer)  # miss 2 — probe, mismatch, reauth
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_REAUTH
    # the entry stays loaded while reauth is pending; entities go unavailable
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(CLIMATE).state == "unavailable"
    # and an actionable repair is raised advising cloud creds for auto-healing
    from homeassistant.helpers import issue_registry as ir

    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, "stale_localkey_manual_reauth_A1B2C3D4E5F6"
    )
    assert issue is not None and issue.severity is ir.IssueSeverity.WARNING


def _gateway_entry() -> MockConfigEntry:
    """An entry configured for cloud MQTT-gateway localKey auto-refresh."""
    return _entry(
        gateway_username="0172114171",
        gateway_password="deadbeefdeadbeefdeadbeefdeadbeef",
        cloud_client_id="A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
        access_token="tok-abc",  # no refresh_token -> uses this token directly
    )


async def test_localkey_rotation_auto_refreshes_via_gateway(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """With gateway creds, a rotation is healed in-place via the cloud gateway — NO reauth flow."""
    from unittest.mock import patch

    from haismart_extractor import LocalKey

    from custom_components.haismart.const import CONF_LOCALKEY_VERSION as VER

    new_key = "ffeeddccbbaa99887766554433221100"
    entry = _gateway_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    mock_uss.read.return_value = []
    mock_uss.read.side_effect = None
    mock_uss.probe.return_value = 5  # AC rotated v4 -> v5

    def _refresh(_creds, _device_id, **_kw):
        # the fresh key now decrypts the AC's status again
        mock_uss.read.return_value = [mock_uss.frame]
        return LocalKey(key=new_key, version=5)

    with patch(
        "custom_components.haismart.coordinator.get_localkey_via_gateway",
        side_effect=_refresh,
    ) as gw:
        await _tick(hass, freezer)  # miss 1
        await _tick(hass, freezer)  # miss 2 -> probe, rotation, gateway auto-refresh
        await hass.async_block_till_done()
        await _tick(hass, freezer)  # clean cycle now reads with the new key
        await hass.async_block_till_done()

    assert gw.called
    # the fetch was asked to refresh this device's key
    assert gw.call_args.args[1] == "A1B2C3D4E5F6"
    # no reauth flow; the key + version are updated in place and persisted
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert entry.data[CONF_LOCAL_KEY] == new_key
    assert entry.data[VER] == 5
    # the AC recovered on the new key (not stuck unavailable / reauth)
    assert hass.states.get(CLIMATE).state != "unavailable"
    # self-healed silently — no manual-re-key repair is raised
    from homeassistant.helpers import issue_registry as ir

    assert ir.async_get(hass).async_get_issue(
        DOMAIN, "stale_localkey_manual_reauth_A1B2C3D4E5F6"
    ) is None


async def test_token_refresh_uses_has_shared_http_client(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """Regression (#2): minting an access token from the stored refreshToken must go through HA's
    shared httpx client. Letting the cloud library build its own client loads the CA bundle from
    disk on the event loop, which HA reports as a blocking call."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from haismart_extractor import LocalKey

    entry = _entry(
        cloud_client_id="A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
        refresh_token="2_RT",          # -> the token-refresh branch runs
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    mock_uss.read.return_value = []
    mock_uss.read.side_effect = None
    mock_uss.probe.return_value = 5  # AC rotated -> triggers the cloud refresh path

    def _refresh(_creds, _device_id, **_kw):
        mock_uss.read.return_value = [mock_uss.frame]
        return LocalKey(key="ffeeddccbbaa99887766554433221100", version=5)

    with patch(
        "custom_components.haismart.coordinator.get_localkey_via_gateway", side_effect=_refresh
    ), patch("custom_components.haismart.coordinator.HaierCloud") as cloud_cls:
        cloud_cls.return_value.refresh_token = AsyncMock(
            return_value=SimpleNamespace(access_token="tok-new")
        )
        await _tick(hass, freezer)  # miss 1
        await _tick(hass, freezer)  # miss 2 -> probe, rotation, cloud token refresh
        await hass.async_block_till_done()

    assert cloud_cls.call_args is not None
    assert cloud_cls.call_args.kwargs["transport"] is not None


async def test_gateway_refresh_failure_falls_back_to_reauth(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """If the gateway fetch fails, the coordinator still reauths (no silent stall)."""
    from unittest.mock import patch

    from haismart_extractor import GatewayError

    entry = _gateway_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    mock_uss.read.return_value = []
    mock_uss.read.side_effect = None
    mock_uss.probe.return_value = 5
    with patch(
        "custom_components.haismart.coordinator.get_localkey_via_gateway",
        side_effect=GatewayError("CONNACK rc=4"),
    ):
        await _tick(hass, freezer)
        await _tick(hass, freezer)
        await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_REAUTH
    assert entry.data[CONF_LOCAL_KEY] == "00112233445566778899aabbccddeeff"  # unchanged


async def test_diagnostics_redacts_secrets(hass: HomeAssistant, mock_uss) -> None:
    from custom_components.haismart.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = await _setup(hass)
    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["entry"][CONF_LOCAL_KEY] == "**REDACTED**"
    # The deviceId is NOT redacted: it is just the Wi-Fi MAC, it is not a credential, and it is
    # needed to interpret a status capture. What must never appear is the account credentials -
    # `refresh_token` in particular is durable and reusable, so leaking it in the file users are
    # told to attach to issues would hand over the whole Haier account.
    assert diag["entry"][CONF_DEVICE_ID] == "**REDACTED**"
    assert diag["localkey_version"] == 4
    assert diag["state"]["mode"] == "cool"
    assert diag["profile"]["product_code"] == "AAC1UKZ01"
    # decrypted status bytes carry no secret and are kept for offset debugging
    assert diag["last_raw_status"] == mock_uss.frame.hex()


async def test_diagnostics_redacts_cloud_credentials(hass: HomeAssistant, mock_uss) -> None:
    """Every credential a cloud-onboarded entry stores must be redacted, and must not survive
    anywhere else in the payload. The older test above builds an entry with no tokens in it, so it
    was structurally incapable of noticing that the account tokens were dumped in full — and users
    are asked to attach this file to public issues. `refresh_token` is durable and reusable: leaking
    it hands over the whole Haier account.
    """
    import json

    from custom_components.haismart.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    secrets = {
        "refresh_token": "2_SECRET_REFRESH",
        "access_token": "SECRET_ACCESS",
        "cloud_client_id": "SECRETCLIENTID0123456789ABCDEF01",
        "gateway_username": "0172114171",
        "gateway_password": "SECRETGATEWAYPASSWORD0000000000",
    }
    entry = _entry(**secrets)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, entry)
    dumped = json.dumps(diag)
    for key, value in secrets.items():
        assert diag["entry"][key] == "**REDACTED**", key
        assert value not in dumped, f"{key} leaked elsewhere in the payload"
    assert diag["entry"][CONF_LOCAL_KEY] == "**REDACTED**"


async def test_empty_reads_same_version_is_transient(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """No decodable status but the key version still matches -> UpdateFailed, no reauth."""
    await _setup(hass)

    mock_uss.read.return_value = []
    await _tick(hass, freezer)
    await _tick(hass, freezer)  # probe runs, versions match (both v4)
    await _tick(hass, freezer)  # ...and past the cycles the last reading stands in for
    assert hass.states.get(CLIMATE).state == "unavailable"
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_prolonged_outage_never_falsely_reauths_and_throttles_probe(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """Many empty cycles with a matching key version: never reauth, and the version probe is
    throttled (reset after a matching probe) rather than fired every single cycle."""
    await _setup(hass)
    mock_uss.read.return_value = []
    mock_uss.probe.reset_mock()

    for _ in range(6):
        await _tick(hass, freezer)

    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert hass.states.get(CLIMATE).state == "unavailable"
    # 6 empty cycles, probe every _MISSES_BEFORE_PROBE(=2) -> 3 probes, not 6
    assert mock_uss.probe.call_count == 3


async def test_recovery_after_probe_reset(hass: HomeAssistant, mock_uss, freezer) -> None:
    """A miss that reset the counter still recovers cleanly on the next good read."""
    await _setup(hass)
    mock_uss.read.return_value = []
    await _tick(hass, freezer)
    await _tick(hass, freezer)  # probe + reset
    await _tick(hass, freezer)  # ...and past the hold, so the entity really is unavailable
    assert hass.states.get(CLIMATE).state == "unavailable"

    mock_uss.read.return_value = [make_status_frame(target_temp=22)]
    await _tick(hass, freezer)
    climate = hass.states.get(CLIMATE)
    assert climate.state == "cool"
    assert climate.attributes["temperature"] == 22.0


async def test_coordinator_builds_profile_from_digital_model(hass: HomeAssistant, mock_uss) -> None:
    """A config entry with a stored cloud digital model self-builds the profile from it."""
    import json as _json

    from custom_components.haismart.const import CONF_DIGITAL_MODEL
    from custom_components.haismart.coordinator import _build_profile, _load_digital_model

    # a model whose fan enum differs from the hardcoded AAC1UKZ01 profile — proves it's used
    model = {"attributes": [
        {"name": "windSpeed", "valueRange": {"type": "LIST", "dataList": [
            {"data": "1", "desc": "高"}, {"data": "5", "desc": "自动"}]}},
        {"name": "operationMode", "valueRange": {"type": "LIST", "dataList": [
            {"data": "1", "desc": "制冷"}]}},
    ]}
    entry = _entry(**{CONF_DIGITAL_MODEL: _json.dumps(model)})
    prof = _build_profile(entry, "AAC1UKZ01", _load_digital_model(entry))
    assert prof.fan_values == {"1": "high", "5": "auto"}  # from the model, not the 4-val default
    assert prof.mode_values == {"1": "cool"}


async def test_coordinator_falls_back_to_hardcoded_profile(hass: HomeAssistant, mock_uss) -> None:
    from haismart_hrdp import profile_for

    from custom_components.haismart.coordinator import _build_profile, _load_digital_model

    entry = _entry()  # no digital model stored
    prof = _build_profile(entry, "AAC1UKZ01", _load_digital_model(entry))
    assert prof.fan_values == profile_for("AAC1UKZ01").fan_values


# --- per-model write lockdown (validate_write wired into the send path) ---------------------------
# A deliberately restrictive model: temperature capped at 24, only cool + auto-fan. The capture
# allowlist would still accept e.g. mode=dry or temp=30, but the device model must veto them.
_LOCKED_MODEL = {"attributes": [
    {"name": "targetTemperature", "writable": True, "valueRange": {
        "type": "STEP", "dataStep": {"minValue": "16", "maxValue": "24", "step": "1"}}},
    {"name": "operationMode", "writable": True, "valueRange": {
        "type": "LIST", "dataList": [{"data": "1", "desc": "cool"}]}},
    {"name": "windSpeed", "writable": True, "valueRange": {
        "type": "LIST", "dataList": [{"data": "5", "desc": "auto"}]}},
]}


async def _setup_with_model(hass: HomeAssistant, model: dict):
    import json as _json

    from custom_components.haismart.const import CONF_DIGITAL_MODEL

    entry = _entry(**{CONF_DIGITAL_MODEL: _json.dumps(model)})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_model_rejects_out_of_range_temperature(hass: HomeAssistant, mock_uss) -> None:
    import pytest
    from homeassistant.exceptions import HomeAssistantError

    entry = await _setup_with_model(hass, _LOCKED_MODEL)
    with pytest.raises(HomeAssistantError, match="does not accept that setting"):
        await entry.runtime_data.async_send_control({"targetTemperature": 30 - 16})
    assert mock_uss.send.await_count == 0  # rejected before any write


async def test_model_rejects_unsupported_enum(hass: HomeAssistant, mock_uss) -> None:
    import pytest
    from homeassistant.exceptions import HomeAssistantError

    entry = await _setup_with_model(hass, _LOCKED_MODEL)
    # dry (2) passes the capture allowlist, but the model lists only cool -> the model vetoes it
    with pytest.raises(HomeAssistantError, match="does not accept that setting"):
        await entry.runtime_data.async_send_control({"operationMode": 2})
    assert mock_uss.send.await_count == 0


async def test_model_allows_in_range_control(hass: HomeAssistant, mock_uss) -> None:
    entry = await _setup_with_model(hass, _LOCKED_MODEL)
    await entry.runtime_data.async_send_control({"targetTemperature": 22 - 16})
    assert mock_uss.send.await_count == 1  # 22 is within [16, 24] -> sent


async def test_device_specific_field_skips_model_gate(hass: HomeAssistant, mock_uss) -> None:
    # ecoMode isn't a standard model attribute, so the model gate must not touch it — the capture
    # allowlist stays its sole gate (a valid eco level still sends under the restrictive model).
    entry = await _setup_with_model(hass, _LOCKED_MODEL)
    await entry.runtime_data.async_send_control({"ecoMode": 6})
    assert mock_uss.send.await_count == 1


# The SHAPE the real cloud model actually uses: booleans are LIST
# enums with codes 'false'/'true' (NOT 0/1), and Haier flags several confirmed grSetDAC fields
# (targetTemperature, rapidMode) as writable=False. Regression guard for both fixes.
_REAL_SHAPE_MODEL = {"attributes": [
    {"name": "targetTemperature", "writable": False, "valueRange": {  # read-only in cloud model...
        "type": "STEP", "dataStep": {"minValue": "16", "maxValue": "30", "step": "1"}}},
    {"name": "operationMode", "writable": True, "valueRange": {
        "type": "LIST", "dataList": [{"data": c} for c in ("0", "1", "2", "6")]}},
    {"name": "screenDisplayStatus", "writable": True, "valueRange": {
        "type": "LIST", "dataList": [{"data": "false"}, {"data": "true"}]}},
    {"name": "rapidMode", "writable": False, "valueRange": {  # ...yet observed in real app writes
        "type": "LIST", "dataList": [{"data": "false"}, {"data": "true"}]}},
]}


async def test_boolean_switch_maps_to_false_true_code(hass: HomeAssistant, mock_uss) -> None:
    # The exact bug: screenDisplayStatus=1 must validate against the model's ['false','true'] codes
    # (was rejected as "screenDisplayStatus='1' not in allowed ['false', 'true']").
    entry = await _setup_with_model(hass, _REAL_SHAPE_MODEL)
    await entry.runtime_data.async_send_control({"screenDisplayStatus": 1})
    assert mock_uss.send.await_count == 1


async def test_model_writable_false_field_still_sends(hass: HomeAssistant, mock_uss) -> None:
    # targetTemperature and rapidMode are writable=False in the cloud model but confirmed —
    # the send path authorizes writability via the capture allowlist, gating only the valueRange.
    entry = await _setup_with_model(hass, _REAL_SHAPE_MODEL)
    await entry.runtime_data.async_send_control({"targetTemperature": 25 - 16})
    await entry.runtime_data.async_send_control({"rapidMode": 1})
    assert mock_uss.send.await_count == 2


async def test_model_valuerange_still_enforced_when_writable_bypassed(
    hass: HomeAssistant, mock_uss
) -> None:
    # Bypassing the writable flag must NOT weaken valueRange gating: a temp above the STEP max is
    # still vetoed even though the field is writable=False.
    import pytest
    from homeassistant.exceptions import HomeAssistantError

    entry = await _setup_with_model(hass, _REAL_SHAPE_MODEL)
    with pytest.raises(HomeAssistantError, match="does not accept that setting"):
        await entry.runtime_data.async_send_control({"targetTemperature": 40 - 16})
    assert mock_uss.send.await_count == 0


async def test_localkey_backup_sensor_disabled_by_default(
    hass: HomeAssistant, mock_uss
) -> None:
    """The localKey backup sensor exists but is diagnostic + disabled (it's a secret)."""
    from homeassistant.const import EntityCategory
    from homeassistant.helpers import entity_registry as er

    await _setup(hass)
    reg = er.async_get(hass)
    eid = reg.async_get_entity_id("sensor", DOMAIN, "A1B2C3D4E5F6_local_key")
    assert eid is not None
    ent = reg.entities[eid]
    assert ent.disabled_by is not None                       # opt-in
    assert ent.entity_category == EntityCategory.DIAGNOSTIC
    assert hass.states.get(eid) is None                      # no state while disabled


async def test_localkey_backup_sensor_exposes_key_when_enabled(
    hass: HomeAssistant, mock_uss
) -> None:
    """Enabled, it exposes the key + the manual-onboarding fields for backup."""
    from homeassistant.helpers import entity_registry as er

    entry = await _setup(hass)
    reg = er.async_get(hass)
    eid = reg.async_get_entity_id("sensor", DOMAIN, "A1B2C3D4E5F6_local_key")
    reg.async_update_entity(eid, disabled_by=None)           # user enables it
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    st = hass.states.get(eid)
    assert st is not None
    assert st.state == "00112233445566778899aabbccddeeff"    # the localKey
    assert st.attributes["device_id"] == "A1B2C3D4E5F6"
    assert st.attributes[CONF_HOST] == "192.168.1.50"
    assert st.attributes[CONF_LOCALKEY_VERSION] == 4


async def test_unknown_report_layout_degrades_and_reports(hass: HomeAssistant, mock_uss) -> None:
    """An unrecognised report length must work partially, say so, and refuse to write.

    Before, it decoded to nothing and surfaced as "no decodable status" - indistinguishable from a
    stale key - while diagnostics reported a null blob, i.e. the one artefact needed to fix it was
    discarded. Now: the layout-independent fields still drive the thermostat, a repair explains the
    situation, and control is refused rather than guessing where the control words end.
    """
    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.helpers import issue_registry as ir

    from custom_components.haismart.const import ISSUE_UNKNOWN_LAYOUT

    # a real 125-byte report with one byte appended -> an odd span, so not derivable
    mock_uss.read.return_value = [mock_uss.frame + b"\x00"]
    await _setup(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    coordinator = entry.runtime_data

    state = coordinator.data
    assert state["partial"] is True and state["layout"] == "unknown"
    # the thermostat still works ...
    assert "power" in state and "target_temperature" in state and "operation_mode" in state
    # ... and nothing whose offset depends on the word count was invented
    assert "current_temperature" not in state
    assert "outdoor_temperature" not in state

    # the blob is RETAINED, which is what a maintainer needs
    assert coordinator.last_raw_status == mock_uss.frame + b"\x00"
    assert coordinator.unknown_layout == len(mock_uss.frame) + 1

    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, f"{ISSUE_UNKNOWN_LAYOUT}_{coordinator.device_id}")

    # writing is refused, with a reason rather than a stack trace
    with pytest.raises(HomeAssistantError, match="not recognised"):
        await coordinator.async_send_control({"onOffStatus": 1})


async def test_diagnostics_carry_what_a_new_model_report_needs(
    hass: HomeAssistant, mock_uss
) -> None:
    """Diagnostics must be sufficient to add a layout without a second round-trip."""
    from custom_components.haismart.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = await _setup(hass)
    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["report"]["length"] == len(mock_uss.frame)
    assert diag["report"]["unknown_layout"] is None
    assert 125 in diag["report"]["known_lengths"] and 127 in diag["report"]["known_lengths"]
    assert diag["report"]["layout"]["resolved"] is True
    assert diag["report"]["layout"]["verified"] is True
    assert diag["last_raw_status"] == mock_uss.frame.hex()


async def test_diagnostics_read_the_attributes_the_device_declares(
    hass: HomeAssistant, mock_uss
) -> None:
    """A unit declares far more attributes than any family map carries, all at published positions.

    Diagnostics reads them and reports what they say. They land here rather than in entities first
    because the placement rests on the published map rather than on a capture per attribute, and a
    wrong value in a diagnostics file costs nothing.
    """
    from custom_components.haismart.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = await _setup_with_model(hass, {
        "attributes": [
            {"name": "lockStatus", "valueRange": {"type": "LIST"}},
            {"name": "indoorHumidity", "valueRange": {"type": "STEP"}},
            {"name": "onOffStatus", "valueRange": {"type": "LIST"}},   # the map already has it
            # so does the display light, now that this family reads its comfort settings back
            {"name": "screenDisplayStatus", "valueRange": {"type": "LIST"}},
        ],
    })
    diag = await async_get_config_entry_diagnostics(hass, entry)

    declared = diag["model_declared_fields"]
    assert declared is not None, "a classic unit's declared attributes were not read"
    assert set(declared) == {"lockStatus", "indoorHumidity"}
    assert declared["lockStatus"] is False


async def test_diagnostics_carry_the_values_the_device_reports(
    hass: HomeAssistant, mock_uss
) -> None:
    """The values the device publishes must be in the file, not just the ranges they fall in.

    They are the tie-breaker the layout search uses, so without them a maintainer re-running the
    search over the attachments — which is how a reporter's stated states get scored at all — ranks
    on plausibility alone and cannot reproduce the candidates the file itself carries.
    """
    from custom_components.haismart.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = await _setup_with_model(hass, {
        "attributes": [
            {"name": "targetTemperature", "value": "24",
             "valueRange": {"type": "STEP", "dataStep": {"minValue": "16", "maxValue": "30"}}},
            {"name": "onOffStatus", "value": "true", "valueRange": {"type": "LIST"}},
            # no value reported -- must not appear as a null
            {"name": "windSpeed", "valueRange": {"type": "LIST"}},
        ],
    })
    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["digital_model"]["reported_values"] == {
        "targetTemperature": "24", "onOffStatus": "true"
    }
    # and the ranges are still there beside them
    assert "windSpeed" in diag["digital_model"]["attributes"]


async def test_diagnostics_propose_layouts_for_an_unrecognised_report(
    hass: HomeAssistant, mock_uss
) -> None:
    """An unrecognised report must arrive with candidate layouts attached.

    The point is that a diagnostics download is self-sufficient: without this, every new model costs
    a round-trip to the reporter before anyone can even see what the report might be. The candidates
    are proposals to check, not conclusions — but they turn a blank page into a shortlist.
    """
    from haismart_hrdp import parse_full_status

    from custom_components.haismart.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    # a real report with one byte appended -> a length nothing claims
    mock_uss.read.return_value = [mock_uss.frame + b"\x00"]
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    assert coordinator.unknown_layout is not None

    diag = await async_get_config_entry_diagnostics(hass, entry)
    layout = diag["report"]["layout"]
    assert layout["resolved"] is False
    # This report IS the classic family, so that is what must be proposed -- and the proposal has to
    # reproduce the decode the classic path itself produces, or it is not a usable starting point.
    candidates = layout["candidates"]
    assert candidates, "no layout proposed for a report that is a known map plus a stray byte"
    best = candidates[0]
    assert best["family"] == "classic"
    # ... and it must reproduce what the classic path itself decodes from the unpadded report,
    # field for field. A proposal that merely looks plausible is not a usable starting point.
    truth = parse_full_status(mock_uss.frame)
    assert best["decoded"][0] == {
        key: truth[key]
        for key in (
            "power", "target_temperature", "current_temperature", "outdoor_temperature",
            "operation_mode", "wind_speed", "swing_vertical", "heat_capable",
            "error_code", "last_changed_by",
        )
    }

    # the reports the proposals were derived from are kept, and dropped once a layout is recognised
    assert coordinator.recent_reports
    coordinator._clear_unknown_layout()
    assert coordinator.recent_reports == ()


async def test_control_errors_are_translated_and_name_the_device(
    hass: HomeAssistant, mock_uss
) -> None:
    """Control failures must read as sentences, not as raw Python.

    They used to surface as `failed to send control to 192.168.1.50: [Errno 113] No route to host`
    and `control rejected by the device model: ...` — untranslatable, and written for whoever wrote
    the code rather than whoever is holding the phone.
    """
    from homeassistant.exceptions import HomeAssistantError

    await _setup(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    coordinator = entry.runtime_data

    mock_uss.send.side_effect = OSError("[Errno 113] No route to host")
    with pytest.raises(HomeAssistantError) as err:
        await coordinator.async_send_control({"onOffStatus": 1})

    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == "control_failed"
    message = str(err.value)
    assert entry.title in message, "the message should say WHICH air conditioner"
    assert "No route to host" in message, "the underlying cause is still worth keeping"


async def test_undecodable_frames_are_debug_logged(
    hass: HomeAssistant, mock_uss, freezer, caplog
) -> None:
    """A read that decrypts but doesn't decode must log the frame, so the report is actionable:
    the localKey is fine and what the AC pushed simply isn't a status report.

    An unrecognised report *length* is a different case entirely here — it decodes partially and
    raises a repair (see `test_unknown_report_layout_degrades_and_reports`), so it never reaches
    this log.
    """
    await _setup(hass)
    caplog.set_level("DEBUG", logger="custom_components.haismart.coordinator")
    caplog.clear()

    # decrypts fine (it came back from async_read_status) but isn't a full-status report
    mock_uss.read.return_value = [bytes.fromhex("00002799") + bytes(60)]
    await _tick(hass, freezer)

    assert "localKey is good" in caplog.text
    assert "unrecognised frame" in caplog.text
    assert "len=64 00002799" in caplog.text  # length + the frame itself, for offset work


async def test_nothing_decrypted_is_debug_logged_as_key_or_silence(
    hass: HomeAssistant, mock_uss, freezer, caplog
) -> None:
    """The other half: no payloads at all means the AC pushed nothing OR the key is wrong/stale
    (a failed MD5 check is dropped silently), and the log has to say so — they're indistinguishable
    here but need opposite fixes."""
    await _setup(hass)
    caplog.set_level("DEBUG", logger="custom_components.haismart.coordinator")
    caplog.clear()

    mock_uss.read.return_value = []
    await _tick(hass, freezer)

    assert "nothing decrypted this cycle" in caplog.text
    assert "wrong/stale key" in caplog.text
    assert "localKey v4" in caplog.text  # the stored version, for comparing against the AC's


# --- cloud-connectivity sensor (key-free UDISCOVERY query) -----------------------------------

CLOUD = "binary_sensor.downstairs_ac_cloud_connection"


async def test_cloud_sensor_reports_the_ac_reaching_haier(
    hass: HomeAssistant, mock_uss
) -> None:
    """The AC answers a local, unauthenticated query with its own cloud state — the whole point
    being that verifying a firewall block never requires contacting Haier."""
    await _setup(hass)

    state = hass.states.get(CLOUD)
    assert state is not None
    assert state.state == "on"
    assert state.attributes["raw_state"] == 1000


async def test_cloud_sensor_goes_off_when_the_ac_is_firewalled(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """`off` is the state a user who blocked their AC wants to see, and 1006 is the code a unit
    reports while it cannot reach the cloud."""
    from haismart_hrdp.udiscovery import DeviceInfo

    mock_uss.cloud.return_value = DeviceInfo(
        device_id="A1B2C3D4E5F6", host="192.168.1.50", cloud_state=1006
    )
    await _setup(hass)
    freezer.tick(timedelta(seconds=UDISCOVERY_INTERVAL + 1))
    await _tick(hass, freezer)

    state = hass.states.get(CLOUD)
    assert state.state == "off"
    assert state.attributes["raw_state"] == 1006


async def test_silent_unit_reads_unknown_not_disconnected(
    hass: HomeAssistant, mock_uss
) -> None:
    """A module that doesn't implement the query must not be reported as cut off — that would tell
    someone their firewall works when nothing was ever measured."""
    mock_uss.cloud.return_value = None
    await _setup(hass)

    state = hass.states.get(CLOUD)
    assert state.state == "unknown"
    assert state.attributes["raw_state"] is None


async def test_cloud_query_is_throttled_and_then_backed_off(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """Two behaviours that keep this cheap: the query runs on its own slow cadence rather than every
    status read (the flag only moves on a ~4-minute timescale), and a unit that stays silent while
    demonstrably reachable stops being asked on that cadence."""
    await _setup(hass)
    assert mock_uss.cloud.await_count == 1

    await _tick(hass, freezer)  # a normal poll interval is shorter than UDISCOVERY_INTERVAL
    assert mock_uss.cloud.await_count == 1

    mock_uss.cloud.return_value = None
    for _ in range(UDISCOVERY_MISSES + 2):
        freezer.tick(timedelta(seconds=UDISCOVERY_INTERVAL + 1))
        await _tick(hass, freezer)
    # the successful query at setup, then exactly UDISCOVERY_MISSES silent ones, then it stops
    # asking on the minute cadence (see the retry test below for what happens an hour later)
    assert mock_uss.cloud.await_count == 1 + UDISCOVERY_MISSES

    # ...and the entity says "unknown" rather than inventing a state
    assert hass.states.get(CLOUD).state == "unknown"


async def test_a_silent_unit_is_retried_an_hour_later(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """Backing off must not mean giving up for the rest of the run.

    Three lost datagrams in a row is something a busy access point does, and a module can gain the
    capability in a firmware update — so an hour later it is asked again, and an answer restores the
    sensor, the firmware version and the cloud-free uPlusId learning.
    """
    from haismart_hrdp.udiscovery import DeviceInfo

    mock_uss.cloud.return_value = None
    entry = await _setup(hass)
    for _ in range(UDISCOVERY_MISSES + 1):
        freezer.tick(timedelta(seconds=UDISCOVERY_INTERVAL + 1))
        await _tick(hass, freezer)
    assert entry.runtime_data.supports_udiscovery is False
    asked_when_given_up = mock_uss.cloud.await_count

    # nothing more on the minute cadence...
    freezer.tick(timedelta(seconds=UDISCOVERY_INTERVAL + 1))
    await _tick(hass, freezer)
    assert mock_uss.cloud.await_count == asked_when_given_up

    # ...but an hour later it tries again, and the unit is answering now
    mock_uss.cloud.return_value = DeviceInfo(
        device_id="A1B2C3D4E5F6", host="192.168.1.50", cloud_state=1000, firmware=("1.2.3",)
    )
    freezer.tick(timedelta(seconds=UDISCOVERY_RETIRE_INTERVAL))
    await _tick(hass, freezer)
    assert mock_uss.cloud.await_count == asked_when_given_up + 1
    assert entry.runtime_data.supports_udiscovery is True
    assert hass.states.get(CLOUD).state == "on"


async def test_cloud_query_failure_never_breaks_polling(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """It is a diagnostic signal riding along inside the read cycle, so a socket error on it must
    not be able to take the climate entity down."""
    await _setup(hass)
    mock_uss.cloud.side_effect = OSError("network unreachable")
    freezer.tick(timedelta(seconds=UDISCOVERY_INTERVAL + 1))
    await _tick(hass, freezer)

    assert hass.states.get(CLIMATE).state == "cool"
    assert hass.states.get(CLOUD).state == "unknown"


async def test_diagnostics_carry_cloud_reachability(
    hass: HomeAssistant, mock_uss
) -> None:
    """A cut-off AC cannot be re-keyed, so this explains a stale-localKey report that would
    otherwise look like a protocol bug."""
    from custom_components.haismart.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = await _setup(hass)
    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["cloud"] == {
        "connected": True,
        "raw_state": 1000,
        "state_name": "connected",
        "supported": True,
        "reported_host": "192.168.1.50",
        "reported_port": 56800,
        "host_matches": True,
    }


async def test_diagnostics_flags_an_ac_that_moved_on_dhcp(
    hass: HomeAssistant, mock_uss
) -> None:
    """A DHCP move presents as "the AC stopped responding", indistinguishable from a dead unit or a
    bad key. The AC reports where it thinks it is, so say outright when that has diverged."""
    from haismart_hrdp.udiscovery import DeviceInfo

    from custom_components.haismart.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    mock_uss.cloud.return_value = DeviceInfo(
        device_id="A1B2C3D4E5F6", host="192.168.1.77", port=56800, cloud_state=1000
    )
    entry = await _setup(hass)
    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["cloud"]["reported_host"] == "192.168.1.77"
    assert diag["cloud"]["host_matches"] is False


async def test_diagnostics_report_the_stated_device_type_not_just_a_derived_class(
    hass: HomeAssistant, mock_uss
) -> None:
    """A uPlusId yields the device's *class*; the variant digits cannot be derived from it. Cloud
    onboarding is handed the full deviceType, so a report from unfamiliar hardware should name the
    variant exactly rather than leaving a maintainer to guess which sibling it is.

    Absent for manual installs — the LAN discovery payload carries a uPlusId but no deviceType — so
    the field reports None rather than a class dressed up as one."""
    from custom_components.haismart.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = _entry(**{CONF_DEVICE_TYPE: "0201203a"})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.device_type == "0201203a"
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["device_identity"]["device_type"] == "0201203a"
    # Independent identifiers, from different sources: this entry stored no uPlusId, so the derived
    # class is unavailable while the stated deviceType answers anyway.
    assert diag["device_identity"]["device_type_class"] is None

    bare = await _setup(hass)
    assert bare.runtime_data.device_type is None
    assert (await async_get_config_entry_diagnostics(hass, bare))["device_identity"][
        "device_type"
    ] is None


async def test_uplus_id_is_learned_from_the_device_and_persisted(
    hass: HomeAssistant, mock_uss
) -> None:
    """A manual (fully offline) install has no uPlusId, which is what forces the decoder to key on
    report length. The AC hands it over for free, so learn it — and write it to the config entry so
    it survives restarts and rides along in Home Assistant backups like the localKey does."""
    from haismart_hrdp.udiscovery import DeviceInfo

    uplus = "2008610800820324021200118012560000000000000000000000000000000040"
    mock_uss.cloud.return_value = DeviceInfo(
        device_id="A1B2C3D4E5F6", host="192.168.1.50", uplus_id=uplus, cloud_state=1000
    )
    entry = await _setup(hass)

    assert entry.data[CONF_UPLUS_ID] == uplus
    assert entry.runtime_data.uplus_id == uplus


async def test_cloud_provided_uplus_id_wins_over_the_device(
    hass: HomeAssistant, mock_uss
) -> None:
    """When onboarding already stored one, keep it: a mismatch is worth logging but not ours to
    resolve silently, and the cloud value is what the vendor app itself uses."""
    from haismart_hrdp.udiscovery import DeviceInfo

    mock_uss.cloud.return_value = DeviceInfo(
        device_id="A1B2C3D4E5F6", host="192.168.1.50", uplus_id="9" * 64, cloud_state=1000
    )
    entry = _entry(**{CONF_UPLUS_ID: "1" * 64})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.data[CONF_UPLUS_ID] == "1" * 64


async def test_all_zero_uplus_id_is_not_learned(hass: HomeAssistant, mock_uss) -> None:
    """An all-zero field means "not reported" — storing it would poison wire-model selection."""
    from haismart_hrdp.udiscovery import DeviceInfo

    mock_uss.cloud.return_value = DeviceInfo(
        device_id="A1B2C3D4E5F6", host="192.168.1.50", uplus_id="0" * 64, cloud_state=1000
    )
    entry = await _setup(hass)

    assert not entry.data.get(CONF_UPLUS_ID)


async def test_firmware_reaches_the_device_registry(hass: HomeAssistant, mock_uss) -> None:
    """Firmware belongs on the device page as a version, not as an entity."""
    from haismart_hrdp.udiscovery import DeviceInfo
    from homeassistant.helpers import device_registry as dr

    mock_uss.cloud.return_value = DeviceInfo(
        device_id="A1B2C3D4E5F6",
        host="192.168.1.50",
        firmware=("e_4.3.00", "R_6.0.01"),
        cloud_state=1000,
    )
    await _setup(hass)

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "A1B2C3D4E5F6")})
    assert device is not None
    assert device.sw_version == "e_4.3.00 / R_6.0.01"


async def test_firmware_learned_late_still_reaches_the_device_page(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """Firmware that arrives after the entities exist must still land on the device page.

    DeviceInfo is built once per entity, so a unit whose first discovery query went unanswered used
    to show no firmware version for the rest of the run even once it started answering.
    """
    from haismart_hrdp.udiscovery import DeviceInfo
    from homeassistant.helpers import device_registry as dr

    mock_uss.cloud.return_value = None                       # silent at setup
    await _setup(hass)
    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, "A1B2C3D4E5F6")})
    assert device is not None and device.sw_version is None

    mock_uss.cloud.return_value = DeviceInfo(
        device_id="A1B2C3D4E5F6",
        host="192.168.1.50",
        firmware=("e_4.3.00", "R_6.0.01"),
        cloud_state=1000,
    )
    freezer.tick(timedelta(seconds=UDISCOVERY_INTERVAL + 1))
    await _tick(hass, freezer)

    device = registry.async_get_device(identifiers={(DOMAIN, "A1B2C3D4E5F6")})
    assert device.sw_version == "e_4.3.00 / R_6.0.01"


async def test_localkey_backup_sensor_carries_the_uplus_id(
    hass: HomeAssistant, mock_uss, entity_registry
) -> None:
    """The backup sensor is the one-stop cloud-independent record: with the key AND the uPlusId, a
    manual re-add decodes the unit exactly as a cloud-onboarded one would."""
    from haismart_hrdp.udiscovery import DeviceInfo

    uplus = "2008610800820324021200118012560000000000000000000000000000000040"
    mock_uss.cloud.return_value = DeviceInfo(
        device_id="A1B2C3D4E5F6", host="192.168.1.50", uplus_id=uplus, cloud_state=1000
    )
    await _setup(hass)
    entity_registry.async_update_entity(
        "sensor.downstairs_ac_local_key", disabled_by=None
    )
    entries = hass.config_entries.async_entries(DOMAIN)
    await hass.config_entries.async_reload(entries[0].entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.downstairs_ac_local_key")
    assert state is not None
    assert state.attributes[CONF_UPLUS_ID] == uplus


async def test_ac_that_moved_on_dhcp_is_followed_automatically(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """These modules move on DHCP, which until now looked exactly like an AC that died: the entry
    kept pointing at the old address and only a human could fix it. The broadcast query answers with
    the deviceId, so the unit is recognised wherever it landed and the entry follows it."""

    entry = await _setup(hass)
    assert hass.states.get(CLIMATE).state == "cool"

    # the read fails at the old address, then succeeds once the coordinator follows the move
    mock_uss.read.side_effect = [OSError("no route to host"), [mock_uss.frame]]
    mock_uss.rediscover.return_value = "192.168.1.77"
    await _tick(hass, freezer)

    assert entry.data[CONF_HOST] == "192.168.1.77"
    assert entry.runtime_data.host == "192.168.1.77"
    # recovered inside the same cycle: the user never sees it go unavailable
    assert hass.states.get(CLIMATE).state == "cool"
    # ...and the device page's link follows too, rather than pointing at the address it left
    from homeassistant.helpers import device_registry as dr

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "A1B2C3D4E5F6")})
    assert device.configuration_url == "http://192.168.1.77"


async def test_rediscovery_leaves_host_alone_when_nothing_matches(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """Nothing on the network claiming to be this AC means the host stays put."""
    entry = await _setup(hass)
    mock_uss.read.side_effect = OSError("host down")
    mock_uss.rediscover.return_value = None
    for _ in range(3):   # past the cycles the previous reading stands in for
        await _tick(hass, freezer)

    assert entry.data[CONF_HOST] == "192.168.1.50"
    assert hass.states.get(CLIMATE).state == "unavailable"


async def test_rediscovery_is_cooled_down(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """A genuinely offline AC (powered off) must not trigger a network sweep on every poll."""
    await _setup(hass)
    mock_uss.read.side_effect = OSError("host down")

    for _ in range(4):
        await _tick(hass, freezer)
    assert mock_uss.rediscover.call_count == 1

    freezer.tick(timedelta(seconds=REDISCOVER_COOLDOWN + 1))
    await _tick(hass, freezer)
    assert mock_uss.rediscover.call_count == 2


async def test_runtime_data_writes_do_not_reload_the_integration(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """The coordinator writes to entry.data at runtime (rotated key, learned uPlusId, followed DHCP
    move). Update listeners fire on data changes too, so an unguarded reload would drop every entity
    in response to a change the integration had just made itself."""
    entry = await _setup(hass)
    before = entry.runtime_data

    mock_uss.read.side_effect = [OSError("no route to host"), [mock_uss.frame]]
    mock_uss.rediscover.return_value = "192.168.1.77"
    await _tick(hass, freezer)
    await hass.async_block_till_done()

    assert entry.data[CONF_HOST] == "192.168.1.77"
    assert entry.runtime_data is before  # same coordinator: no reload happened
    assert hass.states.get(CLIMATE).state == "cool"


async def test_options_change_still_reloads(hass: HomeAssistant, mock_uss) -> None:
    """The listener must still do its actual job: a new poll interval needs a rebuild."""
    entry = await _setup(hass)
    before = entry.runtime_data

    hass.config_entries.async_update_entry(entry, options={CONF_SCAN_INTERVAL: 60})
    await hass.async_block_till_done()

    assert entry.runtime_data is not before
    assert entry.runtime_data.update_interval == timedelta(seconds=60)


async def test_model_id_sensor_is_enabled_and_independent_of_the_key_sensor(
    hass: HomeAssistant, mock_uss
) -> None:
    """The uPlusId is a model identifier, not a secret — reading it must not require enabling the
    entity whose state is your localKey. It is what a bug report about an undecoded model needs."""
    from haismart_hrdp.udiscovery import DeviceInfo

    uplus = "2008610800820324021200118012560000000000000000000000000000000040"
    mock_uss.cloud.return_value = DeviceInfo(
        device_id="A1B2C3D4E5F6", host="192.168.1.50", uplus_id=uplus, cloud_state=1000
    )
    await _setup(hass)

    state = hass.states.get("sensor.downstairs_ac_model_id")
    assert state is not None                      # enabled by default
    # the state is shortened so a 64-character identifier does not run past the edge of the UI;
    # the exact value stays on the attribute, which is what a report should quote
    assert state.state == "2008610800820324\u20260040"
    assert state.attributes[CONF_UPLUS_ID] == uplus
    assert state.attributes["product_code"] == "AAC1UKZ01"
    # the key sensor stays disabled: the two are no longer coupled
    assert hass.states.get("sensor.downstairs_ac_local_key") is None


async def test_model_id_sensor_is_unknown_when_never_learned(
    hass: HomeAssistant, mock_uss
) -> None:
    """A manual entry whose AC doesn't answer the discovery query has no model ID — that must read
    unknown, not an empty string that looks like a real value."""
    mock_uss.cloud.return_value = None
    await _setup(hass)

    assert hass.states.get("sensor.downstairs_ac_model_id").state == "unknown"


async def test_cloud_sensor_labels_the_raw_code(hass: HomeAssistant, mock_uss, freezer) -> None:
    """`raw_state=1010` means nothing to a user; the label says which half of an outage they are
    looking at — still ramping down, or settled."""
    from haismart_hrdp.udiscovery import DeviceInfo

    mock_uss.cloud.return_value = DeviceInfo(
        device_id="A1B2C3D4E5F6", host="192.168.1.50", cloud_state=1010
    )
    await _setup(hass)

    state = hass.states.get(CLOUD)
    assert state.state == "off"
    assert state.attributes["raw_state"] == 1010
    assert state.attributes["state_name"] == "retrying"


async def test_fault_sensor_names_the_active_faults(hass: HomeAssistant, mock_uss) -> None:
    """A fault frame arrives with every status push, so the problem sensor costs no extra request.

    Naming the faults matters: "problem: on" tells an owner nothing, while the service code is what
    they quote to an engineer.
    """
    from haismart_hrdp import build_epp_frame

    def alarm_frame(flags: bytes) -> bytes:
        return b"\x00\x00\x27\x15" + bytes(76) + build_epp_frame(0x04, b"\x0f\x5a", flags)

    # position 20 = E1, indoor temperature sensor: low bit of the last byte is position 0, so
    # position 20 is bit 4 of the third byte from the end
    mock_uss.read.return_value = [mock_uss.frame, alarm_frame(bytes(5) + b"\x10" + bytes(2))]
    entry = await _setup(hass)

    fault = hass.states.get("binary_sensor.downstairs_ac_fault")
    assert fault is not None and fault.state == "on"
    assert fault.attributes["faults"] == ["E1 - Indoor temperature sensor failure"]
    assert fault.attributes["fault_codes"] == [20]
    assert entry.runtime_data.data["alarm_count"] == 1


async def test_fault_sensor_reads_clear_when_the_bitmap_is_empty(
    hass: HomeAssistant, mock_uss
) -> None:
    """An all-clear frame is a real answer -- distinct from never having seen one."""
    from haismart_hrdp import build_epp_frame

    mock_uss.read.return_value = [
        mock_uss.frame,
        b"\x00\x00\x27\x15" + bytes(76) + build_epp_frame(0x04, b"\x0f\x5a", bytes(8)),
    ]
    await _setup(hass)
    fault = hass.states.get("binary_sensor.downstairs_ac_fault")
    assert fault is not None and fault.state == "off"
    assert fault.attributes["faults"] == []


async def test_the_unit_can_veto_heat_that_its_model_advertises(
    hass: HomeAssistant, mock_uss
) -> None:
    """A model listing Heat does not make the hardware capable of it.

    The unit states its own heat capability in every status frame, and that has to win over a model
    claiming otherwise -- or the user gets a Heat button that silently does nothing. Putting Heat
    back needs the profile to be able to encode the mode as well, so capability alone is not enough.
    """
    from haismart_hrdp import STATUS_LAYOUTS

    heating_model = {"attributes": [
        {"name": "operationMode", "writable": True, "valueRange": {"type": "LIST", "dataList": [
            {"data": "1", "desc": "cool"}, {"data": "4", "desc": "heat"}]}},
        {"name": "windSpeed", "writable": True, "valueRange": {
            "type": "LIST", "dataList": [{"data": "5", "desc": "auto"}]}},
    ]}

    # the model says the unit heats; the unit says it does not
    cooling_only = bytearray(mock_uss.frame)
    cooling_only[STATUS_LAYOUTS[len(mock_uss.frame)].outdoor_temp + 1] |= 0x80
    mock_uss.read.return_value = [bytes(cooling_only)]

    await _setup_with_model(hass, heating_model)
    climate = hass.states.get("climate.downstairs_ac")
    assert "heat" not in climate.attributes["hvac_modes"], "cooling-only unit was offered Heat"


async def test_heat_is_offered_when_the_unit_and_its_model_agree(
    hass: HomeAssistant, mock_uss
) -> None:
    """The same model on a unit that does report heat capability keeps Heat."""
    heating_model = {"attributes": [
        {"name": "operationMode", "writable": True, "valueRange": {"type": "LIST", "dataList": [
            {"data": "1", "desc": "cool"}, {"data": "4", "desc": "heat"}]}},
        {"name": "windSpeed", "writable": True, "valueRange": {
            "type": "LIST", "dataList": [{"data": "5", "desc": "auto"}]}},
    ]}
    await _setup_with_model(hass, heating_model)
    climate = hass.states.get("climate.downstairs_ac")
    assert "heat" in climate.attributes["hvac_modes"]


_CO_COMMAND_MODEL = {
    "attributes": [
        {"name": "operationMode", "writable": True, "valueRange": {"type": "LIST", "dataList": [
            {"data": "1", "desc": "cool"}, {"data": "6", "desc": "fan"}]}},
        {"name": "windSpeed", "writable": True, "valueRange": {"type": "LIST", "dataList": [
            {"data": "3", "desc": "low"}, {"data": "5", "desc": "auto"}]}},
        {"name": "muteStatus", "writable": True, "valueRange": {"type": "LIST", "dataList": [
            {"data": "false"}, {"data": "true"}]}},
    ],
    "constraints": [
        {"pendingCondition": {"operator": "AND", "commands": {"operationMode": ["6"]}},
         "additionalCommands": {"commands": [
             {"name": "windSpeed", "value": "3"},
             {"name": "muteStatus", "value": "false"}]}},
    ],
}


async def test_the_model_s_co_commands_travel_with_the_change(
    hass: HomeAssistant, mock_uss
) -> None:
    """The unit drops a mode change that conflicts with the state it would leave behind.

    The model states which settings have to travel together, so sending the mode alone is what
    fails. Asserting on the frame proves the extras really reached the unit.
    """
    entry = await _setup_with_model(hass, _CO_COMMAND_MODEL)
    await entry.runtime_data.async_send_control({"operationMode": 6})

    assert _sent_field(mock_uss.send, "operationMode") == 6
    assert _sent_field(mock_uss.send, "windSpeed") == 3       # low, not the auto it was on
    assert _sent_field(mock_uss.send, "muteStatus") == 0


async def test_co_commands_never_override_an_explicit_choice(
    hass: HomeAssistant, mock_uss
) -> None:
    """A rule supplies a default; it must not overwrite what the user actually asked for."""
    entry = await _setup_with_model(hass, _CO_COMMAND_MODEL)
    await entry.runtime_data.async_send_control({"operationMode": 6, "windSpeed": 5})

    assert _sent_field(mock_uss.send, "windSpeed") == 5


# The rules a 209-byte unit is really governed by: its own family asks for the economy setting and a
# fan speed alongside dry, auto and fan-only -- and its group-set can write neither (the settable
# array stops at word 24). Rules are published per product, the write map per report layout, so this
# combination is not a mismatch to be corrected: it is normal, and every unit on the family hits it.
_UNWRITABLE_CO_COMMAND_MODEL = {
    "attributes": [
        {"name": "operationMode", "writable": True, "valueRange": {"type": "LIST", "dataList": [
            {"data": "1", "desc": "cool"}, {"data": "6", "desc": "fan"}]}},
        {"name": "muteStatus", "writable": True, "valueRange": {"type": "LIST", "dataList": [
            {"data": "false"}, {"data": "true"}]}},
    ],
    "constraints": [
        {"pendingCondition": {"operator": "OR", "commands": {"operationMode": ["6"]}},
         "additionalCommands": {"commands": [
             {"name": "generatorMode", "value": "0"},      # ecoMode: absent from extended-46
             {"name": "windSpeed", "value": "3"},          # also absent from extended-46
             {"name": "muteStatus", "value": "false"}]}},   # this one it can write
    ],
}


async def test_a_co_command_the_family_cannot_write_does_not_fail_the_command(
    hass: HomeAssistant, mock_uss
) -> None:
    """The mode change goes through, carrying the co-commands that fit and dropping the rest.

    Handing the encoder a field its family has no room for raised, and raising took the *whole*
    group-set with it: every mode change on a 209-byte unit failed with "'ecoMode' is not a writable
    field on extended46", so the air conditioner could not be put into dry, auto or fan-only at all
    (issue #6). A co-command is an addition made on the model's behalf; failing to place one must
    cost that co-command and nothing else.
    """
    from conftest import make_extended46_frame
    from haismart_hrdp.wire_models import select_wire_model

    frame = make_extended46_frame(mode_code=1)
    mock_uss.read.return_value = [frame]
    mock_uss.send.baseline = frame
    entry = await _setup_with_model(hass, _UNWRITABLE_CO_COMMAND_MODEL)

    await entry.runtime_data.async_send_control({"operationMode": 6})

    wm = select_wire_model(len(frame), None)
    sent = mock_uss.send.last_frame[12:-1]

    def field(name: str) -> int:
        wf = wm.write_fields[name]
        off = (wf.word - 1) * 2
        return ((sent[off] << 8) | sent[off + 1]) >> wf.bit & ((1 << wf.length) - 1)

    assert field("operationMode") == 6      # what was asked for, and it reached the unit
    assert field("muteStatus") == 0         # the co-command that this family can place
    assert "ecoMode" not in wm.write_fields and "windSpeed" not in wm.write_fields


async def test_fan_only_reaches_a_family_that_cannot_set_its_fan_speed(
    hass: HomeAssistant, mock_uss
) -> None:
    """Selecting fan-only through the entity works where the fan speed is read-only.

    Our own hardware silently drops fan-only combined with fan=auto, so the entity substitutes a
    concrete speed. On a family whose group-set has no fan speed in it that substitution could only
    ever raise -- and it would fail the very mode change it exists to make work.
    """
    from conftest import make_extended46_frame

    frame = make_extended46_frame(mode_code=1)
    mock_uss.read.return_value = [frame]
    mock_uss.send.baseline = frame
    await _setup_with_model(hass, _UNWRITABLE_CO_COMMAND_MODEL)

    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": CLIMATE, "hvac_mode": "fan_only"}, blocking=True
    )
    assert mock_uss.send.await_count == 1


async def test_controls_the_unit_ignores_stay_readable_and_refuse_the_command(
    hass: HomeAssistant, mock_uss
) -> None:
    """A unit in fan-only discards its setpoint, boost, quiet and sleep — its own model says so.

    Offering those controls as if they worked is how an owner ends up believing a setting took
    effect. Taking the entities away is not the answer either: the settings are still perfectly
    readable, so an unavailable entity reads as a fault and leaves a gap in the history for as long
    as the mode lasts. They stay, showing the truth, and the *command* is refused with the reason
    the model gives.

    The climate entity drops the temperature control rather than the whole entity — that is the
    mechanism Home Assistant provides for exactly this, and why the thermostat looks right while
    the switches looked broken.
    """
    mock_uss.read.return_value = [make_status_frame(mode_code=6, fan_code=3)]  # fan-only
    entry = _entry(digital_model=json.dumps(locking_digital_model()))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.locked_fields == {
        "targetTemperature", "silentSleepStatus", "muteStatus", "rapidMode", "ecoMode",
    }
    # readable throughout — a locked setting is a normal operating state, not a fault
    for key in ("sleep", "quiet", "strong", "health"):
        assert hass.states.get(f"switch.downstairs_ac_{key}").state not in (
            "unavailable", "unknown",
        )
    assert hass.states.get("select.downstairs_ac_eco").state not in ("unavailable", "unknown")

    # ...and the command is refused, naming the condition rather than failing blankly
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            "switch", "turn_on",
            {"entity_id": "switch.downstairs_ac_quiet"}, blocking=True,
        )
    assert "fan-only" in str(err.value) or "current state" in str(err.value)

    # a control the model does NOT lock in this mode still works
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.downstairs_ac_health"}, blocking=True,
    )

    climate = hass.states.get(CLIMATE)
    assert climate.state == "fan_only"                          # the entity itself still works
    features = ClimateEntityFeature(climate.attributes["supported_features"])
    assert ClimateEntityFeature.TARGET_TEMPERATURE not in features
    assert ClimateEntityFeature.FAN_MODE in features            # fan speed is still settable
    assert ClimateEntityFeature.TURN_ON in features
    # every preset's field is locked in this mode, so the control goes rather than standing empty
    assert ClimateEntityFeature.PRESET_MODE not in features
    assert "preset_modes" not in climate.attributes


async def test_a_fault_locks_the_settings_but_never_the_power(
    hass: HomeAssistant, mock_uss
) -> None:
    """A faulted unit ignores nearly every setting. It must still be possible to turn it off."""
    from haismart_hrdp import build_epp_frame

    alarm = b"\x00\x00\x27\x15" + bytes(76) + build_epp_frame(
        0x04, b"\x0f\x5a", bytes(7) + b"\x01"       # position 0 = the model's first real alarm
    )
    mock_uss.read.return_value = [make_status_frame(), alarm]
    entry = _entry(digital_model=json.dumps(locking_digital_model()))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert "windSpeed" in entry.runtime_data.locked_fields
    features = ClimateEntityFeature(hass.states.get(CLIMATE).attributes["supported_features"])
    assert ClimateEntityFeature.FAN_MODE not in features
    assert ClimateEntityFeature.TARGET_TEMPERATURE not in features
    assert ClimateEntityFeature.TURN_OFF in features and ClimateEntityFeature.TURN_ON in features
    # and the mode picker stays, because it is the way back
    assert hass.states.get(CLIMATE).attributes["hvac_modes"]


async def test_an_off_unit_keeps_its_controls(hass: HomeAssistant, mock_uss) -> None:
    """The model marks nearly everything unwritable while a unit is off, and that rule is not
    honoured on purpose: it also marks the MODE unwritable, which is exactly what this integration
    writes to turn a unit on — and hardware accepts it. Honouring it would hide the controls someone
    reaches for while setting up an air conditioner that is off."""
    mock_uss.read.return_value = [make_status_frame(power=False)]
    entry = _entry(digital_model=json.dumps(locking_digital_model()))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.locked_fields == frozenset()
    climate = hass.states.get(CLIMATE)
    assert climate.state == "off"
    features = ClimateEntityFeature(climate.attributes["supported_features"])
    assert ClimateEntityFeature.TARGET_TEMPERATURE in features
    assert hass.states.get("switch.downstairs_ac_health").state != "unavailable"


async def test_locking_is_a_no_op_without_a_model(hass: HomeAssistant, mock_uss) -> None:
    """The manual onboarding path stores no model, so nothing states these rules — every control
    stays as it was rather than guessing which ones a unit ignores."""
    mock_uss.read.return_value = [make_status_frame(mode_code=6, fan_code=3)]
    entry = await _setup(hass)

    assert entry.runtime_data.locked_fields == frozenset()
    assert hass.states.get("switch.downstairs_ac_quiet").state != "unavailable"


async def test_sleep_does_not_strand_the_preset_control(hass: HomeAssistant, mock_uss) -> None:
    """Sleep locks boost, so the Strong SWITCH refuses — but Boost must stay selectable as a
    preset, because a preset write clears sleep in the very same command. Filtering it out there
    would leave a unit stuck in whichever preset it was last given."""
    frame = make_status_frame()
    frame = bytes(frame[:97] + bytes([frame[97] | 0x20]) + frame[98:])   # sleep bit on
    mock_uss.read.return_value = [frame]
    mock_uss.send.baseline = frame
    entry = _entry(digital_model=json.dumps(locking_digital_model()))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert "rapidMode" in entry.runtime_data.locked_fields
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": "switch.downstairs_ac_strong"}, blocking=True,
        )

    climate = hass.states.get(CLIMATE)
    assert climate.attributes["preset_mode"] == "sleep"
    assert "boost" in climate.attributes["preset_modes"]
    await hass.services.async_call(
        "climate", "set_preset_mode", {"entity_id": CLIMATE, "preset_mode": "boost"}, blocking=True
    )
    assert _sent_field(mock_uss.send, "rapidMode") == 1
    assert _sent_field(mock_uss.send, "silentSleepStatus") == 0    # cleared in the same write


async def test_recorded_rules_reach_a_unit_whose_model_arrived_without_them(
    hass: HomeAssistant, mock_uss
) -> None:
    """End to end: the model a real unit hands out has no rules in it, so without filling them in
    nothing is ever locked. With them, fan-only stops offering the settings it discards."""
    from custom_components.haismart.const import CONF_UPLUS_ID

    model = heat_capable_digital_model()          # attributes only, exactly as a unit hands it out
    assert "modifiers" not in model
    mock_uss.read.return_value = [make_status_frame(mode_code=6, fan_code=3)]
    entry = _entry(digital_model=json.dumps(model), **{
        CONF_UPLUS_ID: "2008610800820324021200118012560000000000000000000000000000000040",
    })
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert "targetTemperature" in entry.runtime_data.locked_fields
    # and the lock reaches the entities: quiet is locked in fan-only, so the command is refused
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": "switch.downstairs_ac_quiet"}, blocking=True,
        )


async def test_setting_up_a_credentialed_entry_makes_no_real_request(
    hass: HomeAssistant, mock_uss, refused_cloud_requests
) -> None:
    """Setting an entry up starts the model-rules top-up in the background, and an entry carrying
    credentials makes that a live cloud call.

    That task can outlive the test body and run during teardown, which is how this suite came to
    resolve and dial a real host intermittently. The transport is refused for every test now; this
    asserts the path really is exercised on setup and really is intercepted, so the guard cannot
    quietly stop covering the thing it was added for.
    """
    # A stored model with no rules in it plus credentials is what makes the top-up due, which is
    # the shape the flaking test had.
    entry = _entry(
        digital_model=json.dumps(heat_capable_digital_model()),
        refresh_token="2_RT",
        cloud_client_id="c" * 32,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert refused_cloud_requests, "the top-up did not reach the transport at all"
    assert entry.state is ConfigEntryState.LOADED   # and a refused fetch changes nothing


async def test_recorded_rules_do_not_suppress_fetching_the_published_ones(
    hass: HomeAssistant, mock_uss
) -> None:
    """The recorded fallback must not stand in for the real thing.

    Rules for a known model are merged into the model in memory, so deciding whether to fetch on
    *that* would mean the one family we hold rules for never fetched its own — the fallback masking
    what it is a fallback for. The decision is made on what the entry stores.
    """
    from custom_components.haismart.const import CONF_UPLUS_ID

    uplus = "2008610800820324021200118012560000000000000000000000000000000040"
    entry = _entry(digital_model=json.dumps(heat_capable_digital_model()), **{
        CONF_UPLUS_ID: uplus, "refresh_token": "r", "cloud_client_id": "c" * 32,
    })
    entry.add_to_hass(hass)
    with patch("custom_components.haismart.coordinator.rules_for_product", return_value=None):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coord = entry.runtime_data
    assert coord.digital_model["modifiers"]          # the fallback filled the in-memory model
    # ...and the fetch still considers itself due, because the ENTRY holds no rules
    called = False

    async def _fake_config(*args, **kwargs):
        nonlocal called
        called = True
        return {"modifiers": [{"trigger": {}, "actions": []}], "constraints": [{"x": 1}]}

    with patch.object(HaierCloud, "refresh_token", new=AsyncMock(return_value=SimpleNamespace(
        access_token="t"))), patch.object(
        HaierCloud, "list_devices_v2", new=AsyncMock(return_value=[SimpleNamespace(
            device_id="A1B2C3D4E5F6", model="M", uplus_id=uplus, prod_no="P", device_type="T")])
    ), patch.object(HaierCloud, "get_device_config", new=_fake_config):
        assert await coord.async_fetch_model_rules() is True
    assert called
    stored = json.loads(entry.data["digital_model"])
    assert stored["constraints"] == [{"x": 1}]       # written back to the entry


_ECO_MODEL = {"attributes": [
    {"name": "operationMode", "writable": True, "valueRange": {
        "type": "LIST", "dataList": [{"data": c} for c in ("0", "1", "2", "6")]}},
    {"name": "generatorMode", "writable": True, "valueRange": {
        "type": "LIST", "dataList": [{"data": c} for c in ("0", "1", "2", "3")]}},
]}


async def test_economy_control_needs_the_device_to_declare_it(
    hass: HomeAssistant, mock_uss
) -> None:
    """Off the classic family the economy setting is reached through the published map, where the
    upper of its two bits belongs to a neighbouring attribute. So it is offered only where the
    device's own model declares the setting -- otherwise a unit without it would have something
    else written over instead."""
    mock_uss.read.return_value = [make_extended36_frame(length=175, eco=2)]

    entry = await _setup_with_model(hass, _ECO_MODEL)
    assert entry.runtime_data.supports_eco is True
    eco = hass.states.get("select.downstairs_ac_eco")
    assert eco is not None and eco.state == "level2"

    # the same unit whose model says nothing about it gets no control at all
    entry2 = await _setup_with_model(hass, _REAL_SHAPE_MODEL)
    assert entry2.runtime_data.supports_eco is False


async def test_model_rules_fall_back_to_the_public_catalogue(
    hass: HomeAssistant, mock_uss
) -> None:
    """An entry with no cloud credentials still gets its rules.

    The account's resource service can only answer for devices the signed-in account owns, so an
    install set up by hand would never receive the conditional rules or the invisible flags -- and
    so would never get conditional availability or the optional-feature entities that depend on
    knowing a unit's real feature set. A catalogue keyed on product code needs no account, and is
    what such an entry falls back to.
    """
    import json as _json
    from unittest.mock import AsyncMock, patch

    from custom_components.haismart.const import CONF_DIGITAL_MODEL

    shadow = {"attributes": [{"name": "operationMode"}]}
    published = {
        "attributes": [{"name": "operationMode"}, {"name": "freshAirStatus", "invisible": True}],
        "modifiers": [{"trigger": {}, "actions": []}],
        "alarms": [{"name": "F1"}],
    }
    entry = _entry(**{CONF_DIGITAL_MODEL: _json.dumps(shadow)})
    entry.add_to_hass(hass)
    # the shipped rules would satisfy the top-up during setup and leave this scenario with nothing
    # to do, so they are withheld while the entry starts: what is under test here is the fetch.
    with patch("custom_components.haismart.coordinator.rules_for_product", return_value=None):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    with patch(
        "custom_components.haismart.coordinator.get_public_device_config",
        new=AsyncMock(return_value=published),
    ) as fetch:
        assert await entry.runtime_data.async_fetch_model_rules() is True

    # asked the catalogue for THIS entry's product code, with no token of any kind
    assert fetch.await_args.args[0] == "AAC1UKZ01"
    merged = _json.loads(entry.data[CONF_DIGITAL_MODEL])
    assert merged["modifiers"] and merged["alarms"]
    # the invisible set is recorded, which is what the optional-feature entities gate on
    assert merged["invisible_attributes"] == ["freshAirStatus"]


async def test_model_rules_refuse_to_guess_a_product_code(
    hass: HomeAssistant, mock_uss
) -> None:
    """A product code the entry never learned must not be used to look rules up.

    `product_code` falls back to a built-in default, and a default reads exactly like a device
    genuinely carrying that code. Fetching on one would hand this device another model's rulebook --
    the wrong entities unavailable, the wrong faults named -- which is worse than having none.
    """
    import json as _json
    from unittest.mock import AsyncMock, patch

    from custom_components.haismart.const import CONF_DIGITAL_MODEL, CONF_PRODUCT_CODE

    entry = _entry(**{CONF_DIGITAL_MODEL: _json.dumps({"attributes": [{"name": "operationMode"}]})})
    entry.add_to_hass(hass)
    # an entry that never stored one at all
    hass.config_entries.async_update_entry(
        entry, data={k: v for k, v in entry.data.items() if k != CONF_PRODUCT_CODE}
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with patch(
        "custom_components.haismart.coordinator.get_public_device_config", new=AsyncMock()
    ) as fetch:
        assert await entry.runtime_data.async_fetch_model_rules() is False
    assert fetch.await_count == 0


async def test_diagnostics_say_which_device_a_report_came_from(
    hass: HomeAssistant, mock_uss
) -> None:
    """A report is only useful for adding a model if it identifies its device -- and says when the
    product code is a built-in default rather than one the device actually carries."""
    from custom_components.haismart.const import CONF_PRODUCT_CODE
    from custom_components.haismart.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = await _setup(hass)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    ident = diag["device_identity"]
    assert ident["product_code"] == "AAC1UKZ01"
    assert ident["product_code_is_fallback"] is False

    # an entry that never learned one reports the default, and says so
    entry2 = _entry(unique_id="B1B2C3D4E5F6")
    entry2.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry2, data={k: v for k, v in entry2.data.items() if k != CONF_PRODUCT_CODE}
    )
    await hass.config_entries.async_setup(entry2.entry_id)
    await hass.async_block_till_done()
    ident2 = (await async_get_config_entry_diagnostics(hass, entry2))["device_identity"]
    assert ident2["product_code_is_fallback"] is True


async def test_model_rules_stop_after_a_catalogue_top_up(
    hass: HomeAssistant, mock_uss
) -> None:
    """A model topped up from the open catalogue must not be re-fetched on every startup.

    The catalogue carries a device's feature set but not its conditional rules, so a check that
    required both would never be satisfied for such an entry and would go back to the network on
    every single restart, forever. The signal that a top-up happened is the recorded invisible set,
    which is present even when it is empty.
    """
    import json as _json
    from unittest.mock import AsyncMock, patch

    from custom_components.haismart.const import CONF_DIGITAL_MODEL

    topped_up = {
        "attributes": [{"name": "operationMode"}],
        "alarms": [{"name": "F1"}],
        "invisible_attributes": [],   # recorded, empty -- the "we know the feature set" signal
    }
    entry = _entry(**{CONF_DIGITAL_MODEL: _json.dumps(topped_up)})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with patch(
        "custom_components.haismart.coordinator.get_public_device_config", new=AsyncMock()
    ) as fetch:
        assert await entry.runtime_data.async_fetch_model_rules() is False
    assert fetch.await_count == 0, "re-fetched a model that was already topped up"


async def test_shipped_rules_answer_when_the_catalogue_is_unreachable(
    hass: HomeAssistant, mock_uss
) -> None:
    """With no internet at all, the rules still arrive -- they travel with the integration.

    This is the configuration the integration exists for: a unit firewalled off the cloud, on a
    network that may have no route out either. Everything else works offline once the key is stored,
    and until now the rule layer was the exception -- locks, fault names and co-commands all quietly
    absent because the only source was a fetch. The shipped bundle is consulted last, so a reachable
    catalogue still wins and stays authoritative.

    The top-up runs during setup, so the failure has to be in place before it, not after.
    """
    import json as _json
    from unittest.mock import AsyncMock, patch

    from custom_components.haismart.const import CONF_DIGITAL_MODEL

    entry = _entry(**{CONF_DIGITAL_MODEL: _json.dumps({"attributes": [{"name": "operationMode"}]})})
    entry.add_to_hass(hass)
    with patch(
        "custom_components.haismart.coordinator.get_public_device_config",
        new=AsyncMock(side_effect=OSError("no route to host")),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    merged = _json.loads(entry.data[CONF_DIGITAL_MODEL])
    # the real published figures for this model, not a placeholder
    assert len(merged["modifiers"]) == 6
    assert len(merged["constraints"]) == 10
    assert len(merged["alarms"]) == 52
    # and the flag only the published model carries, which the optional features gate on
    assert merged["invisible_attributes"]


async def test_shipped_rules_are_not_reached_when_the_catalogue_answers(
    hass: HomeAssistant, mock_uss
) -> None:
    """A reachable catalogue wins: the bundle is a snapshot and the service is current."""
    import json as _json
    from unittest.mock import AsyncMock, patch

    from custom_components.haismart.const import CONF_DIGITAL_MODEL

    entry = _entry(**{CONF_DIGITAL_MODEL: _json.dumps({"attributes": [{"name": "operationMode"}]})})
    entry.add_to_hass(hass)
    live = {"attributes": [{"name": "operationMode"}], "alarms": [{"name": "F1"}], "modifiers": []}
    with patch(
        "custom_components.haismart.coordinator.get_public_device_config",
        new=AsyncMock(return_value=live),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    merged = _json.loads(entry.data[CONF_DIGITAL_MODEL])
    assert [a["name"] for a in merged["alarms"]] == ["F1"]   # the live answer, not the 52 shipped


async def test_a_silent_unit_is_asked_the_other_published_way_first(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """Before giving up on telemetry, the query is re-sent under the other published frame type.

    Two generations of the same product line publish this command differently, and on the wire a
    unit of the second generation looks exactly like a unit that has none: it simply says nothing.
    Concluding "no telemetry" from silence to one form would take the power and compressor sensors
    away from a unit that would have answered the other.
    """
    from custom_components.haismart.coordinator import EXTENDED_STATUS_FRAME_TYPES

    mock_uss.read.return_value = [make_status_frame()]        # never answers the extended query
    entry = await _setup(hass)
    coordinator = entry.runtime_data

    def forms_asked():
        return [
            call.kwargs["extra_request"][9]
            for call in mock_uss.read.await_args_list
            if call.kwargs.get("extra_request")
        ]

    assert set(forms_asked()) == {EXTENDED_STATUS_FRAME_TYPES[0]}

    for _ in range(EXTENDED_MISSES):
        await _tick(hass, freezer)

    assert coordinator.supports_extended is None             # not written off yet
    assert EXTENDED_STATUS_FRAME_TYPES[1] in forms_asked()   # the other form was tried


async def test_the_two_published_copies_are_combined_not_chosen_between(
    hass: HomeAssistant, mock_uss
) -> None:
    """Neither publication of a model is a superset of the other, so take the union of them.

    A device's own account returns the group command and the command pseudo-attributes; the open
    catalogue returns `invalid_reasons` -- the sentences explaining why a control is unavailable --
    which the account copy leaves null. Preferring one wholesale loses whatever only the other has,
    and for a signed-in install that meant controls greying out correctly with nothing to say why.

    Filling gaps only: anything the fetched copy actually answers must stand, because it is current
    where the shipped one is a snapshot.
    """
    from custom_components.haismart.coordinator import _fill_gaps

    fetched = {
        "attributes": [{"name": "operationMode"}],
        "modifiers": [{"a": 1}],
        "invalid_reasons": None,          # the account copy leaves this out
        "groupCommands": [{"name": "grSetDAC"}],
    }
    bundled = {
        "attributes": [{"name": "stale"}],
        "modifiers": [{"b": 2}],          # older; must NOT win
        "invalid_reasons": {"50001": "not available while the unit reports a fault"},
        "alarms": [{"name": "E1"}],       # absent upstream entirely
    }

    merged = _fill_gaps(fetched, bundled)
    assert merged["attributes"] == fetched["attributes"], "current data must not be overridden"
    assert merged["modifiers"] == fetched["modifiers"], "current data must not be overridden"
    assert merged["groupCommands"] == fetched["groupCommands"]
    assert merged["invalid_reasons"] == bundled["invalid_reasons"], "the gap must be filled"
    assert merged["alarms"] == bundled["alarms"], "a section absent upstream must be filled"

    # and with nothing shipped for this product, the fetched copy passes through untouched
    assert _fill_gaps(fetched, None) == fetched


async def test_identity_missing_from_an_older_entry_is_learned_not_asked_for(
    hass: HomeAssistant, mock_uss
) -> None:
    """An entry can be told what its own account already knows, instead of being re-added.

    Entries added through an account before the product code and device type were kept do not store
    them. The credentials are still there, and the device list has always carried both, so the gap
    closes on the next start with nothing asked of anyone.
    """
    from unittest.mock import AsyncMock, patch

    from haismart_extractor.cloud import CloudDevice

    from custom_components.haismart.const import (
        CONF_CLOUD_CLIENT_ID,
        CONF_REFRESH_TOKEN,
    )

    entry = _entry(**{
        CONF_REFRESH_TOKEN: "2_RT",
        CONF_CLOUD_CLIENT_ID: "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
        CONF_PRODUCT_CODE: None,        # the older shape: neither was stored
    })
    entry.add_to_hass(hass)
    device = CloudDevice("A1B2C3D4E5F6", "Downstairs", "0201203a", "UPLUS", True,
                         prod_no="AAD180E00")
    with (
        patch("custom_components.haismart.coordinator.HaierCloud.refresh_token",
              new=AsyncMock(return_value=type("R", (), {"access_token": "2_F"})())),
        patch("custom_components.haismart.coordinator.HaierCloud.list_devices_v2",
              new=AsyncMock(return_value=[device])),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.data[CONF_PRODUCT_CODE] == "AAD180E00", "learned, not defaulted"
    assert entry.data[CONF_DEVICE_TYPE] == "0201203a"
    assert entry.data[CONF_UPLUS_ID] == "UPLUS"


async def test_identity_already_known_is_never_overwritten(
    hass: HomeAssistant, mock_uss
) -> None:
    """What is stored may have come from somewhere this lookup cannot see, so it wins."""
    from unittest.mock import AsyncMock, patch

    from haismart_extractor.cloud import CloudDevice

    from custom_components.haismart.const import (
        CONF_CLOUD_CLIENT_ID,
        CONF_REFRESH_TOKEN,
    )

    entry = _entry(**{
        CONF_REFRESH_TOKEN: "2_RT",
        CONF_CLOUD_CLIENT_ID: "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
        CONF_PRODUCT_CODE: "AAC1UKZ01",
        # the uPlusId this product code really publishes. A placeholder here made the entry
        # self-contradictory -- a stored code whose own uPlusId is not the one the appliance reports
        # is a *falsified* code, which is the one thing this lookup is now allowed to replace -- so
        # the fixture has to be a coherent appliance for the test to be about overwriting at all.
        CONF_UPLUS_ID: "2008610800820324021200118012560000000000000000000000000000000040",
        CONF_DEVICE_TYPE: "0201203a",
    })
    entry.add_to_hass(hass)
    listed = AsyncMock(return_value=[
        CloudDevice("A1B2C3D4E5F6", "x", "9999", "THEIRS", True, prod_no="WRONG")
    ])
    with (
        patch("custom_components.haismart.coordinator.HaierCloud.refresh_token",
              new=AsyncMock(return_value=type("R", (), {"access_token": "2_F"})())),
        patch("custom_components.haismart.coordinator.HaierCloud.list_devices_v2", new=listed),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.data[CONF_PRODUCT_CODE] == "AAC1UKZ01"      # not the list's "WRONG"
    assert entry.data[CONF_UPLUS_ID].startswith("20086108008203240212001180125")  # not "THEIRS"
    assert listed.await_count == 0, "nothing was missing, so nothing should have been fetched"


async def test_a_product_code_the_appliance_disowns_is_corrected_from_the_account(
    hass: HomeAssistant, mock_uss
) -> None:
    """A stored code whose own uPlusId is not this appliance's has been falsified, not bettered.

    Until v0.34 onboarding pre-filled this project's own product code, so appliances that never
    declared one were recorded as hardware they are not — and that record cannot be corrected by the
    source it came from, because there was none. It decides which controls lock and what a fault is
    called, so an owner otherwise has to delete the appliance and add it again to shift it.
    """
    from unittest.mock import AsyncMock, patch

    from haismart_extractor.cloud import CloudDevice

    from custom_components.haismart.const import CONF_CLOUD_CLIENT_ID, CONF_REFRESH_TOKEN

    theirs = "2008610800820324021200118017740000000000000000000000000000000040"
    entry = _entry(**{
        CONF_REFRESH_TOKEN: "2_RT",
        CONF_CLOUD_CLIENT_ID: "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
        CONF_PRODUCT_CODE: "AAC1UKZ01",   # this project's own, pre-filled by an old setup form
        CONF_UPLUS_ID: theirs,            # ...but the appliance reports a different family
        CONF_DEVICE_TYPE: "0201203a",
    })
    entry.add_to_hass(hass)
    listed = AsyncMock(return_value=[
        CloudDevice("A1B2C3D4E5F6", "x", "9999", theirs, True, prod_no="AAD47CZ00")
    ])
    with (
        patch("custom_components.haismart.coordinator.HaierCloud.refresh_token",
              new=AsyncMock(return_value=type("R", (), {"access_token": "2_F"})())),
        patch("custom_components.haismart.coordinator.HaierCloud.list_devices_v2", new=listed),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.data[CONF_PRODUCT_CODE] == "AAD47CZ00"
    assert entry.runtime_data.product_code == "AAD47CZ00"   # and in memory, not only on disk


async def test_a_disowned_code_is_left_alone_when_the_account_disagrees_too(
    hass: HomeAssistant, mock_uss
) -> None:
    """The list has to be answering about the same appliance for its answer to be a correction.

    What condemned the stored code was that it publishes a different uPlusId than the appliance
    reports. A reply that disagrees about the uPlusId as well is a second candidate, not a fix — so
    nothing is replaced and the warning stands.
    """
    from unittest.mock import AsyncMock, patch

    from haismart_extractor.cloud import CloudDevice

    from custom_components.haismart.const import CONF_CLOUD_CLIENT_ID, CONF_REFRESH_TOKEN

    entry = _entry(**{
        CONF_REFRESH_TOKEN: "2_RT",
        CONF_CLOUD_CLIENT_ID: "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
        CONF_PRODUCT_CODE: "AAC1UKZ01",
        CONF_UPLUS_ID: "2008610800820324021200118017740000000000000000000000000000000040",
        CONF_DEVICE_TYPE: "0201203a",
    })
    entry.add_to_hass(hass)
    listed = AsyncMock(return_value=[
        CloudDevice("A1B2C3D4E5F6", "x", "9999", "SOMETHING-ELSE", True, prod_no="AAD47CZ00")
    ])
    with (
        patch("custom_components.haismart.coordinator.HaierCloud.refresh_token",
              new=AsyncMock(return_value=type("R", (), {"access_token": "2_F"})())),
        patch("custom_components.haismart.coordinator.HaierCloud.list_devices_v2", new=listed),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.data[CONF_PRODUCT_CODE] == "AAC1UKZ01"


async def test_rules_from_a_disowned_product_code_are_not_applied(
    hass: HomeAssistant, mock_uss
) -> None:
    """A code the appliance contradicts must not supply this appliance's rulebook.

    The rules decide which controls lock, what a fault is called and which hardware a unit is
    credited with. Applying another product's was reported as fault names that did not match the
    unit (issue #6). What the whole family agrees on is correct without knowing the model, so that
    is what a disowned code falls back to.
    """
    from custom_components.haismart.const import CONF_DIGITAL_MODEL

    theirs = "2008610800820324021200118017740000000000000000000000000000000040"
    entry = _entry(**{
        CONF_PRODUCT_CODE: "AAC1UKZ01",
        CONF_UPLUS_ID: theirs,
        CONF_DIGITAL_MODEL: json.dumps({"attributes": [{"name": "operationMode"}]}),
    })
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coord = entry.runtime_data
    assert coord.model_rules_agreement == "identity-mismatch"
    # the alarm names now come from the family the appliance says it belongs to, and its list is a
    # different length from the one the stored code publishes
    from haismart_hrdp import family_rules, rules_for_product

    assert coord.digital_model["alarms"] == family_rules(theirs)["alarms"]
    assert len(coord.digital_model["alarms"]) != len(rules_for_product("AAC1UKZ01")["alarms"])


async def test_a_product_code_the_bundle_never_heard_of_still_gets_its_family_s_rules(
    hass: HomeAssistant, mock_uss
) -> None:
    """A code absent from the catalogue is not a wrong code, and it should not cost the rules.

    The published catalogue is a snapshot of one region and appliances arrive carrying codes that
    are not in it -- the 209-byte reporter's own is one, and so is its model number. That entry was
    getting no fault names and no explanation for a greyed-out control, while the rules its family
    agrees on were sitting in the bundle unused. Its uPlusId reaches them, and the appliance
    announces that without a key.
    """
    from haismart_hrdp import family_rules, rules_for_product

    from custom_components.haismart.const import CONF_DIGITAL_MODEL

    theirs = "2008610800820324021200118017740000000000000000000000000000000040"
    # A code no bundle can know: the catalogue is a snapshot, so a product published after it was
    # taken looks exactly like this. (An earlier version of this test used a real code from another
    # region -- which the bundle now covers, the fixture's premise having been the bug.)
    unknown = "ZZNOSUCH00"
    assert rules_for_product(unknown) is None

    entry = _entry(**{
        CONF_PRODUCT_CODE: unknown,
        CONF_UPLUS_ID: theirs,
        CONF_DIGITAL_MODEL: json.dumps({"attributes": [{"name": "operationMode"}]}),
    })
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    model = entry.runtime_data.digital_model
    assert model["alarms"] == family_rules(theirs)["alarms"]
    # and no verdict is claimed about a code there is nothing to compare against
    assert entry.runtime_data.model_rules_agreement is None


async def test_an_offline_entry_on_a_still_connected_appliance_is_warned_early(
    hass: HomeAssistant, mock_uss
) -> None:
    """Two facts together are a countdown, so say so before the clock runs out.

    An appliance that can still reach the manufacturer is issued a new key several times a day. An
    entry added without an account cannot fetch the new one, so the next restart after a change
    abandons setup — the entities vanish and it reads as the integration losing its configuration,
    not as a key problem. Re-adding by hand lasts until the next change.

    Both remedies are things to do while everything still works, which is the whole reason for
    raising this before the failure rather than after it.
    """
    from homeassistant.helpers import issue_registry as ir

    from custom_components.haismart.const import ISSUE_KEY_WILL_ROTATE

    entry = _entry()                       # no account credentials
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    issues = ir.async_get(hass)
    assert issues.async_get_issue(
        DOMAIN, f"{ISSUE_KEY_WILL_ROTATE}_A1B2C3D4E5F6"
    ), "an appliance still on the internet with no way to re-key must be flagged"


async def test_no_rotation_warning_once_either_remedy_is_in_place(
    hass: HomeAssistant, mock_uss
) -> None:
    """Blocking it freezes the key; an account lets us follow it. Either one ends this."""
    from haismart_hrdp.udiscovery import DeviceInfo
    from homeassistant.helpers import issue_registry as ir

    from custom_components.haismart.const import CONF_REFRESH_TOKEN, ISSUE_KEY_WILL_ROTATE

    # 1) blocked from the internet: the key can no longer change
    mock_uss.cloud.return_value = DeviceInfo(
        device_id="A1B2C3D4E5F6", host="192.168.1.50", cloud_state=1006
    )
    blocked = _entry()
    blocked.add_to_hass(hass)
    await hass.config_entries.async_setup(blocked.entry_id)
    await hass.async_block_till_done()
    assert not ir.async_get(hass).async_get_issue(
        DOMAIN, f"{ISSUE_KEY_WILL_ROTATE}_A1B2C3D4E5F6"
    ), "a blocked appliance's key is frozen, so there is nothing to warn about"

    # 2) still online, but an account is attached: rotations are fetched
    await hass.config_entries.async_unload(blocked.entry_id)
    mock_uss.cloud.return_value = DeviceInfo(
        device_id="B1B2C3D4E5F6", host="192.168.1.51", cloud_state=1000
    )
    signed_in = _entry(**{CONF_REFRESH_TOKEN: "2_RT"})
    signed_in.add_to_hass(hass)
    await hass.config_entries.async_setup(signed_in.entry_id)
    await hass.async_block_till_done()
    assert not ir.async_get(hass).async_get_issue(
        DOMAIN, f"{ISSUE_KEY_WILL_ROTATE}_B1B2C3D4E5F6"
    )


async def test_a_failed_key_refresh_does_not_tell_you_to_add_an_account_you_have(
    hass: HomeAssistant, mock_uss
) -> None:
    """Two reasons a key had to be re-entered by hand, and opposite advice for each.

    Either there is no account to fetch with, or there is one and fetching failed anyway. One
    message cannot serve both: telling someone to add an account they already added reads as the
    integration being broken, and that is how a recurring key problem becomes a habit of deleting
    and re-adding the appliance instead of reporting it.
    """
    from unittest.mock import AsyncMock, patch

    from homeassistant.helpers import issue_registry as ir

    from custom_components.haismart.const import (
        CONF_REFRESH_TOKEN,
        ISSUE_KEY_REFRESH_FAILED,
        ISSUE_STALE_LOCALKEY,
    )

    async def _rotated(entry_kwargs, device_id):
        entry = _entry(**entry_kwargs)
        entry.add_to_hass(hass)
        with patch(
            "custom_components.haismart.coordinator.HaismartCoordinator"
            "._async_gateway_refresh",
            new=AsyncMock(return_value=False),          # the fetch was tried and failed
        ):
            coordinator = HaismartCoordinator(hass, entry)
            coordinator._raise_stale_localkey_issue(45, 46)
        return ir.async_get(hass)

    from custom_components.haismart.coordinator import HaismartCoordinator

    # no account stored: the advice is to add one
    issues = await _rotated({}, "A1B2C3D4E5F6")
    assert issues.async_get_issue(DOMAIN, f"{ISSUE_STALE_LOCALKEY}_A1B2C3D4E5F6")
    assert not issues.async_get_issue(DOMAIN, f"{ISSUE_KEY_REFRESH_FAILED}_A1B2C3D4E5F6")

    # account already stored: the advice must NOT be to add one
    issues = await _rotated({CONF_REFRESH_TOKEN: "2_RT"}, "A1B2C3D4E5F6")
    assert issues.async_get_issue(DOMAIN, f"{ISSUE_KEY_REFRESH_FAILED}_A1B2C3D4E5F6")


async def test_a_slow_identity_lookup_does_not_hold_up_startup(
    hass: HomeAssistant, mock_uss
) -> None:
    """An improvement must never become a tax on every restart.

    The lookup is awaited because what it learns decides which rules are read moments later. But a
    lookup that cannot reach the network learns nothing, so the entry still needs it next time —
    without a bound, every single start would pay the full HTTP timeout for it, and the installs
    most likely to be offline are exactly the ones this integration is for.
    """
    import asyncio
    from unittest.mock import patch

    from custom_components.haismart.const import (
        CONF_CLOUD_CLIENT_ID,
        CONF_PRODUCT_CODE,
        CONF_REFRESH_TOKEN,
    )

    entry = _entry(**{
        CONF_REFRESH_TOKEN: "2_RT",
        CONF_CLOUD_CLIENT_ID: "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
        CONF_PRODUCT_CODE: None,
    })
    entry.add_to_hass(hass)

    async def _never_answers(*_a, **_k):
        await asyncio.sleep(3600)

    with patch(
        "custom_components.haismart.coordinator.HaismartCoordinator.async_topup_identity",
        new=_never_answers,
    ), patch("custom_components.haismart.IDENTITY_TOPUP_TIMEOUT", 0.05):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # setup completed anyway, and the appliance works without what the lookup would have added
    assert entry.state is ConfigEntryState.LOADED
    assert [s for s in hass.states.async_all() if s.entity_id.startswith("climate.")], (
        "the appliance must still be usable when the lookup times out"
    )


async def test_a_command_does_not_blank_the_fault_sensor(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    """Only a read cycle asks for the fault frame, so a command must not read as "unknown".

    A control session does not request it, and a command also pushes the next poll a full interval
    away — so every command blanked the problem sensor for a while. On a *problem* entity that reads
    as the check having stopped working, which is worse than briefly saying what it last saw.

    The reading is held for the same span as the telemetry, and for the same reason: past that it no
    longer speaks for the unit, and honest silence beats a stale answer.
    """
    from custom_components.haismart.const import TELEMETRY_MAX_AGE

    entry = await _setup(hass)
    coordinator = entry.runtime_data

    reading = {"alarm_codes": (), "fault": False}
    assert coordinator._held_alarms(reading) == reading      # a read cycle records it
    assert coordinator._held_alarms({}) == reading, (
        "a control session carries no alarm frame; the last reading must stand in"
    )

    freezer.tick(timedelta(seconds=TELEMETRY_MAX_AGE + 1))
    assert coordinator._held_alarms({}) == {}, "a stale fault reading must not persist"


async def test_a_command_leaves_every_sensor_reading_as_it_found_them(
    hass: HomeAssistant, mock_uss
) -> None:
    """Sending a command must not blank sensors that have nothing to do with it.

    The reply to a command is a status report and nothing else — no alarm frame — so publishing it
    unchanged dropped the fault sensor and the optional-feature sensors until the next poll, which
    the command itself had just pushed a full interval away. On a problem entity that reads as the
    check having stopped working.

    Regression guard for the whole class: whatever a poll publishes beyond the plain status, a
    command's echo has to publish too, either by re-reading it or by holding the last value.
    """
    entry = await _setup(hass)
    coordinator = entry.runtime_data

    polled = set(coordinator.data)
    await coordinator.async_send_control({"targetTemperature": 24 - 16})
    await hass.async_block_till_done()

    missing = polled - set(coordinator.data)
    assert not missing, f"a command dropped these readings: {sorted(missing)}"


async def test_diagnostics_says_whether_the_units_real_feature_set_is_known(
    hass: HomeAssistant, mock_uss
) -> None:
    """A generic model lists every attribute the product line might have and marks the ones this
    unit lacks `invisible`. That flag decides whether optional-feature entities can be offered at
    all, so a diagnostics file has to say whether it is known — and has to distinguish "known, and
    this unit lacks nothing" from "not known". Both would otherwise be an absent list.
    """
    from custom_components.haismart.diagnostics import _model_summary

    unknown = _model_summary({"attributes": [{"name": "onOffStatus"}]})
    assert unknown["feature_set_known"] is False
    assert unknown["invisible_attributes"] is None

    empty = _model_summary({"attributes": [{"name": "onOffStatus"}], "invisible_attributes": []})
    assert empty["feature_set_known"] is True
    assert empty["invisible_attributes"] == []

    known = _model_summary(
        {"attributes": [{"name": "onOffStatus"}], "invisible_attributes": ["freshAirStatus"]}
    )
    assert known["feature_set_known"] is True
    assert known["invisible_attributes"] == ["freshAirStatus"]


async def test_a_lock_rule_gains_the_reason_code_its_catalogue_twin_states() -> None:
    """Filling empty sections is not enough to explain a lock, and the reason is easy to miss.

    The sentences live in `invalid_reasons`, but the *code* choosing one lives on the rule itself.
    A signed-in install has rules, so that section is not empty, so nothing is filled — and the
    account copy states no code on any rule. The sentences arrive with nothing pointing at them,
    which is why controls greyed out correctly and could never say why.

    Rules are matched on their trigger, since that is what identifies a rule. Action lists are
    allowed to differ — they do — and nothing about them is copied, so this can never change what
    is locked.
    """
    from haismart_hrdp import lock_reasons

    from custom_components.haismart.coordinator import _fill_gaps

    fan_only = {"operator": "AND", "conditions": {"operationMode": ["6"]}}
    fetched = {
        "attributes": [{"name": "operationMode"}],
        # as a device's own account publishes them: no invalid_code anywhere
        "modifiers": [
            {"priority": 4, "trigger": fan_only,
             "actions": [{"name": "targetTemperature", "writable": False}]},
        ],
    }
    bundled = {
        "invalid_reasons": {"50009": "not available in fan-only mode"},
        "modifiers": [
            # the same rule, and it names more attributes than the account copy does
            {"priority": 4, "trigger": fan_only, "invalid_code": "50009",
             "actions": [{"name": "targetTemperature", "writable": False},
                         {"name": "generatorMode", "writable": False}]},
        ],
    }

    merged = _fill_gaps(fetched, bundled)
    rule = merged["modifiers"][0]
    assert rule["invalid_code"] == "50009"
    assert rule["actions"] == fetched["modifiers"][0]["actions"], (
        "only the code may be adopted — the actions decide what is locked"
    )

    # end to end: the lock can now say why, in the state that triggers it
    assert lock_reasons(merged, {"operationMode": "6"}) == {
        "targetTemperature": "not available in fan-only mode"
    }
    # and without the fix there is nothing to say
    assert lock_reasons(fetched, {"operationMode": "6"}) == {"targetTemperature": ""}


async def test_a_rule_that_states_its_own_reason_keeps_it() -> None:
    """Only a missing code is filled in; a rule that names one is left alone."""
    from custom_components.haismart.coordinator import _fill_gaps

    trigger = {"operator": "AND", "conditions": {"operationMode": ["6"]}}
    fetched = {"modifiers": [{"trigger": trigger, "invalid_code": "50001", "actions": []}]}
    bundled = {"modifiers": [{"trigger": trigger, "invalid_code": "50009", "actions": []}]}
    assert _fill_gaps(fetched, bundled)["modifiers"][0]["invalid_code"] == "50001"


async def test_an_unmatched_rule_is_left_without_a_reason_rather_than_given_a_wrong_one() -> None:
    """A trigger with no twin gets nothing. A wrong explanation is worse than none, and the lock
    itself does not depend on having one."""
    from custom_components.haismart.coordinator import _fill_gaps

    fetched = {"modifiers": [
        {"trigger": {"operator": "AND", "conditions": {"operationMode": ["2"]}}, "actions": []}
    ]}
    bundled = {"modifiers": [
        {"trigger": {"operator": "AND", "conditions": {"operationMode": ["6"]}},
         "invalid_code": "50009", "actions": []}
    ]}
    assert "invalid_code" not in _fill_gaps(fetched, bundled)["modifiers"][0]


async def test_diagnostics_carries_what_a_bug_report_needs_without_transcription(
    hass: HomeAssistant, mock_uss
) -> None:
    """Reporters were asked to write down the model number, the module and its firmware by hand.

    Two of the three the integration already knows, and the third it can look up. The model number
    is derivable from the stored product code via the shipped catalogue, and the module's firmware
    and SDK version arrive from the appliance's own discovery answer. They were reaching the device
    page and nothing else — and the device page is not in the file people attach to issues.
    """
    from custom_components.haismart.diagnostics import (
        _model_number,
        async_get_config_entry_diagnostics,
    )

    entry = await _setup(hass)
    coordinator = entry.runtime_data
    coordinator.firmware = "e_4.3.00 / R_6.0.01"
    coordinator.sdk_version = "2.18"

    diag = await async_get_config_entry_diagnostics(hass, entry)
    identity = diag["device_identity"]
    assert identity["module_firmware"] == "e_4.3.00 / R_6.0.01"
    assert identity["module_sdk_version"] == "2.18"
    # the readable number off the sticker, not the product code it was looked up from
    assert identity["product_code"] == "AAC1UKZ01"
    assert identity["model_number"] == "HSU-24VRRA03TF"

    # a product code the catalogue does not cover yields nothing rather than a guess
    assert _model_number("ZZZZZZZZZ") is None
    assert _model_number(None) is None


# --- a published model must be usable, not merely stored ----------------------------------------


def _catalogue_doc():
    """A published model exactly as the open catalogue spells it, trimmed to what matters here."""
    def attr(name, data_type, variants):
        return {"name": name, "dataType": data_type, "description": "d-" + name,
                "invisible": False, "readable": True, "writable": True, "writeType": "G",
                "standardType": "1", "variants": variants}
    return {"property": [
        attr("operationMode", "enum", {"enumList": [
            {"stdValue": "0", "description": "auto"}, {"stdValue": "1", "description": "cool"},
            {"stdValue": "2", "description": "dry"}, {"stdValue": "6", "description": "fan"}]}),
        attr("windSpeed", "enum", {"enumList": [
            {"stdValue": "1", "description": "high"}, {"stdValue": "2", "description": "mid"},
            {"stdValue": "3", "description": "low"}, {"stdValue": "5", "description": "auto"}]}),
        attr("targetTemperature", "double",
             {"doubleStep": {"minValue": 16, "maxValue": 30, "step": 1, "unit": "C"}}),
        attr("onOffStatus", "bool", {"boolList": [
            {"stdValue": "false", "description": "off"},
            {"stdValue": "true", "description": "on"}]}),
    ]}


def test_a_catalogue_model_builds_a_profile_and_bounds_a_write() -> None:
    """The offline install's whole point: its published model has to actually drive the entities.

    Before the catalogue's attribute spelling was adapted, this raised and the coordinator fell back
    to a hardcoded per-product profile -- fine for a product that has one, and a generic guess for
    any appliance that does not. The assertions are on the *contents*: the modes and speeds the
    model declared, and bounds that genuinely refuse a value outside them.
    """
    from haismart_extractor.cloud import normalize_public_config
    from haismart_hrdp.profiles import profile_from_device_config, validate_write

    cfg = normalize_public_config(_catalogue_doc())
    profile = profile_from_device_config(cfg)

    assert set(profile.mode_values.values()) >= {"cool", "dry", "fan_only"}
    assert set(profile.fan_values.values()) >= {"high", "medium", "low", "auto"}
    # keyed by the numeric STD codes the decoder actually emits, not by words
    assert profile.mode_values["1"] == "cool" and profile.fan_values["3"] == "low"
    # ...and the flag that separates a real profile from the generic STD fallback. This is the
    # crux: the fallback lists every code the protocol defines so decoding always works, and must
    # never be read as a capability list. An offline install used to get exactly that.
    assert profile.modes_authoritative

    assert validate_write(cfg, "targetTemperature", 24)[0]
    assert not validate_write(cfg, "targetTemperature", 44)[0]
    assert validate_write(cfg, "operationMode", 1)[0]
    assert not validate_write(cfg, "operationMode", 9)[0]
    assert validate_write(cfg, "onOffStatus", "true")[0]


def test_an_unbounded_attribute_is_refused_rather_than_waved_through() -> None:
    """An attribute whose range could not be read must cost a control, never gain a free one."""
    from haismart_extractor.cloud import normalize_public_config
    from haismart_hrdp.profiles import validate_write

    doc = _catalogue_doc()
    doc["property"].append({"name": "mystery", "dataType": "enum", "description": "?",
                            "invisible": False, "readable": True, "writable": True,
                            "variants": {"unknownKind": [{"stdValue": "1"}]}})
    cfg = normalize_public_config(doc)
    ok, why = validate_write(cfg, "mystery", "1")
    assert not ok and "unsupported valueRange" in why


def test_the_two_published_serialisations_agree_attribute_for_attribute() -> None:
    """The same model from the account and from the catalogue must reach consumers identically.

    This is the property the adapter exists to provide, so it is asserted directly rather than
    inferred from the pieces: adapt the catalogue spelling and compare against the account
    spelling of the same attributes, key for key.
    """
    from haismart_extractor.cloud import normalize_public_config

    account = {
        "name": "operationMode", "desc": "d-operationMode", "invisible": False,
        "readable": True, "writable": True, "operationType": "G", "standardType": "1",
        "dataType": "enum",
        "valueRange": {"type": "LIST", "dataList": [
            {"data": "0", "desc": "auto"}, {"data": "1", "desc": "cool"},
            {"data": "2", "desc": "dry"}, {"data": "6", "desc": "fan"}]},
    }
    adapted = normalize_public_config(_catalogue_doc())["attributes"][0]
    assert adapted == account


def test_the_published_model_states_which_features_a_unit_actually_has() -> None:
    """A generic model over-declares; the published one says what this unit is missing.

    The optional-feature entities refuse to appear unless that set is known, because guessing
    produces sensors for hardware that is not fitted -- so an offline install that stored the flags
    but never collected them got no such entities at all. On the reference product's published
    model 25 of 39 attributes are invisible, leaving the same 14 an account yields.
    """
    from haismart_hrdp import invisible_attributes

    model = {"attributes": [
        {"name": "onOffStatus", "invisible": False},
        {"name": "freshAirStatus", "invisible": True},
        {"name": "humidificationStatus", "invisible": True},
        {"name": "echoStatus", "invisible": False},
    ]}
    assert invisible_attributes(model) == frozenset({"freshAirStatus", "humidificationStatus"})
    # and the presence of the key is itself the signal, so an all-visible model records an EMPTY
    # list rather than nothing -- "we checked" and "we do not know" must stay distinguishable
    assert sorted(invisible_attributes({"attributes": [{"name": "a", "invisible": False}]})) == []
