"""Per-family EPP wire models — the positional attribute map for status reports whose layout is
*not* the classic split-AC family that :func:`haismart_hrdp.uss.parse_full_status` decodes inline.

Background
----------
Every Haier AC packs its status attributes into a bit-field array of 16-bit big-endian words that
begins at byte 92 of the decrypted report (right after the ``6d 01`` getAllProperty response code).
*Where* each attribute sits in that array is the **wire model**, and it is a property of the model a
device reports itself as (its uPlusId) rather than of the device. The *digital* model we fetch per
device carries an attribute's valueRange and enums but no position, so these maps are transcribed
from the published per-model descriptions and validated field by field against real captured
reports. :mod:`haismart_hrdp.canonical_map` covers where those descriptions agree with each other,
which is nearly everywhere; this module covers the families and the exceptions.

What a "family" is
------------------
A family is a **distinct field map**, and one map can span several report lengths (the classic
split-AC family is described at report lengths 109/121/125 and appears on real hardware at 127 —
only its trailing word count differs). So report length alone is a *good but imperfect* key: among
AC split units each length maps to a single field map, but there is a genuine collision at 149 B (a
floor/heat-pump class we don't target). Selection therefore prefers an exact uPlusId match and
otherwise keys on report length **with a decode sanity-check** (see :meth:`WireModel.decode`),
degrading to the caller's unknown-layout path rather than mis-decoding.

The classic family stays in ``uss.py``
--------------------------------------
The classic 125/127-byte family keeps its existing hardware-verified decode + the grSetDAC **write**
path in ``uss.py`` untouched. This module adds decoding for other families, plus — for a family whose
group-set command its model fully specifies (``group_cmd`` + :attr:`WireModel.write_fields`)
— a **control encoder** built on that spec. That spec basis is the same one heat mode shipped on
(model-derived, method hardware-confirmed on other units); a family without a ``group_cmd`` stays
monitoring-only.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from .canonical_map import CANONICAL, CANONICAL_WRITE, PROFILE_DISPLACEMENTS
from .panel import PANEL_BOOL_CONTROLS, PANEL_ENUM_CONTROLS, PANEL_EXTRA_POSITIONS

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
    word (bit 0 = least-significant).

    An attribute wider than the word that holds its LSB simply continues into the words **before**
    it: ``word``/``bit`` locate the least-significant end, and significance grows backwards through
    the array. The published map is written that way and only makes sense read that way — its
    32-bit cumulative counter puts its low half at the stated word and its high half one word
    earlier (both families carrying it agree), and its two 24-bit stamps, at word 7 bit 8 and word 8
    bit 0, tile words 6..8 exactly with no overlap backwards and collide forwards.

    ``kind`` selects the decode:

    * ``"bool"``  -> ``bool(raw)``
    * ``"int"``   -> ``raw * k + c`` (a temperature/number)
    * ``"temp"``  -> ``raw * k + c``, but ``None`` for a raw value that means "no such probe"
      (``0x00``/``0xFF``) or that lands outside :data:`_PLAUSIBLE_SENSOR_C`. Use this for a *sensor*
      reading rather than ``"int"``: a unit without an outdoor probe reports 0, which the raw formula
      would turn into a confident −64 °C, and one fabricated MEASUREMENT permanently skews the
      min/max/mean of a user's long-term statistics. This mirrors ``uss._sensor_temp`` on the classic
      family.
    * ``"raw"``   -> the field's integer value, unscaled: a code, or a reading that needs no
      scaling at all (a register already in watts). ``"int"`` would return the same number as a
      float, which is right for a scaled temperature and wrong for a whole-unit counter.
    * ``"counter"`` -> like ``"raw"``, but ``None`` for zero. A cumulative register that reads
      exactly 0 is one the firmware never populates rather than a unit that has used nothing —
      whole classes of these air conditioners carry the register and leave it at zero for their
      whole service life, and a total that is permanently 0 is worse than absent: it sits in the
      Energy dashboard reporting no consumption.
    * ``"enum"``  -> ``enum[raw]`` — translates the raw wire value into the code the device
      **publishes** for that attribute, or drops the field when the raw value isn't in the map. Most
      attributes number themselves the same way in both places and need no entry here; the few that
      do not are the reason this exists. The mapped-to value is a Haier STD code — a string where a
      per-model :class:`~haismart_hrdp.models.AttributeProfile` names it, an integer where the
      published map carries the translation itself.
    * ``"humidity"`` -> the raw percentage, but ``None`` for 0 or anything above 100. A humidity
      probe never reads a true 0 in habitable air; units without the probe leave the register at
      zero for their whole service life (every capture of every family so far), and a permanent
      0 % is a fabricated reading, not a measurement.
    """

    word: int
    bit: int
    length: int
    kind: str = "int"
    k: float = 1.0
    c: float = 0.0
    enum: Mapping[int, str] | Mapping[int, int] | None = None

    def read(self, data: bytes):
        # The words this field spans, ending at its own: one for anything that fits a single word,
        # more for an attribute whose significance runs back into the words before it.
        span = (self.bit + self.length + 15) // 16
        end = _ATTR_BASE + self.word * 2
        start = end - span * 2
        if start < _ATTR_BASE or end > len(data):
            return None
        raw = int.from_bytes(data[start:end], "big") >> self.bit & ((1 << self.length) - 1)
        if self.kind == "bool":
            return bool(raw)
        if self.kind == "raw":
            return raw
        if self.kind == "counter":
            return raw or None
        if self.kind == "bool_inv":
            return not raw
        if self.kind == "vane_v":
            return vane_v_sweeping(raw)
        if self.kind == "vane_h":
            return vane_h_sweeping(raw)
        if self.kind == "enum":
            return None if self.enum is None else self.enum.get(raw)
        if self.kind == "humidity":
            return raw if 0 < raw <= 100 else None
        if self.kind == "temp":
            if raw in _SENSOR_ABSENT:
                return None
            value = raw * self.k + self.c
            lo, hi = _PLAUSIBLE_SENSOR_C
            return value if lo <= value <= hi else None
        return raw * self.k + self.c


# Who made the last change. The unit reports this in every status frame, which lets an automation
# tell an owner reaching for the handset apart from a command it sent itself.
#
# ⚠️ Only two of the four are evidenced. **1 (handset) and 3 (module/app)** are confirmed against an
# independent implementation of the same protocol. **0 and 2 are not**: the device models declare the
# attribute as a plain two-bit integer with no descriptions for its values, so nothing states what
# they mean. `other` is a catch-all and asserts nothing; `panel` names a wired wall controller, which
# is the obvious remaining source on this hardware and is still an inference. Do not cite it as
# evidence that a unit accepts wired control -- that would be this project's own guess coming back as
# a fact. A reading taken while a wired controller is used would settle it.
OPERATION_SOURCE: Mapping[int, str] = {0: "other", 1: "remote", 2: "panel", 3: "network"}


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

# Model code -> wire value for the UP-DOWN vane. The left-right vane needs no such table: the code
# its model names is the value on the wire. This axis is different — a model numbers its stops 0, 2,
# 4, 5, 6, 8 while the unit works in even steps — and the difference is why a position on this axis
# cannot simply be passed through.
#
# Confirmed on hardware: a unit stepped through every stop its app offers, one capture per stop,
# reported 0, 2, 4, 6, 8 and 12 for the model's 0, 2, 4, 5, 6 and 8. The last of those is the same
# 0x0C the classic family has always used for "auto", which is the check that the two ends agree.
# ``7`` completes the table on the same pattern; no model seen here lists it.
VANE_V_MODEL_TO_EPP: Mapping[int, int] = {0: 0, 2: 2, 4: 4, 5: 6, 6: 8, 7: 10, 8: 12}
VANE_V_EPP_TO_MODEL: Mapping[int, int] = {epp: std for std, epp in VANE_V_MODEL_TO_EPP.items()}


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
class SingleParam:
    """A control written one parameter at a time (not via the group-set).

    ``on``/``off`` are the two-byte EPP commands that set the attribute — for a paired boolean the
    command itself carries the value (``4d05`` = electric-heat on, ``4d04`` = off), so there is no
    data payload. ``off`` is ``None`` for a start-only trigger (self-clean has no off command).
    ``read`` is the :class:`WireField` its state is read back from, so the control shows real state.
    """

    on: bytes
    off: bytes | None
    read: WireField

    def command(self, value: int) -> bytes | None:
        """The EPP command for ``value`` (1 = on / 0 = off), or ``None`` if that direction has no
        command (a start-only trigger asked to turn off)."""
        return self.on if value else self.off


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
    # Write fields that carry a POSITION rather than an on/off state — the vanes, on a family that
    # packs them as the multi-bit code they are. A family that collapses a vane to a single bit
    # (compact-12 does, and its own model describes it that way) must leave the field out: a position
    # packed there would arrive as "sweep", which is not what was asked for.
    position_fields: frozenset[str] = frozenset()
    # This family's whole-word offset from the published map, when it HAS one. Set only where the
    # map has been checked against real reports field for field -- classic at -19 (9 of 9 positions
    # reproduced) and extended-36 at 0 (12 of 12).
    canonical_displacement: int | None = None
    # A block this family inserts that the published map does not describe, as
    # ``(first inserted word, how many words)``. A family with an insert is still a displacement of
    # the map -- just a piecewise one: everything below the pivot sits at ``canonical_displacement``
    # and everything from it upward is pushed along by the insert.
    #
    # extended-46 is the case: canonical, with ten words inserted at w25 for a dual-airflow
    # cabinet's per-tower vane and fan, which the published map does not carry because no bundled
    # model has that hardware. This used to be expressed by leaving the displacement ``None``, which
    # said "unplaceable" when the truth was "placeable, in two pieces" -- so nothing read the
    # attributes this family's devices declare, and its optional-feature entities never appeared.
    canonical_insert: tuple[int, int] | None = None
    # Like ``canonical_insert``, but applying only to reports of a given LENGTH, for a family whose
    # members differ by one inserted word. The classic family is the case: its 125-byte members are
    # the flat map at -19, while the 127-byte rental SKU carries one extra word (``targetRentTime``,
    # its report word 6) that the published map does not describe, pushing everything from canonical
    # word 25 up along by one. The report length is the evidence for the insert -- the 127-byte
    # layout's hardware-confirmed sensor offsets (indoor temperature at byte 104, outdoor at 106,
    # the energy counter's low word at 124) are each exactly one word past where the flat map puts
    # them, and each reproduces under the insert.
    length_inserts: Mapping[int, tuple[int, int]] = field(default_factory=dict)
    # Controls written ONE PARAMETER AT A TIME rather than through the group-set, for families that
    # publish per-attribute write commands (compact-12 does: `4d04`/`4d05` electric-heat, …). Maps an
    # attribute name to ``SingleParam`` — its off/on EPP command bytes and the WireField to read its
    # state back with. This is a different mechanism from ``group_cmd``: each write is its own op with
    # no baseline, and a boolean's command IS its value (the on-command sets on, the off-command off).
    single_param_fields: Mapping[str, SingleParam] = field(default_factory=dict)

    def canonical_word(self, word: int) -> int | None:
        """Where a published map word lands in this family's report, or ``None`` if unplaceable.

        The safe direction is ``None``: a family whose relationship to the map has not been checked
        against real reports must place nothing, since a guessed offset puts every attribute
        somewhere plausible and wrong.
        """
        if self.canonical_displacement is None:
            return None
        placed = word + self.canonical_displacement
        if self.canonical_insert is not None:
            pivot, count = self.canonical_insert
            if word >= pivot:
                placed += count
        return placed

    def model_fields(self, declared: Iterable[str], report_length: int) -> dict[str, WireField]:
        """Fields for the attributes ``declared`` by this device that the family map does not carry.

        Empty for a family whose relationship to the map is unknown, which is the safe direction:
        the device keeps the attributes that were established from captures and gains nothing
        invented.
        """
        if self.canonical_displacement is None:
            return {}
        place = self.canonical_word
        if insert := self.length_inserts.get(report_length):
            pivot, count = insert

            def place(word: int, _base=self.canonical_word) -> int | None:
                placed = _base(word)
                if placed is None:
                    return None
                return placed + count if word >= pivot else placed

        return declared_fields(
            place, declared,
            word_limit=(report_length - _ATTR_BASE) // 2,
        )

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

    def single_param_value(self, report: bytes, name: str) -> int | None:
        """Read a single-parameter control's current state back from ``report``, or ``None``.

        A single-parameter control is written by command rather than into the group-set word block,
        so its state is read from its own :class:`SingleParam.read` position, not from ``write_fields``.
        """
        sp = self.single_param_fields.get(name)
        if sp is None:
            return None
        value = sp.read.read(report)
        return int(value) if isinstance(value, bool) else value

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

        # A report this family cannot actually read is NOT a report of this family. Both anchors
        # have to arrive, or the checks below are asked about values that were never read -- and a
        # check on a value that was never read passes, which is the whole of Rule 13. What made
        # this reachable is that a uPlusId match wins over the length in `matches`, deliberately
        # (the appliance names its own family on the discovery channel, key-free). So a SHORT frame
        # from a known appliance -- an ack, a reply to a query the unit does not implement -- was
        # claimed by its family, read nothing, vetoed nothing, and came back as a successful decode
        # carrying only the two markers below. Downstream that is a full status report: it becomes
        # the coordinator's cached blob, and the next control command seeds its group-set from a
        # 93-byte "report" and fails with `report too short (93) for extended46 baseline` until a
        # poll happens to overwrite it. Refusing here costs nothing -- the caller falls through to
        # the related-layout and partial paths exactly as it does for any unclaimed report.
        for anchor in (self.indoor_key, self.target_key):
            if anchor in self.fields and anchor not in out:
                return None

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
# model uses, so the AttributeProfile names them (STD 4 = heat, 2 = dry, 6 = fan, etc.). The mapping
# is the one this model publishes in its own stdCode:eppValue table, i.e. epp 2 == STD "4".
_COMPACT12_MODE = {0: "0", 1: "1", 2: "4", 3: "6", 4: "2"}   # auto / cool / heat / fan_only / dry
_COMPACT12_FAN = {0: "1", 1: "2", 2: "3", 3: "5"}            # high / medium / low / auto

# Control (group-set): this model fully specifies its group command — eppCmd
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
    # 16..30 C (the model's own minValue/maxValue), i.e. EPP 0..14 — same range as the classic
    # family, and far narrower than the 16 bits the field occupies.
    "targetTemperature": WriteField(12, 0, 16, "passthrough", min_epp=0, max_epp=14),
    "onOffStatus": WriteField(9, 0, 1, "passthrough"),
}

# The "compact-12" family: a 12-word report (117 B) where every attribute — sensors included — lives
# in the word array (unlike the classic family's separate sensor block). Transcribed from the two
# published models that describe it, and validated field-for-field against three real reports from a
# HSU-12HFMF (haismart-local issue #4): power/setpoint/indoor/mode/fan/both swings all matched the
# state the reporter said the unit was in.
#
# The family's own published description positions every one of its 38 fields, and all of them are
# now read (below). The ones with UNPROVEN MEANING are keyed so no entity consumes them — they land
# in the decode (hence diagnostics) only, and each names what promotes it:
#
#   * `w2_low_raw` (w2 LOW byte) — `外温`/outdoorTemperature, a real sensor this variant HAS (the
#     catalogue marks it invisible:false) and NOT humidity: this variant declares no humidity
#     hardware (its humidity attributes are invisible:true, and w11 `实湿` reads 0), so smartair2's
#     `room_humidity` at the same offset describes a DIFFERENT variant, not this one. It reads raw
#     59 / 60 / 60 across off / cool / fan-only. The only open part is the ENCODING, and both survivors
#     are outdoor temperatures — humidity is ruled out either way:
#       - taken at face value (k=1) it is ~60, an outdoor-UNIT / hot-side reading — 60 °C off the
#         condenser while cooling is ordinary (the telemetry family's outdoor-air byte runs 60–85 °C),
#         holding ~59 stale when off (the v0.39.0 dormant-probe behaviour);
#       - nine sibling models declare this attribute min −30 / max 60, which would make it ambient
#         ~30 via a −30 offset.
#     Held raw/diagnostic until one reading at a known outdoor temperature fixes the offset; never an
#     "outdoor temperature" sensor (a user reads that as ambient, and it may be the hot side).
#     ⚠️ An earlier note called this humidity, on "59 can't be outdoor". Rule 6 trap: 60 °C IS
#     reasonable for outdoor-unit air, and the invisible flags settle it as outdoor. Retracted.
#     `w2_high_raw` is `空质`/air-quality per the vendor; kept neutral, unconfirmed.
#   * `input_power_raw` (w3, low+high byte) — LIVE (0 off, 15 cooling, 0 fan-only on the real
#     reports; it moves with the compressor), but 15 of anything is not watts while cooling, so the
#     description's unit cannot be taken at face value (0.1 kW steps → 1.5 kW would be plausible).
#     The same bar that keeps the 209-family's counter out: no unit, no sensor. One reporter reading
#     their meter or app beside a capture settles the scale.
#   * the toggles/flags — positions published, every capture so far reads them 0, so there is no
#     positive confirmation and no entity; they read back for diagnostics and for the day a capture
#     exercises one.
#
# Control covers the core climate fields (power / mode / fan / setpoint / both swings) via the group
# command its model specifies; the description also names per-attribute write commands, which stay
# unused (a different mechanism, documented, not needed while the group command works).
# The compact family's per-attribute (single-parameter) write commands, from its own published
# profile: paired 开/关 (on/off) EPP commands, and the report position each reads back at (verified
# against the three issue-#4 reports). This is how the app controls the toggles this family's group
# command (`4d5f`, mode/fan/vanes/temp/onoff) does not carry. Keyed by the digital-model attribute
# name so the coordinator's declared∩¬invisible gate applies unchanged; the Chinese-label→name
# mapping is the profile glossary (电=electric-heat, 新=fresh air, 康=health, 自=self-clean).
# Only the panel controls this family declares are enabled here. The controls offered through
# `panel_switch_fields`/`panel_select_fields` are gated by the device DECLARING the attribute
# (declared ∩ ¬invisible), so a compact unit without electric-heat is not offered it. The family's
# health (`4d09`/`4d08`) and self-clean (`4d26`, start-only) are included now that a
# single-parameter control is offered by declaration (see `coordinator.supports_field`), so a
# compact unit without the function gets no control. The remaining published pairs — `4d18`/`4d19`
# (child lock), `4d1c`/`4d1d` (humidify) — stay out on the documentary rule, not the gate: the
# app's panel renders no widget for either, so neither do we.
_COMPACT12_SINGLE_PARAM = {
    "electricHeatingStatus": SingleParam(b"\x4d\x05", b"\x4d\x04", WireField(9, 1, 1, kind="bool")),
    "freshAirStatus": SingleParam(b"\x4d\x1f", b"\x4d\x1e", WireField(10, 0, 1, kind="bool")),
    # The health toggle and the self-clean trigger, from the family's own published records —
    # paired on/off commands with the state bit each reads back from, same shape as the two above.
    # Self-clean has no off command (the cycle runs to completion), hence the start-only form.
    # These are OFFERED by declaration (`coordinator.supports_field` requires a single-parameter
    # control's attribute to be declared and not invisible), so a compact unit without the function
    # gets no control for it.
    "healthMode": SingleParam(b"\x4d\x09", b"\x4d\x08", WireField(9, 3, 1, kind="bool")),
    "selfCleaningStatus": SingleParam(b"\x4d\x26", None, WireField(9, 2, 1, kind="bool")),
}

COMPACT12 = WireModel(
    family="compact12",
    report_lengths=frozenset({117}),
    single_param_fields=_COMPACT12_SINGLE_PARAM,
    # Every one of the family's 509 catalogue products carries this same 32-character identifier —
    # it is the family, not a member — so an appliance announcing it on the discovery channel
    # resolves here before its first report. Length keying stays as the fallback for a unit whose
    # identifier was never learned.
    uplus_ids=frozenset({"00000000000000008080000000041410"}),
    writable=True,
    group_cmd=b"\x4d\x5f",
    word_count=12,
    write_fields=_COMPACT12_WRITE,
    # ── Label glossary (AUTHORITATIVE — the profile gives Chinese labels, not English names, and
    # mis-translating them is a recurring error, so the mapping is written down here once). Each field
    # below is keyed by the profile's own Chinese label; the token is the literal, verified reading.
    #   实温 indoor temp · 外温 outdoor(-UNIT) temp · 空质 air quality · 功率低/高 power low/high byte ·
    #   PM值 PM value · 模式 mode · 风速 fan speed · 上下 up-down vane · 左右 left-right vane ·
    #   开/关机 power · 电 electric heat · 自 self-clean · 康 health · 湿 humidify · 节能有无 energy-save
    #   CAPABILITY · 单位切换 temp-unit toggle · 感人 human/presence sensing · 云适(应) cloud-ADAPTIVE
    #   (NOT cloud-control) · 眠线 sleep curve · 锁 lock · 新 fresh air · 强力有无 boost CAPABILITY ·
    #   静音有无 quiet CAPABILITY · 健康上吹/下吹 healthy airflow up/down · 屏显有无 display CAPABILITY ·
    #   实湿 indoor humidity · 设湿 target humidity · 设温 target temp.
    # 有无 = "has / has-not" = a CAPABILITY flag (does the unit HAVE the function), NOT its on/off state.
    fields={
        "power": WireField(9, 0, 1, kind="bool"),                 # 开机/关机
        "target_temperature": WireField(12, 0, 16, kind="int", k=1.0, c=16.0),   # 设温
        "current_temperature": WireField(1, 0, 16, kind="int", k=1.0, c=0.0),    # 实温
        "operation_mode": WireField(6, 0, 16, kind="enum", enum=_COMPACT12_MODE),  # 模式
        "wind_speed": WireField(7, 0, 16, kind="enum", enum=_COMPACT12_FAN),     # 风速
        "swing_vertical": WireField(8, 0, 1, kind="bool"),       # 上下
        "swing_horizontal": WireField(8, 1, 1, kind="bool"),     # 左右
        # --- the rest of the published description (positions verified against the real reports;
        # none of these keys is consumed by an entity — diagnostics only, see the note above) ---
        "w2_low_raw": WireField(2, 0, 8, kind="raw"),            # 外温 — outdoor temp (unit; ~60 hot)
        "w2_high_raw": WireField(2, 8, 8, kind="raw"),           # 空质 — air quality (unconfirmed)
        "input_power_raw": WireField(3, 0, 16, kind="raw"),      # 功率 — power register, unit unproven
        "pm_raw": WireField(4, 0, 16, kind="raw"),               # PM值
        "indoor_humidity": WireField(11, 0, 8, kind="humidity"), # 实湿
        "target_humidity": WireField(11, 8, 8, kind="humidity"), # 设湿
        # word 9: the state bits beside power (b0)
        "electric_heat": WireField(9, 1, 1, kind="bool"),        # 电
        # keyed the same as the canonical families' self-clean state so the running indicator and
        # the "last self-clean" timestamp read it — the button this family now offers needs both
        "self_cleaning": WireField(9, 2, 1, kind="bool"),        # 自
        "health": WireField(9, 3, 1, kind="bool"),               # 康
        "humidify": WireField(9, 6, 1, kind="bool"),             # 湿 (开湿/关湿 = moisture on/off)
        "temp_unit": WireField(9, 11, 1, kind="raw"),            # 单位切换 — °C/°F toggle
        "human_sensing": WireField(9, 12, 1, kind="bool"),       # 感人
        "cloud_adaptive": WireField(9, 13, 1, kind="bool"),      # 云适应 (was mis-mapped "cloud_control")
        "sleep_curve": WireField(9, 14, 1, kind="bool"),         # 眠线
        "lock": WireField(9, 15, 1, kind="bool"),                # 锁
        # word 10: fresh air + the healthy-airflow pair, and the 有无 CAPABILITY flags
        "fresh_air": WireField(10, 0, 1, kind="bool"),           # 新
        "healthy_wind_up": WireField(10, 3, 1, kind="bool"),     # 健康上吹
        "healthy_wind_down": WireField(10, 4, 1, kind="bool"),   # 健康下吹
        "cap_strong": WireField(10, 1, 1, kind="bool"),          # 强力有无
        "cap_quiet": WireField(10, 2, 1, kind="bool"),           # 静音有无
        "cap_display": WireField(10, 5, 1, kind="bool"),         # 屏显有无
        "cap_energy_saving": WireField(9, 10, 1, kind="bool"),   # 节能有无
    },
)

# --- extended-36 (165-byte report) --------------------------------------------------------------

# operationMode / windSpeed are plain STD enums here: the model maps stdValue -> eppValue 1:1 for
# both, so the raw wire value IS the STD code the digital model and the profile already speak.
_EXT36_MODE = {0: "0", 1: "1", 2: "2", 4: "4", 6: "6"}   # auto / cool / dry / heat / fan_only
_EXT36_FAN = {1: "1", 2: "2", 3: "3", 5: "5"}            # high / medium / low / auto

# --- fields from the published map ------------------------------------------
# The families below are the same published attribute map at different displacements (see
# `canonical_map`). So their positions and scaling are read from it rather than written out again:
# what stays here is the part the map does not state, which is how we choose to DECODE each field —
# that a temperature sensor reporting its zero sentinel means "no probe" rather than 0 °C, that a
# vane nibble is a position code with only some values meaning "sweeping", and which enum table
# names a code. Those are policies, not published facts.
#
# Each entry is our key -> (published name, kind[, enum]).
_CLIMATE_SPEC: Mapping[str, tuple] = {
    "power": ("onOffStatus", "bool"),
    "target_temperature": ("targetTemperature", "int"),
    "current_temperature": ("indoorTemperature", "temp"),
    "outdoor_temperature": ("outdoorTemperature", "temp"),
    "heat_capable": ("acType", "bool_inv"),
    "error_code": ("errCode", "raw"),
    "last_changed_by": ("opSrc", "enum", OPERATION_SOURCE),
    "operation_mode": ("operationMode", "enum", _EXT36_MODE),
    "wind_speed": ("windSpeed", "enum", _EXT36_FAN),
    "swing_vertical": ("windDirectionVertical", "vane_v"),
    "swing_horizontal": ("windDirectionHorizontal", "vane_h"),
    "self_cleaning": ("selfCleaningStatus", "bool"),
    "energy_wh": ("totalElectricityUsed", "counter"),
    # The comfort settings, which share one word with the power flag. A family that offers these as
    # switches must also READ them: a switch whose state never moves looks to its owner like a
    # command that did nothing, even when the air conditioner obeyed it.
    "strong": ("rapidMode", "bool"),
    "quiet": ("muteStatus", "bool"),
    "health": ("healthMode", "bool"),
    "sleep": ("silentSleepStatus", "bool"),
    "lamp": ("screenDisplayStatus", "bool"),
}


def canonical_fields(
    displacement: int | Callable[[int], int | None],
    keys: Sequence[str],
    spec: Mapping[str, tuple] = _CLIMATE_SPEC,
) -> dict[str, WireField]:
    """Our decode fields for ``keys``, taken from the published map.

    ``displacement`` is a whole-word offset, or -- for a family that displaces the map piecewise --
    the placement rule itself (:meth:`WireModel.canonical_word`). A key the rule cannot place is
    omitted rather than guessed at.
    """
    place = (lambda w: w + displacement) if isinstance(displacement, int) else displacement
    out: dict[str, WireField] = {}
    for key in keys:
        name, kind, *rest = spec[key]
        c = CANONICAL[name]
        word = place(c.word)
        if word is None:
            continue
        out[key] = WireField(word, c.bit, c.length, kind=kind,
                             k=c.k, c=c.c, enum=rest[0] if rest else None)
    return out


# A published attribute's declared type, mapped to how we decode it. `string` is deliberately absent:
# a dozen attributes declare it, and a run of characters is not something a bit field at a word/bit
# position renders into anything meaningful, so those are skipped rather than guessed at.
_DTYPE_KINDS = {"bool": "bool", "int": None, "double": None}


def declared_fields(
    displacement: int | Callable[[int], int | None],
    declared: Iterable[str],
    *,
    word_limit: int,
) -> dict[str, WireField]:
    """Decode fields for the attributes a DEVICE ITSELF declares, placed by the published map.

    The hand-written family maps carry the dozen or so attributes that were worked out from
    captures. A device's own model routinely declares three or four times that many -- every one of
    them at a position the published map already states -- and none of them was being read. This
    closes that gap without needing a capture per attribute: membership comes from the device's own
    model, position comes from the map, and the two are independent of each other.

    Keys are the published attribute names (``lockStatus``), never our own field keys, so nothing
    here can collide with or silently redefine a hand-mapped field. Attributes already covered by
    :data:`_CLIMATE_SPEC` are skipped for the same reason.

    ``displacement`` is a family's *confirmed* whole-word offset, or the placement rule of a family
    that displaces the map piecewise (:meth:`WireModel.canonical_word`, which handles an inserted
    block). Either way it must be confirmed against real reports: a guessed offset would put every
    one of these attributes somewhere plausible and wrong, which is the failure this gate exists to
    prevent, and a rule that cannot place a word returns ``None`` so the attribute is dropped.

    ``word_limit`` is the report's word count; an attribute the displacement would push past the end
    of the report is dropped rather than read off whatever follows.
    """
    place = (lambda w: w + displacement) if isinstance(displacement, int) else displacement
    covered = {name for name, *_ in _CLIMATE_SPEC.values()}
    out: dict[str, WireField] = {}
    for name in declared:
        c = CANONICAL.get(name)
        if c is None or name in covered:
            continue
        if c.dtype not in _DTYPE_KINDS:
            continue
        word = place(c.word)
        if word is None:
            continue
        # The field's most significant end runs backwards from its word, so both ends must land
        # inside the array -- see WireField.read.
        span = (c.bit + c.length + 15) // 16
        if word - span + 1 < 1 or word > word_limit:
            continue
        kind, enum = _DTYPE_KINDS[c.dtype], None
        if kind is None:
            # How a number is read depends on what the published map says about its codes, and the
            # map states this for every attribute it carries -- there is no third case where the
            # answer is unknown.
            #
            #  * scaled or offset -> a READING, which the wire carries directly.
            #  * unscaled with a translation -> a CODE the device publishes under different numbers
            #    than it puts on the wire. The map carries that translation as `enum`, so apply it;
            #    reporting the raw value here means reporting something the device never says.
            #  * unscaled with no translation -> a CODE the map states is the same in both places,
            #    so the wire value is already the published one. An absent `enum` is the map saying
            #    the two agree, not the map having nothing to say.
            if (c.k, c.c) != (1.0, 0.0):
                kind = "int"
            elif c.enum:
                kind, enum = "enum", c.enum
            else:
                kind = "raw"
        out[name] = WireField(word, c.bit, c.length, kind=kind, k=c.k, c=c.c, enum=enum)
    return out



# Control: the model's own `grSetDAC` operation gives the group command (`6001`) and a five-word
# array whose bit map is **byte-for-byte the classic family's** — targetTemperature w1.b8,
# windDirectionVertical w1.b0, operationMode w2.b13, windSpeed w2.b8, then the w3 boolean block
# (onOff b0, health b1, rapid b3, mute b4, sleep b5, screenDisplay b9) and windDirectionHorizontal
# w4.b0. That map is hardware-verified on the classic units, and `6001` is the same command the
# captured classic write path sends; what differs on this family is only *where the report keeps
# that block* (see `write_base_word` below), not how the op is packed.
#
# Enum values are restricted to the app's own mode table {auto, cool, dry, heat, fan_only} and the
# four fan speeds rather than the full 0..6 the model declares — codes 3 and 5 have no known
# meaning, and the encoder's job is to refuse what we cannot name.
# The panel's frame-positioned controls (`haismart_hrdp.panel`), as WriteFields built straight from
# the invariant group-set frame. Every grSetDAC family (classic, extended-36, extended-46, and the
# related layouts) packs these at the same words, so they are shared here rather than transcribed per
# family. Bools take 0/1; the two enums (presence airflow, fresh-air speed) take their raw 0..3. A
# device is only OFFERED the ones it declares and does not mark invisible (the coordinator's
# `panel_switch_fields`/`panel_select_fields`), and the family bit-reuse guard still applies -- so
# merging the whole set into a family's write map is safe: membership here means "the frame places
# it", not "every unit has it".
_FRAME_PANEL_WRITE = {
    **{
        name: WriteField(
            CANONICAL_WRITE[name].word,
            CANONICAL_WRITE[name].bit,
            CANONICAL_WRITE[name].length,
            "passthrough",
            max_epp=(1 if name in PANEL_BOOL_CONTROLS else (1 << CANONICAL_WRITE[name].length) - 1),
        )
        for name in (*PANEL_BOOL_CONTROLS, *PANEL_ENUM_CONTROLS)
        if name in CANONICAL_WRITE
    },
    # order-derived (not in the frame): all bools, so passthrough max 1
    **{
        name: WriteField(w, b, ln, "passthrough", max_epp=1)
        for name, (w, b, ln) in PANEL_EXTRA_POSITIONS.items()
    },
}

_EXT36_WRITE = {
    "targetTemperature": WriteField(1, 8, 8, "passthrough", min_epp=0, max_epp=14),  # 16..30 C
    # Both vanes take their wire value straight through, so a POSITION reaches the unit rather than
    # only "fixed" or "sweep". The caller passes the wire value — 0x0C is still what "swing on"
    # means for the up-down axis — and the position codes a device publishes are translated to wire
    # values before they get here (see `VANE_V_MODEL_TO_EPP`; the left-right axis needs no table).
    "windDirectionVertical": WriteField(1, 0, 4, "passthrough", max_epp=0x0C),
    "operationMode": WriteField(2, 13, 3, "std_enum", std_to_epp={0: 0, 1: 1, 2: 2, 4: 4, 6: 6}),
    "windSpeed": WriteField(2, 8, 3, "std_enum", std_to_epp={1: 1, 2: 2, 3: 3, 5: 5}),
    "onOffStatus": WriteField(3, 0, 1, "passthrough"),
    "healthMode": WriteField(3, 1, 1, "passthrough"),
    "rapidMode": WriteField(3, 3, 1, "passthrough"),
    "muteStatus": WriteField(3, 4, 1, "passthrough"),
    "silentSleepStatus": WriteField(3, 5, 1, "passthrough"),
    "screenDisplayStatus": WriteField(3, 9, 1, "passthrough"),
    "windDirectionHorizontal": WriteField(4, 0, 3, "passthrough", max_epp=0x07),
    # The multi-level economy setting, in the same word as the left-right vane and just above it.
    # This family spends two bits on it and counts them 0..3; the classic family puts it at the same
    # bit of the same word but spends three, with an enable bit above two level bits (0/5/6/7). The
    # caller keeps handing the classic codes -- that is what `std_enum` is for -- so nothing above
    # this line has to know which family it is talking to.
    #
    # Its upper bit is one the published map assigns to a neighbouring attribute, so this placement
    # rests on the device's own declaration rather than on the shared map; see the guard on offering
    # the control at all.
    "ecoMode": WriteField(4, 3, 2, "std_enum", std_to_epp={0: 0, 5: 1, 6: 2, 7: 3}),
    # Start-only self-clean trigger. This family writes with the same 6001 group command at zero
    # displacement, so the flag sits where the shared write frame puts it (w5.b4) — the same place a
    # live write confirmed on the classic family. Value is restricted to the start (1); the model
    # declares no OFF command, and its own modifiers (off / auto / sleep / fault) gate availability.
    "selfCleaningStatus": WriteField(5, 4, 1, "passthrough", max_epp=1),
    # The rest of the panel's frame-positioned control surface (offered per device, see the note on
    # `_FRAME_PANEL_WRITE`).
    **_FRAME_PANEL_WRITE,
}

# The "extended-36" family: a 36-word report (165 B) carrying the **classic** climate block displaced
# by 19 words. Those leading 19 words are a voice/media module (volume, playback, dialect, …) that the
# generic model describes but a plain split AC leaves inert — which is exactly why the classic
# partial decode misfires on this model: byte 92 is the module's `volume`, not the setpoint, so the
# setpoint reads as 48 C and power reads as off (haismart-local issue #5).
#
# Transcribed from the published models for `02012036` (挂机通用_V2D18S_0D05, wall mounted) and its
# floor-standing sibling `0301200n` (柜机通用_V2D18S_0D05) — the only two that imply a 165-byte
# report, and their field maps are identical, so keying this family on report length is unambiguous.
# Validated against the two distinct reports captured on a
# real HSU-12KCROC(IN)-R32 (issue #5): power off/on matched the stated states, the setpoint decoded to
# the 22 C the reporter had set, indoor read 30.0/27.5 C, and vertical swing matched fixed/swinging.
#
# Deliberately omitted from the READ: indoorHumidity and the air-quality attributes (this class of
# unit has no such probes and every capture read 0), and `specialMode`. `outdoorTemperature` IS read,
# but as a ``"temp"`` field — both captures report the 0 sentinel, which surfaces as "no reading"
# rather than a fabricated −64 C.
#
# **175 B is the same map with five words on the end** (haismart-local issue #8, a Malaysian
# HS-25VRB03). Every field above sits at the same word, and the unit's own published attribute values
# agree with what this map decodes out of its report on ten of them — setpoint, mode, fan speed,
# power, screen light, self-clean, both vane POSITIONS (vertical 2, horizontal 5) and indoor
# temperature to within the half degree the two readings were taken apart. So the longer report is
# this family, not a new one, and the extra words are additional registers rather than a displacement.
#
# What those five carry, from the same comparison: an input-power register at word 41 (`acInput`,
# watts) and the published map's cumulative counter at words 34+35, mirrored at 39+40 — the unit
# publishes `accumulatedUseMainsPower` and `totalElectricityUsed` with one identical value, and both
# wire pairs read that number.
#
# **The counter is in watt-hours**, settled against a unit whose owner captured it in known states
# and read its own app's energy page at the same moment. Three measurements, on three timescales:
#
#   * The register accumulates in fixed intervals rather than continuously — the model publishes the
#     interval as `energySavePeriod`, 15 minutes on this unit. One whole interval spent cooling
#     added 347, i.e. 1388 W held for 15 minutes, against the 1224..1432 W its own power register
#     read across that same quarter hour.
#   * A 26-minute session at a measured ~1190 W average added 478, against 494 expected.
#   * Between a capture at 00:53 and one at 12:07, on a day whose usage began after the first, it
#     added 7516 — and the app reported 7.52 kWh for that day.
#
# So one count is one watt-hour to within the precision of the comparison, three times over, and the
# entity is published. It reads absent while the register is zero, which is the state our own units
# and the 165-byte reports are in — those carry the register and never populate it.
EXTENDED36 = WireModel(
    family="extended36",
    # This family IS the published map, unmoved: all 12 of its mapped positions are reproduced by
    # the map at displacement 0, so a device's other declared attributes can be read off it too.
    canonical_displacement=0,
    report_lengths=frozenset({165, 175}),
    # The uPlusId of the 175-byte variant, which the units report on the discovery channel — so a
    # unit that answers it is keyed exactly rather than by length.
    uplus_ids=frozenset({
        "2008610800820324021200118018900000000000000000000000000000000040",
    }),
    writable=True,
    group_cmd=b"\x60\x01",
    word_count=5,
    write_base_word=20,     # report word 20 == group-set word 1 (19 words precede it: media, then a gap)
    write_fields=_EXT36_WRITE,
    position_fields=frozenset({"windDirectionVertical", "windDirectionHorizontal"}),
    fields={
        # the published map, undisplaced -- this family is where it starts
        **canonical_fields(0, [
            "power", "target_temperature", "current_temperature", "outdoor_temperature",
            "heat_capable", "error_code", "last_changed_by", "operation_mode", "wind_speed",
            "swing_vertical", "swing_horizontal", "self_cleaning",
            # The comfort settings this family offers as switches. They sit in the same word as the
            # power flag, at the positions the published map states, and a report from a unit with
            # boost on and another with sleep on carry exactly those two bits.
            "strong", "quiet", "health", "sleep", "lamp",
            # Cumulative energy, in watt-hours (see above). Absent on the units that leave the
            # register at zero, which includes every 165-byte report seen — that length reaches the
            # word, so it is the register being unpopulated rather than the field being off the end.
            "energy_wh",
        ]),
        # Live input power, on the units whose report runs to word 41 (the 175-byte variant; a
        # shorter report simply has no such word and the field reads absent). Watts: zero with the
        # unit off, 1432 at full cooling, and a thousand-odd while it holds a room -- and the unit
        # publishes an `acInput` of its own that agrees. This is a real measurement rather than the
        # figure the classic family derives from its current sensor.
        "power_w": WireField(41, 0, 16, kind="raw"),
    },
)

# --- extended-46 (209-byte report) --------------------------------------------------------------

# Control: words 20..24 — the whole settable block — are positioned exactly as on the extended-36
# family, so the group-set is that family's: command `6001`, five words, seeded from report word 20.
# What differs is only the setpoint's units (see below).
#
# `windSpeed` and the up-down vane ARE offered here. `windDirectionHorizontal` is not, and the
# reason is only that nothing in this family's report reads it back -- see the rule below.
#
# ★ Their WRITE positions are published, and are not in doubt. `Operation[grSetDAC].variants` is
# the write frame, and across every published air-conditioner device type (`02011`, `02012`,
# `0201201G`, `02012036`, `03012`, `0301200L`, `0301200n`) it is ONE frame -- 39 attributes,
# eppCmd `6001`, frameType 1, and **zero position disagreements between families**. It places
# `windDirectionVertical` at w1.b0/4, `windSpeed` at w2.b8/3 and `windDirectionHorizontal` at
# w4.b0/3, and the three positions this family confirmed on hardware (targetTemperature w1.b8,
# operationMode w2.b13, onOffStatus w3.b0) reproduce it exactly.
#
# ⚠️ The old reason -- "its vertical vane answers at a different word, so the position is not
# settled" -- conflated two different frames. A displacement in the REPORT says nothing about the
# group-set: the report inserts ten words at w25 on this family, the write frame displaces nowhere.
# That conflation is also why the vendor app can command one of these while misreading its sensors:
# it resolves a profile by **deviceType** (a prefix hierarchy -- the class model `02012` covers this
# whole class), and the class model's group-set needs no displacement at all.
#
# ★★ SETTLED, by one file that carries a report and a cloud record taken together. What had blocked
# these was a conflict with the READ map: `write_base_word + write_word - 1` is the report word a
# written bit reads back at, so the published write frame puts the vane at report w20, while this
# family's captures put it at w25. Both could not be right, and every capture then held read 0 at
# both, so nothing could choose. One could, and it had been on disc for a day:
#
#   | report                       | that same file's cloud record        |
#   | w20.b0 (map's vane)     = 0  | windDirectionVertical  = 2           |
#   | w25    (inserted block) = 2  | windDirectionVerticalL/R = 0 / 0     |
#   | w21.b8 (map's fan)      = 6  | windSpeed              = 1           |
#   | w26.b9 (inserted block) = 1  | windSpeedL/R           = 3 / 5       |
#
# That record is fresh, and provably so in its own file: its setpoint (22.0), indoor temperature
# (28.0), power and all six word-22 toggles agree with the report bit for bit. So the inserted
# block holds the APPLIANCE's vane and fan, and the map's own positions do not read them here.
#
# ⛔ It also falsifies the PER-TOWER explanation those two positions were withdrawn under -- using
# the very document that withdrew them. A per-tower register cannot read the appliance value: the
# towers are published in the same record as 3 / 5 and 0 / 0, and the wire reads 1 and 2.
#
# So the relation above holds on this family for words 1..3 as WORDS -- the setpoint, the mode and
# the whole boolean block land at report w20/w21/w22 -- and fails for exactly two bit-fields inside
# the first two of them. The five toggles keep their support regardless, having been confirmed 6/6
# against that fresh record rather than by arithmetic alone.
#
# ⚠️ What is NOT established is which way that failure runs: whether the appliance ignores those
# bits in the group-set, or accepts them and reports the result only in the inserted block. Only a
# write observes that, which is why these two ship as a control the reporter can now verify himself
# -- the readback is restored, so setting the fan from Home Assistant and watching w26.b9 follow is
# the whole test. `windDirectionHorizontal` stays out until this family reads one back.
# ★ The vane and fan positions here are the APPLIANCE's own, in the ten-word block this family
# inserts -- group-set words 6 and 7, i.e. report words 25 and 26 -- NOT the shared-frame positions
# at group-set w1/w2. That is settled from the vendor's own published data plus this family's
# captures, three lines converging (see `test_ext46_writes_the_appliance_vane_not_the_tower`):
#
#   1. the vendor's own `grSetDAC` order for this family (the 74-name `attrNameList`), packed by its
#      own word-ascending/bit-descending rule, puts `windDirectionVerticalL`/`R` and `windSpeedL` at
#      group-set w1.b0 / w1.b4 / w2.b8 -- the shared-frame vane/fan slots are the LEFT/RIGHT TOWERS
#      on a twin-tower cabinet, and the appliance's own vane/fan fall in the appended tail (word 6+);
#   2. the captures place the appliance's vane at report w25.b0 and its fan at report w26.b9
#      (`swing_vertical` / `wind_speed` in the read map), moving with the owner's stated swing/speed
#      while `windDirectionVerticalL/R` and `windSpeedL/R` held other values in the cloud record;
#   3. those two report words are exactly `write_base_word + write_word - 1` for group-set words 6
#      and 7 -- so retargeting here makes this family OBEY the write<->read relation every other
#      family obeys, rather than needing an exception for it.
#
# ⚠️ Until v0.47.x these wrote group-set w1.b0 / w2.b8 -- the LEFT TOWER's vane and fan -- and
# `word_count = 5` stopped the frame before word 6, so the appliance's own vane and fan could not be
# reached at all. That is corrected here. The one thing source cannot supply is a unit confirming it
# honours the 7-word frame (Rule 8); the read side is capture-confirmed at these positions and the
# relation holds, which is as far as no-hardware evidence reaches.
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
    # The appliance's own vane and fan, in the inserted block (group-set words 6/7 = report w25/w26).
    "windDirectionVertical": WriteField(6, 0, 4, "passthrough", max_epp=0x0C),
    "windSpeed": WriteField(7, 9, 3, "std_enum", std_to_epp={1: 1, 2: 2, 3: 3, 5: 5}),
    # The panel's frame-positioned control surface — same words as every grSetDAC family, in this
    # family's first five words (all ≤ w5, within word_count). Offered per device; the bit-reuse
    # guard keeps a family that puts a different attribute at one of these positions from writing it.
    **_FRAME_PANEL_WRITE,
}

# The "extended-46" family: a 58-word report (209 B) that is the **extended-36 layout with a ten-word
# block inserted around word 25**. The climate block at words 20..22 sits exactly where extended-36
# puts it, and every attribute from extended-36's word 25 upward is found ten words later. The
# inserted block was taken for a dual-airflow cabinet's second set of fan and vane attributes, which
# these units' device models do declare; a single-flow unit leaves most of it at zero.
#
# ⚠️ That reading is WRONG for the two words we read from it. The block's w25 and w26 carry the
# APPLIANCE's vane and fan, not a tower's: on a report whose cloud record was fresh, they read 2 and
# 1, while the same record published `windDirectionVerticalL`/`R` as 0 / 0 and `windSpeedL`/`R` as
# 3 / 5. Whatever the other eight words are, those two are not per-tower.
#
# ⚠️ **Where the block BEGINS is not pinned, and it matters for anything read from words 23..24.**
# The captures confirm w20/w21/w22 unmoved, w35/w36 at +10, and a vane at w25 with the fan speed at
# w26.b9 inside the block — so it starts after w22 and at or before w25, i.e. at w23, w24 or w25.
# Every one of those predicts indoor temperature at w35, so that cannot separate them, and w23, w24,
# w33 and w34 all read zero in every capture. Anything mapped into that gap would be a guess: the
# flag word carrying `selfCleaningStatus` lands at report w24 under one reading and w34 under the
# other two, which is why this family gets no self-clean field. A single capture with any flag-word
# feature switched on (health, ambient light, fresh air) pins it.
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
# Deliberately omitted from the READ: horizontal swing, and the air-quality/humidity attributes.
# `windSpeed` WAS omitted, on the grounds that this family reports a code its own device model does
# not declare — true of the map's position (a constant 6) and not of the appliance, which answers at
# w26.b9 with codes its model does declare. See the field below.
# Also left out: the cumulative-energy register at words 44+45, which works on this family (unlike
# the classic one, where it reads zero). The register is now known to count watt-hours on
# extended-36, and it is the same published attribute here — but this is the one family that has
# been caught departing from the published map three times over, and its counter's position is
# itself derived from the inserted block. Inheriting an unverified unit into somebody's energy
# history is not a thing to do on the strength of a map this family already disagrees with. One
# reading off the owner's app, against a capture, settles it the same way it was settled there.
# This family is NOT built from the published map, and deliberately: its vane sits five words past
# where the map puts it, its setpoint counts half degrees rather than whole degrees offset by 16,
# and its fan speed answers from the inserted block. Written out, those read as what they are —
# a family with three exceptions — where a displacement plus three overrides would read as a rule
# with more exceptions than rule.
_EXT46_PIVOT = 25
_EXT46_INSERT_WORDS = 10


def _ext46_word(word: int) -> int:
    """Where a published map word lands in the 209-byte report: the map, ten words inserted at 25.

    Kept beside the model because the fields are built while the model is being constructed. A test
    asserts it agrees with ``EXTENDED46.canonical_word`` for every word, so the pivot cannot be
    stated twice and drift.
    """
    return word + (_EXT46_INSERT_WORDS if word >= _EXT46_PIVOT else 0)


EXTENDED46 = WireModel(
    family="extended46",
    report_lengths=frozenset({209}),
    # Keyed exactly as well as by length: the uPlusId is reported by the units themselves on the
    # discovery channel, so it is available without cloud credentials.
    uplus_ids=frozenset({"2008610800820324021200118017740000000000000000000000000000000040"}),
    writable=True,
    group_cmd=b"\x60\x01",
    # Seven words, not five: the appliance's own vane and fan live in the inserted block at group-set
    # words 6 and 7 (report w25/w26), so the frame has to reach them. The extra two words are seeded
    # from the live report like the rest (read-modify-write), so nothing else in them is disturbed.
    word_count=7,
    write_base_word=20,     # report word 20 == group-set word 1, as on extended-36
    write_fields=_EXT46_WRITE,
    canonical_displacement=0,
    # Ten words inserted at w25, which no bundled model describes. Two of them are read explicitly
    # below -- the appliance's own vane and fan, which answer here rather than where the map puts
    # them -- and everything else is taken from the map either side of the pivot.
    canonical_insert=(_EXT46_PIVOT, _EXT46_INSERT_WORDS),
    fields={
        # Everything the published map describes, placed by the pivot: words below 25 where the map
        # puts them, words from 25 up pushed along by the insert. Written out as a derivation rather
        # than as a table, because the table was the bug: eleven fields were typed in, five that the
        # map already placed were left out, and the switches for those five were offered and then
        # sat unavailable for want of anything to read.
        **canonical_fields(_ext46_word, [
            "target_temperature", "operation_mode", "power",
            "health", "strong", "quiet", "sleep", "lamp",
            "current_temperature", "outdoor_temperature", "heat_capable",
            "error_code", "last_changed_by", "energy_wh",
        ]),
        # The five secondary toggles, which this family could WRITE and never read back -- so the
        # switches were offered and then sat unavailable forever, having no state to show. The same
        # defect extended-36 had, and the audit that was owed after it finally run across every
        # family.
        #
        # Position is not inferred from a resemblance: the group-set frame IS a slice of the report
        # beginning at `write_base_word`, so a written bit's report word is `write_base_word +
        # write_word - 1`. That correspondence is already load-bearing here for three fields whose
        # report positions were established independently -- targetTemperature (write w1 b8 ->
        # report w20 b8), operationMode (w2 b13 -> w21 b13) and onOffStatus (w3 b0 -> w22 b0) -- and
        # it places all five of these in write word 3, alongside the power bit, at report word 22.
        #
        # Confirmed against the appliance's own cloud record rather than left as arithmetic: on a
        # report from a running unit, all six bits of that word agree with what the manufacturer
        # separately reported for the same attributes, including the two that were set.
        # ⚠️ A measured departure from the map, not an oversight. The map encodes a setpoint the
        # classic way -- degrees above 16 -- and this family sends HALF-DEGREES FROM ZERO. Taking
        # the scaling from the map would read 24 °C as 40 °C, on a field whose position the map
        # gets right. Position from the map, scaling from a reading: the same rule that applies to
        # meaning applies here, and this is why the generation is field-wise rather than wholesale.
        "target_temperature": WireField(_ext46_word(20), 8, 8, kind="int", k=0.5, c=0.0),
        # The two fields the published map cannot place HERE, though it names them both: they answer
        # from the inserted block, not from the words the map assigns them. Established from
        # captures taken in stated states on one appliance, and confirmed on a second against a
        # cloud record fresh enough to agree with its own file on everything else.
        #
        # The vane: 0x0C with the owner's swing switched on, a parked position (2) where the record
        # said 2, zero where the unit was off. The map's own w20.b0 reads 0 through all of it.
        "swing_vertical": WireField(25, 0, 4, kind="vane_v"),
        # ★ Fan speed, restored -- and this is the third decision about it, so the evidence is in
        # the tests on both sides rather than only the winning one.
        #
        # Word 21 bit 8, where every other family keeps it, reads a CONSTANT 6 in all seven captures
        # held from two different appliances -- including between one owner's stated high and stated
        # low. Whatever that is, it is not this appliance's fan.
        #
        # Word 26 bit 9 reads 1 where a capture was taken on high, 3 where taken on low, 0 with the
        # unit off, and 1 where a fresh cloud record for that same report said windSpeed was 1.
        #
        # It was withdrawn once on a fourth capture that read 0 here while "the appliance's own
        # cloud record said 1". That record was STALE -- the same frozen document as the file
        # before it, and its setpoint disagreed with the report it was compared against (22.0 vs
        # 24.0) in that very file. The freshness test used ("agreed with 53 attributes, disagreed
        # with none") runs over `model_declared_fields`, which holds only inert attributes -- the
        # voice module, probes this unit does not have, tempUnit -- so it agrees by construction and
        # can never detect staleness. See `test_the_209_family_reads_its_fan_speed`.
        #
        # `enum` and not `raw`: an unlisted code yields NO reading. So the idle-unit 0 and the
        # constant 6 both surface as absence, never as an invented speed.
        "wind_speed": WireField(26, 9, 3, kind="enum", enum=_EXT36_FAN),
        # Cumulative energy in watt-hours, 32 bits whose low half sits at word 45 and high half at
        # word 44 -- the published map states this register one word past the indoor temperature,
        # and both anchors land ten words later on this family, which puts it exactly here.
        #
        # Confirmed against the appliance's own cloud record rather than inferred: a report reading
        # 777,385 was taken minutes after that record showed 773,862 for the same register, the wire
        # figure being the newer of the two. Nothing else in the report is within three orders of
        # magnitude of either number. The unit is watt-hours, as measured on extended-36 against an
        # owner's own energy page.
        #
        # Absent when it reads zero, like every counter here: most of these appliances carry the
        # register and never populate it, and a permanent 0 kWh in someone's energy history is worse
        # than no sensor at all.
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
    # The map 19 words earlier, and confirmed as such: displaced -19 it reproduces all 9 of this
    # family's mapped positions, and decodes a real 125-byte report in agreement with the classic
    # decoder on every field the two share.
    canonical_displacement=-19,
    report_lengths=frozenset(),
    fields=canonical_fields(-19, [
        "power", "target_temperature", "current_temperature", "outdoor_temperature",
        "heat_capable", "error_code", "last_changed_by", "operation_mode", "wind_speed",
        "swing_vertical",
    ]),
    # The 127-byte member (the rental SKU) carries one word the map does not describe --
    # `targetRentTime`, its report word 6 -- so canonical words 25 and up sit one further along than
    # the flat -19 says. Confirmed three ways against that layout's hardware-verified offsets:
    # indoorTemperature w25 lands at byte 104 (= STATUS_LAYOUTS[127].indoor_temp), outdoorTemperature
    # w26 at byte 106, and the 32-bit energy counter's low word (w35) at byte 124 -- each of which
    # the flat map misses by exactly one word. Without this, every declared attribute above the flag
    # word (humidity, the air-quality suite) read one word early on 127-byte reports.
    length_inserts={127: (25, 1)},
)

# The probe list. The classic and extended families are one map at two displacements, so the search
# over displacements covers both from either entry; compact-12 is a genuinely different packing and
# has to be its own candidate.
PROBE_FAMILIES: tuple[WireModel, ...] = (EXTENDED46, EXTENDED36, COMPACT12, _CLASSIC_PROBE)

# How the prober weighs each piece of agreement. Sensor plausibility is worth less than agreeing with
# a value the device itself reported through another channel, because plausibility is cheap to hit by
# chance in a report that is mostly zeros. A stated state is worth as much: someone set the unit that
# way and wrote it down, which is evidence of the same kind — and unlike the shadow, it needs no
# cloud. A contradiction costs more than agreement earns, because a report that is mostly zeros can
# agree by accident but rarely disagrees by accident.
_SCORE_SHADOW_MATCH = 4
_SCORE_STATED_MATCH = 4
_SCORE_STATED_MISS = -6
_SCORE_ORDER_MATCH = 1
# A contradiction costs far more than an agreement earns: consecutive settings agreeing is the
# default even for a wrong map, while a swap is the device saying outright that this is not it.
_SCORE_ORDER_MISS = -8
_SCORE_ENUM_KNOWN = 2
_SCORE_SENSOR_PLAUSIBLE = 1

# How close a decoded room temperature must be to the one someone read off the handset. Wide enough
# for a different sensor in a different part of the room and some minutes between the two readings.
_STATED_INDOOR_TOLERANCE_C = 2.0

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


@dataclass(frozen=True)
class StatedState:
    """What a capture was known to be in, as the person who took it described it.

    This is the ground truth a new-model report already collects and nothing used: three captures in
    stated states plus the room temperature from the handset. It is worth as much as the device's own
    cloud shadow and costs nothing to obtain, which is what takes the cloud off the critical path for
    adding a model.

    Every field is optional; only what was stated is scored.

    ``mode_group`` and ``fan_group`` are how a state gets used without knowing the model's codes,
    which is the whole difficulty — a reporter says "cool" and "fan-only", not "1" and "6". Give the
    captures opaque labels instead: captures with *different* labels must decode to different codes,
    captures sharing one must decode to the same. A map that lands on an empty word reads the same
    code in every state and fails that immediately, which is exactly the failure the prober exists
    to catch.
    """

    power: bool | None = None
    target_temperature: float | None = None
    current_temperature: float | None = None      # as read off the handset, ±2 °C
    swing_vertical: bool | None = None
    mode_group: str | None = None
    fan_group: str | None = None


def _score_stated(decoded: Sequence[dict], stated: Sequence[StatedState | None]) -> int:
    """Score decoded reports against the states they were captured in."""
    score = 0
    for got, want in zip(decoded, stated, strict=False):
        if want is None:
            continue
        for key in ("power", "swing_vertical"):
            expected, actual = getattr(want, key), got.get(key)
            if expected is None or actual is None:
                continue
            score += _SCORE_STATED_MATCH if bool(actual) is expected else _SCORE_STATED_MISS
        for key, tolerance in (
            ("target_temperature", 0.51), ("current_temperature", _STATED_INDOOR_TOLERANCE_C)
        ):
            expected, actual = getattr(want, key), got.get(key)
            if expected is None or actual is None:
                continue
            score += (
                _SCORE_STATED_MATCH if abs(float(actual) - float(expected)) <= tolerance
                else _SCORE_STATED_MISS
            )
    # The relational half: same label => same code, different labels => different codes.
    for attr, key in (("mode_group", "operation_mode"), ("fan_group", "wind_speed")):
        labelled = [
            (getattr(want, attr), got.get(key))
            for got, want in zip(decoded, stated, strict=False)
            if want is not None and getattr(want, attr) is not None and got.get(key) is not None
        ]
        for i, (label, code) in enumerate(labelled):
            for other_label, other_code in labelled[i + 1:]:
                agrees = (str(code) == str(other_code)) is (label == other_label)
                score += _SCORE_STATED_MATCH if agrees else _SCORE_STATED_MISS
    return score


def _score_order(model: WireModel, order: Sequence[str]) -> int:
    """Score a candidate against the order the device declares its settings in.

    What this catches is a **family** whose map arranges its settings differently — extended-46 puts
    a vane five words on and its fan speed inside an inserted block, and compact-12 is not this
    lineage at all. Against a real declaration both are refused outright, every candidate of them,
    while every classic and extended-36 candidate passes.

    What it does NOT catch is a wrong displacement, and the reason is worth stating so nobody
    expects more of it: the search only ever moves fields *later*, so a pivot and a positive shift
    preserve an ascending order whatever they are. Order prunes the family branch; the offset still
    has to come from the reports and the states they were captured in.
    """
    ranks = {name: i for i, name in enumerate(order)}
    placed = sorted(
        (ranks[name], f.word, -f.bit)
        for key, f in model.fields.items()
        if (name := _CLIMATE_SPEC.get(key, (None,))[0]) in ranks
    )
    score = 0
    for (_, word, bit), (_, next_word, next_bit) in zip(placed, placed[1:], strict=False):
        agrees = (word, bit) <= (next_word, next_bit)
        score += _SCORE_ORDER_MATCH if agrees else _SCORE_ORDER_MISS
    return score


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
    stated: Sequence[StatedState | None] | None = None,
    order: Sequence[str] | None = None,
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
    * **``order``** — the settings the device declares its group-set carries, in wire order, from
      :func:`~haismart_hrdp.declared_order`. It cannot place anything on its own: displacing every
      field alike preserves the order exactly, so it says nothing about *where* a block starts. What
      it does is reject a **family** that arranges its settings differently: on a real declaration
      it rules out every extended-46 and compact-12 candidate — **375 of 800** — before any of them
      is decoded, and passes every classic and extended-36 one. It prunes the family branch, not the
      offset: the search only moves fields later, so no pivot or shift can violate an ascending
      order. It therefore adds to the stated states rather than replacing them.
    * **``stated``** — what each capture was known to be in, one :class:`StatedState` per report (or
      ``None`` for a capture nobody described). This is the ground truth a new-model report already
      collects: three captures in stated states, plus the room temperature off the handset. It is
      worth as much as the shadow and needs no cloud, so a model can be added from the captures
      alone. Contradicting a stated state costs more than matching one earns.

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
                    # The per-report scores answer "is each of these plausible on its own"; the
                    # stated states answer "do they agree with what the unit was actually doing",
                    # which is a judgement over the set and so is added once.
                    score = min(scores)
                    if stated:
                        score += _score_stated(decodes, stated)
                    if order:
                        score += _score_order(candidate, order)
                    out.append(
                        {
                            "family": model.family,
                            "pivot": pivot,
                            "shift": shift,
                            "setpoint": encoding[0],
                            "score": score,
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


# The climate attributes a related-model layout is built from. Deliberately the core block and not
# everything the map states: these are the fields the plausibility check below can actually judge,
# and the ones a thermostat needs. Anything further would be placed on the strength of the
# relationship alone, which is what `canonical_displacement` exists to refuse.
_RELATED_KEYS: tuple[str, ...] = (
    "power", "target_temperature", "current_temperature", "outdoor_temperature",
    "heat_capable", "error_code", "last_changed_by", "operation_mode", "wind_speed",
    "swing_vertical",
)

#: How much of an identifier two models must share before one is treated as the other's relative.
#: The published models that are genuinely the same specification share far more than this; the
#: leading characters below it are a product class, which is explicitly not a layout.
_RELATED_PREFIX_MIN = 20


def displacement_candidates(uplus_id: str | None) -> tuple[int, ...]:
    """Displacements used by the published models most closely related to ``uplus_id``.

    A device announces an identifier whose leading characters it shares with its relatives -- the
    same specification, a revision apart -- and every published air conditioner is the one map at a
    whole-word offset. So the models sharing the longest prefix with an unfamiliar device name the
    offsets its report is likely to use.

    Returns them ordered and without duplicates, empty when nothing shares a meaningful prefix. It
    is a shortlist and nothing more: in practice the closest relatives of a given device disagree,
    one carrying the leading media block and one not, so the answer is normally two candidates and
    the report itself has to choose between them.
    """
    if not uplus_id:
        return ()
    best = 0
    ranked: dict[int, int] = {}
    for profile, disp in PROFILE_DISPLACEMENTS.items():
        shared = 0
        # strict=False on purpose: identifiers are compared only as far as the shorter runs, and a
        # truncated one sharing everything it has is still a relative.
        for a, b in zip(uplus_id, profile, strict=False):
            if a != b:
                break
            shared += 1
        if shared < _RELATED_PREFIX_MIN or shared < best:
            continue
        if shared > best:
            best, ranked = shared, {}
        ranked.setdefault(disp, shared)
    return tuple(ranked)


# How each field of the published group-set frame is packed. Positions come from
# :data:`~haismart_hrdp.canonical_map.CANONICAL_WRITE`, which is the frame itself; what lives here is
# only what the frame does not state -- how a caller's classic-shaped value becomes the wire value,
# and the ranges narrower than the bit width. These are the same kinds the two hardware-confirmed
# families use, and the frame does not displace between families, so they are family-independent.
#
# Deliberately a SUBSET of the frame's 39 attributes: these are the settings this project has a
# control for. An attribute nobody can command is not made writable merely because it is positioned.
_FRAME_WRITE_SPEC: Mapping[str, Mapping[str, object]] = {
    "targetTemperature": {"kind": "passthrough", "min_epp": 0, "max_epp": 14},   # 16..30 C
    "windDirectionVertical": {"kind": "passthrough", "max_epp": 0x0C},
    "operationMode": {"kind": "std_enum", "std_to_epp": {0: 0, 1: 1, 2: 2, 4: 4, 6: 6}},
    "windSpeed": {"kind": "std_enum", "std_to_epp": {1: 1, 2: 2, 3: 3, 5: 5}},
    "onOffStatus": {"kind": "passthrough", "max_epp": 1},
    "healthMode": {"kind": "passthrough", "max_epp": 1},
    "rapidMode": {"kind": "passthrough", "max_epp": 1},
    "muteStatus": {"kind": "passthrough", "max_epp": 1},
    "silentSleepStatus": {"kind": "passthrough", "max_epp": 1},
    "screenDisplayStatus": {"kind": "passthrough", "max_epp": 1},
    "windDirectionHorizontal": {"kind": "passthrough", "max_epp": 0x07},
    "selfCleaningStatus": {"kind": "passthrough", "max_epp": 1},
    # The panel's frame-positioned control surface, so a related layout offers the same controls a
    # registered grSetDAC family does (still gated by the product's own group-set order and the
    # bit-reuse guard, below). Bools 0/1; the two enums their raw 0..3.
    **{
        name: {"kind": "passthrough",
               "max_epp": (1 if name in PANEL_BOOL_CONTROLS
                           else (1 << CANONICAL_WRITE[name].length) - 1)}
        for name in (*PANEL_BOOL_CONTROLS, *PANEL_ENUM_CONTROLS)
        if name in CANONICAL_WRITE
    },
    **{name: {"kind": "passthrough", "max_epp": 1} for name in PANEL_EXTRA_POSITIONS},
}


def frame_write_fields(
    order: Sequence[str] | None, uplus_id: str | None = None
) -> dict[str, WriteField]:
    """The group-set fields a product can be commanded on, from the frame it publishes.

    Four gates, and each removes a different way of being wrong:

    * **the frame** -- a field is packed where `CANONICAL_WRITE` says, which is one frame across
      every published air-conditioner device type with no displacement between families;
    * **the product's own group-set list** (``order``) -- a setting this product does not carry is
      not offered, so nothing is written into a word its appliance uses for something else;
    * **:func:`~haismart_hrdp.family_write.displaced_write_fields`** -- a handful of families keep a
      *different attribute* at one of the frame's positions (a twin-tower cabinet's left-hand vane
      and fan, and sterilization where the frame puts self-clean). Those are refused outright: a
      group-set is packed by position, so the wrong function would run rather than the write failing;
    * **:func:`~haismart_hrdp.wire_order.consistent_with_frame`** -- the order is positional (word
      ascending, bit descending), so it can also contradict the frame for an attribute under its
      *own name*: every twin-tower family lists the appliance's vane, fan and horizontal vane in
      its appended tail, past the words the shared frame reaches, which the reuse table cannot see
      because nothing else was ever placed at those slots. A field the product's own order places
      elsewhere is not offered; an order the frame cannot be reconciled with at all offers nothing.

    Returns ``{}`` when ``order`` is unknown, which keeps a layout read-only rather than commanding
    an appliance whose own published contract has not been seen.
    """
    from .family_write import ALIASES, displaced_write_fields
    from .wire_order import consistent_with_frame

    if not order:
        return {}
    refused = displaced_write_fields(uplus_id)
    spelled_as = dict(ALIASES) | {v: k for k, v in ALIASES.items()}

    def position(name: str) -> tuple[int, int, int] | None:
        cf = CANONICAL_WRITE.get(name) or CANONICAL_WRITE.get(spelled_as.get(name, ""))
        if cf is not None:
            return (cf.word, cf.bit, cf.length)
        return PANEL_EXTRA_POSITIONS.get(name) or PANEL_EXTRA_POSITIONS.get(
            spelled_as.get(name, "")
        )

    known = {}
    for name in order:
        pos = position(name)
        if pos is not None:
            known[name] = pos[:2]
    corroborated = consistent_with_frame(order, known)
    if corroborated is None:
        return {}

    carried = set(order)
    out: dict[str, WriteField] = {}
    for name, spec in _FRAME_WRITE_SPEC.items():
        spelled = name if name in carried else spelled_as.get(name, name)
        if name in refused or spelled not in carried:
            continue
        if spelled in known and spelled not in corroborated:
            continue
        pos = position(name)
        if pos is None:
            continue
        out[name] = WriteField(*pos, **spec)  # type: ignore[arg-type]
    return out


def related_wire_model(
    length: int,
    displacement: int,
    *,
    order: Sequence[str] | None = None,
    uplus_id: str | None = None,
) -> WireModel:
    """A layout for reports of ``length``, taken from the published map at ``displacement``.

    **Control is offered when the appliance's own group-set list is known**, and not otherwise. That
    is a change from the original read-only rule, and the reason it is safe now is that the two
    things the old rule was waiting for have both been established from published data rather than
    from a capture:

    * the group-set frame is **one frame** across every published air-conditioner device type -- same
      attributes, same words, same bits, and **no displacement between families**; and
    * the report word the frame's first word lands on is **``20 + displacement``** -- the climate
      block begins at map word 20 and the group-set is those words lifted out, so the base word is
      the definition restated rather than a constant anyone fitted. Checked against all three
      hardware-confirmed families and exact each time.

    The displacement itself is not assumed: it is whichever candidate the report agreed with, which
    is the same evidence the read path already required before publishing a single value.

    ``canonical_displacement`` stays unset regardless -- that gates the *further* attributes a device
    declares, which rest on the offset being checked field-for-field against a real report, and this
    one has only been checked against the core block.
    """
    write = frame_write_fields(order, uplus_id)
    return WireModel(
        family=f"related{displacement:+d}",
        report_lengths=frozenset({length}),
        fields=canonical_fields(displacement, list(_RELATED_KEYS)),
        writable=bool(write),
        group_cmd=b"\x60\x01" if write else None,
        word_count=5 if write else 0,
        write_base_word=20 + displacement,
        write_fields=write,
        position_fields=frozenset(
            {"windDirectionVertical", "windDirectionHorizontal"} & set(write)
        ),
    )


def related_wire_models(
    length: int,
    uplus_id: str | None,
    *,
    order: Sequence[str] | None = None,
) -> tuple[WireModel, ...]:
    """Candidate layouts for a report no registered family claims, best-related first."""
    return tuple(
        related_wire_model(length, d, order=order, uplus_id=uplus_id)
        for d in displacement_candidates(uplus_id)
    )


#: What a related layout must actually produce before it is believed. The plausibility check alone
#: cannot do this job: the candidate that is wrong by nineteen words reads *past the end* of a
#: shorter report, so every field comes back absent, and a decode holding no readings at all passes
#: a check on the readings it does not have. Absence is not agreement -- so require the block a
#: thermostat is made of to be present before the layout counts as identified.
_RELATED_REQUIRED = ("power", "target_temperature", "current_temperature")


def related_model_named(
    family: str,
    length: int,
    *,
    order: Sequence[str] | None = None,
    uplus_id: str | None = None,
) -> WireModel | None:
    """Rebuild the related layout a decode reported, by the name it put in ``layout``.

    :func:`decode_related` picks a displacement by trying each candidate and keeping the one the
    report agreed with, and it returns that choice only as a name (``related-19``). A caller that
    needs the *model* -- to know which settings it may command, and to pack them -- would otherwise
    have to repeat the search. Parsing the name back is exact: it is generated from the displacement
    and nothing else.

    ``None`` for any name that is not one of ours, so an unrecognised layout cannot become writable.
    """
    if not family.startswith("related"):
        return None
    try:
        displacement = int(family[len("related"):])
    except ValueError:
        return None
    return related_wire_model(length, displacement, order=order, uplus_id=uplus_id)


def decode_related(
    data: bytes,
    uplus_id: str | None,
    profile=None,
    *,
    order: Sequence[str] | None = None,
) -> dict | None:
    """Decode ``data`` with the layout of the closest published relative that the report agrees with.

    Tries each candidate offset in turn and keeps the first that both places the core readings and
    finds them plausible. ``None`` when no relative fits, which leaves the caller on the partial
    decode it would have used anyway -- an unfamiliar appliance is never made worse off by this.
    """
    for wm in related_wire_models(len(data), uplus_id, order=order):
        decoded = wm.decode(data, profile)
        if decoded is not None and all(k in decoded for k in _RELATED_REQUIRED):
            return decoded
    return None


def device_type_class(uplus_id: str | None) -> str | None:
    """The five-character device-type class a uPlusId belongs to, or ``None``.

    A device type is written either as five characters (a whole product class -- split air
    conditioners, cabinet air conditioners, and so on) or as eight (one particular product). The
    class half is carried in the uPlusId and can be read straight out of it:

        class = uplus_id[16:18] + "0" + uplus_id[18:20]

    e.g. ``…0324` `0212` `0011801…`` -> ``02012``. This holds for every published model that states
    a device type, bar one that declares a placeholder.

    ⚠️ The remaining three characters of an eight-character device type are **not** in the uPlusId,
    so a device's specific identity cannot be computed from it -- only looked up. And a class is
    **not** a layout: devices sharing one class are known to report in different wire families, so
    this must never be used to choose a decoder. It is an identifier, for reporting and lookup.
    """
    if not uplus_id or len(uplus_id) < 20:
        return None
    head = uplus_id[16:20]
    if not head.isalnum():
        return None
    return f"{head[:2]}0{head[2:]}".lower()
