"""Set up a real config entry for one appliance of every class and look at what comes out.

Validating specs is not the same as running them. Home Assistant rejects a state whose device class
and unit disagree, logs an error for an enum sensor whose value is not in its options, and refuses
an entity with no unique id — none of which a spec-level check sees, and none of which a user of an
appliance nobody here owns could report.

So this builds an entry per device class, feeds it a synthesised report of that class's own length,
and asserts the appliance comes up with entities that hold real values and nothing in the log.

⚠️ The report is synthesised, so this proves the CODE PATH and never the byte map. What proves a
byte map is a capture, and the project holds four: two air conditioners, a heat-pump water heater
and (in the development tree) prior art's washing machine.
"""
from __future__ import annotations

import json

import pytest
from haismart_hrdp.appliance import CLASS_LABELS
from haismart_hrdp.device_model import ATTR_BASE, known_typeids, model_for
from haismart_hrdp.entity_spec import specs_for
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haismart.const import (
    CONF_DEVICE_ID,
    CONF_DIGITAL_MODEL,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_LOCALKEY_VERSION,
    CONF_PRODUCT_CODE,
    CONF_UPLUS_ID,
    DOMAIN,
)

# One typeid per device class, picked by sort order so the choice is stable and not curated.
SAMPLE = sorted(
    {model_for(t).device_class: t for t in sorted(known_typeids(), reverse=True)}.items()
)


def _report(typeid: str) -> bytes:
    """A status report as long as this class's own map describes.

    The payload is a repeating pattern rather than zeros: an all-zero frame reads every enum as its
    first value and every number as its minimum, which is the case least likely to expose a bad
    classification.
    """
    model = model_for(typeid)
    assert model is not None
    words = max(model.extent(), 20)
    body = bytes((i * 7 + 3) & 0xFF for i in range(2 * words + 2))
    head = bytearray(ATTR_BASE)
    head[2:4] = b"\x27\x15"                   # the uSS status-container marker
    head[ATTR_BASE - 4 : ATTR_BASE] = b"\x06\x6d\x01\x00"
    return bytes(head) + body


def _entry(typeid: str) -> MockConfigEntry:
    model = model_for(typeid)
    assert model is not None
    # Every attribute declared, which no real device does -- the upper bound, on purpose.
    digital_model = {
        "attributes": [{"name": f.name, "writable": f.writable} for f in model.fields],
        "alarms": [{"name": n} for n, _ in model.alarms],
    }
    return MockConfigEntry(
        domain=DOMAIN,
        title="Appliance",
        unique_id="A1B2C3D4E5F6",
        data={
            CONF_HOST: "192.168.1.50",
            CONF_DEVICE_ID: "A1B2C3D4E5F6",
            CONF_LOCAL_KEY: "00112233445566778899aabbccddeeff",
            CONF_PRODUCT_CODE: "TESTCODE0",
            CONF_LOCALKEY_VERSION: 4,
            CONF_UPLUS_ID: typeid,
            CONF_DIGITAL_MODEL: json.dumps(digital_model),
        },
    )


async def _setup(hass: HomeAssistant, mock_uss, typeid: str) -> MockConfigEntry:
    report = _report(typeid)
    mock_uss.read.return_value = [report]
    mock_uss.send.baseline = report
    entry = _entry(typeid)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.mark.parametrize(("device_class", "typeid"), SAMPLE, ids=[c for c, _ in SAMPLE])
async def test_an_appliance_of_every_class_sets_up_without_errors(
    hass: HomeAssistant, mock_uss, caplog, device_class: str, typeid: str
) -> None:
    """It loads, it creates entities, and nothing in the log says it went wrong."""
    with caplog.at_level("ERROR"):
        entry = await _setup(hass, mock_uss, typeid)

    assert entry.state is ConfigEntryState.LOADED, CLASS_LABELS.get(device_class)
    errors = [r.message for r in caplog.records if r.levelname == "ERROR"]
    assert not errors, errors[:5]

    registry = er.async_get(hass)
    entities = [e for e in registry.entities.values() if e.config_entry_id == entry.entry_id]
    assert entities, f"{device_class} produced no entities at all"


@pytest.mark.parametrize(("device_class", "typeid"), SAMPLE, ids=[c for c, _ in SAMPLE])
async def test_every_entity_holds_a_state_home_assistant_accepts(
    hass: HomeAssistant, mock_uss, caplog, device_class: str, typeid: str
) -> None:
    """The check a spec-level test cannot make: Home Assistant validating the real state.

    An enum sensor whose value is not among its options, or a measurement whose unit does not match
    its device class, is logged and dropped at write time. Invisible until somebody looks.
    """
    with caplog.at_level("WARNING"):
        entry = await _setup(hass, mock_uss, typeid)

    complaints = [
        r.message
        for r in caplog.records
        if r.levelname in ("ERROR", "WARNING")
        and any(
            token in str(r.message).lower()
            for token in ("device class", "state class", "unit of measurement", "is not a valid")
        )
    ]
    assert not complaints, complaints[:5]

    # And the appliance is actually furnished: for a class whose map places anything, at least one
    # entity must hold a real value rather than every one reading unknown.
    states = [
        hass.states.get(e.entity_id)
        for e in er.async_get(hass).entities.values()
        if e.config_entry_id == entry.entry_id and e.disabled_by is None
    ]
    live = [s for s in states if s and s.state not in ("unknown", "unavailable")]
    model = model_for(typeid)
    if specs_for(model, [{"name": f.name} for f in model.fields]):
        assert live, f"{device_class}: every entity read unknown"


@pytest.mark.parametrize(("device_class", "typeid"), SAMPLE, ids=[c for c, _ in SAMPLE])
async def test_diagnostics_serialise_for_every_class(
    hass: HomeAssistant, mock_uss, device_class: str, typeid: str
) -> None:
    """A diagnostics download is the first thing asked for in a bug report.

    It is also where a value that is fine in memory and not JSON-serialisable brings the whole
    download down -- and for an appliance nobody here owns, that download is the ONLY evidence
    anybody will ever send.
    """
    from custom_components.haismart.diagnostics import async_get_config_entry_diagnostics

    entry = await _setup(hass, mock_uss, typeid)
    data = await async_get_config_entry_diagnostics(hass, entry)
    json.dumps(data)                       # raises if anything in there cannot be serialised
    assert data["appliance"]["device_class"] == device_class
    assert data["appliance"]["kind"]


async def test_an_appliance_with_no_model_yet_still_sets_up(
    hass: HomeAssistant, mock_uss
) -> None:
    """A manually-added appliance has no digital model, so nothing declares anything.

    It must come up anyway, with no generic entities rather than the whole class map -- which is
    the safe direction, and it picks them up when the model arrives.
    """
    typeid = SAMPLE[0][1]
    report = _report(typeid)
    mock_uss.read.return_value = [report]
    entry = _entry(typeid)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, data={k: v for k, v in entry.data.items() if k != CONF_DIGITAL_MODEL}
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.entity_specs == ()


@pytest.mark.parametrize(("device_class", "typeid"), SAMPLE[:8], ids=[c for c, _ in SAMPLE[:8]])
async def test_unload_and_reload_leaves_nothing_behind(
    hass: HomeAssistant, mock_uss, device_class: str, typeid: str
) -> None:
    """Platforms are chosen per entry, so unload must be handed the same list setup used.

    Unloading a platform that was never forwarded leaves its entities behind on every reload, and
    the list differs by appliance kind -- which is exactly the condition that makes this worth
    asserting rather than assuming.
    """
    entry = await _setup(hass, mock_uss, typeid)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


def test_every_shipped_gzip_bundle_is_preloaded_off_the_event_loop() -> None:
    """⛔ Home Assistant flags a blocking `open` on the event loop, and a test suite does not.

    The package ships its big tables as gzip files read behind an `lru_cache`, so the FIRST read
    decompresses — on whichever thread asks. `model_rules` has been warmed in an executor at setup
    since it was added; the byte map was not, because `device_model.preload` was written and never
    called. A running instance reported it on the first poll after deployment:

        Detected blocking call to open … device_models.json.gz inside the event loop

    So this asserts the RULE rather than the two instances: every gzip the package ships must be
    warmed by `async_setup_entry`, and the next one added fails here instead of in somebody's log.
    """
    import inspect
    from pathlib import Path

    import haismart_hrdp

    from custom_components.haismart import async_setup_entry

    package = Path(inspect.getfile(haismart_hrdp)).parent
    bundles = sorted(p.name for p in package.glob("*.json.gz"))
    assert bundles, "the premise: the package ships gzip bundles"

    setup = inspect.getsource(async_setup_entry)
    warmed = setup.count("async_add_executor_job")
    assert warmed >= len(bundles), (
        f"{len(bundles)} gzip bundles ship ({bundles}) but async_setup_entry warms only {warmed}; "
        "an unwarmed one decompresses on the event loop"
    )
