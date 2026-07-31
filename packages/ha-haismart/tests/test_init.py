"""Entry setup, coordinator read cycle, entity state, and localKey-rotation reauth."""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import pytest
from conftest import (
    heat_capable_digital_model,
    make_compact12_frame,
    make_extended36_frame,
    make_extended_frame,
    make_status_frame,
)
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.haismart.const import (
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_LOCALKEY_VERSION,
    CONF_PRODUCT_CODE,
    CONF_SCAN_INTERVAL,
    CONF_UPLUS_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EXTENDED_MISSES,
    REDISCOVER_COOLDOWN,
    TELEMETRY_MAX_AGE,
    UDISCOVERY_INTERVAL,
    UDISCOVERY_MISSES,
    UDISCOVERY_RETIRE_INTERVAL,
)

CLIMATE = "climate.downstairs_ac"


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
    """A unit that ignores the extended query keeps working, and we stop appending the frame.

    It takes EXTENDED_MISSES cycles rather than one, because a single dropped reply must not be
    mistaken for a unit that has no extended report at all.

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

    for _ in range(EXTENDED_MISSES - 1):
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
    group-set (setpoint packed at word 12, per the APK group-command spec)."""
    frame = make_compact12_frame(power=True, target_temp=22, indoor_temp=27, mode_epp=1, fan_epp=3)
    mock_uss.read.return_value = [frame]
    mock_uss.send.baseline = frame   # the AC's in-session push that seeds the group-set
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    climate = hass.states.get(CLIMATE)
    assert climate is not None and climate.state == "cool"
    assert climate.attributes["current_temperature"] == 27.0
    assert climate.attributes["temperature"] == 22.0

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
    assert _sent_field(mock_uss.send, "windSpeed") == 2       # medium substituted, NOT auto(5)


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
    assert _sent_field(mock_uss.send, "windDirectionVertical") == 0x08


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


async def test_setup_retries_when_unreachable(hass: HomeAssistant, mock_uss) -> None:
    mock_uss.read.side_effect = OSError("connection refused")
    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_transient_outage_marks_unavailable_then_recovers(
    hass: HomeAssistant, mock_uss, freezer
) -> None:
    await _setup(hass)
    assert hass.states.get(CLIMATE).state == "cool"

    mock_uss.read.side_effect = OSError("host down")
    await _tick(hass, freezer)
    assert hass.states.get(CLIMATE).state == "unavailable"

    mock_uss.read.side_effect = None
    await _tick(hass, freezer)
    assert hass.states.get(CLIMATE).state == "cool"


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
            "operation_mode", "wind_speed", "swing_vertical",
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
