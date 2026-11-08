"""What a laundry appliance may be told to do, and what must hold before it is.

Everything here is Haier's own configFile for the class, not inference: the ``0504`` laundry centre
(AWD14_BD4LCU1L, sold as HWD140-BD14LCGNU1) publishes, per attribute, whether it is writable at all
(``writable``), whether it may be written ON ITS OWN (``operationType`` ``I`` or ``IG``, against
``G`` = only inside a group command) and the single-parameter command that writes it (``eppCmd``,
``5Dxx``; the washer drum's carry the ``0x80`` drum bit, ``5D82``-``5DD2``).

⛔ **Off unless the owner turns it on.** No laundry write has been observed being accepted yet, and
the costs are not symmetrical: a dryer started from a dashboard by mistake is a real thing in a
real room. So the integration builds these controls only behind an option, and every command is
gated on the machine's OWN remote-control flag for that drum -- a flag set only at the panel, which
the machine enforces anyway.

Prior art agrees on the shape. Zuz666/uplus-reborn's twin-drum HWD120-B1558U (a ``0501``-class
unit) is commanded per drum with the same ``0x80`` drum bit, starts a new cycle with ONE group write
and never with its programme setter, and treats a command as proven only by a fresh report
afterwards. Its single remote flag is machine-wide (``6D01`` word 3 bit 1); this unit has one per
drum, as Haier's CLC108 laundry centre does. banto6/haier's washers ran spin-only cycles when the
programme and the start were sent as separate writes -- by hand too, seconds apart (#130, #241,
#288). Remote control lapses when a cycle ends, the panel knob is turned or the door is opened, so
expect to enable it at the panel once per cycle.

⛔ **The programme is chosen at the machine's panel, never written from here.** Haier's own app
never selects one with a single-parameter write: it sends one group command carrying the programme
AND that programme's whole parameter set (``grOnlineWash`` / ``grCommonDry``), and a real washer's
board traffic shows exactly that -- one group frame took it from idle to running, with no ``5Dxx``
write anywhere in the capture. A programme written on its own would load without its parameters,
which is the likeliest route to the spin-only cycles above. Starting (and resuming) on its own IS a
documented single command, so start, pause and cancel are offered; so are the options Haier marks
writable on their own.

The machine's own refusal codes are in :data:`LAUNDRY_REFUSALS`, so a refused command says why.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

__all__ = [
    "DRUMS",
    "LAUNDRY_ACTIONS",
    "LAUNDRY_REFUSALS",
    "MACHINE_WIDE",
    "Drum",
    "LaundryAction",
    "drum_of",
    "drums_for",
    "laundry_writable",
]

#: Status report → which drum it describes. The dryer reports in ``6D01``/``7D01`` and the washer
#: in ``6D02``/``7D02``. ``6D01`` is also the machine's common report (see :data:`MACHINE_WIDE`).
_DRUM_OF_REPORT = {"6D01": "dryer", "7D01": "dryer", "6D02": "washer", "7D02": "washer"}


@dataclass(frozen=True)
class Drum:
    """One drum's own control attributes, as its class publishes them."""

    key: str                    # "washer" / "dryer"
    report: str                 # its status report
    remote_valid: str           # the panel-set flag that allows remote control of it
    running_mode: str           # 1 = start / resume, 2 = not running (epp 1 / 0)
    programme: str              # its programme selection (read; chosen at the panel)
    return_standby: str         # write-only: abandon the cycle and return to standby
    phase: str                  # where in a cycle the drum is
    idle_phases: frozenset[int]  # the phases with nothing in progress: standby, or finished


#: ``running_mode`` 2 is 暂停 ("pause") in the model, but the machine reports it in standby too -- the
#: idle dryer of the capture reads 2 at phase 0 -- so it cannot tell "paused mid-cycle, water in the
#: drum" from "nothing to do". The PHASE can, and is what every gate below reads.
DRUMS: Mapping[str, Drum] = MappingProxyType({
    "washer": Drum(
        "washer", "6D02", "washerRemoteCtrValid", "washerRunningMode",
        "washerUnifiedProgramSettings", "washerReturnStandby",
        # 0 待机/未启动 standby · 14 结束 end · 18/19 the post-wash dry / detangle finished
        "laundryCyclePhase", frozenset({0, 14, 18, 19}),
    ),
    "dryer": Drum(
        "dryer", "6D01", "dryerRemoteCtrValid", "dryerRunningMode",
        "dryerUnifiedProgramSettings", "dryerReturnStandby",
        # 0 待机状态 standby · 6 程序结束 finished
        "dryerCyclePhase", frozenset({0, 6}),
    ),
})


@dataclass(frozen=True)
class LaundryAction:
    """A write-only command: published with a write id and a value, but no report position.

    The shipped byte map keeps only attributes with a position, so these are carried here, quoted
    from the class's configFile ``Property`` entries (``writable: true``, ``frameType: 1``,
    ``paramLen: 2``, one variant ``{stdValue: 1, eppValue: 1}``).
    """

    name: str
    drum: str
    epp_cmd: str
    value: int

    def frame_parts(self) -> tuple[bytes, bytes]:
        return bytes.fromhex(self.epp_cmd), self.value.to_bytes(2, "big")


#: Per device class. ``washerReturnStandby`` / ``dryerReturnStandby`` are 返回待机 -- the cancel
#: the panel's own "cancel" performs: the cycle is abandoned and the drum goes back to standby.
LAUNDRY_ACTIONS: Mapping[str, Mapping[str, LaundryAction]] = MappingProxyType({
    "0504": MappingProxyType({
        "washerReturnStandby": LaundryAction("washerReturnStandby", "washer", "5DA4", 1),
        "dryerReturnStandby": LaundryAction("dryerReturnStandby", "dryer", "5D23", 1),
    }),
})

#: Writable on their own, but not offered. Each would change something an owner would not expect
#: a dashboard toggle to change:
_NOT_OFFERED = frozenset({
    # "Long-term authorisation" keeps remote control allowed with no panel action -- it would
    # switch off the very safeguard every other control relies on.
    "longTimeAuthorizationStatus", "dryerLongTimeAuthorizationStatus",
    # Lets the cloud power the machine on remotely.
    "remotePowerOn",
    # The load weight the machine measures for itself; set by hand it misleads the dosing.
    "weight",
    # Start and pause are buttons, with their own gate; as a select they would read "Paused"
    # in standby and start a cycle when changed.
    "washerRunningMode", "dryerRunningMode",
    # The programme: Haier sets one only inside a group command with its parameters (module
    # docstring). Chosen at the panel.
    "washerUnifiedProgramSettings", "dryerUnifiedProgramSettings",
    # Haier's washer-dryer manual: the network can neither set nor clear the child lock
    # (物联网不能解除童锁，也不能通过物联网设置童锁) -- and the machine refuses with code 0009 while it is on.
    "childLockStatus",
    # One-shot actions and factory resets. None has a report position, so none qualifies anyway;
    # named so that a later map which gave one a position still could not offer it.
    "dryerResetOpt", "washerResetOpt", "unlockShutdown", "maxSpinIntDry", "sendTestCmd",
})

#: Why a laundry board refused a command -- Haier's laundry refusal table (UART protocol
#: specification, appendix 9, 无效信息表), for a unit whose own model publishes no reasons of its
#: own. The 0504's does not.
LAUNDRY_REFUSALS: Mapping[int, str] = MappingProxyType({
    0x0000: "invalid command",
    0x0001: "no programme selected, so it cannot start",
    0x0002: "it cannot be set once the programme is running",
    0x0003: "it cannot be set while the machine is off",
    0x0004: "it cannot be set while running",
    0x0005: "the value is outside what this programme allows",
    0x0006: "this function is not available in this programme",
    0x0007: "this setting cannot be adjusted in this programme",
    0x0008: "this programme is not available in this mode",
    0x0009: "the child lock is on -- unlock it at the machine first",
    0x000A: "the last rinse is under way, so the rinse count cannot change",
    0x000B: "this stage has finished, so it cannot be set",
    0x000C: "the load weight cannot be set in this programme",
    0x000D: "it cannot be set until the programme ends, or it is already set",
    0x000E: "the setting is wrong",
    0x000F: "remote control is not activated -- turn it on at the machine's panel",
    0x0010: "the door was opened, which switches remote control off until it is turned on again",
    0x0011: "the drum is too hot to start",
})


#: Settings that act on the whole machine although ``6D01`` files them: power (``onOffStatus`` --
#: the configFile reports each drum's own power separately, as washerPowerStatus / dryerPowerStatus),
#: the panel child lock, the buzzer, and wash-then-dry linkage. Each needs BOTH drums' remote flags.
MACHINE_WIDE = frozenset({"onOffStatus", "childLockStatus", "buzzerDisabled", "wdLinkageStatus"})


def drums_for(name: str, report: str | None) -> tuple[str, ...]:
    """The drums a write of ``name`` (filed under ``report``) must be allowed on: one, or both."""
    if name in MACHINE_WIDE:
        return tuple(DRUMS)
    drum = drum_of(report)
    return (drum,) if drum is not None else ()


def drum_of(report: str | None) -> str | None:
    """Which drum a status report (``6D01`` ...) describes, or ``None``."""
    return _DRUM_OF_REPORT.get((report or "").upper())


def laundry_writable(
    fields: Iterable[Any], declared: Iterable[Mapping[str, Any]] | None
) -> frozenset[str]:
    """The attributes a laundry appliance may be written one at a time, from its own two sources.

    ``fields`` is the class map (each with ``name``, ``epp_cmd``, ``writable``, ``status_cmd``) and
    ``declared`` the unit's digital-model attributes. An attribute qualifies only when the map
    publishes a single-parameter write id for it in a status report it also reads back from, AND
    the unit declares it writable, individually (``operationType`` containing ``I``), and visible.
    """
    by_name = {a.get("name"): a for a in (declared or ()) if a.get("name")}
    offered: set[str] = set()
    for field in fields:
        attr = by_name.get(field.name)
        if (
            attr is None
            or not field.epp_cmd
            or not field.writable
            or drum_of(field.status_cmd) is None
            or field.name in _NOT_OFFERED
        ):
            continue
        if not attr.get("writable") or attr.get("invisible"):
            continue
        if "I" not in str(attr.get("operationType") or ""):
            continue
        offered.add(field.name)
    return frozenset(offered)
