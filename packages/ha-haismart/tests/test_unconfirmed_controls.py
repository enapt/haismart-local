"""Controls on appliances no command has been confirmed on: off until the owner turns them on, and
never on a burner, an oven or a sterilising cabinet.

Haier's byte map publishes a write id for most of an appliance's settings, and building a switch or
a number for every one of them is exactly what a model-driven layer does well -- for a refrigerator,
a hood or a purifier, no harm in it beyond a setting that may be refused. For a gas hob it means a
burner's ignition, for an oven a bake temperature up to 300 °C. Not one command to any of these
classes has been observed being accepted. So:

* every class that is not an air conditioner, a water heater or laundry is read-only by default;
* its owner can turn controls on, where the class is one Haier names and not a heat source -- and
  even then nothing that lights, heats or cooks is offered;
* a heat source (``HEAT_SOURCE_CLASSES``) never gets a control, whatever the option says;
* the ``0501`` front loader is laundry, behind the same gates as the ``0504`` laundry centre: read
  from prior art's real capture of one, below.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from ha_compat import MockConfigEntry
from haismart_hrdp.appliance import HEAT_SOURCE_CLASSES, ApplianceKind, heats_or_ignites, kind_for
from haismart_hrdp.device_model import ATTR_BASE, known_typeids, model_for
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.haismart.const import (
    CONF_APPLIANCE_CONTROLS,
    CONF_DEVICE_ID,
    CONF_DIGITAL_MODEL,
    CONF_HOST,
    CONF_LAUNDRY_CONTROLS,
    CONF_LOCAL_KEY,
    CONF_LOCALKEY_VERSION,
    CONF_PRODUCT_CODE,
    CONF_UPLUS_ID,
    DOMAIN,
)

_CONTROLS = frozenset({"switch", "select", "number", "button"})

# One typeid per class of each kind, picked by sort order so the choice is stable and not curated.
_BY_CLASS = {model_for(t).device_class: t for t in sorted(known_typeids(), reverse=True)}
OTHER = sorted(
    (c, t) for c, t in _BY_CLASS.items() if kind_for(t) is ApplianceKind.OTHER
)
HEAT_SOURCES = sorted((c, t) for c, t in OTHER if c in HEAT_SOURCE_CLASSES)


def _report(typeid: str) -> bytes:
    """A status report as long as this class's map describes (see test_every_appliance_sets_up)."""
    model = model_for(typeid)
    assert model is not None
    words = max(model.extent(), 20)
    body = bytes((i * 7 + 3) & 0xFF for i in range(2 * words + 2))
    head = bytearray(ATTR_BASE)
    head[2:4] = b"\x27\x15"                   # the uSS status-container marker
    # The EPP frame it carries, as a real report has it: FF FF at 80, the type (06, a report) at 89
    # and the command (6D01) at 90. A laundry appliance reads a report only when its command says
    # which one it is.
    head[80:82] = b"\xff\xff"
    head[89:92] = b"\x06\x6d\x01"
    return bytes(head) + body


def _value_range(field) -> dict | None:
    """The ``valueRange`` a device model publishes, rebuilt from the class map's own values."""
    if field.is_enum:
        return {"type": "LIST", "dataList": [
            {"data": str(v["stdValue"]).lower()} for v in field.variants
            if v.get("stdValue") is not None
        ]}
    bounds = field.bounds()
    if bounds is not None:
        step = field.variants.get("step") or 1
        return {"type": "STEP", "dataStep": {
            "minValue": str(bounds[0]), "maxValue": str(bounds[1]), "step": str(step)
        }}
    return None


def _entry(typeid: str, **options) -> MockConfigEntry:
    model = model_for(typeid)
    assert model is not None
    # Every attribute declared once (a map files some under both 6D01 and 7D01), writable and
    # individually so wherever the map says writable: the upper bound, which no real device
    # reaches. ``invisible_attributes`` present (empty) says the feature set is KNOWN -- without it
    # nothing is declared and nothing decodes.
    attributes: dict[str, dict] = {}
    for f in model.fields:
        attr = attributes.setdefault(f.name, {"name": f.name, "writable": False})
        if f.writable:
            attr.update(writable=True, operationType="I", valueRange=_value_range(f))
    # A write-only command has no report position, so the map does not carry it; the device's own
    # model declares it (the 0501's cancel, as the 0504's real model declares its two).
    if model.device_class == "0501":
        attributes["returnStandby"] = {
            "name": "returnStandby", "writable": True, "operationType": "I", "readable": False,
            "valueRange": {"type": "LIST", "dataList": [{"data": "1"}]},
        }
    digital_model = {"attributes": list(attributes.values()), "invisible_attributes": []}
    return MockConfigEntry(
        domain=DOMAIN,
        title="Appliance",
        unique_id="A1B2C3D4E5F6",
        data={
            CONF_HOST: "192.168.1.50",
            CONF_DEVICE_ID: "A1B2C3D4E5F6",
            CONF_LOCAL_KEY: "00112233445566778899aabbccddeeff",
            CONF_PRODUCT_CODE: "TESTCODE0",
            CONF_LOCALKEY_VERSION: 4,
            CONF_UPLUS_ID: typeid,
            CONF_DIGITAL_MODEL: json.dumps(digital_model),
        },
        options=options,
    )


async def _setup(hass: HomeAssistant, mock_uss, typeid: str, report: bytes | None = None,
                 **options) -> MockConfigEntry:
    report = report if report is not None else _report(typeid)
    mock_uss.read.return_value = [report]
    mock_uss.send.baseline = report
    entry = _entry(typeid, **options)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _rows(hass: HomeAssistant, entry: MockConfigEntry) -> list[er.RegistryEntry]:
    return [e for e in er.async_get(hass).entities.values() if e.config_entry_id == entry.entry_id]


def _controls(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, str]:
    """``attribute -> domain`` for every control entity of the entry."""
    return {
        e.unique_id.removeprefix("A1B2C3D4E5F6_"): e.domain
        for e in _rows(hass, entry)
        if e.domain in _CONTROLS
    }


def test_the_heat_sources_are_the_classes_the_catalogue_names_as_one() -> None:
    """A gas hob, the two ovens and the two sterilising cabinets, each in the shipped bundle."""
    from haismart_hrdp.appliance import CLASS_LABELS

    assert {c: CLASS_LABELS[c] for c, _ in HEAT_SOURCES} == {
        "0b11": "Sterilising cabinet", "0b12": "Sterilising cabinet",
        "1a01": "Steam oven", "1d01": "Gas hob", "3e01": "Steam oven",
    }


def test_every_ignition_and_bake_setting_reads_as_one_that_heats() -> None:
    """The name rule must catch the settings the review named, or it is not a second line."""
    for typeid, names in (
        (_BY_CLASS["1d01"], ("leftIgnitionStatus", "middleIgnitionStatus", "rightIgnitionStatus",
                             "leftFlameStatus")),
        (_BY_CLASS["3e01"], ("bakeTargetTemperature", "dnBakeTargetTemperature")),
        (_BY_CLASS["1a01"], ("bakeTargetTemperature", "fastPreHeatStatus")),
    ):
        model = model_for(typeid)
        assert model is not None
        for name in names:
            assert model.field(name) is not None and model.field(name).writable, name
            assert heats_or_ignites(name), name


@pytest.mark.parametrize(("device_class", "typeid"), OTHER, ids=[c for c, _ in OTHER])
async def test_no_unconfirmed_class_gets_a_control_by_default(
    hass: HomeAssistant, mock_uss, device_class: str, typeid: str
) -> None:
    entry = await _setup(hass, mock_uss, typeid)
    assert _rows(hass, entry), f"{device_class} has no entities at all"
    assert not _controls(hass, entry), device_class


@pytest.mark.parametrize(("device_class", "typeid"), HEAT_SOURCES, ids=[c for c, _ in HEAT_SOURCES])
async def test_a_heat_source_never_gets_a_control_even_when_its_owner_asks(
    hass: HomeAssistant, mock_uss, device_class: str, typeid: str
) -> None:
    entry = await _setup(hass, mock_uss, typeid, **{CONF_APPLIANCE_CONTROLS: True})
    coordinator = entry.runtime_data
    assert not coordinator.appliance_controls_available
    assert not coordinator.model_write_fields()
    assert not _controls(hass, entry), device_class


async def test_a_heat_source_refuses_a_command_whatever_sends_it(
    hass: HomeAssistant, mock_uss
) -> None:
    """No entity is built, and the coordinator refuses on its own -- a group set read off a hob's
    report could carry anything."""
    entry = await _setup(hass, mock_uss, _BY_CLASS["1d01"], **{CONF_APPLIANCE_CONTROLS: True})
    mock_uss.send.reset_mock()
    for change in ({"leftIgnitionStatus": True}, {"targetTemperature": 5}, {"onOffStatus": True}):
        with pytest.raises(HomeAssistantError, match="not a control of this appliance"):
            await entry.runtime_data.async_send_control(change)
    mock_uss.send.assert_not_called()


async def test_a_named_class_gets_its_controls_once_turned_on_but_nothing_that_heats(
    hass: HomeAssistant, mock_uss
) -> None:
    """A cooker hood: its light and fan become controls; its heated self-clean stays a reading."""
    typeid = _BY_CLASS["0901"]
    entry = await _setup(hass, mock_uss, typeid, **{CONF_APPLIANCE_CONTROLS: True})
    controls = _controls(hass, entry)
    assert controls.get("lightingStatus") == "switch"
    assert controls.get("windSpeedLevel") in {"select", "number"}
    heating = {"meltWashStatus", "cookRemindStatus"}
    assert not heating & set(controls), heating & set(controls)
    readings = {e.unique_id.removeprefix("A1B2C3D4E5F6_") for e in _rows(hass, entry)}
    assert heating <= readings, "withheld as a control, still read"


async def test_turning_controls_off_again_removes_them(hass: HomeAssistant, mock_uss) -> None:
    typeid = _BY_CLASS["0121"]
    entry = await _setup(hass, mock_uss, typeid, **{CONF_APPLIANCE_CONTROLS: True})
    assert _controls(hass, entry)
    hass.config_entries.async_update_entry(entry, options={CONF_APPLIANCE_CONTROLS: False})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert not _controls(hass, entry)


@pytest.mark.parametrize(
    ("device_class", "appliance", "laundry"),
    [
        ("0121", True, False),      # refrigerator: a named class, not a heat source
        ("0901", True, False),      # cooker hood
        ("1d01", False, False),     # gas hob: never
        ("3e01", False, False),     # steam oven: never
        ("0b11", False, False),     # sterilising cabinet: never
        ("0501", False, True),      # front loader: laundry, its own option and gates
        ("0504", False, True),      # laundry centre
    ],
)
async def test_the_options_offer_controls_only_where_they_can_exist(
    hass: HomeAssistant, mock_uss, device_class: str, appliance: bool, laundry: bool
) -> None:
    entry = await _setup(hass, mock_uss, _BY_CLASS[device_class])
    result = await hass.config_entries.options.async_init(entry.entry_id)
    fields = {str(key) for key in result["data_schema"].schema}
    assert (CONF_APPLIANCE_CONTROLS in fields) is appliance
    assert (CONF_LAUNDRY_CONTROLS in fields) is laundry


async def test_the_options_offer_controls_on_an_entry_that_is_not_loaded(
    hass: HomeAssistant, mock_uss
) -> None:
    """A unit that is offline at the moment still shows its toggle: it follows from the class."""
    for device_class, key in (("0504", CONF_LAUNDRY_CONTROLS), ("0121", CONF_APPLIANCE_CONTROLS)):
        entry = _entry(_BY_CLASS[device_class])
        entry.add_to_hass(hass)
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert key in {str(k) for k in result["data_schema"].schema}, device_class
        await hass.config_entries.async_remove(entry.entry_id)


async def test_an_option_the_form_did_not_show_is_kept(hass: HomeAssistant, mock_uss) -> None:
    """The form replaces the options wholesale; a value it did not show is carried, not lost."""
    entry = await _setup(hass, mock_uss, _BY_CLASS["1d01"], **{CONF_APPLIANCE_CONTROLS: True})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(result["flow_id"], {"scan_interval": 60})
    await hass.async_block_till_done()
    assert entry.options[CONF_APPLIANCE_CONTROLS] is True
    assert not entry.runtime_data.appliance_controls_enabled     # and it still does nothing


# --- the 0501 front loader, through the laundry gates --------------------------------------------

# Prior art's HW90-B14959U1, tapped on its board <-> module wire (esphome-haier issue #37); its
# typeid is read from the capture's own 71 reply. The same frames `haismart_hrdp`'s
# `test_washer.py` decodes. A UART frame is the EPP frame a LAN status message carries, so it is
# wrapped here in a real LAN header -- the 0504's -- and its word array lands at byte 92.
WASHER = "201c51890c31c30805010021800239584d000000000000000000000000000140"
_UART_IDLE = bytes.fromhex(
    "ffff7a400000000000066d01440a0100000801021e00000a000a00000000018b00000000018100028500286e00000000"
    "008c00000000000000018201000000000000000000000000000000000000000065636f34305f36300000000000000000"
    "00000000304d4c4674374871304e544533413d3d0000000000000000cd"
)
_LAN_HEAD = bytes.fromhex(
    json.loads((Path(__file__).parent / "fixtures" / "laundry_0504.json").read_text("utf-8"))
    ["frames"]["6d01_dryer_running"]
)[:80]


def _washer(*, remote: bool, phase: int | None = None, running: bool = False) -> bytes:
    """The idle report with the panel's remote flag, the phase and the running mode set as asked,
    at the positions the class's own map publishes."""
    model = model_for(WASHER)
    assert model is not None
    blob = bytearray(_LAN_HEAD + _UART_IDLE)
    assert blob[89] == 0x06 and blob[90:92] == b"\x6d\x01"

    def put(name: str, value: int) -> None:
        field = model.field(name)
        assert field is not None and field.status_cmd == "6D01" and field.bit + field.length <= 16
        at = ATTR_BASE + 2 * (field.word - 1)
        word = int.from_bytes(blob[at:at + 2], "big")
        mask = ((1 << field.length) - 1) << field.bit
        word = (word & ~mask) | ((value << field.bit) & mask)
        blob[at:at + 2] = word.to_bytes(2, "big")

    put("remoteCtrValid", int(remote))
    put("runningMode", 1 if running else 0)
    if phase is not None:
        put("cyclePhase", phase)
    return bytes(blob)


def test_the_capture_reads_as_an_idle_washer_with_remote_control_off() -> None:
    """What the gates will read off the unwrapped capture, before anything is set."""
    model = model_for(WASHER)
    assert model is not None
    state = model.decode(_LAN_HEAD + _UART_IDLE, status_cmd="6D01")
    assert state["remoteCtrValid"] is False
    assert state["cyclePhase"] == 0
    assert state["spinSpeed"] == 1400                       # the decode test_washer.py pins


async def test_a_0501_washer_is_read_only_by_default(hass: HomeAssistant, mock_uss) -> None:
    entry = await _setup(hass, mock_uss, WASHER, _washer(remote=True))
    assert entry.runtime_data.appliance_kind is ApplianceKind.LAUNDRY
    assert not _controls(hass, entry)
    readings = {e.unique_id.removeprefix("A1B2C3D4E5F6_") for e in _rows(hass, entry)}
    assert {"spinSpeed", "washTemp", "cyclePhase"} <= readings
    assert not {e.domain for e in _rows(hass, entry)} & {"climate"}


async def test_a_0501_washer_with_controls_on_has_start_pause_and_cancel(
    hass: HomeAssistant, mock_uss
) -> None:
    entry = await _setup(hass, mock_uss, WASHER, _washer(remote=True),
                         **{CONF_LAUNDRY_CONTROLS: True})
    controls = _controls(hass, entry)
    for action in ("start", "pause", "cancel"):
        assert controls.get(f"washer_{action}") == "button", action
    # ⛔ Never a control: the programme (set by Haier only inside a group command with its
    # parameters), start/pause as a dropdown, the child lock, the factory reset.
    assert not {"laundryCycle", "runningMode", "childLockStatus", "resetOpt"} & set(controls)


async def test_nothing_is_sent_to_a_0501_while_its_panel_has_remote_control_off(
    hass: HomeAssistant, mock_uss
) -> None:
    entry = await _setup(hass, mock_uss, WASHER, _washer(remote=False),
                         **{CONF_LAUNDRY_CONTROLS: True})
    mock_uss.send.reset_mock()
    with pytest.raises(HomeAssistantError, match="remote control is not enabled for the washer"):
        await entry.runtime_data.async_send_control({"runningMode": 1})
    mock_uss.send.assert_not_called()


@pytest.mark.parametrize(
    ("change", "frame_cmd", "payload"),
    [
        ({"runningMode": 1}, "5d21", "0001"),        # start
        ({"runningMode": 2}, "5d21", "0000"),        # pause
        ({"returnStandby": 1}, "5d24", "0001"),      # cancel: back to standby
    ],
)
async def test_a_0501_command_is_its_class_s_own_single_command(
    hass: HomeAssistant, mock_uss, change: dict, frame_cmd: str, payload: str
) -> None:
    entry = await _setup(hass, mock_uss, WASHER, _washer(remote=True),
                         **{CONF_LAUNDRY_CONTROLS: True})
    await entry.runtime_data.async_send_control(change)
    frame = mock_uss.send.last_frame
    assert frame is not None and frame[:2] == b"\xff\xff"
    assert frame[9] == 0x01, "a single-parameter write, never a group set"
    assert frame[10:12].hex() == frame_cmd and frame[12:14].hex() == payload


async def test_a_0501_is_not_switched_off_mid_cycle(hass: HomeAssistant, mock_uss) -> None:
    """Phase 5 is 洗涤, washing: power-off waits for standby or the end, as on the 0504."""
    entry = await _setup(hass, mock_uss, WASHER, _washer(remote=True, phase=5, running=True),
                         **{CONF_LAUNDRY_CONTROLS: True})
    mock_uss.send.reset_mock()
    with pytest.raises(HomeAssistantError, match="cycle in progress"):
        await entry.runtime_data.async_send_control({"onOffStatus": False})
    mock_uss.send.assert_not_called()
