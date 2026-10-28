"""What an appliance IS when nothing here recognises it -- and the question that settles it.

A 0504 washer-dryer was the case that made this matter: no class row, a cloud label nothing read,
and a dryer report whose 165 bytes are also an air-conditioner family's length, so it was given a
thermostat. The catalogue now knows 0504, but the next appliance nobody has catalogued arrives the
same way. So:

* the owner is asked, at setup, when the device identified itself and nothing recognised it;
* "laundry" makes it read-only sensors; "not an air conditioner" withholds the thermostat and the
  AC entity set whatever its report looks like; "decide from its reports" is what happened before;
* an air conditioner set up as most are -- recognised, or saying nothing -- is never asked.
"""
from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haismart.const import (
    CONF_APP_TYPE,
    CONF_APPLIANCE_KIND,
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_LOCALKEY_VERSION,
    CONF_SCAN_INTERVAL,
    CONF_UPLUS_ID,
    DOMAIN,
    KIND_LAUNDRY,
    KIND_NOT_AIR_CONDITIONER,
)

LOCAL_KEY = "00112233445566778899aabbccddeeff"
# A class field (chars 16:20) nobody has catalogued: no kind row, no name, not the laundry family.
UNKNOWN = "201c51890c31c3089a0100218004514845000000000000000000000000000040"
AC = "2008610800820324021200118012560000000000000000000000000000000040"   # class 0212


def _reports(uplus: str):
    from haismart_hrdp.udiscovery import DeviceInfo

    return patch(
        "custom_components.haismart.config_flow.udiscovery.async_query",
        return_value=DeviceInfo(device_id="A1B2C3D4E5F6", host="192.168.1.50", uplus_id=uplus),
    )


async def _manual(hass: HomeAssistant, uplus: str):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "manual"}
    )
    with _reports(uplus):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.1.50", CONF_LOCAL_KEY: LOCAL_KEY}
        )
    if result.get("step_id") == "model":
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"product_code": "skip"}
        )
    return result


async def test_an_unrecognised_appliance_is_asked_about_and_the_answer_is_kept(
    hass: HomeAssistant, mock_uss
) -> None:
    result = await _manual(hass, UNKNOWN)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "appliance_kind"

    done = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_APPLIANCE_KIND: KIND_LAUNDRY}
    )
    await hass.async_block_till_done()
    assert done["type"] == FlowResultType.CREATE_ENTRY
    assert done["data"][CONF_UPLUS_ID] == UNKNOWN
    # An option, not data: it is the owner's to change later.
    assert done["options"] == {CONF_APPLIANCE_KIND: KIND_LAUNDRY}


async def test_a_recognised_air_conditioner_is_never_asked(hass: HomeAssistant, mock_uss) -> None:
    result = await _manual(hass, AC)
    await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert CONF_APPLIANCE_KIND not in result["options"]


def _entry(uplus: str, **options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Mystery appliance",
        unique_id="A1B2C3D4E5F6",
        data={
            CONF_HOST: "192.168.1.50",
            CONF_DEVICE_ID: "A1B2C3D4E5F6",
            CONF_LOCAL_KEY: LOCAL_KEY,
            CONF_LOCALKEY_VERSION: 4,
            CONF_UPLUS_ID: uplus,
        },
        options=options,
    )


async def _domains(hass: HomeAssistant, entry: MockConfigEntry) -> set[str]:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    return {
        e.domain for e in registry.entities.values() if e.config_entry_id == entry.entry_id
    }


async def test_without_an_answer_an_unrecognised_ac_keeps_its_thermostat(
    hass: HomeAssistant, mock_uss
) -> None:
    """The no-regression clause: a report that really decodes as an AC still gets climate."""
    assert "climate" in await _domains(hass, _entry(UNKNOWN))


async def test_not_an_air_conditioner_withholds_the_thermostat_and_the_ac_set(
    hass: HomeAssistant, mock_uss
) -> None:
    """The same AC-shaped report, and no thermostat, no AC switch, nothing the AC set builds."""
    entry = _entry(UNKNOWN, **{CONF_APPLIANCE_KIND: KIND_NOT_AIR_CONDITIONER})
    domains = await _domains(hass, entry)
    assert "climate" not in domains and "switch" not in domains and "select" not in domains
    assert entry.runtime_data.ruled_out_air_conditioner


async def test_laundry_makes_an_unrecognised_appliance_read_only(
    hass: HomeAssistant, mock_uss
) -> None:
    entry = _entry(UNKNOWN, **{CONF_APPLIANCE_KIND: KIND_LAUNDRY})
    assert await _domains(hass, entry) <= {"sensor", "binary_sensor"}
    assert str(entry.runtime_data.appliance_kind) == "laundry"


async def test_an_answer_never_re_types_a_catalogued_appliance(
    hass: HomeAssistant, mock_uss
) -> None:
    """A stale or hand-edited answer on an AC is ignored: the class field settles what it is."""
    entry = _entry(AC, **{CONF_APPLIANCE_KIND: KIND_LAUNDRY})
    domains = await _domains(hass, entry)
    assert "climate" in domains
    assert str(entry.runtime_data.appliance_kind) == "air_conditioner"
    assert not entry.runtime_data.ruled_out_air_conditioner


async def test_a_laundry_label_from_the_cloud_needs_no_question(
    hass: HomeAssistant, mock_uss
) -> None:
    """Haier's device list calls the 0504 laundry centre "Roller Washer"; that is enough."""
    entry = _entry(UNKNOWN)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_APP_TYPE: "Roller Washer"}
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert str(entry.runtime_data.appliance_kind) == "laundry"


async def test_the_options_offer_the_question_only_where_it_is_open(
    hass: HomeAssistant, mock_uss
) -> None:
    for uplus, offered in ((UNKNOWN, True), (AC, False)):
        entry = _entry(uplus)
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        form = await hass.config_entries.options.async_init(entry.entry_id)
        assert (CONF_APPLIANCE_KIND in form["data_schema"].schema) is offered, uplus
        if offered:
            done = await hass.config_entries.options.async_configure(
                form["flow_id"],
                {CONF_APPLIANCE_KIND: KIND_NOT_AIR_CONDITIONER, CONF_SCAN_INTERVAL: 30},
            )
            assert done["type"] == FlowResultType.CREATE_ENTRY
            assert entry.options[CONF_APPLIANCE_KIND] == KIND_NOT_AIR_CONDITIONER
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()


async def test_changing_the_answer_removes_what_the_appliance_no_longer_has(
    hass: HomeAssistant, mock_uss
) -> None:
    """No unavailable thermostat or AC switch left behind: the 0504 unit was left with 13."""
    entry = _entry(UNKNOWN)
    assert "climate" in await _domains(hass, entry)
    hass.config_entries.async_update_entry(entry, options={CONF_APPLIANCE_KIND: KIND_LAUNDRY})
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    left = {e.domain for e in registry.entities.values() if e.config_entry_id == entry.entry_id}
    assert left <= {"sensor", "binary_sensor"}, left
    for row in er.async_entries_for_config_entry(registry, entry.entry_id):
        if row.disabled_by is None:     # a disabled row has no entity by design, and is kept
            assert hass.states.get(row.entity_id) is not None, f"{row.entity_id}: no entity"


async def test_an_air_conditioner_keeps_every_row_it_had(hass: HomeAssistant, mock_uss) -> None:
    """⛔ The cleanup never runs for an AC: a row it stopped creating is left as it always was."""
    entry = _entry(AC)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    ghost = registry.async_get_or_create(
        "switch", DOMAIN, "A1B2C3D4E5F6_not_built_today", config_entry=entry
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(ghost.entity_id) is not None


async def test_an_answer_overrules_a_laundry_label_but_not_a_class(
    hass: HomeAssistant, mock_uss
) -> None:
    """A label can be wrong ("Hand Dryer"), so the owner can overrule it; a class cannot be."""
    entry = _entry(UNKNOWN, **{CONF_APPLIANCE_KIND: KIND_NOT_AIR_CONDITIONER})
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_APP_TYPE: "Hand Dryer"})
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert str(entry.runtime_data.appliance_kind) == "other"
    assert entry.runtime_data.ruled_out_air_conditioner
    assert "climate" not in {
        e.domain for e in er.async_get(hass).entities.values()
        if e.config_entry_id == entry.entry_id
    }


async def test_the_question_leaves_the_options_once_the_class_settles_it(
    hass: HomeAssistant, mock_uss
) -> None:
    """An old answer on what turned out to be an AC is neither offered nor lost."""
    entry = _entry(AC, **{CONF_APPLIANCE_KIND: KIND_LAUNDRY, CONF_SCAN_INTERVAL: 30})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    form = await hass.config_entries.options.async_init(entry.entry_id)
    assert CONF_APPLIANCE_KIND not in form["data_schema"].schema
    await hass.config_entries.options.async_configure(form["flow_id"], {CONF_SCAN_INTERVAL: 60})
    await hass.async_block_till_done()
    assert entry.options == {CONF_APPLIANCE_KIND: KIND_LAUNDRY, CONF_SCAN_INTERVAL: 60}
