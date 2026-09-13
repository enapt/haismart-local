"""The manufacturer's own byte map, per typeid — a decoder that needs no per-family code.

Every Haier appliance packs its status attributes into a bit-field array of 16-bit big-endian words
beginning at byte 92 of the decrypted report. Where each attribute sits is published, per device
class, in Haier's own EPP ``configFile``; :mod:`haismart_hrdp.wire_models` derives that map by hand
for the AC families this project has captured, and this module reads it from the file instead.

Why it exists
-------------
Hand-derivation is what limited the integration to air conditioners. The published map is the same
map: a decoder reading only ``startWord``/``startBit``/``length``/``caeType``/``variants``
reproduces the shipped decoder field for field on the classic/ext-36 family and on the ``0d12``
cabinets, **and** decodes classes this project has never captured — 144/144 attribute comparisons
over 12 stored captures, 3 device classes and 3 report lengths
(``tools/re/configfile_decode.py --selftest`` in the development tree).

What makes it safe to use where length-keying is not
----------------------------------------------------
:class:`~haismart_hrdp.wire_models.WireModel` guesses a family from a report's LENGTH and therefore
needs plausibility vetoes to catch a collision. A :class:`DeviceModel` is selected by **exact
typeid** — the 64-hex uPlusId the appliance itself announces on the key-free discovery channel — so
there is nothing to guess and no veto to get wrong. A typeid that is not in the bundle decodes
nothing at all, which is the safe direction.

What it deliberately does NOT do
--------------------------------
It reads positions and applies ``variants``. It does not apply the absent-probe rule
(:func:`absent_probe`, offered separately and applied by the caller), any declaration gate — only
attributes a device's OWN model declares should become entities, else they are phantom — or any
write encoding. Keeping those out means what it reproduces is attributable to the manufacturer's
file rather than to policy borrowed from the AC path.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = [
    "ATTR_BASE",
    "DeviceModel",
    "ModelField",
    "absent_probe",
    "device_classes",
    "known_typeids",
    "model_for",
    "preload",
    "read_field",
    "MODELS_PATH",
]

MODELS_PATH = Path(__file__).with_name("device_models.json.gz")

# Shared with uss.py and wire_models.py: word N (1-based) starts at byte 92 + 2*(N-1), big-endian.
ATTR_BASE = 92

# The status commands a report can carry. 6D01 is getAllProperty; 7D01 the extended/telemetry frame.
STATUS_ALL = "6D01"
STATUS_BIGDATA = "7D01"

# ``caeType`` is what ``variants`` MEANS. Enumerated over all 20,224 carried fields of the 164
# bundled typeids, every field falls in exactly one row and none is left over:
#
#   1, 6   -> variants {k, c}                         raw * k + c
#   2      -> variants [{stdValue, eppValue}]         enum lookup, drop an unnamed raw value
#   3      -> variants [2 x {startWord,startBit,len}] composite time  HH:MM
#   4      -> variants [3 x ...]                      composite time  HH:MM:SS
#   5      -> variants [3 x ...]                      composite date
#   13     -> variants null or []                     opaque string (uniqueId, token, clientId, ...)
#
# ⚠️ Only caeType 3 is confirmed against ground truth — the cloud mirror reports "22:11" where the
# two parts read 22 and 11 (issue #13's captures). 4 and 5 are rendered the same way BY CONSTRUCTION
# and no capture in the corpus carries one with a published value beside it. Treat a caeType 4/5
# value as unverified on first contact with a new class.
_COMPOSITE_TYPES = frozenset({3, 4, 5})
_OPAQUE_TYPES = frozenset({13})

# The raw values a unit reports for a probe it does not have (``uss._sensor_temp``'s sentinels).
_SENSOR_SENTINELS = (0x00, 0xFF)
# ⛔ There is deliberately no global plausibility band here. ``uss._PLAUSIBLE_TEMP_C`` is
# (-30, 70) C, which is right for an air conditioner and WRONG the moment the appliance is not one:
# it rejects issue #13's 75 C reservation temperature as implausible, and a water heater's own map
# declares 30-80. The manufacturer states per-field bounds, so those are used instead of a constant.
_CELSIUS = "\u2103"


def read_field(data: bytes, word: int, bit: int, length: int) -> int | None:
    """The integer at ``(word, bit, length)``, or ``None`` if it falls outside ``data``.

    ``(word, bit)`` locates the field's LEAST-significant bit and significance grows **backwards**
    through the array — the convention :class:`haismart_hrdp.wire_models.WireField` documents and
    the published maps are written in.
    """
    value = 0
    for index in range(length):
        source_word, source_bit = word, bit + index
        while source_bit > 15:
            source_bit -= 16
            source_word -= 1
        offset = ATTR_BASE + 2 * (source_word - 1)
        if source_word < 1 or offset + 1 >= len(data):
            return None
        if ((data[offset] << 8 | data[offset + 1]) >> source_bit) & 1:
            value |= 1 << index
    return value


@dataclass(frozen=True)
class ModelField:
    """One attribute's published position and how to turn its raw bits into a value."""

    name: str
    word: int
    bit: int
    length: int
    cae_type: int | None
    status_cmd: str | None
    epp_cmd: str | None          # the `5Dxx`/`4Dxx` single-parameter write id, where one is published
    writable: bool
    data_type: str | None        # bool / int / double / string
    variants: Any

    @property
    def unit(self) -> str | None:
        """The unit the manufacturer states for a scaled field (``℃``, ``L``, ``%``, …)."""
        return self.variants.get("unit") if isinstance(self.variants, dict) else None

    @property
    def is_enum(self) -> bool:
        return bool(isinstance(self.variants, list) and self.variants
                    and "eppValue" in self.variants[0])

    @property
    def is_composite(self) -> bool:
        return self.cae_type in _COMPOSITE_TYPES

    def bounds(self) -> tuple[float, float] | None:
        """The class-wide ``(min, max)`` for a scaled field.

        ⚠️ Class-wide. A device's OWN model usually narrows it — issue #13's water heater declares
        35–75 °C where its class map says 30–80 — so prefer the device model where there is one.
        """
        if isinstance(self.variants, dict) and "minValue" in self.variants:
            return float(self.variants["minValue"]), float(self.variants["maxValue"])
        return None

    def read(self, data: bytes) -> Any:
        """This field's published value in ``data``, or ``None`` if it cannot be read."""
        raw = read_field(data, self.word, self.bit, self.length)
        if raw is None:
            return None
        return self.interpret(raw, data)

    def encode(self, value: Any) -> int:
        """The raw wire value for a published ``value`` — the inverse of :meth:`interpret`.

        Refuses anything the manufacturer's map does not name, because control may only ever emit a
        mapped attribute with a supported value. That guard is the same one the group-set encoder
        applies and it exists for the same reason: a value the appliance does not recognise is at
        best discarded and at worst lands in a neighbouring field.
        """
        if self.is_composite or self.cae_type in _OPAQUE_TYPES:
            raise ValueError(f"{self.name}: a {self.data_type} field is not written this way")
        if self.is_enum:
            for entry in self.variants:
                if entry.get("stdValue") == value or str(entry.get("stdValue")) == str(value):
                    return int(entry["eppValue"])
            raise ValueError(f"{self.name}: {value!r} is not a value this attribute publishes")
        if isinstance(self.variants, dict) and ("k" in self.variants or "c" in self.variants):
            bounds = self.bounds()
            numeric = float(value)
            if bounds is not None and not bounds[0] <= numeric <= bounds[1]:
                raise ValueError(
                    f"{self.name}: {value!r} is outside the published range "
                    f"{bounds[0]}..{bounds[1]}"
                )
            scale = float(self.variants.get("k", 1) or 1)
            raw = round((numeric - float(self.variants.get("c", 0))) / scale)
        else:
            raw = int(value)
        if not 0 <= raw < (1 << self.length):
            raise ValueError(f"{self.name}: {value!r} does not fit the field's {self.length} bits")
        return raw

    def interpret(self, raw: int, data: bytes | None = None) -> Any:
        """Apply ``variants`` to a raw field value, per the ``caeType`` table above."""
        if self.cae_type in _OPAQUE_TYPES:
            return None
        if isinstance(self.variants, dict) and ("k" in self.variants or "c" in self.variants):
            return raw * self.variants.get("k", 1) + self.variants.get("c", 0)
        if isinstance(self.variants, list) and self.variants:
            if "eppValue" in self.variants[0]:
                for entry in self.variants:
                    if entry.get("eppValue") == raw:
                        return entry.get("stdValue")
                return None      # a raw value the manufacturer's table does not name: never guess
            if "startWord" in self.variants[0]:
                # A composite (caeType 3/4/5): the value is its PARTS, each read at its own
                # position. Reading the field as one integer yields a number that means nothing.
                if data is None:
                    return None
                parts = [
                    read_field(data, part["startWord"], part["startBit"], part["length"])
                    for part in self.variants
                ]
                if any(part is None for part in parts):
                    return None
                return ":".join(f"{part:02d}" for part in parts)
        return raw


def absent_probe(field: ModelField, data: bytes) -> bool:
    """Whether ``field`` reads as a probe this unit does not have.

    The rule is ``uss._sensor_temp``'s, and it exists because a model without (say) an outdoor probe
    reports 0 for it, which ``raw * k + c`` turns into a confident −64 °C. Published as a
    MEASUREMENT that lands in long-term statistics, one fabricated reading permanently skews the
    min/max/mean of a user's history, so an absent sensor must read as absent.

    Two tests, and each is needed — neither subsumes the other:

    * **The sentinel**, applied only where raw 0 would FABRICATE a reading. A raw sensor byte is
      scaled with an offset at or below zero (outdoor temperature is ``raw − 64``), so raw 0 means
      "no probe"; a setpoint is encoded as an offset from the bottom of its own range (the classic
      family's ``targetTemperature`` is ``raw + 16``, the water heater's ``raw + 30``), so raw 0 is
      a real 16 °C or 30 °C and must survive. ``c`` is that discriminator.
      ⛔ Not ``writable``: this project's own standing trap is that a published ``writable: false``
      does not mean unwritable — seven of the nine ids that work on ``0d12`` are published that way,
      and the classic family publishes its own setpoint as read-only.
    * **The manufacturer's own bounds** for this field, which catch what the sentinel cannot (an
      out-of-range value that is not 0x00/0xFF). The sentinel is still load-bearing: outdoor
      temperature declares ``minValue: -64``, so −64 is *inside* its declared range and only the
      sentinel rejects it.
    """
    if field.unit != _CELSIUS:
        return False
    raw = read_field(data, field.word, field.bit, field.length)
    if raw is None:
        return True
    offset = field.variants.get("c", 0) if isinstance(field.variants, dict) else 0
    if offset <= 0 and raw in _SENSOR_SENTINELS:
        return True
    value = field.interpret(raw, data)
    if not isinstance(value, (int, float)):
        return False
    bounds = field.bounds()
    return bounds is not None and not bounds[0] <= value <= bounds[1]


@dataclass(frozen=True)
class DeviceModel:
    """The published map for one typeid."""

    typeid: str
    name: str | None            # the manufacturer's own name for the class, e.g. 热泵定频_零冷水_3D_增压
    device_class: str           # the typeid's class field, e.g. "2001" — chars 16:20
    version: str | None
    fields: tuple[ModelField, ...]
    alarms: tuple[tuple[str, int], ...]
    operations: tuple[tuple[str, int | None, str | None], ...]

    def field(self, name: str) -> ModelField | None:
        return next((f for f in self.fields if f.name == name), None)

    def fields_for(self, status_cmd: str = STATUS_ALL) -> tuple[ModelField, ...]:
        return tuple(f for f in self.fields if f.status_cmd == status_cmd)

    def writable_fields(self) -> tuple[ModelField, ...]:
        """Fields the class publishes a single-parameter write id for."""
        return tuple(f for f in self.fields if f.writable and f.epp_cmd)

    def encode_write(self, name: str, value: Any) -> tuple[bytes, bytes]:
        """The EPP command and 2-byte big-endian payload that set ``name`` to ``value``.

        The single-parameter mechanism: the command names the attribute (``0x5D00 | id``, published
        per attribute as ``eppCmd``) and the payload carries the value, so nothing needs to be
        seeded from a live report and no word block is packed. It is the path the ``0d12`` cabinets
        already ship and the one issue #13's water heater publishes for all sixteen of its writable
        attributes.

        ⛔ Refuses an attribute the class publishes no write id for. That a class publishes one is
        NOT evidence the appliance accepts it — this project's own record is that seven of the nine
        ids working on ``0d12`` are published as unwritable, and the converse holds too. The
        appliance is the only authority, and the caller must check the read-back.
        """
        field = self.field(name)
        if field is None:
            raise KeyError(f"{name!r} is not an attribute of {self.typeid}")
        if not field.epp_cmd:
            raise KeyError(f"{name!r} has no single-parameter write id on {self.typeid}")
        command = bytes.fromhex(field.epp_cmd)
        if len(command) != 2:
            raise ValueError(f"{name!r}: unusable write id {field.epp_cmd!r}")
        raw = field.encode(value)
        return command, bytes(((raw >> 8) & 0xFF, raw & 0xFF))

    def decode(
        self,
        data: bytes,
        *,
        status_cmd: str = STATUS_ALL,
        only: frozenset[str] | None = None,
        drop_absent_probes: bool = True,
    ) -> dict[str, Any]:
        """Decode ``data`` to ``{attribute name: published value}``.

        ``only`` is the declaration gate and should almost always be supplied: the class map lists
        every attribute the PLATFORM can carry, and a device declares a subset. Building entities
        from the map alone produces phantoms — the trap :mod:`haismart_hrdp.features` exists for.
        """
        out: dict[str, Any] = {}
        for field in self.fields:
            if field.status_cmd != status_cmd:
                continue
            if only is not None and field.name not in only:
                continue
            if drop_absent_probes and absent_probe(field, data):
                continue
            value = field.read(data)
            if value is not None:
                out[field.name] = value
        return out


@lru_cache(maxsize=1)
def _bundle() -> dict[str, Any]:
    with gzip.open(MODELS_PATH, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def preload() -> None:
    """Warm the bundle so the first lookup does not read from disk.

    A host that decodes on its event loop — Home Assistant does — should call this from an executor
    first, so the one-off decompression happens off the loop. A no-op after the first call.
    """
    _bundle()


@lru_cache(maxsize=64)
def model_for(typeid: str | None) -> DeviceModel | None:
    """The published map for ``typeid``, or ``None`` if the bundle does not carry it.

    ``None`` is the safe answer and the caller must treat it as "decode nothing": there is no
    near-miss fallback here on purpose. A sibling typeid's map is a different device's map, and the
    project's own history — a two-model account once giving one AC the other's constraints — is what
    that costs.
    """
    if not typeid:
        return None
    raw = _bundle()["models"].get(typeid.lower())
    if raw is None:
        return None
    return DeviceModel(
        typeid=typeid.lower(),
        name=raw.get("name"),
        device_class=raw.get("cls", typeid[16:20]),
        version=raw.get("ver"),
        fields=tuple(ModelField(*row) for row in raw["fields"]),
        alarms=tuple((name, pos) for name, pos in raw.get("alarms", [])),
        operations=tuple(tuple(op) for op in raw.get("ops", [])),
    )


def known_typeids() -> frozenset[str]:
    return frozenset(_bundle()["models"])


def device_classes() -> frozenset[str]:
    """The typeid class fields the bundle covers (``"2001"``, ``"0212"``, …)."""
    return frozenset(m["cls"] for m in _bundle()["models"].values())
