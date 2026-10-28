"""What KIND of appliance a device is — the question the integration never used to ask.

Every config entry got a climate entity, because every device was an air conditioner. Issue #13 is
what that costs when it is not: a heat-pump water heater rendered with cool / dry / fan_only modes,
a 16–30 °C clamp against a real 35–75 °C setpoint, and its own current temperature nowhere.

Independent sources, used in this order:

1. **The typeid's class field** — characters 16:20 of the 64-hex uPlusId. It is the manufacturer's
   own device-class code, the appliance **announces it on the key-free discovery channel**, and it
   is the key Haier's byte maps are filed under. That makes it available offline, before any poll,
   and for a device nobody has an account for.
2. **The class's family**, for laundry only: an unnamed ``05xx`` class is a washer or dryer.
3. **The cloud's ``appTypeName``**, when the device list supplied one. Used only where the class is
   unknown to us, because it is a marketing-facing label (``"Pump"`` for a heat-pump water heater)
   and it is absent for any locally-added device. A label naming laundry ("Roller Washer") is
   matched on its words, since the result is read-only; every other label must match exactly.

Where all of them fail, setup asks the owner (``CONF_APPLIANCE_KIND`` in the integration).

⛔ **Unknown maps to :data:`ApplianceKind.OTHER`, and OTHER is not a synonym for "wrong".** The
caller decides what to build; this module only refuses to guess. Naming a class here is a claim
about what an appliance IS, and the evidence for every row below is the manufacturer's own name for
that class in its configFile — printed beside each entry.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

__all__ = [
    "ApplianceKind",
    "answer_applies",
    "asks_owner",
    "CLASS_KINDS",
    "CLASS_LABELS",
    "class_of",
    "identified_not_air_conditioner",
    "kind_for",
    "label_for",
]


class ApplianceKind(StrEnum):
    """What a device is, to the degree the evidence supports."""

    AIR_CONDITIONER = "air_conditioner"
    WATER_HEATER = "water_heater"
    # A washer, dryer or twin washer + dryer. Read-only by construction (see `PLATFORMS_BY_KIND`):
    # its whole state is the manufacturer's byte map, split across two status frames (6D01 dryer,
    # 6D02 washer on the 0504 laundry centre), and no hand-built family describes any of it.
    LAUNDRY = "laundry"
    OTHER = "other"


# Every row is justified by the `BasicInfo.name` Haier ships in that class's own configFile.
CLASS_KINDS: Mapping[str, ApplianceKind] = MappingProxyType({
    # --- air conditioners -----------------------------------------------------------------------
    "0211": ApplianceKind.AIR_CONDITIONER,   # 分体空调 — split
    "0212": ApplianceKind.AIR_CONDITIONER,   # 挂机通用 / 东南亚挂机 / 共享空调 — wall-mounted
    "0214": ApplianceKind.AIR_CONDITIONER,   # 卡萨帝双风区挂机 — dual-airflow wall
    "0312": ApplianceKind.AIR_CONDITIONER,   # 柜机空调 / 变频柜机 — floor standing
    "0d12": ApplianceKind.AIR_CONDITIONER,   # candy版协议 / 商空商铺机型 — central cabinet
    "0d21": ApplianceKind.AIR_CONDITIONER,   # 柜嵌通用 / 家中机通用 — built-in cabinet
    "3912": ApplianceKind.AIR_CONDITIONER,   # 海外窗机 / 菲律宾窗机 — window
    # --- water heaters --------------------------------------------------------------------------
    "0612": ApplianceKind.WATER_HEATER,      # 电热水器 — electric storage
    "0616": ApplianceKind.WATER_HEATER,      # 卡萨帝…系列电热水器
    "0618": ApplianceKind.WATER_HEATER,      # 海尔…系列电热水器
    "0619": ApplianceKind.WATER_HEATER,      # 海尔…系列电热水器
    "061a": ApplianceKind.WATER_HEATER,      # 电热水器…型号
    "1812": ApplianceKind.WATER_HEATER,      # 78EF燃气热水器 — gas
    "1813": ApplianceKind.WATER_HEATER,      # 786普通燃气热水器
    "1814": ApplianceKind.WATER_HEATER,      # 燃气热水器JM6 / F5SPSU1
    "1815": ApplianceKind.WATER_HEATER,      # 燃气R5R6型
    "1817": ApplianceKind.WATER_HEATER,      # 500S / 788零冷水燃气热水器
    "2001": ApplianceKind.WATER_HEATER,      # 热泵热水器 — heat pump (issue #13)
    # --- laundry ----------------------------------------------------------------------------------
    # AWD14_BD4LCU1L越南中子 — twin washer + dryer (HWD140-BD14LCGNU1); its configFile files washer
    # fields under 6D02/7D02 and dryer fields under 6D01/7D01, and the cloud labels it Roller Washer.
    "0504": ApplianceKind.LAUNDRY,
})

# ⛔ NOT listed, deliberately. `0601`, `0602` and `1801` sit in the numbering next to classes that
# ARE water heaters, and their only catalogue members are V2 text profiles whose command labels are
# generic (开关机 / 查询状态) and name no appliance. Assigning them from the numbering alone would be
# an inference dressed as evidence, and nothing is gained by it: the V2 text format is not in the
# shipped byte-map bundle, so a device of those classes decodes nothing either way.
#
# Also unlisted, and known to be something else — each would be a real appliance kind of its own,
# and none has ever been seen in the field by this project:
#   0121 0122 0123 0124 0128  BCD_… / 风冷三门 — refrigerators
#   0501 0502                 单滚筒XQG… — washing machines (0501 keeps its generic, model-driven
#                             entities; an unnamed 05xx such as 0502 resolves to LAUNDRY by family)
#   0901 0902                 烟机 / 定频油烟机 — cooker hoods
#   0b11 0b12                 消毒柜 — sterilising cabinets
#   1a01                      S45TXXXU1 — dishwasher
#   1d01                      燃气灶 — gas hob
#   2101                      空气净化器 — air purifier
#   3e01                      H3蒸烤箱 — steam oven
#   0f01 3b01 150e 2702       智能电视 / 语音 / 体脂秤 / 陀螺仪 — TV, voice, scale, sensor

# What each device class IS, in English. Separate from :class:`ApplianceKind` on purpose: a kind
# decides which entities get built and there are only three, while a label is what a person reads
# and there is one per class. Every entry is Haier's own `BasicInfo.name` for that class, translated
# -- so "refrigerator" is not an inference from the class number, it is what the file says.
CLASS_LABELS: Mapping[str, str] = MappingProxyType({
    "0121": "Refrigerator", "0122": "Refrigerator", "0123": "Refrigerator",
    "0124": "Refrigerator", "0128": "Refrigerator",
    "0211": "Air conditioner", "0212": "Air conditioner", "0214": "Air conditioner",
    "0312": "Air conditioner", "0d12": "Air conditioner", "0d21": "Air conditioner",
    "3912": "Air conditioner",
    "0501": "Washing machine",
    "0504": "Washer-dryer",
    "0612": "Water heater", "0616": "Water heater", "0618": "Water heater",
    "0619": "Water heater", "061a": "Water heater",
    "1812": "Gas water heater", "1813": "Gas water heater", "1814": "Gas water heater",
    "1815": "Gas water heater", "1817": "Gas water heater",
    "2001": "Heat-pump water heater",
    "0901": "Cooker hood", "0902": "Cooker hood",
    "0b11": "Sterilising cabinet", "0b12": "Sterilising cabinet",
    "1a01": "Dishwasher",
    "1d01": "Gas hob",
    "2101": "Air purifier",
    "3e01": "Steam oven",
    "0f01": "Television",
    "3b01": "Voice assistant",
    "150e": "Body-composition scale",
    "2702": "Sensor",
})


def label_for(uplus_id: str | None) -> str | None:
    """What this device class is, in English, or ``None`` if we have no name for it."""
    device_class = class_of(uplus_id)
    return CLASS_LABELS.get(device_class) if device_class else None


# The cloud's own category label, used ONLY when the typeid's class is unknown to us. Keys are the
# `appTypeName` strings Haier's device list returns (`appTypeCode` in brackets for the record).
_APP_TYPE_KINDS: Mapping[str, ApplianceKind] = MappingProxyType({
    "wall mounted": ApplianceKind.AIR_CONDITIONER,          # A177
    "floor standing": ApplianceKind.AIR_CONDITIONER,        # A178
    "central ac": ApplianceKind.AIR_CONDITIONER,            # A120
    "window ac": ApplianceKind.AIR_CONDITIONER,             # A182
    "electric water heater": ApplianceKind.WATER_HEATER,    # A013
    "solar-water-heater": ApplianceKind.WATER_HEATER,       # A058
    # ⚠️ "Pump" (A048) is issue #13's own category, and it is exactly the kind of label that must
    # not be trusted on its own: a heat pump is also a circulation pump, a pool pump, a booster.
    # The typeid's class field (2001 = 热泵热水器) is what identifies that device; this entry is
    # deliberately absent so a "Pump" of an unknown class resolves to OTHER rather than to a water
    # heater with a 75 °C setpoint.
})


# The laundry FAMILY: a class whose first two digits are 05. Used only for a 05xx class this module
# has no row for -- a named class keeps exactly what its row says -- and only ever to say "laundry",
# which builds sensors and nothing that writes, so a wrong answer costs a reading, never a command.
# The evidence that 05 is laundry and nothing else: every 05xx configFile Haier ships names a washer
# (0501 单滚筒XQG…, 0502 the same in the V2 text format, 0504 AWD14_BD4LCU1L — a twin washer +
# dryer), and the SEA app files its washer-and-dryer cards under middle classes 4 and 5 of that
# family (`washerAndDryerMiddleClass_4` / `_5`, libapp.so of com.haier.uhome.uplus.seasia 5.7.0).
_LAUNDRY_FAMILY = "05"

# A cloud category that names laundry, for a device whose class we cannot read or have no row for.
# "Roller Washer" is the label Haier's device list gives the 0504 laundry centre; the SEA app's own
# washer types are roller, pulsator, double roller, double pulsator and dryer. Matched on whole
# words, so "Dishwasher" is not a washer -- and "Dish Washer" is excluded by name.
_LAUNDRY_LABEL = re.compile(r"\b(?:washer|washing|dryer|laundry)\b", re.IGNORECASE)
_NOT_LAUNDRY_LABEL = re.compile(r"\bdish", re.IGNORECASE)


def _is_laundry_label(app_type_name: str) -> bool:
    return bool(_LAUNDRY_LABEL.search(app_type_name)) and not _NOT_LAUNDRY_LABEL.search(
        app_type_name
    )


def class_of(uplus_id: str | None) -> str | None:
    """The device-class field of a uPlusId — characters 16:20 — or ``None`` if there isn't one."""
    if not uplus_id or len(uplus_id) < 20:
        return None
    value = uplus_id[16:20].lower()
    # An all-zero uPlusId is how a unit says "not reported"; so is an all-zero class field.
    return value if value.strip("0") else None


def kind_for(uplus_id: str | None, app_type_name: str | None = None) -> ApplianceKind:
    """What kind of appliance this is, from its typeid first and the cloud's label second.

    Returns :data:`ApplianceKind.OTHER` when neither source settles it. That is the honest answer
    and the caller must treat it as one — in particular, OTHER must not silently become "air
    conditioner", which is the behaviour issue #13 reported.
    """
    device_class = class_of(uplus_id)
    if device_class is not None and device_class in CLASS_KINDS:
        return CLASS_KINDS[device_class]
    # A class we have a name for is settled by that name, whatever the cloud calls it: a 0501
    # front loader is a "Roller Washer" too, and a label must not quietly change what it gets.
    if device_class is not None and device_class in CLASS_LABELS:
        return ApplianceKind.OTHER
    if device_class is not None and device_class.startswith(_LAUNDRY_FAMILY):
        return ApplianceKind.LAUNDRY
    if app_type_name:
        label = app_type_name.strip()
        if _is_laundry_label(label):
            return ApplianceKind.LAUNDRY
        return _APP_TYPE_KINDS.get(label.lower(), ApplianceKind.OTHER)
    return ApplianceKind.OTHER


def identified_not_air_conditioner(uplus_id: str | None, app_type_name: str | None = None) -> bool:
    """Whether the evidence positively says this is NOT an air conditioner.

    The other half of the unidentified-device rule. An ``OTHER`` keeps a thermostat while its report
    decodes as one, because some uncatalogued classes are working air conditioners -- but a report
    length is not an identity: the 0504 dryer's 165-byte report is also an AC family's length, and
    read that way it had a setpoint, a mode and a 50.5 °C "room". A class Haier names as something
    else (a refrigerator, a 0501 washer, a hood) has answered the question, so its report is never
    read as an AC's, whichever length it happens to be.
    """
    kind = kind_for(uplus_id, app_type_name)
    if kind is ApplianceKind.AIR_CONDITIONER:
        return False
    if kind is not ApplianceKind.OTHER:
        return True
    device_class = class_of(uplus_id)
    return device_class is not None and device_class in CLASS_LABELS


def asks_owner(uplus_id: str | None, app_type_name: str | None = None) -> bool:
    """Whether the owner should be asked what this appliance is.

    Only where the device said who it is and nothing here recognised it: a class field we have no
    row or name for, or a cloud label we do not know. A device that said nothing at all -- a manual
    install whose unit did not answer the key-free query -- is not asked, because that is how most
    air conditioners arrive and they need no answer; the coordinator learns the uPlusId at runtime,
    and the question is in the entry's options from then on.
    """
    if kind_for(uplus_id, app_type_name) is not ApplianceKind.OTHER:
        return False
    device_class = class_of(uplus_id)
    if device_class is not None:
        return device_class not in CLASS_LABELS
    return bool(app_type_name and app_type_name.strip())


def answer_applies(uplus_id: str | None) -> bool:
    """Whether the owner's answer can decide the kind -- i.e. the class field does not.

    A class this module has a row or a name for settles it, and so does the laundry family. What is
    left is a class nobody here knows, or none at all, where the only other evidence is the cloud's
    label -- and a label can be wrong ("Hand Dryer" reads as laundry), so the owner's answer outranks
    it there.
    """
    device_class = class_of(uplus_id)
    if device_class is None:
        return True
    return not (
        device_class in CLASS_KINDS
        or device_class in CLASS_LABELS
        or device_class.startswith(_LAUNDRY_FAMILY)
    )
