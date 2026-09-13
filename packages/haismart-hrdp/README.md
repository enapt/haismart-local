# haismart-hrdp

Standalone, async, fully-typed Python client for Haier's local **uSS/HRDP** protocol (Haismart / U+
SE-Asia appliances). No Home Assistant coupling, no cloud.

## What it does

- Plaintext handshake on TCP `:56800`, then AES-128-CBC biz-data (key = `MD5(localKey)`).
- **Read:** `read_status` / `async_read_status` → `parse_full_status` decodes power, target / indoor /
  outdoor temperature, mode, fan, swing, and the secondary toggles.
- **Control:** the `grSetDAC` group-set write path (`grsetdac_baseline_from_status` →
  `set_grsetdac_field` → `async_send_op`), where the encoder only emits fields and values in its
  allowlist. Appliances that publish no group-set command are written **one setting at a time**
  instead — a command per attribute, gated on the appliance's own declaration — which is how the
  central cabinets and the compact family are controlled.
- Per-model semantics via `AttributeProfile`, built from the device digital model (`profiles.py`).
  A device declares three or four times what any family map names by hand, and `model_fields` reads
  those too — membership from the device's own model, position from the shared map, the two arrived
  at independently — so no capture is needed per attribute.
- **Several report layouts.** Models pack their attributes into the same word array at different
  offsets; `canonical_map.py` carries the map they share and `wire_models.py` the families that are
  versions of it, so an unfamiliar report is usually a displacement rather than new work. A layout
  that matches none of them is decoded as far as the layout-independent fields allow and flagged
  `partial`, never guessed at — and `probe_layout()` will rank candidates for it.
- **Any appliance category, from the manufacturer's own byte map** (`device_model.py`). Haier
  publishes, per product type, the word/bit/width of every field in a status report plus its scaling,
  enum labels and fault table; a bundle of **165 product types across 36 device classes** ships with
  the library (`device_models.json.gz`), and `model_for(uplus_id)` returns one. `DeviceModel.decode`
  reads a report at those positions — the same base-92 word geometry the air-conditioner path uses —
  and `encode_write` builds a single-parameter write for a field the map marks writable.
  ⛔ `placeable_limit` refuses fields at or past a reserved run the firmware may have omitted: a map
  can describe a longer report than a given firmware sends, and a field placed past the gap reads as
  a plausible, wrong number.
- **What entities an appliance should have** (`entity_spec.py`). Given a model and the device's own
  declaration, `specs_for` returns one spec per field — control kind, English name, unit, device
  class, state class, range, options — with the declaration as the gate, so nothing a unit does not
  declare is offered. Indexed runs of read-only booleans (a schedule grid published as one flag per
  hour) collapse into a single summary rather than 192 entities.
- **What KIND of appliance it is** (`appliance.py`): `kind_for(uplus_id)` from the class field of the
  typeid, `label_for` for its English category name.
- **One decoder, provably** (`ac_view.py`). A shim that produces the air-conditioner state dict from
  the byte map alone, so the hand-derived decoder and the published map can be compared key for key.
  ⓘ Nothing decodes with it yet — it exists to measure the gap before anything is switched over.
- **Discovery + cloud reachability** on UDP `:7083` (`udiscovery.py`): a key-free query that returns a
  unit's deviceId, `uPlusId`, address, firmware — and whether it can currently reach Haier's cloud.
  Needs no localKey and no account.

## Example (read)

```python
import haismart_hrdp as h
blobs = h.read_status("192.168.1.50", "A1B2C3D4E5F6", "<localKey>")
blob = next(b for b in blobs if h.derive_status_layout(b) is not None)
print(h.parse_full_status(blob, h.profile_for("AAC1UKZ01")))
```

## Example (discovery — no key needed)

```python
from haismart_hrdp import udiscovery

info = udiscovery.query("192.168.1.50")
print(info.device_id, info.uplus_id, info.firmware, info.cloud_connected)

# whole-LAN sweep (binds :7083, which the protocol requires for broadcast)
for dev in udiscovery.discover():
    print(dev.device_id, dev.host)
```

## Tests

```bash
python -m pytest
```
