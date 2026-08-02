"""The canonical attribute map air conditioners share, and the displacements they use.

Every air conditioner packs the same attributes into the same words, at the same bits, with the same
widths and the same scaling. What differs between models is only **where the block starts**: a model
carrying the leading voice/media attributes reports them from word 1, and a model without them
reports the same climate attributes a fixed number of words earlier. Nothing else moves.

That is not an inference from our own hardware. Every device model published for an air conditioner
agrees on it: same widths, same bits, same order, one whole-word displacement each. The map below is
that agreement, transcribed rather than hand-derived, and it reproduces every report layout this
project supports — including the two it never had a published model for.

Positions are relative to the un-displaced map, so a classic-layout unit reads ``word - 19``.
``k``/``c`` scale a raw value (``value = raw * k + c``); ``enum`` maps a raw wire value to the
standard code a model names it by, and is present only where the two differ.

Transcribed from the published device models, not written by hand — so do not edit it by
hand either; correct the models it came from and regenerate.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalField:
    """One attribute's place in the shared map, before any displacement is applied."""

    word: int
    bit: int
    length: int
    dtype: str
    k: float = 1.0
    c: float = 0.0
    enum: Mapping[int, int] | None = None


# Displacements seen across the published models, and how many models use each.
DISPLACEMENTS: Mapping[int, int] = {0: 2, -19: 5}

CANONICAL: Mapping[str, CanonicalField] = {
    "volume": CanonicalField(1, 0, 8, "int"),
    "otaControl": CanonicalField(1, 10, 2, "int"),
    "updateStatus": CanonicalField(1, 12, 1, "bool"),
    "runningMode": CanonicalField(1, 13, 2, "int"),
    "uniqueId": CanonicalField(2, 0, 16, "string"),
    "token": CanonicalField(3, 0, 16, "string"),
    "clientId": CanonicalField(4, 0, 16, "string"),
    "location": CanonicalField(5, 0, 16, "string"),
    "date": CanonicalField(7, 8, 24, "string"),
    "time": CanonicalField(8, 0, 24, "string"),
    "currentMediaName": CanonicalField(9, 0, 16, "string"),
    "playTime": CanonicalField(10, 0, 16, "int"),
    "authVersion": CanonicalField(11, 0, 8, "int"),
    "playProgress": CanonicalField(11, 8, 8, "int"),
    "scheduleVersion": CanonicalField(12, 0, 16, "string"),
    "softVersion": CanonicalField(13, 0, 16, "string"),
    "hardVersion": CanonicalField(14, 0, 16, "string"),
    "messageVersion": CanonicalField(15, 0, 16, "string"),
    "vboxId?": CanonicalField(16, 0, 16, "string"),
    "voiceprintRecogStatus": CanonicalField(17, 1, 1, "bool"),
    "voiceRecogMode": CanonicalField(17, 3, 5, "int"),
    "dialect": CanonicalField(17, 8, 8, "int"),
    "playMode": CanonicalField(18, 8, 3, "int"),
    "currentSongFavourited": CanonicalField(18, 11, 1, "bool"),
    "playControl": CanonicalField(18, 13, 2, "int"),
    "playStatus": CanonicalField(18, 15, 1, "bool"),
    "windDirectionVertical": CanonicalField(
        20,
        0,
        4,
        "int",
        enum={0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 6: 5, 8: 6, 10: 7, 12: 8, 14: 9, 13: 10},
    ),
    "targetTemperature": CanonicalField(20, 8, 8, "double", c=16.0),
    "energySavePeriod": CanonicalField(21, 0, 8, "int", c=15),
    "windSpeed": CanonicalField(21, 8, 3, "int"),
    "specialMode": CanonicalField(21, 11, 2, "int"),
    "operationMode": CanonicalField(21, 13, 3, "int"),
    "onOffStatus": CanonicalField(22, 0, 1, "bool"),
    "healthMode": CanonicalField(22, 1, 1, "bool"),
    "electricHeatingStatus": CanonicalField(22, 2, 1, "bool"),
    "rapidMode": CanonicalField(22, 3, 1, "bool"),
    "muteStatus": CanonicalField(22, 4, 1, "bool"),
    "silentSleepStatus": CanonicalField(22, 5, 1, "bool"),
    "lockStatus": CanonicalField(22, 6, 1, "bool"),
    "echoStatus": CanonicalField(22, 7, 1, "bool"),
    "10degreeHeatingStatus": CanonicalField(22, 8, 1, "bool"),
    "screenDisplayStatus": CanonicalField(22, 9, 1, "bool"),
    "halfDegreeSettingStatus": CanonicalField(22, 10, 1, "bool"),
    "intelligenceStatus": CanonicalField(22, 11, 1, "bool"),
    "pmvStatus": CanonicalField(22, 12, 1, "bool"),
    "tempUnit": CanonicalField(22, 13, 1, "int", enum={0: 1, 1: 2}),
    "heatAccumulationStatus": CanonicalField(22, 14, 1, "bool"),
    "selfCleaning56Status": CanonicalField(22, 15, 1, "bool"),
    "windDirectionHorizontal": CanonicalField(23, 0, 3, "int"),
    "freshWindSpeed": CanonicalField(23, 4, 2, "int"),
    "humanSensingStatus": CanonicalField(23, 6, 2, "int"),
    "targetHumidity": CanonicalField(23, 8, 8, "int", c=30),
    "freshAirStatus": CanonicalField(24, 0, 1, "bool"),
    "humidificationStatus": CanonicalField(24, 1, 1, "bool"),
    "pm2p5CleaningStatus": CanonicalField(24, 2, 1, "bool"),
    "ch2oCleaningStatus": CanonicalField(24, 3, 1, "bool"),
    "selfCleaningStatus": CanonicalField(24, 4, 1, "bool"),
    "lightStatus": CanonicalField(24, 5, 1, "bool"),
    "energySavingStatus": CanonicalField(24, 6, 1, "bool"),
    "localFilterChangeFlag": CanonicalField(24, 8, 1, "bool"),
    "voiceStatus": CanonicalField(24, 9, 1, "bool"),
    "voiceSignStatus": CanonicalField(24, 10, 1, "bool"),
    "windSensingStatus": CanonicalField(24, 11, 1, "bool"),
    "humidityCtrlStatus": CanonicalField(24, 12, 1, "bool"),
    "indoorHumidity": CanonicalField(25, 0, 8, "int"),
    "indoorTemperature": CanonicalField(25, 8, 8, "double", k=0.5),
    "pm2p5Level": CanonicalField(26, 0, 2, "int"),
    "airQuality": CanonicalField(26, 2, 2, "int"),
    "sensingResult": CanonicalField(26, 4, 2, "int"),
    "acType": CanonicalField(26, 7, 1, "int"),
    "outdoorTemperature": CanonicalField(26, 8, 8, "double", c=-64.0),
    "opSrc": CanonicalField(27, 0, 2, "int"),
    "operationModeHK": CanonicalField(27, 2, 2, "int"),
    "ErrAckFlag": CanonicalField(27, 7, 1, "bool"),
    "errCode": CanonicalField(27, 8, 8, "int"),
    "totalCleaningTime": CanonicalField(28, 0, 16, "int"),
    "indoorPM2p5Value": CanonicalField(29, 0, 16, "int"),
    "outdoorPM2p5Value": CanonicalField(30, 0, 16, "int"),
    "ch2oValue": CanonicalField(31, 0, 16, "int"),
    "vocValue": CanonicalField(32, 0, 16, "int"),
    "co2Value": CanonicalField(33, 0, 16, "int"),
    "totalElectricityUsed": CanonicalField(35, 0, 32, "int"),
    "co2ExceedRemind": CanonicalField(36, 0, 2, "int"),
    "pm2p5ExceedRemind": CanonicalField(36, 2, 2, "int"),
}


@dataclass(frozen=True)
class WriteField:
    """One attribute's place in the group-set write frame."""

    word: int
    bit: int
    length: int


@dataclass(frozen=True)
class Command:
    """One command a device accepts, as the model states it."""

    cae_type: int
    frame_type: int
    epp_cmd: str | None


# The group-set write frame. This is a **separate coordinate space from the report map above**: an
# attribute's word and bit in a group-set command bear no relation to its position in a status
# report, and the two must never be used interchangeably. Unlike the report map this needs no
# displacement -- every model states the same place for every field, so one map serves all of them.
#
# A field appearing here means the model puts it in the write frame. It does **not** mean a given
# unit will honour a write to it: a group-set can be accepted whole while an individual bit is
# ignored. Treat this as the candidate list and confirm each field against real hardware.
CANONICAL_WRITE: Mapping[str, WriteField] = {
    "windDirectionVertical": WriteField(1, 0, 4),
    "targetTemperature": WriteField(1, 8, 8),
    "energySavePeriod": WriteField(2, 0, 8),
    "windSpeed": WriteField(2, 8, 3),
    "specialMode": WriteField(2, 11, 2),
    "operationMode": WriteField(2, 13, 3),
    "onOffStatus": WriteField(3, 0, 1),
    "healthMode": WriteField(3, 1, 1),
    "electricHeatingStatus": WriteField(3, 2, 1),
    "rapidMode": WriteField(3, 3, 1),
    "muteStatus": WriteField(3, 4, 1),
    "silentSleepStatus": WriteField(3, 5, 1),
    "lockStatus": WriteField(3, 6, 1),
    "echoStatus": WriteField(3, 7, 1),
    "10degreeHeatingStatus": WriteField(3, 8, 1),
    "screenDisplayStatus": WriteField(3, 9, 1),
    "halfDegreeSettingStatus": WriteField(3, 10, 1),
    "intelligenceStatus": WriteField(3, 11, 1),
    "pmvStatus": WriteField(3, 12, 1),
    "tempUnit": WriteField(3, 13, 1),
    "heatAccumulationStatus": WriteField(3, 14, 1),
    "selfCleaning56Status": WriteField(3, 15, 1),
    "windDirectionHorizontal": WriteField(4, 0, 3),
    "freshWindSpeed": WriteField(4, 4, 2),
    "humanSensingStatus": WriteField(4, 6, 2),
    "targetHumidity": WriteField(4, 8, 8),
    "freshAirStatus": WriteField(5, 0, 1),
    "humidificationStatus": WriteField(5, 1, 1),
    "pm2p5CleaningStatus": WriteField(5, 2, 1),
    "ch2oCleaningStatus": WriteField(5, 3, 1),
    "selfCleaningStatus": WriteField(5, 4, 1),
    "lightStatus": WriteField(5, 5, 1),
    "energySavingStatus": WriteField(5, 6, 1),
    "cleaningTimeStatus": WriteField(5, 7, 1),
    "cloudFilterChangeFlag": WriteField(5, 8, 1),
    "voiceStatus": WriteField(5, 9, 1),
    "voiceSignStatus": WriteField(5, 10, 1),
    "windSensingStatus": WriteField(5, 11, 1),
    "humidityCtrlStatus": WriteField(5, 12, 1),
}

OPERATIONS: Mapping[str, Command] = {
    "getAllAlarm": Command(12, 115, None),
    "getAllProperty": Command(11, 1, "4D01"),
    "getBigDataFrame": Command(11, 1, "4DFE"),
    "grSetDAC": Command(10, 1, "6001"),
    "stopCurrentAlarm": Command(12, 9, None),
}

# Commands a minority of models state differently. Where a device rejects the form in `OPERATIONS`,
# these are the other published forms.
OPERATION_ALTERNATES: Mapping[str, tuple[Command, ...]] = {
    "getBigDataFrame": (Command(11, 96, "4DFE"),),
}
