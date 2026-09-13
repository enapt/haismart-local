"""What KIND of appliance a device is — the question the integration never used to ask.

Every config entry got a climate entity, because every device was an air conditioner. Issue #13 is
what that costs when it is not: a heat-pump water heater rendered with cool / dry / fan_only modes,
a 16–30 °C clamp against a real 35–75 °C setpoint, and its own current temperature nowhere.

Two independent sources, and they are used in that order:

1. **The typeid's class field** — characters 16:20 of the 64-hex uPlusId. It is the manufacturer's
   own device-class code, the appliance **announces it on the key-free discovery channel**, and it
   is the key Haier's byte maps are filed under. That makes it available offline, before any poll,
   and for a device nobody has an account for.
2. **The cloud's ``appTypeName``**, when the device list supplied one. Used only where the class is
   unknown to us, because it is a marketing-facing label (``"Pump"`` for a heat-pump water heater)
   and it is absent for any locally-added device.

⛔ **Unknown maps to :data:`ApplianceKind.OTHER`, and OTHER is not a synonym for "wrong".** The
caller decides what to build; this module only refuses to guess. Naming a class here is a claim
about what an appliance IS, and the evidence for every row below is the manufacturer's own name for
that class in its configFile — printed beside each entry.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

__all__ = [
    "ApplianceKind",
    "CLASS_KINDS",
    "CLASS_LABELS",
    "class_of",
    "kind_for",
    "label_for",
]


class ApplianceKind(StrEnum):
    """What a device is, to the degree the evidence supports."""

    AIR_CONDITIONER = "air_conditioner"
    WATER_HEATER = "water_heater"
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
#   0501 0502                 单滚筒XQG… — washing machines
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
    if app_type_name:
        return _APP_TYPE_KINDS.get(app_type_name.strip().lower(), ApplianceKind.OTHER)
    return ApplianceKind.OTHER
