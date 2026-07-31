"""Constants for the Haismart local integration."""
from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "haismart"

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.SELECT,
]

CONF_HOST = "host"
CONF_DEVICE_ID = "device_id"
CONF_LOCAL_KEY = "local_key"
CONF_NAME = "name"
# Cloud credential provisioned by the email/password Login onboarding path (the durable, reusable
# refreshToken + the account access token + per-install clientId + region). The coordinator uses
# these to auto-refresh a rotated localKey from the cloud gateway; the localKey itself stays local.
CONF_REFRESH_TOKEN = "refresh_token"
CONF_ACCESS_TOKEN = "access_token"
CONF_CLOUD_CLIENT_ID = "cloud_client_id"  # per-install uSDK CLIENTID (32-hex), the token's terminal
CONF_ZONE_INFO = "zone_info"
# Optional MQTT-gateway CONNECT credentials. No longer required: the coordinator derives every
# gateway credential (`_async_gateway_refresh` + `haismart_extractor.gateway.derive_gateway_auth`) —
# clientId from CONF_CLOUD_CLIENT_ID, token from CONF_REFRESH_TOKEN, and the username/password from
# the derivation formula. These stay only to optionally PIN a username body; leave them blank.
CONF_GATEWAY_USERNAME = "gateway_username"
CONF_GATEWAY_PASSWORD = "gateway_password"
# The device's digital model (JSON string), fetched from the cloud during discovery. When present
# the coordinator self-builds the AttributeProfile from it (correct for ANY model); else it falls
# back to the hardcoded profile_for(product_code).
CONF_DIGITAL_MODEL = "digital_model"
# Cloud product_code/pid (e.g. AAC1UKZ01) — selects the AttributeProfile for status decode.
CONF_PRODUCT_CODE = "product_code"
# The device's uPlusId (cloud device-list `wifiType`) — the app's own key for a device's wire model.
# product_code is NOT a safe wire-model key (different AC families share one, e.g. AAC1UKZ01 covers
# both the 127-byte classic and the 117-byte compact-12 layout), so the decoder prefers this when
# known. Stored by the cloud onboarding paths; absent for manual onboarding (report length is the
# fallback key there).
CONF_UPLUS_ID = "uplus_id"
# Human-readable identity from the cloud device list's `extendedInfo` (prodNo/model/brand). Shown on
# the HA device page instead of the raw product code.
CONF_MODEL_NAME = "model_name"
CONF_BRAND = "brand"
# The AC's localKey version at config time (HELLO_RESP payload). The key rotates server-side;
# a version mismatch on a later probe means the cached key is stale -> reauth.
CONF_LOCALKEY_VERSION = "localkey_version"

# UDISCOVERY (UDP :7083) — the key-free query that reports whether the AC can reach Haier's cloud.
# Polled on its own slow cadence inside the read cycle: the flag moves on a ~4-minute timescale (an
# MQTT keepalive has to expire before a cut shows up), so polling it every status read would be pure
# waste. Give up on a unit that stays silent while demonstrably reachable — older modules may not
# implement it, and there is no point querying those forever.
UDISCOVERY_INTERVAL = 60.0   # seconds between cloud-state queries
UDISCOVERY_TIMEOUT = 2.0     # per-query socket timeout (a healthy unit answers in <50 ms)
UDISCOVERY_MISSES = 3        # consecutive silent queries (while reachable) before we back off
# ...and how long we then leave it before trying again. Not "never": three lost datagrams in a
# row is a thing a busy access point does, and a module can gain the capability in a firmware
# update — while giving up for good costs the cloud-connection sensor, the firmware version and
# the cloud-free uPlusId learning for the rest of the run. Hourly is cheap enough to be free.
UDISCOVERY_RETIRE_INTERVAL = 3600.0
# Rediscovery after a failed read: these units move on DHCP, and a moved unit is indistinguishable
# from a dead one until you go looking for it. Cooled down so a genuinely offline AC (powered off,
# off the network) doesn't trigger a network sweep on every poll.
REDISCOVER_COOLDOWN = 300.0  # seconds between attempts
# The extended report (running power / compressor figures) only arrives in a READ cycle, so a cycle
# that does not carry one — every control op, plus the occasional dropped reply — would otherwise
# blank all of that telemetry. The last reading stands in for up to this long instead; these are
# slow-moving measurements, so a value from seconds ago beats a gap, while a unit that has genuinely
# stopped reporting still ends up honestly unknown rather than frozen on an old number.
TELEMETRY_MAX_AGE = 120.0    # seconds a previous extended reading may stand in for a missing one
# Consecutive cycles that carry status but no extended report before we conclude the unit does not
# answer that query and stop appending it. More than one, because a single reply can simply be
# dropped and the conclusion is expensive: it removes the power, current, frequency, coil,
# discharge, compressor and fan entities for the rest of the run. Same reasoning as
# UDISCOVERY_MISSES.
EXTENDED_MISSES = 3

CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 30  # seconds between read cycles (each is handshake+collect+close)
MIN_SCAN_INTERVAL = 10
DEFAULT_PRODUCT_CODE = "AAC1UKZ01"
READ_TIMEOUT = 4.0  # per-connection socket timeout used by the uSS read cycle
WRITE_TIMEOUT = 5.0  # per-connection socket timeout for a control (grSetDAC) op session

MANUFACTURER = "Haier"

# Haier's `deviceType` encodes the appliance class in its FIRST BYTE, as hex (from Haier's own uSDK
# device-type enum; e.g. 0201201d -> 0x02 = split AC, 21001001 -> 0x21 = air purifier). Used to warn
# when a picked device is not an air conditioner at all.
AC_DEVICE_CLASSES: dict[str, str] = {
    "02": "split AC",
    "03": "cabinet AC",
    "0d": "commercial AC",
    "39": "window AC",
}

# Repairs: raised when the localKey rotated but the entry has no cloud credentials to self-heal, so
# the user must reauth by hand. Advises adding account creds so rotation auto-refreshes in future.
ISSUE_STALE_LOCALKEY = "stale_localkey_manual_reauth"

# Repairs: the AC's status report is a length we have no confirmed layout for. Reads fall back
# to the layout-independent fields, so the thermostat still works, but temperatures are absent
# and control is refused rather than risking a sensor byte being written back as a control word.
ISSUE_UNKNOWN_LAYOUT = "unknown_report_layout"

# mDNS service the AC's wifi module announces (instance name = deviceId, e.g. A1B2C3D4E5F6).
ZEROCONF_TYPE = "_cae._udp.local."
