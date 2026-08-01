"""Test config for the HA integration.

These tests need Home Assistant + pytest-homeassistant-custom-component. When those are not
installed (e.g. the library-only CI job), skip the HA test files cleanly rather than erroring.

No sockets are opened: the uSS read cycle (`async_read_status`) and the key-free version probe
(`probe_localkey_version`) are mocked at the point of use, fed with synthetic 127-byte
full-status reports built by `make_status_frame` (same offsets `parse_full_status` decodes).
"""
from __future__ import annotations

try:
    import pytest_homeassistant_custom_component  # noqa: F401

    pytest_plugins = ["pytest_homeassistant_custom_component"]
    _HA_AVAILABLE = True
except ImportError:  # pragma: no cover
    _HA_AVAILABLE = False
    collect_ignore = ["test_config_flow.py", "test_init.py"]


def make_status_frame(
    *,
    power: bool = True,
    target_temp: int = 24,
    indoor_temp: float = 26.5,
    outdoor_temp: int = 33,
    mode_code: int = 1,  # STD operationMode (1 = cool on AAC1UKZ01)
    fan_code: int = 5,  # STD windSpeed (5 = auto)
    swing: bool = True,
    vane_h: int = 0,  # left-right vane POSITION code (0 = fixed .. 7 = auto), word 4 bits 0-2
) -> bytes:
    """Build a synthetic AAC1UKZ01 127-byte full-status report (offsets per uss.py)."""
    frame = bytearray(127)
    frame[2:4] = b"\x27\x15"
    frame[92] = target_temp - 16
    # 0x0c is the vane's auto/sweep code. 0x08 -- used here previously -- is the vane parked
    # pointing down, which is not swinging, so a fixture built with it could not represent the
    # state its own argument name claims.
    frame[93] = 0x0c if swing else 0x00
    frame[94] = (mode_code << 5) | fan_code
    frame[97] = 1 if power else 0
    frame[99] = vane_h                        # word 4 low byte; eco (bits 3-5) stays 0
    frame[104] = int(indoor_temp * 2)
    frame[106] = outdoor_temp + 64
    return bytes(frame)


def make_extended_frame(
    *,
    power_w: int = 910,
    current_a: float = 4.0,
    frequency_hz: int = 43,
    coil_temp: float = 12.0,
    discharge_temp: int = 58,
    compressor: bool = True,
    fan: bool = True,
) -> bytes:
    """Build a synthetic 141-byte extended-status report (offsets per uss.parse_extended_status).

    The command word inside the frame is what marks it as extended rather than status, so it has to
    be present: the parser identifies report kinds by command, not by length.
    """
    frame = bytearray(141)
    frame[2:4] = b"\x27\x15"
    at = 80
    frame[at:at + 2] = b"\xff\xff"
    frame[at + 2] = 0x3A                      # inner length
    frame[at + 9] = 0x06                      # report
    frame[at + 10:at + 12] = b"\x7d\x01"      # extended-status report command
    frame[126:128] = power_w.to_bytes(2, "big")
    frame[128] = int((coil_temp + 20.0) / 0.5)
    frame[129] = discharge_temp + 64
    frame[133] = frequency_hz
    frame[134:136] = int(round(current_a * 10)).to_bytes(2, "big")
    # actuator word: bits 0-1 compressor, bits 2-3 indoor fan
    actuators = (0x01 if compressor else 0) | (0x04 if fan else 0)
    frame[136:138] = actuators.to_bytes(2, "big")
    return bytes(frame)


def make_compact12_frame(
    *,
    power: bool = True,
    target_temp: int = 22,
    indoor_temp: int = 27,
    mode_epp: int = 1,   # EPP index (1 = cool on this family; see wire_models.COMPACT12)
    fan_epp: int = 3,    # EPP index (3 = auto)
    swing_v: bool = False,
    swing_h: bool = False,
) -> bytes:
    """Build a synthetic 117-byte 'compact-12' full-status report (a different wire family — all
    attributes live in the word array; positions per wire_models.COMPACT12). No valid EPP checksum
    is needed: parse_full_status only needs the 2715 magic + length, then reads the word bits."""
    frame = bytearray(117)
    frame[2:4] = b"\x27\x15"

    def setword(w: int, val: int) -> None:
        off = 92 + (w - 1) * 2
        frame[off], frame[off + 1] = (val >> 8) & 0xFF, val & 0xFF

    setword(1, int(indoor_temp))                                   # indoorTemperature
    setword(6, mode_epp)                                           # operationMode (EPP index)
    setword(7, fan_epp)                                            # windSpeed (EPP index)
    setword(8, (1 if swing_v else 0) | (2 if swing_h else 0))      # swing V=bit0, H=bit1
    setword(9, 1 if power else 0)                                  # onOffStatus
    setword(12, target_temp - 16)                                  # targetTemperature
    return bytes(frame)


def make_extended36_frame(
    *,
    power: bool = True,
    target_temp: int = 22,
    indoor_temp: float = 27.5,
    mode_code: int = 1,   # STD code == EPP value on this family (1 = cool)
    fan_code: int = 1,    # STD code == EPP value (1 = high)
    swing_v: bool = False,
    swing_h: bool = True,
    lamp: bool = True,
    length: int = 165,
    power_w: int = 0,
    energy_wh: int = 0,
) -> bytes:
    """Build a synthetic 165-byte 'extended-36' full-status report (issue #5). Same bit map as the
    classic family, but displaced 19 words: the report keeps a voice/media block at words 1..19 and
    the climate block from word 20 (positions per wire_models.EXTENDED36).

    ``length`` covers the 175-byte variant of the same family (issue #8), which carries five further
    words — the cumulative energy total and a live power reading — after the climate block and is
    otherwise identical.
    """
    frame = bytearray(length)
    frame[2:4] = b"\x27\x15"

    def setword(w: int, val: int) -> None:
        off = 92 + (w - 1) * 2
        frame[off], frame[off + 1] = (val >> 8) & 0xFF, val & 0xFF

    setword(1, 0x2064)                                             # the media block (volume etc.)
    setword(20, ((target_temp - 16) << 8) | (0x08 if swing_v else 0))
    setword(21, (mode_code << 13) | (fan_code << 8))
    setword(22, (1 if power else 0) | (0x200 if lamp else 0))
    setword(23, 0x07 if swing_h else 0x00)                         # windDirectionHorizontal
    setword(25, int(indoor_temp * 2) << 8)                         # indoorTemperature (k=0.5)
    if length >= 175:
        setword(41, power_w)                                       # live input power, watts
        # cumulative energy in watt-hours: 32 bits whose LOW half sits at word 35, the high half in
        # the word before it
        setword(34, (energy_wh >> 16) & 0xFFFF)
        setword(35, energy_wh & 0xFFFF)
    return bytes(frame)


def make_extended46_frame(
    *,
    power: bool = True,
    target_temp: int = 22,
    indoor_temp: float = 27.0,
    mode_code: int = 1,   # STD code == EPP value on this family (1 = cool)
    swing_v: bool = False,
) -> bytes:
    """Build a synthetic 209-byte 'extended-46' full-status report (issue #6).

    The extended-36 map with a ten-word block inserted at word 25, so everything from there up moves
    ten words later — and the setpoint counts half degrees from zero rather than whole degrees
    offset by 16 (positions per wire_models.EXTENDED46).
    """
    frame = bytearray(209)
    frame[2:4] = b"\x27\x15"

    def setword(w: int, val: int) -> None:
        off = 92 + (w - 1) * 2
        frame[off], frame[off + 1] = (val >> 8) & 0xFF, val & 0xFF

    setword(1, 0x2064)                                    # the media block (volume etc.)
    setword(20, int(target_temp * 2) << 8)                # targetTemperature is degC x 2 here
    setword(21, mode_code << 13)
    setword(22, 1 if power else 0)
    setword(25, 0x08 if swing_v else 0)                   # the vane, inside the inserted block
    setword(35, int(indoor_temp * 2) << 8)                # indoorTemperature (k=0.5)
    return bytes(frame)


def heat_capable_digital_model() -> dict:
    """A digital model like a heat-pump AC's: the reference unit's attributes plus operationMode 4
    (heat), which our own cooling-only hardware doesn't declare. The model is what authorizes heat,
    so this is the fixture for "does a unit that HAS heat get to use it".
    """
    return {
        "attributes": [
            {
                "name": "operationMode", "writable": True,
                "valueRange": {"type": "LIST", "dataList": [
                    {"data": "0", "desc": "智能/自动/舒适"},
                    {"data": "1", "desc": "制冷"},
                    {"data": "2", "desc": "除湿"},
                    {"data": "4", "desc": "制热"},
                    {"data": "6", "desc": "送风"},
                ]},
            },
            {
                "name": "windSpeed", "writable": True,
                "valueRange": {"type": "LIST", "dataList": [
                    {"data": "1", "desc": "高"}, {"data": "2", "desc": "中"},
                    {"data": "3", "desc": "低"}, {"data": "5", "desc": "自动"},
                ]},
            },
            {
                "name": "targetTemperature", "writable": True,
                "valueRange": {"type": "STEP", "dataStep": {
                    "minValue": "16", "maxValue": "30", "step": "1"}},
            },
            {
                "name": "onOffStatus", "writable": True,
                "valueRange": {"type": "LIST", "dataList": [
                    {"data": "false", "desc": "关"}, {"data": "true", "desc": "开"},
                ]},
            },
        ]
    }


def locking_digital_model() -> dict:
    """The model above plus the conditional rules a real one carries: which settings a unit ignores
    in which state. Transcribed from a real device model, including the rule that fires on a fault
    (shortened to two alarm names) and the one that fires while the unit is off."""
    model = heat_capable_digital_model()
    model["alarms"] = [
        {"name": "alarmCancel"},          # not a position -- position N is entry N+1
        {"name": "outdoorModuleErr"},
        {"name": "outdoorDeforstSensorErr"},
    ]
    model["modifiers"] = [
        {
            "priority": 5,
            "trigger": {"operator": "AND", "conditions": {"silentSleepStatus": ["true"]}},
            "actions": [{"name": "rapidMode", "writable": False}],
        },
        {
            "priority": 4,
            "trigger": {"operator": "AND", "conditions": {"operationMode": ["6"]}},
            "actions": [
                {"name": name, "writable": False}
                for name in ("targetTemperature", "silentSleepStatus", "muteStatus",
                             "rapidMode", "generatorMode")
            ],
        },
        {
            "priority": 3,
            "trigger": {"operator": "AND", "conditions": {"operationMode": ["2"]}},
            "actions": [{"name": "muteStatus", "writable": False},
                        {"name": "rapidMode", "writable": False}],
        },
        {
            "priority": 1,
            "trigger": {"operator": "OR", "conditions": {},
                        "alarms": ["outdoorModuleErr", "outdoorDeforstSensorErr"]},
            "actions": [
                {"name": name, "writable": False}
                for name in ("targetTemperature", "windDirectionVertical", "operationMode",
                             "windSpeed", "screenDisplayStatus", "silentSleepStatus",
                             "muteStatus", "rapidMode", "healthMode", "generatorMode")
            ],
        },
        {
            "priority": 0,
            "trigger": {"operator": "OR",
                        "conditions": {"onOffStatus": ["false"], "selfCleaningStatus": ["true"]}},
            "actions": [
                {"name": name, "writable": False}
                for name in ("targetTemperature", "windDirectionVertical", "operationMode",
                             "windSpeed", "healthMode")
            ],
        },
    ]
    return model


def vane_positions_digital_model(
    codes: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6, 7),
    vertical: tuple[int, ...] = (),
) -> dict:
    """The model above, plus the stops each vane publishes.

    ``codes`` is the left-right axis, whose model code IS its wire value. ``vertical`` is the
    up-down axis, whose codes are NOT wire values (a model's 8 reaches the wire as 0x0c) — the
    values a real unit lists there are 0, 2, 4, 5, 6, 8.
    """
    model = heat_capable_digital_model()
    model["attributes"].append({
        "name": "windDirectionHorizontal", "writable": True,
        "valueRange": {"type": "LIST", "dataList": [
            {"data": str(code), "desc": f"左右摆位置{code + 1}"} for code in codes
        ]},
    })
    if vertical:
        model["attributes"].append({
            "name": "windDirectionVertical", "writable": True,
            "valueRange": {"type": "LIST", "dataList": [
                {"data": str(code), "desc": "上下摆"} for code in vertical
            ]},
        })
    return model


if _HA_AVAILABLE:
    from unittest.mock import DEFAULT, AsyncMock, patch

    import pytest
    from haismart_hrdp.udiscovery import CLOUD_STATE_CONNECTED, DeviceInfo

    LOCALKEY_VERSION = 4

    @pytest.fixture(autouse=True)
    def _enable_custom_integrations(enable_custom_integrations):  # noqa: ANN001, ANN201
        yield

    @pytest.fixture
    def mock_uss():
        """Patch the uSS entrypoints in both modules that import them.

        Yields a namespace whose `read` (AsyncMock) and `probe` (MagicMock) drive what the
        AC "sends"; `send` (AsyncMock) captures control (grSetDAC) ops so control tests assert the
        exact frame without opening a socket. Tests mutate return_value/side_effect as needed.
        """
        frame = make_status_frame()
        read = AsyncMock(return_value=[frame])

        # ``async_send_op`` is called with a ``build_frame`` callback (single-session
        # read-modify-write): the real function feeds it the AC's post-handshake push; here we
        # simulate that push with ``send.baseline`` (defaults to the current status frame; tests may
        # override it) so the seeding logic runs, and stash the built grSetDAC frame on
        # ``send.last_frame`` for assertions. Returning DEFAULT makes the mock use
        # ``send.return_value`` as the op reply (tests still set that).
        def _send_side_effect(*args, **kwargs):
            build = kwargs.get("build_frame")
            if build is not None:
                send.last_frame = build(send.baseline)
            elif len(args) >= 4 and args[3] is not None:
                send.last_frame = args[3]
            return DEFAULT

        send = AsyncMock(side_effect=_send_side_effect, return_value=[])
        send.baseline = frame
        send.last_frame = None

        # The key-free UDISCOVERY query the coordinator uses for cloud reachability. Mocked here
        # too: it is a real UDP round trip, so without this every coordinator cycle would try to
        # open a socket. Default is a device reporting a healthy cloud link; tests override
        # `cloud.return_value` (None = the unit did not answer).
        # Host rediscovery (an ARP sweep, falling back to a UDP broadcast). Mocked to "not found"
        # so the failure path stays fast and touches no network; tests that exercise a DHCP move
        # set `rediscover.return_value` to the new address.
        rediscover = AsyncMock(return_value=None)
        cloud = AsyncMock(
            return_value=DeviceInfo(
                device_id="A1B2C3D4E5F6",
                host="192.168.1.50",
                port=56800,
                cloud_state=CLOUD_STATE_CONNECTED,
            )
        )
        with (
            patch(
                "custom_components.haismart.coordinator.async_read_status", read
            ),
            patch(
                "custom_components.haismart.config_flow.async_read_status", read
            ),
            patch(
                "custom_components.haismart.coordinator.async_send_op", send
            ),
            patch(
                "custom_components.haismart.coordinator.probe_localkey_version",
                return_value=LOCALKEY_VERSION,
            ) as probe,
            patch(
                "custom_components.haismart.config_flow.probe_localkey_version",
                probe,
            ),
            patch(
                "custom_components.haismart.coordinator.udiscovery.async_query", cloud
            ),
            patch(
                "custom_components.haismart.coordinator.async_find_host", rediscover
            ),
        ):
            yield type(
                "MockUss",
                (),
                {
                    "read": read,
                    "send": send,
                    "probe": probe,
                    "frame": frame,
                    "cloud": cloud,
                    "rediscover": rediscover,
                },
            )
