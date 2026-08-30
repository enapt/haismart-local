

# Real 133-byte reports from issue #12's cabinets. `.102` reads `humanSensingStatus` = 3 at
# canonical w23.b6; `.64` -- same model, same firmware -- reads 0 there.
STATUS_133_PRESENCE_ON = (
    "00002715000000004e5601000003020000040100000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000035ffff320000000000"
    "00066d0104042200020114c30000000000000003021330325b80000300000000000000000000000000000000"
    "02"
)
STATUS_133_PRESENCE_OFF = (
    "0000271500000000000000000000000000000000000000000000000000000000000000000000000033433136"
    "343030463444363300000000000000000000000000000000000000000000000000000035ffff320000000000"
    "00066d0108024100020114030000000000000003020330325980000700000000000000000000000000000000"
    "55"
)
_D12_UPLUS = "201c10c7088081000d1205464544850000009cd68e692c104e2a333eab95d140"


def test_a_class_that_carries_presence_undeclared_still_reports_it():
    """Issue #12's cabinets carry `humanSensingStatus` on the wire and never declare it.

    Applying the declaration gate literally hides a reading the appliance is plainly sending. The
    same gate applied to `outdoorTemperature` -- 0 of 187 `0d12` products declare an outdoor probe
    and every one observed has a working one -- would delete a sensor this integration already
    ships, which is why the exception is per class and carries its own evidence.
    """
    from haismart_hrdp.features import declared_enum_features, read_enum_features
    from haismart_hrdp.wire_models import related_model_named

    model = {"invisible_attributes": [], "attributes": {"onOffStatus": {}}}
    assert "humanSensingStatus" not in declared_enum_features(model)
    assert "humanSensingStatus" in declared_enum_features(model, "0d12")

    # the reporter's own report: `humanSensingStatus` reads 3 at canonical w23.b6
    blob = bytes.fromhex(STATUS_133_PRESENCE_ON)
    wm = related_model_named("related-19+4@25", len(blob), uplus_id=_D12_UPLUS)
    assert read_enum_features(wm, model, blob, "0d12")["humanSensingStatus"] == "on"
    assert read_enum_features(wm, model, blob) == {}          # unchanged without the class


def test_an_inferred_presence_reading_of_zero_is_not_reported_as_off():
    """Where the hardware is inferred from the class rather than declared, 0 is ambiguous.

    On a product that declares the attribute, 0 is the real state "off". On one that does not, it
    cannot be told from "no sensor fitted" -- so it is dropped and the entity reads unknown, the
    call already made for `sensingResult`'s 无此功能. The three sibling cabinets all read 0.
    """
    from haismart_hrdp.features import read_enum_features
    from haismart_hrdp.wire_models import related_model_named

    model = {"invisible_attributes": [], "attributes": {"onOffStatus": {}}}
    blob = bytes.fromhex(STATUS_133_PRESENCE_OFF)
    wm = related_model_named("related-19+4@25", len(blob), uplus_id=_D12_UPLUS)
    assert "humanSensingStatus" not in read_enum_features(wm, model, blob, "0d12")

    # but a product that DOES declare it keeps 0 as a real "off"
    declaring = {"invisible_attributes": [], "attributes": {"humanSensingStatus": {}}}
    assert read_enum_features(wm, declaring, blob, "0d12")["humanSensingStatus"] == "off"


def test_the_presence_feature_ships_as_BOTH_halves():
    """The vendor models presence as a setting plus a reading, and both belong on this class.

    `humanSensingStatus` w23.b6/2 is the SETTING (0 off / 1 avoid / 2 follow / 3 on -- the panel's
    two toggles write 1 and 2, never 3). `sensingResult` w26.b4/2 is the READING (0 no-such-function
    / 1 nobody / 2 one person / 3 several). Surfacing only the setting would report the mode while
    hiding what the sensor sees.

    ⚠️ `sensingResult`'s 0 already means "no such function" and its state map drops it, so a cabinet
    without the sensor gains no entity either way -- which is every cabinet observed so far.
    """
    from haismart_hrdp.features import (
        CLASS_CARRIED_ENUM_FEATURES,
        declared_enum_features,
        read_enum_features,
    )
    from haismart_hrdp.wire_models import related_model_named

    assert CLASS_CARRIED_ENUM_FEATURES["0d12"] == {"humanSensingStatus", "sensingResult"}
    model = {"invisible_attributes": [], "attributes": {"onOffStatus": {}}}
    assert declared_enum_features(model, "0d12") == {"humanSensingStatus", "sensingResult"}

    blob = bytes.fromhex(STATUS_133_PRESENCE_ON)
    wm = related_model_named("related-19+4@25", len(blob), uplus_id=_D12_UPLUS)
    read = read_enum_features(wm, model, blob, "0d12")
    assert read["humanSensingStatus"] == "on"      # the mode the unit is in
    assert "sensingResult" not in read             # 0 = 无此功能, dropped rather than shown
