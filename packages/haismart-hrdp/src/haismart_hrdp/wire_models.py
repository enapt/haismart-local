"""Per-family EPP wire models — the positional attribute map for status reports whose layout is
*not* the classic split-AC family that :func:`haismart_hrdp.uss.parse_full_status` decodes inline.

Background
----------
Every Haier AC packs its status attributes into a bit-field array of 16-bit big-endian words that
begins at byte 92 of the decrypted report (right after the ``6d 01`` getAllProperty response code).
*Where* each attribute sits in that array is the **wire model**. Haier ships one wire model per
device as a preset under the app's ``assets/com.haier.uhome.usdk/<uPlusId>`` (174 of them), and the
app resolves a device to its model by uPlusId. There is **no** cloud endpoint that serves the wire
model to us and the device *digital* model (valueRange/enums, which we do fetch) carries no
positional data — so these maps are transcribed from the APK presets and validated against real
captured reports.

What a "family" is
------------------
A family is a **distinct field map**, and one map can span several report lengths (the classic
split-AC family appears at report lengths 109/121/125 in the presets and on our own hardware at
127 — only its trailing word count differs). So report length alone is a *good but imperfect* key:
among AC split units each length maps to a single field map, but the presets do contain a genuine
collision at 149 B (a floor/heat-pump class we don't target). Selection therefore prefers an exact
uPlusId match and otherwise keys on report length **with a decode sanity-check** (see
:meth:`WireModel.decode`), degrading to the caller's unknown-layout path rather than mis-decoding.

The classic family stays in ``uss.py``
--------------------------------------
The classic 125/127-byte family keeps its existing hardware-verified decode + the grSetDAC **write**
path in ``uss.py`` untouched. This module adds decoding for other families, plus — for a family whose
group-set command is fully specified by the APK preset (``group_cmd`` + :attr:`WireModel.write_fields`)
— a **control encoder** built on that spec. That spec basis is the same one heat mode shipped on
(model-derived, method hardware-confirmed on other units); a family without a ``group_cmd`` stays
monitoring-only.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

# Attribute-array geometry, shared with uss.py (kept local to avoid an import cycle).
_ATTR_BASE = 92          # first attribute byte; word N (1-based) starts at _ATTR_BASE + 2*(N-1)
_PLAUSIBLE_INDOOR_C = (0.0, 60.0)   # a decoded indoorTemperature outside this ⇒ wrong family
_PLAUSIBLE_TARGET_C = (10.0, 40.0)  # setpoints live in ~16..30; a wide band still catches a mis-decode
_PLAUSIBLE_SENSOR_C = (-30.0, 70.0)  # band for a ``"temp"`` field (see :class:`WireField`)
_SENSOR_ABSENT = (0x00, 0xFF)        # raw values a unit reports for a probe it does not have


@dataclass(frozen=True)
class WireField:
    """One attribute's position in the word array plus how to turn its raw bits into a value.

    ``word`` is 1-based (word 1 = bytes 92..93). ``bit`` is the LSB within the 16-bit big-endian
    word (bit 0 = least-significant). ``kind`` selects the decode:

    * ``"bool"``  -> ``bool(raw)``
    * ``"int"``   -> ``raw * k + c`` (a temperature/number)
    * ``"temp"``  -> ``raw * k + c``, but ``None`` for a raw value that means "no such probe"
      (``0x00``/``0xFF``) or that lands outside :data:`_PLAUSIBLE_SENSOR_C`. Use this for a *sensor*
      reading rather than ``"int"``: a unit without an outdoor probe reports 0, which the raw formula
      would turn into a confident −64 °C, and one fabricated MEASUREMENT permanently skews the
      min/max/mean of a user's long-term statistics. This mirrors ``uss._sensor_temp`` on the classic
      family.
    * ``"enum"``  -> ``enum[raw]`` — maps the raw EPP value to a **Haier STD code string** (so the
      per-model :class:`~haismart_hrdp.models.AttributeProfile` can name it), or drops the field when
      the raw value isn't in the map.
    """

    word: int
    bit: int
    length: int
    kind: str = "int"
    k: float = 1.0
    c: float = 0.0
    enum: Mapping[int, str] | None = None

    def read(self, data: bytes):
        off = _ATTR_BASE + (self.word - 1) * 2
        if off + 1 >= len(data):
            return None
        raw = ((data[off] << 8) | data[off + 1]) >> self.bit & ((1 << self.length) - 1)
        if self.kind == "bool":
            return bool(raw)
        if self.kind == "vane_v":
            return vane_v_sweeping(raw)
        if self.kind == "vane_h":
            return vane_h_sweeping(raw)
        if self.kind == "enum":
            return None if self.enum is None else self.enum.get(raw)
        if self.kind == "temp":
            if raw in _SENSOR_ABSENT:
                return None
            value = raw * self.k + self.c
            lo, hi = _PLAUSIBLE_SENSOR_C
            return value if lo <= value <= hi else None
        return raw * self.k + self.c


# --- vane semantics, defined once -------------------------------------------
# The vane fields are POSITION CODES, not bitmasks, on every family that inherits the classic map.
# The device model spells them out: vertical 0 = fixed, 2/4/5/6/7 = positions one..five, 8 = auto,
# mapping to wire 0/2/4/6/8/10 and 12; horizontal 0 = fixed, 3..6 = positions, 7 = auto.
#
# Only the auto codes sweep. Testing bit 3 alone also matches wire 8 and 10 -- the vane parked LOW --
# so a stationary vane gets reported to HA as sweeping. Both auto codes (0x0C, and 0x0E used by the
# special modes) have bits 2 and 3 set, so mask for both.
#
# The 117-byte compact family is the exception and is NOT covered here: its own model collapses the
# vane to a genuine 1-bit flag (STD 8/7 auto -> EPP 1, STD 0 fixed -> EPP 0), so it keeps `kind="bool"`.
VANE_V_AUTO_MASK = 0x0C
VANE_H_AUTO = 0x07


def vane_v_sweeping(raw: int) -> bool:
    """True only for the vertical vane's auto codes (0x0C, 0x0E)."""
    return (raw & VANE_V_AUTO_MASK) == VANE_V_AUTO_MASK


def vane_h_sweeping(raw: int) -> bool:
    """True only for the horizontal vane's auto code (7)."""
    return raw == VANE_H_AUTO


@dataclass(frozen=True)
class WriteField:
    """How a control change for one attribute is packed into the group-set word array.

    The coordinator hands control values in the *classic* representation (the same one the climate
    entity builds): a Haier STD code for enums, ``°C − 16`` for the setpoint, ``0/1`` for booleans,
    and a device-specific raw value for swing. ``kind`` says how to turn that into this family's raw
    wire (EPP) value before packing at ``word``/``bit``:

    * ``"passthrough"`` — already the wire value (setpoint, on/off).
    * ``"std_enum"``   — a STD code; map via ``std_to_epp`` (refuse anything not in it).
    * ``"onoff"``      — any nonzero classic "on" value packs ``on_value``; ``0`` packs ``0`` (swing,
      whose classic raw value — 0x0c / 7 — is not this family's code).
    * ``"celsius"``    — a setpoint the family encodes as **°C × ``scale``** rather than as the
      classic ``°C − 16``. The classic value is converted back to °C first, so the caller keeps
      handing setpoints in one representation whatever the family does on the wire.

    ``min_epp``/``max_epp`` bound a field whose valid range is narrower than its bit width — the
    setpoint being the case that matters, where 8 bits would otherwise accept a wire value meaning
    115 °C. The enum kinds are already bounded by their own maps.
    """

    word: int
    bit: int
    length: int
    kind: str = "passthrough"
    std_to_epp: Mapping[int, int] | None = None
    on_value: int = 1
    min_epp: int | None = None
    max_epp: int | None = None
    scale: float = 1.0      # "celsius": wire value per °C


@dataclass(frozen=True)
class WireModel:
    """A decoder (and, when ``group_cmd`` is set, a control encoder) for one AC family, selected by
    uPlusId or report length.

    ``fields`` maps a ``parse_full_status`` output key to its :class:`WireField`. ``mode``/``fan_mode``
    tokens are derived from ``operation_mode``/``wind_speed`` via the profile, exactly as the classic
    path does, so the coordinator/entities see the same shape.

    ``writable`` families additionally define ``group_cmd`` (the group-set EPP command), ``word_count``
    (how many words the settable array holds), ``write_base_word`` (the *report* word at which that
    array starts) and ``write_fields`` (the packing map). Control is a read-modify-write group-set:
    seed the word array from a live report, flip the requested fields, wrap in an ``FF FF`` frame with
    ``group_cmd``.

    ``write_fields`` positions are **group-set-relative** (word 1 = the first word of the op's data),
    while ``fields`` positions are **report-relative** (word 1 = byte 92). On most families these
    coincide, but a family can carry an unrelated block ahead of its climate attributes in the report
    while the op still starts at its own word 1 — ``write_base_word`` is exactly that displacement.
    """

    family: str
    report_lengths: frozenset[int]
    fields: Mapping[str, WireField]
    uplus_ids: frozenset[str] = frozenset()
    writable: bool = False          # False = monitoring-only (no confirmed control path)
    indoor_key: str = "current_temperature"
    target_key: str = "target_temperature"
    group_cmd: bytes | None = None  # group-set EPP command (e.g. b"\x4d\x5f")
    word_count: int = 0             # settable words 1..word_count
    write_base_word: int = 1        # report word holding group-set word 1 (1 = the report's own word 1)
    write_fields: Mapping[str, WriteField] = field(default_factory=dict)

    def matches(self, length: int, uplus_id: str | None) -> bool:
        if uplus_id and uplus_id in self.uplus_ids:
            return True
        return length in self.report_lengths

    def baseline_words(self, report: bytes) -> bytearray:
        """The settable word array (words 1..word_count) sliced from a full-status report — the seed
        for a group-set so untouched attributes are preserved."""
        start = _ATTR_BASE + 2 * (self.write_base_word - 1)
        end = start + 2 * self.word_count
        if len(report) < end:
            raise ValueError(f"report too short ({len(report)}) for {self.family} baseline")
        return bytearray(report[start:end])

    def current_write_value(self, report: bytes, name: str) -> int | None:
        """The live value of a *writable* field, read back out of ``report`` in the same
        representation :meth:`encode_control` accepts — so a caller can show the current state of an
        attribute the read map doesn't publish (the secondary toggles). ``None`` when the field isn't
        writable on this family or the report is too short to carry it."""
        wf = self.write_fields.get(name)
        if wf is None:
            return None
        try:
            words = self.baseline_words(report)
        except ValueError:
            return None
        off = (wf.word - 1) * 2
        if off + 1 >= len(words):
            return None
        raw = ((words[off] << 8) | words[off + 1]) >> wf.bit & ((1 << wf.length) - 1)
        if wf.kind == "std_enum":
            inverse = {epp: std for std, epp in (wf.std_to_epp or {}).items()}
            return inverse.get(raw)
        if wf.kind == "onoff":
            return wf.on_value if raw else 0
        if wf.kind == "celsius":
            return round(raw / wf.scale) - 16
        return raw

    def encode_control(self, baseline: bytes, changes: Mapping[str, int]) -> bytes:
        """Pack ``changes`` ({classic field name: classic value}) into a copy of ``baseline`` (the
        settable word array). Refuses any field/value not in :attr:`write_fields` — the encoder
        safety guard: control can only ever emit a mapped attribute with a supported value."""
        if not self.group_cmd or not self.write_fields:
            raise ValueError(f"{self.family} has no confirmed control path")
        words = bytearray(baseline)
        for name, value in changes.items():
            wf = self.write_fields.get(name)
            if wf is None:
                raise KeyError(f"{name!r} is not a writable field on {self.family}")
            epp = self._to_epp(wf, name, int(value))
            off = (wf.word - 1) * 2
            if off + 1 >= len(words):
                raise ValueError(f"{name}: word {wf.word} outside the {self.family} word array")
            word = (words[off] << 8) | words[off + 1]
            mask = ((1 << wf.length) - 1) << wf.bit
            word = (word & ~mask) | ((epp << wf.bit) & mask)
            words[off], words[off + 1] = (word >> 8) & 0xFF, word & 0xFF
        return bytes(words)

    def _to_epp(self, wf: WriteField, name: str, value: int) -> int:
        if wf.kind == "std_enum":
            epp = (wf.std_to_epp or {}).get(value)
            if epp is None:
                raise ValueError(
                    f"{name}={value} is not a supported code on {self.family} "
                    f"(allowed {sorted(wf.std_to_epp or {})})"
                )
        elif wf.kind == "onoff":
            epp = wf.on_value if value else 0
        elif wf.kind == "celsius":
            epp = round((value + 16) * wf.scale)
        else:  # passthrough
            epp = value
        if not 0 <= epp < (1 << wf.length):
            raise ValueError(f"{name}={epp} does not fit its {wf.length}-bit field on {self.family}")
        lo, hi = wf.min_epp, wf.max_epp
        if (lo is not None and epp < lo) or (hi is not None and epp > hi):
            raise ValueError(
                f"{name}={epp} is outside the {lo}..{hi} this field accepts on {self.family}"
            )
        return epp

    def decode(self, data: bytes, profile=None) -> dict | None:
        """Decode ``data`` to the ``parse_full_status`` dict, or ``None`` if the result fails the
        plausibility sanity-check (the guard that makes length-keying safe against a collision:
        a wrong family reads an implausible indoor temperature / setpoint)."""
        out: dict = {}
        for key, wf in self.fields.items():
            val = wf.read(data)
            if val is not None:
                out[key] = val

        indoor = out.get(self.indoor_key)
        if indoor is not None and not _PLAUSIBLE_INDOOR_C[0] <= indoor <= _PLAUSIBLE_INDOOR_C[1]:
            return None
        target = out.get(self.target_key)
        if target is not None and not _PLAUSIBLE_TARGET_C[0] <= target <= _PLAUSIBLE_TARGET_C[1]:
            return None

        if profile is not None:
            if "operation_mode" in out:
                out["mode"] = profile.normalized_mode(out["operation_mode"])
            if "wind_speed" in out:
                out["fan_mode"] = profile.normalized_fan(out["wind_speed"])
        # Markers the coordinator reads: a known non-classic family (NOT "unknown", so no repair is
        # raised) that is display-only until its write path is capture-confirmed.
        out["layout"] = self.family
        out["writable"] = self.writable
        return out


# --- registry ---------------------------------------------------------------------------------

# operationMode / windSpeed enums map the raw EPP index -> the Haier STD code string the digital
# model uses, so the AttributeProfile names them (STD 4 = heat, 2 = dry, 6 = fan, etc.). Provenance:
# the APK preset's own stdCode:eppValue table (`[模式]^20200D…302004:02…`), i.e. epp 2 == STD "4".
_COMPACT12_MODE = {0: "0", 1: "1", 2: "4", 3: "6", 4: "2"}   # auto / cool / heat / fan_only / dry
_COMPACT12_FAN = {0: "1", 1: "2", 2: "3", 3: "5"}            # high / medium / low / auto

# Control (group-set): the APK preset's `[组命令]` line fully specifies the group command — eppCmd
# `4d5f`, a 12-word array (words 1..12, the same span as the report), and each settable field's
# stdCode->eppValue map. This is the SAME spec basis as heat mode (issue #1): derived from the model,
# not captured on this exact family, but the group-set method is hardware-confirmed on other units.
# Control is read-modify-write from a live report, and the encoder refuses any field/value not below.
#   operationMode STD->EPP: 0->0 (auto) 1->1 (cool) 4->2 (heat) 6->3 (fan) 2->4 (dry)
#   windSpeed     STD->EPP: 1->0 (high) 2->1 (med) 3->2 (low) 5->3 (auto)
#   swings: STD 8/7 (auto) -> EPP 1, STD 0 (fixed) -> EPP 0 ("onoff": the classic 0x0c/7 "on" -> 1)
#   targetTemperature: EPP = °C - 16 (same as classic); onOffStatus: 0/1 (same as classic)
_COMPACT12_WRITE = {
    "operationMode": WriteField(6, 0, 16, "std_enum", std_to_epp={0: 0, 1: 1, 4: 2, 6: 3, 2: 4}),
    "windSpeed": WriteField(7, 0, 16, "std_enum", std_to_epp={1: 0, 2: 1, 3: 2, 5: 3}),
    "windDirectionVertical": WriteField(8, 0, 1, "onoff", on_value=1),
    "windDirectionHorizontal": WriteField(8, 1, 1, "onoff", on_value=1),
    # 16..30 C (the preset's own minValue/maxValue), i.e. EPP 0..14 — same range as the classic
    # family, and far narrower than the 16 bits the field occupies.
    "targetTemperature": WriteField(12, 0, 16, "passthrough", min_epp=0, max_epp=14),
    "onOffStatus": WriteField(9, 0, 1, "passthrough"),
}

# The "compact-12" family: a 12-word report (117 B) where every attribute — sensors included — lives
# in the word array (unlike the classic family's separate sensor block). Transcribed from APK presets
# `00000000000000008080000000041410` / `01c12002400081034080000000100000` and validated field-for-
# field against three real captured reports (haismart-local issue #4, HSU-12HFMF): power/setpoint/
# indoor/mode/fan/both swings all matched the reporter's stated state.
#
# Deliberately omitted from the READ: outdoorTemperature (word 2) — the device's own digital model
# does not declare it and the raw value reads like a condenser probe (~59 C), so publishing it would
# poison long-term statistics; and the secondary toggles — every capture had them OFF, giving no
# positive confirmation of their bit positions, so they stay off the read until a capture exercises
# them. Both can be added once evidence exists. Control covers the core climate fields (power / mode /
# fan / setpoint / both swings) via the APK-specified group command.
COMPACT12 = WireModel(
    family="compact12",
    report_lengths=frozenset({117}),
    writable=True,
    group_cmd=b"\x4d\x5f",
    word_count=12,
    write_fields=_COMPACT12_WRITE,
    fields={
        "power": WireField(9, 0, 1, kind="bool"),
        "target_temperature": WireField(12, 0, 16, kind="int", k=1.0, c=16.0),
        "current_temperature": WireField(1, 0, 16, kind="int", k=1.0, c=0.0),
        "operation_mode": WireField(6, 0, 16, kind="enum", enum=_COMPACT12_MODE),
        "wind_speed": WireField(7, 0, 16, kind="enum", enum=_COMPACT12_FAN),
        "swing_vertical": WireField(8, 0, 1, kind="bool"),
        "swing_horizontal": WireField(8, 1, 1, kind="bool"),
    },
)

# --- extended-36 (165-byte report) --------------------------------------------------------------

# operationMode / windSpeed are plain STD enums here: the preset maps stdValue -> eppValue 1:1 for
# both, so the raw wire value IS the STD code the digital model and the profile already speak.
_EXT36_MODE = {0: "0", 1: "1", 2: "2", 4: "4", 6: "6"}   # auto / cool / dry / heat / fan_only
_EXT36_FAN = {1: "1", 2: "2", 3: "3", 5: "5"}            # high / medium / low / auto

# Control: the preset's own `grSetDAC` Operation gives the group command (`6001`) and a five-word
# array whose bit map is **byte-for-byte the classic family's** — targetTemperature w1.b8,
# windDirectionVertical w1.b0, operationMode w2.b13, windSpeed w2.b8, then the w3 boolean block
# (onOff b0, health b1, rapid b3, mute b4, sleep b5, screenDisplay b9) and windDirectionHorizontal
# w4.b0. That map is hardware-verified on the classic units, and `6001` is the same command the
# captured classic write path sends; what differs on this family is only *where the report keeps
# that block* (see `write_base_word` below), not how the op is packed.
#
# Enum values are restricted to the app's own mode table {auto, cool, dry, heat, fan_only} and the
# four fan speeds rather than the full 0..6 the preset declares — codes 3 and 5 have no known
# meaning, and the encoder's job is to refuse what we cannot name.
_EXT36_WRITE = {
    "targetTemperature": WriteField(1, 8, 8, "passthrough", min_epp=0, max_epp=14),  # 16..30 C
    "windDirectionVertical": WriteField(1, 0, 4, "onoff", on_value=0x0C),
    "operationMode": WriteField(2, 13, 3, "std_enum", std_to_epp={0: 0, 1: 1, 2: 2, 4: 4, 6: 6}),
    "windSpeed": WriteField(2, 8, 3, "std_enum", std_to_epp={1: 1, 2: 2, 3: 3, 5: 5}),
    "onOffStatus": WriteField(3, 0, 1, "passthrough"),
    "healthMode": WriteField(3, 1, 1, "passthrough"),
    "rapidMode": WriteField(3, 3, 1, "passthrough"),
    "muteStatus": WriteField(3, 4, 1, "passthrough"),
    "silentSleepStatus": WriteField(3, 5, 1, "passthrough"),
    "screenDisplayStatus": WriteField(3, 9, 1, "passthrough"),
    "windDirectionHorizontal": WriteField(4, 0, 3, "onoff", on_value=0x07),
}

# The "extended-36" family: a 36-word report (165 B) carrying the **classic** climate block displaced
# by 19 words. Those leading 19 words are a voice/media module (volume, playback, dialect, …) that the
# generic preset describes but a plain split AC leaves inert — which is exactly why the classic
# partial decode misfires on this model: byte 92 is the module's `volume`, not the setpoint, so the
# setpoint reads as 48 C and power reads as off (haismart-local issue #5).
#
# Transcribed from APK presets `2008…691590000…40` (deviceType `02012036`, 挂机通用_V2D18S_0D05, wall
# mounted) and `2008…112410000…40` (`0301200n`, 柜机通用_V2D18S_0D05, the floor-standing sibling) —
# the only two presets implying a 165-byte report, and their field maps are identical, so keying this
# family on report length is unambiguous. Validated against the two distinct reports captured on a
# real HSU-12KCROC(IN)-R32 (issue #5): power off/on matched the stated states, the setpoint decoded to
# the 22 C the reporter had set, indoor read 30.0/27.5 C, and vertical swing matched fixed/swinging.
#
# Deliberately omitted from the READ: indoorHumidity and the air-quality attributes (this class of
# unit has no such probes and every capture read 0), and `specialMode`. `outdoorTemperature` IS read,
# but as a ``"temp"`` field — both captures report the 0 sentinel, which surfaces as "no reading"
# rather than a fabricated −64 C.
EXTENDED36 = WireModel(
    family="extended36",
    report_lengths=frozenset({165}),
    writable=True,
    group_cmd=b"\x60\x01",
    word_count=5,
    write_base_word=20,     # report word 20 == group-set word 1 (the 19-word media block precedes it)
    write_fields=_EXT36_WRITE,
    fields={
        "power": WireField(22, 0, 1, kind="bool"),
        "target_temperature": WireField(20, 8, 8, kind="int", k=1.0, c=16.0),
        "current_temperature": WireField(25, 8, 8, kind="temp", k=0.5, c=0.0),
        "outdoor_temperature": WireField(26, 8, 8, kind="temp", k=1.0, c=-64.0),
        "operation_mode": WireField(21, 13, 3, kind="enum", enum=_EXT36_MODE),
        "wind_speed": WireField(21, 8, 3, kind="enum", enum=_EXT36_FAN),
        # the vane nibble is a position code shared with the classic map; only the auto codes sweep
        # (see `vane_v_sweeping`). Reading bit 3 alone also matched the parked-low positions.
        "swing_vertical": WireField(20, 0, 4, kind="vane_v"),
        "swing_horizontal": WireField(23, 0, 3, kind="vane_h"),
    },
)

# --- extended-46 (209-byte report) --------------------------------------------------------------

# Control: words 20..24 — the whole settable block — are positioned exactly as on the extended-36
# family, so the group-set is that family's: command `6001`, five words, seeded from report word 20.
# What differs is only the setpoint's units (see below).
#
# Not offered here, deliberately: `windSpeed` and the swings. This family reports a wind-speed code
# outside the set its own device model declares, and its vertical vane answers at a different word
# from the one extended-36 uses — so neither position is settled, and the encoder must never emit a
# field it cannot place. Both become available once a report is seen with those controls varied.
_EXT46_WRITE = {
    # 16..30 C. The wire value is °C × 2 on this family, not the classic °C − 16, so 16..30 C is
    # wire 32..60 — a range that would read as 48..76 C under the classic units.
    "targetTemperature": WriteField(1, 8, 8, "celsius", scale=2.0, min_epp=32, max_epp=60),
    "operationMode": WriteField(2, 13, 3, "std_enum", std_to_epp={0: 0, 1: 1, 2: 2, 4: 4, 6: 6}),
    "onOffStatus": WriteField(3, 0, 1, "passthrough"),
    "healthMode": WriteField(3, 1, 1, "passthrough"),
    "rapidMode": WriteField(3, 3, 1, "passthrough"),
    "muteStatus": WriteField(3, 4, 1, "passthrough"),
    "silentSleepStatus": WriteField(3, 5, 1, "passthrough"),
    "screenDisplayStatus": WriteField(3, 9, 1, "passthrough"),
}

# The "extended-46" family: a 58-word report (209 B) that is the **extended-36 layout with a ten-word
# block inserted at word 25**. Words 1..24 sit exactly where extended-36 puts them — the same
# voice/media module in words 1..19, then the climate block at words 20..22 — and every attribute
# from extended-36's word 25 upward is found ten words later. The inserted block belongs to a
# dual-airflow cabinet (the device model for these units carries a second set of per-tower fan and
# vane attributes); a single-flow unit leaves most of it at zero.
#
# Because the report begins with that media module, the classic partial decode misfires here exactly
# as it does on extended-36: byte 92 is the module's `volume` (100), which reads as a 48 C setpoint,
# and the classic power bit lands in an unrelated word so the unit always looks off.
#
# Three positions differ from extended-36 in kind rather than place, and each is fixed by the values
# the reports themselves carry:
#   * `targetTemperature` is **°C × 2**, not °C − 16 (its device model declares whole-degree steps,
#     so the extra bit of resolution is unused, but the encoding is halves).
#   * `current_temperature` is likewise a half-degree count, as on the classic family.
#   * the vertical vane answers at word 25 — inside the inserted block — where the classic vane
#     encoding still applies (the "swinging" flag is bit 3 of the nibble).
#
# Deliberately omitted from the READ: `windSpeed` (this family reports a code its own device model
# does not declare, so its position is not settled — the enum below would drop it anyway, leaving the
# fan mode absent rather than wrong), horizontal swing, and the air-quality/humidity attributes.
# Read but not published as climate: this family DOES carry a working cumulative-energy register at
# words 44+45 (32-bit), unlike the classic family where it reads zero — its unit is not yet
# established, so it stays out until it can be labelled correctly.
EXTENDED46 = WireModel(
    family="extended46",
    report_lengths=frozenset({209}),
    # Keyed exactly as well as by length: the uPlusId is reported by the units themselves on the
    # discovery channel, so it is available without cloud credentials.
    uplus_ids=frozenset({"2008610800820324021200118017740000000000000000000000000000000040"}),
    writable=True,
    group_cmd=b"\x60\x01",
    word_count=5,
    write_base_word=20,     # report word 20 == group-set word 1, as on extended-36
    write_fields=_EXT46_WRITE,
    fields={
        "power": WireField(22, 0, 1, kind="bool"),
        "target_temperature": WireField(20, 8, 8, kind="int", k=0.5, c=0.0),
        "current_temperature": WireField(35, 8, 8, kind="temp", k=0.5, c=0.0),
        "outdoor_temperature": WireField(36, 8, 8, kind="temp", k=1.0, c=-64.0),
        "operation_mode": WireField(21, 13, 3, kind="enum", enum=_EXT36_MODE),
        "swing_vertical": WireField(25, 0, 4, kind="vane_v"),
    },
)

# Every non-classic family known to the library. The classic 125/127 family is NOT here — it keeps
# its verified inline decode + write path in uss.py.
WIRE_MODELS: tuple[WireModel, ...] = (COMPACT12, EXTENDED36, EXTENDED46)


# --- layout probing ------------------------------------------------------------------------------

# The classic family's map, expressed as a WireModel purely so the prober below can try it like any
# other. It is NOT in ``WIRE_MODELS``: the classic lengths keep their hardware-verified inline decode
# in ``uss.py``, and an empty ``report_lengths``/``uplus_ids`` means this can never be *selected*.
_CLASSIC_PROBE = WireModel(
    family="classic",
    report_lengths=frozenset(),
    fields={
        "power": WireField(3, 0, 1, kind="bool"),
        "target_temperature": WireField(1, 8, 8, kind="int", k=1.0, c=16.0),
        "current_temperature": WireField(6, 8, 8, kind="temp", k=0.5, c=0.0),
        "outdoor_temperature": WireField(7, 8, 8, kind="temp", k=1.0, c=-64.0),
        "operation_mode": WireField(2, 13, 3, kind="enum", enum=_EXT36_MODE),
        "wind_speed": WireField(2, 8, 3, kind="enum", enum=_EXT36_FAN),
        "swing_vertical": WireField(1, 0, 4, kind="vane_v"),
    },
)

# Families the prober tries. Ordered widest-first so an equal score prefers the map that explains
# more of the report.
PROBE_FAMILIES: tuple[WireModel, ...] = (EXTENDED46, EXTENDED36, COMPACT12, _CLASSIC_PROBE)

# How the prober weighs each piece of agreement. Sensor plausibility is worth less than agreeing with
# a value the device itself reported through another channel, because plausibility is cheap to hit by
# chance in a report that is mostly zeros.
_SCORE_SHADOW_MATCH = 4
_SCORE_ENUM_KNOWN = 2
_SCORE_SENSOR_PLAUSIBLE = 1

# A report is mostly zeros, so a candidate whose fields all land on empty words "decodes" perfectly
# into a cold, off, 16 C unit. The prober therefore demands a room temperature that a room could
# actually have — an unpowered word reads 0 C and is rejected — rather than the wide band
# `WireModel.decode` uses to guard an already-chosen family.
_PROBE_INDOOR_C = (5.0, 45.0)

# The two setpoint encodings seen in the wild. Some families put whole degrees on the wire offset by
# 16; others count half-degrees from zero. The difference is invisible in a single report — both are
# a plausible setpoint — so the prober tries each rather than assuming.
_SETPOINT_ENCODINGS = (("offset16", 1.0, 16.0), ("half", 0.5, 0.0))

# Shadow attribute name -> the decoded key it should agree with, and how to compare.
_SHADOW_KEYS: Mapping[str, str] = {
    "targetTemperature": "target_temperature",
    "indoorTemperature": "current_temperature",
    "operationMode": "operation_mode",
    "windSpeed": "wind_speed",
    "onOffStatus": "power",
}


def _shift_model(model: WireModel, pivot: int, shift: int, setpoint: tuple) -> WireModel:
    """``model`` with every field at or above ``pivot`` moved ``shift`` words later, and its setpoint
    read with the ``setpoint`` encoding ``(name, k, c)``.

    The displacement is the one transformation that has explained every layout so far: a unit follows
    a known family but carries extra words in the middle of the array, so the fields after the
    insertion point are all displaced by the same amount and the ones before it do not move at all.
    """
    _, k, c = setpoint
    moved = {}
    for key, f in model.fields.items():
        word = f.word + shift if f.word >= pivot else f.word
        if key == model.target_key:
            moved[key] = WireField(word, f.bit, f.length, f.kind, k, c, f.enum)
        else:
            moved[key] = WireField(word, f.bit, f.length, f.kind, f.k, f.c, f.enum)
    return WireModel(
        family=f"{model.family}+{shift}@w{pivot}" if shift else model.family,
        report_lengths=frozenset(),
        fields=moved,
        indoor_key=model.indoor_key,
        target_key=model.target_key,
    )


def _score(decoded: dict, shadow: Mapping[str, str] | None) -> int:
    score = 0
    if decoded.get("current_temperature") is not None:
        score += _SCORE_SENSOR_PLAUSIBLE
    if decoded.get("outdoor_temperature") is not None:
        score += _SCORE_SENSOR_PLAUSIBLE
    if decoded.get("operation_mode") is not None:
        score += _SCORE_ENUM_KNOWN
    if decoded.get("wind_speed") is not None:
        score += _SCORE_ENUM_KNOWN
    if not shadow:
        return score
    for attr, key in _SHADOW_KEYS.items():
        reported, got = shadow.get(attr), decoded.get(key)
        if reported is None or got is None:
            continue
        if key == "power":
            match = got is (str(reported).lower() == "true")
        elif key in ("operation_mode", "wind_speed"):
            match = str(got) == str(reported)
        else:
            try:
                match = abs(float(got) - float(reported)) < 0.51
            except (TypeError, ValueError):
                match = False
        if match:
            score += _SCORE_SHADOW_MATCH
    return score


def probe_layout(
    reports: bytes | Sequence[bytes],
    *,
    shadow: Mapping[str, str] | None = None,
    max_shift: int = 24,
    limit: int = 3,
) -> list[dict]:
    """Rank plausible layouts for a report no registry entry claims — the first step in adding a
    model, done from the reports themselves rather than by hand.

    Every layout met so far is a known family whose fields are displaced from some word onward, so
    the search is over ``(family, pivot, shift, setpoint encoding)``: try each family with its fields
    at or above each ``pivot`` moved up to ``max_shift`` words later, keep the candidates that decode
    plausibly, and rank them.

    Two things separate a real match from a coincidence, and both matter because a status report is
    mostly zeros — a map whose fields all land on empty words "decodes" into a cold, powered-off unit
    at its minimum setpoint:

    * **Several reports.** Pass every report available (they are captured in different states); a
      candidate must decode *all* of them plausibly, and its score is the weakest one's. A map that
      lands on empty words scores the same in every state, so varied states break the tie.
    * **``shadow``** — the device's own attribute values, from its ``digital_model``, keyed by
      attribute name. A candidate that reproduces values the device published through a different
      channel is almost certainly right.

    Returns up to ``limit`` candidates, best first, each ``{"family", "pivot", "shift", "setpoint",
    "score", "decoded"}``. An empty list means nothing fits, which is itself the useful answer: the
    report is a layout unlike any known family rather than a displaced one.
    """
    blobs = [reports] if isinstance(reports, (bytes, bytearray)) else list(reports)
    seen: set[tuple] = set()
    out: list[dict] = []
    for model in PROBE_FAMILIES:
        pivots = sorted({f.word for f in model.fields.values()} | {1})
        for pivot in pivots:
            for shift in range(max_shift + 1):
                for encoding in _SETPOINT_ENCODINGS:
                    candidate = _shift_model(model, pivot, shift, encoding)
                    # A shift below the lowest field restates the pivot=1 map; skip the duplicates so
                    # the ranking is not filled with several spellings of one candidate.
                    key = (
                        encoding[0],
                        tuple(sorted((k, f.word, f.bit) for k, f in candidate.fields.items())),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    scores, decodes = [], []
                    for blob in blobs:
                        decoded = candidate.decode(blob)
                        indoor = (decoded or {}).get(candidate.indoor_key)
                        if (
                            decoded is None
                            or decoded.get(candidate.target_key) is None
                            or indoor is None
                            or not _PROBE_INDOOR_C[0] <= indoor <= _PROBE_INDOOR_C[1]
                        ):
                            scores = []
                            break
                        scores.append(_score(decoded, shadow))
                        decodes.append(
                            {k: v for k, v in decoded.items() if k not in ("layout", "writable")}
                        )
                    if not scores:
                        continue
                    out.append(
                        {
                            "family": model.family,
                            "pivot": pivot,
                            "shift": shift,
                            "setpoint": encoding[0],
                            "score": min(scores),
                            "decoded": decodes,
                        }
                    )
    # Ties are common and the tie-break is the whole difference between a useful proposal and a
    # misleading one: prefer the smallest displacement, then the one that moves the FEWEST fields
    # (the highest pivot). Several pivots produce the same score whenever the words between them
    # carry nothing that varies, and the candidate that disturbs least of a known family is the one
    # that is actually right — a lower pivot drags mode and fan along with the sensors and reads
    # them from the wrong words while still scoring the same.
    out.sort(key=lambda c: (-c["score"], c["shift"], -c["pivot"]))
    return out[:limit]


def select_wire_model(length: int, uplus_id: str | None = None) -> WireModel | None:
    """The :class:`WireModel` for a report, preferring an exact uPlusId match and otherwise keying on
    report ``length``. Returns ``None`` when nothing matches, or when the length is ambiguous across
    families and no uPlusId disambiguates it (safer to fall back to the unknown-layout path than to
    guess). The caller must still gate on the classic lengths owning their inline decode."""
    if uplus_id:
        for wm in WIRE_MODELS:
            if uplus_id in wm.uplus_ids:
                return wm
    candidates = [wm for wm in WIRE_MODELS if length in wm.report_lengths]
    return candidates[0] if len(candidates) == 1 else None
