"""Constants for the Haismart local integration."""
from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "haismart"

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
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
# The device's own deviceType from the cloud device list (e.g. "0201203a"): two class digits, a
# separator, then the variant. It is NOT a layout key — siblings that share a class can carry
# different attribute sets — but it names the exact variant, which the uPlusId only half answers
# (a class can be derived from the uPlusId, the variant cannot). Kept for diagnostics, so a report
# from unfamiliar hardware identifies itself precisely instead of by a derived class.
CONF_DEVICE_TYPE = "device_type"
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
# The outdoor probe sits in the OUTDOOR unit, which is dormant while the AC is off -- so the indoor
# board keeps reporting the last value it took rather than a current one. Documented behaviour of
# this protocol ("remains unchanged, reflecting the last measured value"), and confirmed on
# hardware: on a unit left off, the indoor reading kept moving while the outdoor one stood still.
#
# That reading is published as a MEASUREMENT, so a unit switched off overnight writes a value that
# was true at dusk into eight hours of long-term statistics and skews the daily minimum -- the same
# reasoning that makes an absent probe read absent rather than a confident -64 C. Past this age it
# reads unknown instead, exactly as stale telemetry does.
#
# Generous, because a recently-parked reading is still broadly true and short off-periods are the
# common case; it is the overnight one that invents history. Not a decode check: the value is
# correctly decoded and knowably unrefreshed, which is why it is bounded by age rather than by a
# plausibility band: a band on a confirmed field cannot prevent a decode error, only hide one.
OUTDOOR_TEMP_MAX_AGE = 1800.0  # seconds an outdoor reading may stand while the unit is off
# Consecutive cycles that carry status but no extended report before we conclude the unit does not
# answer that query and stop appending it. More than one, because a single reply can simply be
# dropped and the conclusion is expensive: it removes the power, current, frequency, coil,
# discharge, compressor and fan entities for the rest of the run. Same reasoning as
# UDISCOVERY_MISSES.
EXTENDED_MISSES = 3
# The readings an appliance has told us it does not produce, remembered on the entry so its
# entities are not created again on the next restart.
#
# An entity that will read `unknown` for the life of the installation is worse than no entity: it
# takes a row on the dashboard, it appears in every entity picker, and someone building an
# automation cannot tell it apart from a sensor that is merely waiting for its first value. So once
# an appliance has DECLINED a reading -- not "has not sent one yet", but declined -- the entities
# for it are removed and not offered again.
#
# ⚠️ The bar is a refusal, never an absence. Entities are still created unconditionally at setup
# and still stand at `unknown` while the answer is unknown, because gating creation on the first
# poll is how a sensor that was briefly missing came to never appear at all. What is new is only
# the end of the story: when the appliance has answered the question, the ones it answered "no" to
# go away.
CONF_ABSENT_READINGS = "absent_readings"
# The state keys carried by the extended-status report, i.e. everything that goes when an appliance
# answers none of the published forms of that query. Named here rather than in either platform
# because both a sensor and a binary sensor read from this same frame, and a list that lived in one
# of them would be half the answer.
EXTENDED_READING_KEYS: tuple[str, ...] = (
    "power_w",
    "compressor_current_a",
    "compressor_frequency_hz",
    "coil_temperature",
    "discharge_temperature",
    "compressor_running",
    "fan_running",
)
# A failed read cycle takes every entity of a unit to `unavailable` at once, and on a site with
# rough Wi-Fi that reads as an integration erroring constantly rather than as a dropped packet
# (issue #6: an AC and an unrelated Tuya device going quiet in the same windows). One miss is not
# news -- these modules hold a single session, drop it after ~17 s regardless, and a lost reply is
# ordinary -- so the previous reading stands in for a few cycles, the way a missing telemetry frame
# already does, before the unit is declared unavailable.
#
# Bounded twice, because either bound alone fails on some poll interval: a count keeps a fast poll
# from holding a stale reading for many minutes, and a clock keeps a slow one from doing the same in
# two cycles. Whichever comes first ends the hold, and it ends immediately on a successful read.
STATUS_MISSES_HELD = 2       # consecutive failed cycles the last reading may stand in for
STATUS_HOLD_MAX_AGE = 180.0  # ...and the longest it may stand in for, in seconds

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

# How long startup will wait on the one-off identity lookup before giving up for this run. It is
# awaited rather than backgrounded because what it learns decides which rules are read moments
# later -- but a lookup that cannot reach the network learns nothing, so the entry still needs it
# next time and would pay the full HTTP timeout on every single start. Bounded well under the ten
# seconds at which Home Assistant starts warning about slow setup; the entry simply tries again on
# the next restart, and nothing else depends on it having succeeded.
IDENTITY_TOPUP_TIMEOUT = 6.0

# Repairs: the key rotated and the automatic re-fetch was TRIED and failed, on an entry that does
# have account credentials. Kept apart from the no-credentials case because the advice is opposite:
# telling someone to add an account they already have reads as the integration being broken, which
# is how a recurring key problem turns into repeated deleting and re-adding.
ISSUE_KEY_REFRESH_FAILED = "key_refresh_failed"

# Repairs: raised on an entry with no account credentials whose appliance is still talking to the
# manufacturer. Such an appliance re-keys several times a day, and an entry that cannot re-fetch
# will lose its connection at the next rotation -- which presents as the integration "losing its
# configuration" on restart, since setup is abandoned when the stored key no longer decrypts.
# Raised BEFORE that happens, because both remedies (attach an account, or block the appliance from
# the internet so its key stops changing) are things to do while everything still works.
ISSUE_KEY_WILL_ROTATE = "key_will_rotate"

# Repairs: the AC's status report is a length we have no confirmed layout for. Reads fall back
# to the layout-independent fields, so the thermostat still works, but temperatures are absent
# and control is refused rather than risking a sensor byte being written back as a control word.
ISSUE_UNKNOWN_LAYOUT = "unknown_report_layout"

# mDNS service the AC's wifi module announces (instance name = deviceId, e.g. A1B2C3D4E5F6).
ZEROCONF_TYPE = "_cae._udp.local."

# The appliance-maker's registered MAC prefixes, the same set the manifest's DHCP matchers
# use. Kept here as well so the offline path can find appliances on the network by itself:
# a device ID *is* one of these MACs, so a host whose MAC starts with one of them is worth
# asking whether it is an air conditioner. A test asserts the two lists stay identical.
HAIER_OUIS: tuple[str, ...] = (
    "0007A8",
    "00258D",
    "0439CB",
    "04C9DE",
    "04E229",
    "04FA83",
    "145790",
    "18A7F1",
    "24E8CE",
    "2C37C5",
    "3412DC",
    "3429EF",
    "3C1640",
    "4448FF",
    "540853",
    "5C241F",
    "60B02B",
    "68E478",
    "94224C",
    "A08222",
    "AC8226",
    "ACB722",
    "D8E23F",
    "DC330E",
    "E8EAFA",
)
