"""Cloud client for Haier's SE-Asia cloud: account token refresh + device list / digital model.

Device-center request signing::

    sign = SHA-256_hex_lowercase( path + stripWs(body) + appId + appKey + timestamp )

Endpoints (host ``uhome-sea.haieriot.net`` / ``uhome-sgp.haieriot.net``):
  - device list:  ``/dcs/device-service-2c/get/user/device-list``  (+ ``/dcs/device-info/device/aggregate-query``)
  - device model: ``/dcs/device-service-2c/get/device/model-info/find/info``
  - token refresh: ``POST /uplussea/accounts/v1/user/refreshToken`` (device-center envelope + ``zoneInfo``
    header) -> a fresh ``accountToken``. The ``refreshToken`` is a durable, reusable credential: one account
    sign-in provisions it, and this mints access tokens as needed.

The per-device ``localKey`` itself is fetched over the cloud MQTT gateway — see
:mod:`haismart_extractor.gateway`.

The HTTP transport is injectable, so this module is unit-testable with no network (tests pass a fake
transport); at runtime it uses httpx.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
import weakref
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from cryptography.hazmat.primitives.serialization import load_der_public_key

# --- signing ------------------------------------------------


def _strip_ws(text: str) -> str:
    # SignUtil strips space, tab, CR, LF from the body before hashing .
    return text.replace(" ", "").replace("\t", "").replace("\r", "").replace("\n", "")


def device_center_sign_payload(
    app_id: str, app_key: str, timestamp: str, body: str, path: str
) -> str:
    """The exact pre-hash string for a device-center call. Exposed for golden tests."""
    return path + _strip_ws(body) + app_id + app_key.strip().replace('"', "") + timestamp


def device_center_sign(
    app_id: str, app_key: str, timestamp: str, body: str, path: str
) -> str:
    payload = device_center_sign_payload(app_id, app_key, timestamp, body, path)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --- account email/password login ---
#
# The real SE-Asia login, verified
# (returns retCode 00000 + tokens):
#   POST  https://uhome-sea.haieriot.net/uplussea/accounts/v2/login
#   body  {"username": <email or phone>, "password": <AES>, "sesame": <RSA-wrapped AES key>}
#   sign  the SAME device-center sign as every other call (SHA-256(path + stripped-body + appId + appKey +
#         timestamp)) — appId/appKey are the shipped app creds (MB-SHEYJDNYB-0001 / 5ff4067f…).
#   resp  {retCode:"00000", data:{tokenInfo:{accountToken/uhomeAccessToken, refreshToken, uhomeUserId,…}}}
#
# It's a hybrid scheme (H5 module `D`): a fresh 16-digit random key `k` is generated; the password is
# AES-128-CBC/PKCS7-encrypted with key==iv==k (the 16 ASCII digits), and `k` itself is RSA/PKCS1-v1.5
# encrypted into ``sesame`` (the server RSA-decrypts k, then AES-decrypts the password). Base64 throughout.
LOGIN_PATH = "/uplussea/accounts/v2/login"
LOGIN_HOST = "uhome-sea.haieriot.net"
# app-global RSA-1024 public key (SubjectPublicKeyInfo, base64) the H5 login wraps the AES key with.
LOGIN_PUBKEY_B64 = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCpBUQQP/sCtV6UK4mDD6Qr3OKMuWhVuc7OXj+YHNyTGip0jXR1"
    "PSMPshC6fql/GPMUMhZ2Ler/Yf5UihrgNkQsPK1ePu2lBntZp9B5tJza58fCKDtLeSvU6Z+VgFQsjJ9dcv0sw7P8"
    "EH5HhvXTCcckpqCGMmIBiur59U06GJIQMQIDAQAB"
)


def encrypt_login_password(
    password: str, key: str | None = None, pubkey_b64: str = LOGIN_PUBKEY_B64
) -> tuple[str, str]:
    """Build the login ``(password, sesame)`` pair exactly as the app's H5 login does.

    A fresh 16-digit random ``key`` is used as **both** the AES-128 key and IV (its ASCII bytes);
    ``password = Base64(AES-128-CBC/PKCS7(key, iv=key, plaintext))`` and
    ``sesame = Base64(RSA-PKCS1v15(pubkey, key))`` — the RSA-wrapped AES key the server unwraps to decrypt
    the password. ``key`` is normally random (pass one only for deterministic tests).
    """
    k = key or "".join(secrets.choice("0123456789") for _ in range(16))
    kb = k.encode("utf-8")  # 16 ASCII bytes → AES-128 key AND iv
    padder = PKCS7(128).padder()
    padded = padder.update(password.encode("utf-8")) + padder.finalize()
    enc = Cipher(algorithms.AES(kb), modes.CBC(kb)).encryptor()
    pw_field = base64.b64encode(enc.update(padded) + enc.finalize()).decode("ascii")
    pub = load_der_public_key(base64.b64decode(pubkey_b64))
    sesame = base64.b64encode(pub.encrypt(kb, asym_padding.PKCS1v15())).decode("ascii")
    return pw_field, sesame


# --- config --------------------------------------------------------------------


@dataclass(frozen=True)
class AppCredentials:
    """The app's own identity used to sign requests. Same for every user; shipped as
    the `SEA_APP_CREDENTIALS` constant."""

    app_id: str
    app_key: str
    client_id: str
    app_version: str = "5.5.0"


@dataclass(frozen=True)
class RefreshResult:
    """Result of the account refreshToken exchange.

    ``access_token`` is the response's ``accountToken`` (a fresh, ~10-day access token). ``refresh_token``
    is returned **unchanged** (it is reusable — a durable credential to keep)."""

    access_token: str
    refresh_token: str
    expires_in: int = 0
    uhome_user_id: str = ""
    scope: str = ""
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_response(cls, resp: dict) -> RefreshResult:
        d = resp.get("data") if isinstance(resp.get("data"), dict) else resp
        # SEA wraps tokens under data.tokenInfo, exactly as on login. Without this unwrapping a
        # nested response yielded access_token="" and the client then OVERWROTE its working token
        # with the empty string, turning every later call into a 401 that the class docstring
        # misattributes to a wrong client_id.
        if isinstance(d.get("tokenInfo"), dict):
            d = d["tokenInfo"]
        return cls(
            access_token=d.get("accountToken") or d.get("uhomeAccessToken") or d.get("accessToken", ""),
            refresh_token=d.get("refreshToken", ""),
            expires_in=int(d.get("expiresIn") or 0),
            uhome_user_id=str(d.get("uhomeUserId") or d.get("uHomeUserId") or ""),
            scope=d.get("scope", ""),
            raw=d,
        )


# The appliance types the product catalogue files air conditioners under.
AC_APP_TYPE_CODES = ("A120", "A177", "A178")   # central / wall mounted / floor standing


@dataclass(frozen=True)
class CatalogueProduct:
    """One row of the published product catalogue: the join between a **model number** printed on an
    appliance and the **product code** its rules are keyed by.

    That join exists nowhere else. A product code is opaque and an appliance never announces one, so
    a catalogue row is the only route from what an owner can read off a label to what the rule
    layer needs.
    """

    product_code: str
    model: str
    app_type: str = ""
    app_type_name: str = ""
    brand: str = ""


@dataclass(frozen=True)
class LoginResult:
    """Result of an email/password account login (`HaierCloud.login`).

    ``access_token`` is the **uHome** access token used for device-center calls; ``refresh_token`` is the
    durable, reusable token to persist (HA stores it and mints access tokens from it thereafter).
    ``client_id`` is the per-install uSDK CLIENTID chosen at login — the token is bound to it, so it
    must be reused for every subsequent device-center call and to derive the gateway clientId.
    """

    access_token: str
    refresh_token: str
    client_id: str
    uhome_user_id: str = ""
    expires_in: int = 0
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_response(cls, resp: dict, *, client_id: str) -> LoginResult:
        d = resp.get("data") if isinstance(resp.get("data"), dict) else resp
        # SEA wraps the tokens under data.tokenInfo; some responses put them directly under data.
        if isinstance(d.get("tokenInfo"), dict):
            d = d["tokenInfo"]
        return cls(
            # uHome token drives device calls; accept camelCase (SEA), snake_case, and accountToken.
            access_token=(
                d.get("uhomeAccessToken") or d.get("uhome_access_token")
                or d.get("accountToken") or d.get("access_token", "")
            ),
            refresh_token=d.get("refreshToken") or d.get("refresh_token", ""),
            client_id=client_id,
            uhome_user_id=str(d.get("uhomeUserId") or d.get("uhome_user_id") or ""),
            expires_in=int(d.get("expiresIn") or d.get("expires_in") or 0),
            raw=d,
        )


@dataclass(frozen=True)
class CloudDevice:
    """A device from the account device list, for config-flow discovery.

    ``uplus_id`` is the device-list ``wifiType`` field (the full uPlusId used for the digital model)."""

    device_id: str
    name: str
    device_type: str = ""
    uplus_id: str = ""
    online: bool = False
    # From the device list's `extendedInfo`, which used to be discarded entirely. `prod_no` is the
    # real product code (e.g. "AACRL2E00") — without it the integration had nothing to go on and
    # stamped a hardcoded default on every device, so a heat-capable unit was labelled as a
    # cooling-only one. `model` is the human-readable name ("PRO X INV-42/3PH").
    prod_no: str = ""
    model: str = ""
    brand: str = ""
    app_type_name: str = ""


# The SE-Asia app-level identity — constants that are the same for every install (the same credential
# model the `hon` / `pyhOn` integrations use). `client_id` decodes to "uplusseaappadrd"
# (uplus-sea-app-android). Every field is overridable from the environment via HAISMART_APP_* vars.
SEA_APP_CREDENTIALS = AppCredentials(
    app_id=os.environ.get("HAISMART_APP_ID", "MB-SHEYJDNYB-0001"),
    app_key=os.environ.get("HAISMART_APP_KEY", "5ff4067f62705b9f205ed5277648de3a"),
    client_id=os.environ.get("HAISMART_CLIENT_ID", "uplusseaappadrd"),
    app_version=os.environ.get("HAISMART_APP_VERSION", "5.5.0"),
)


@dataclass(frozen=True)
class Domains:
    """SE-Asia cloud hosts.

    ``uhome`` is the Singapore host: the device API is
    ``uhome-sgp.haieriot.net`` with ``/uplussea/...`` paths, reached with the device-center header
    envelope below (NOT OAuth Bearer — a Bearer-only request 403s "appId cannot be empty"). The old
    ``uhome-sea`` + ``/dcs/...`` map 404s; see ``DEVICE_LIST_PATH_V2``.
    """

    account: str = "account-api.haier.net"
    uhome: str = "uhome-sgp.haieriot.net"
    uws: str = "uws-sgp.haieriot.net"  # verified for the digital-model /shadow/ endpoint
    login: str = "uhome-sea.haieriot.net"  # verified SE-Asia account login host (/uplussea/accounts/*)


# --- endpoints (paths confirmed present in the app; host per Domains) -------

# verified device-list path on uhome-sgp: returns HTTP 401 retCode 21016
# ("Token not created by this terminal") with a valid device-center envelope — i.e. the endpoint +
# host + header envelope + signing are all ACCEPTED; only the account token's terminal-binding fails.
# GET works; the request body is empty. This is the known-good path to validate a token against.
DEVICE_LIST_PATH_V2 = "/uplussea/devices/v2/user/devices"

# Alternate device-center `/dcs/` paths (404 on uhome-sgp; kept for reference):
DEVICE_LIST_PATH = "/dcs/device-service-2c/get/user/device-list"
DEVICE_LIST_PATH_ALT = "/dcs/device-info/device/aggregate-query"
DEVICE_MODEL_PATH = "/dcs/device-service-2c/get/device/model-info/find/info"
# The model-picker's catalogue: model number + product code for everything the region publishes.
PRODUCT_SEARCH_PATH = "/uplussea/devices/v3/prods/global/search"

# Device digital model ("constraintfile") — the queryable per-model attribute spec (valueRanges/enums)
# the app downloads at bind time. Verified on-device (up_http_plugin.db / uplus-resource-database2.db).
DEVICE_CONFIG_HOST = "resource-sea.haieriot.net"
DEVICE_CONFIG_PATH = "/download/resource/selfService/hardware/constraintfile/{name}"
# A device model is not fetched by guessing a filename: it is looked up in the account's resource
# service, which answers with the URL to download (the filename carries a build stamp no caller can
# construct) plus that file's version and MD5. ``model`` and ``typeId`` are both sent — the lookup
# returns nothing for either alone — and ``typeId`` is the uPlusId, not the deviceType. The listing
# is scoped to the ACCOUNT, though, not to those two fields: it answers with the configs published
# for the caller's own devices whatever is asked for, so the response has to be selected from.
DEVICE_CONFIG_LIST_PATH = "/uplussea/resources/v1/conf/list"
DEVICE_CONFIG_RES_TYPE = "DeviceConfig"

# The same model, published a second way: a catalogue keyed on product code that needs no account.
# `get_device_config` above can only ever answer for the caller's OWN devices; this one answers for
# any product code, which is what an install with no cloud credentials needs, and what makes a bug
# report from a device nobody here owns usable.
PUBLIC_CONFIG_URL = "https://standardcfm.haigeek.com/hardwareconfig/app/resource/logicLimit"

# The catalogue publishes an older, parallel schema. Sections whose INNER shape already matches are
# renamed; the two rule sections are ADAPTED, because renaming alone silently produces rules that
# match nothing.
#
# The catalogue is the only source of these rules for a device nobody here owns -- the account-scoped
# fetch answers with the caller's own devices whatever it is asked -- so dropping them meant every
# reporter's family got its attribute list and no conditional availability at all.
PUBLIC_CONFIG_SECTIONS = {
    "alarm": "alarms",
    "basicInfo": "baseInfo",
}

# The catalogue carries one section the account-scoped model leaves empty: what each lock rule's
# reason code means. It is a flat code -> sentence list, so it needs no adaptation beyond becoming a
# mapping, and it is the only place either source states why a control has gone unavailable.
PUBLIC_CONFIG_REASONS_SECTION = "invalidInfo"

# Sections whose inner schema has not been adapted. Dropped, not renamed.
PUBLIC_CONFIG_UNADAPTED = ("operation",)


def _adapt_logic_limit(entries: Any) -> list[dict]:
    """The catalogue's conditional-writability rules, in the shape the rules engine reads.

    Catalogue: ``{priority, trigger:{relation, condition:[{name, value[], invalidCode}] |
    alarm:[{name, invalidCode}]}, action:[{name, writable}]}``. The engine wants
    ``{priority, trigger:{operator, conditions:{name: [values]}, alarms:[names]}, actions:[...]}``
    plus the reason code the rule fires with.
    """
    out: list[dict] = []
    for e in entries or ():
        if not isinstance(e, Mapping):
            continue
        trigger = e.get("trigger") or {}
        conditions = {
            str(c["name"]): [str(v) for v in (c.get("value") or [])]
            for c in (trigger.get("condition") or ()) if isinstance(c, Mapping) and c.get("name")
        }
        alarms = [str(a["name"]) for a in (trigger.get("alarm") or ())
                  if isinstance(a, Mapping) and a.get("name")]
        # The reason code appears in EITHER place depending on the rule: on the trigger itself, or
        # on each of its conditions. Reading only one of the two silently produced rules that lock
        # correctly and explain nothing.
        code = str(trigger.get("invalidCode") or "")
        if not code:
            for item in list(trigger.get("condition") or ()) + list(trigger.get("alarm") or ()):
                if isinstance(item, Mapping) and item.get("invalidCode"):
                    code = str(item["invalidCode"])
                    break
        actions = [{"name": str(a["name"]), "writable": a.get("writable", False)}
                   for a in (e.get("action") or ()) if isinstance(a, Mapping) and a.get("name")]
        if not actions or not (conditions or alarms):
            continue
        rule: dict[str, Any] = {
            "priority": e.get("priority"),
            "trigger": {"operator": str(trigger.get("relation") or "AND").upper()},
            "actions": actions,
        }
        if conditions:
            rule["trigger"]["conditions"] = conditions
        if alarms:
            rule["trigger"]["alarms"] = alarms
        if code:
            rule["invalid_code"] = code
        out.append(rule)
    return out


def _adapt_logic_patch(entries: Any) -> list[dict]:
    """The catalogue's co-command rules, in the shape the co-command engine reads.

    Catalogue: ``{actionType, trigger:{relation, requestParam:{property:[{name, variants:
    {enumList:[{stdValue}]}}]}}, action:[{param:[{name, value}]}]}``. The engine wants
    ``{pendingCondition:{operator, commands:{name: [values]}}, additionalCommands:{mergeType,
    commands:[{name, value}]}}``.
    """
    out: list[dict] = []
    for e in entries or ():
        if not isinstance(e, Mapping):
            continue
        trigger = e.get("trigger") or {}
        req = (trigger.get("requestParam") or {}).get("property") or ()
        commands: dict[str, list[str]] = {}
        for prop in req:
            if not isinstance(prop, Mapping) or not prop.get("name"):
                continue
            values = [str(v["stdValue"]) for v in
                      ((prop.get("variants") or {}).get("enumList") or ())
                      if isinstance(v, Mapping) and v.get("stdValue") is not None]
            commands[str(prop["name"])] = values
        params: list[dict] = []
        for act in (e.get("action") or ()):
            if isinstance(act, Mapping):
                params += [{"name": str(p["name"]), "value": str(p.get("value"))}
                           for p in (act.get("param") or ())
                           if isinstance(p, Mapping) and p.get("name")]
        if not commands or not params:
            continue
        out.append({
            "pendingCondition": {
                "operator": str(trigger.get("relation") or "AND").upper(),
                "commands": commands,
            },
            "additionalCommands": {
                "mergeType": str(e.get("actionType") or "APPEND").upper(),
                "commands": params,
            },
        })
    return out


# How the catalogue spells an attribute's permitted values, against the account model's
# ``valueRange``. Enumerated over every published air-conditioner model (4051 attributes across 171
# products): exactly four ``dataType``\\ s, each paired with exactly one variant kind,
# with no attribute missing its ``variants`` and no pairing ever crossed. So this table is the whole
# vocabulary rather than the part that happened to be looked for.
#
#   bool   -> boolList   [{stdValue, description}]     -> LIST
#   enum   -> enumList   [{stdValue, description}]     -> LIST
#   int    -> intStep    {minValue, maxValue, step, unit} -> STEP
#   double -> doubleStep {minValue, maxValue, step, unit} -> STEP
_VARIANT_LIST_KINDS = ("enumList", "boolList")
_VARIANT_STEP_KINDS = (("doubleStep", "Double"), ("intStep", "Int"))


def _value_range_from_variants(variants: Any) -> dict | None:
    """One attribute's ``variants`` as the ``valueRange`` every consumer here already reads.

    Returns ``None`` when nothing recognisable is present, which leaves the attribute without a
    ``valueRange`` -- and that is the safe outcome, because :func:`validate_write` refuses a write it
    cannot bound. Inventing a permissive range would be the one genuinely dangerous way to fail.
    """
    if not isinstance(variants, Mapping):
        return None
    for kind in _VARIANT_LIST_KINDS:
        items = variants.get(kind)
        if isinstance(items, list):
            # ``desc`` is load-bearing, not decoration: an enum code the Haier-wide STD table does
            # not know is resolved by keyword against exactly this text before it is dropped.
            return {
                "type": "LIST",
                "dataList": [
                    {"data": str(i["stdValue"]), "desc": str(i.get("description") or "")}
                    for i in items
                    if isinstance(i, Mapping) and i.get("stdValue") is not None
                ],
            }
    for kind, data_type in _VARIANT_STEP_KINDS:
        step = variants.get(kind)
        if isinstance(step, Mapping):
            # Bounds are stringified because that is how the account model states them and both
            # readers float() them; keeping one spelling means a test can compare the two sources
            # for equality rather than for equivalence.
            out: dict[str, Any] = {"dataType": data_type}
            for field in ("minValue", "maxValue", "step"):
                if step.get(field) is not None:
                    out[field] = str(step[field])
            if step.get("unit"):
                # Not in the account model, and read by nothing -- but it is real information about
                # the attribute, and discarding it to make the two dicts diff clean would be the
                # wrong way round.
                out["unit"] = str(step["unit"])
            return {"type": "STEP", "dataStep": out}
    return None


def _adapt_property(entries: Any) -> list[dict]:
    """The catalogue's attribute list in the account model's spelling.

    Renaming ``property`` to ``attributes`` was never enough: the two sources describe an
    attribute's permitted values completely differently, and everything downstream --
    ``profile_from_device_config``, ``model_enum_codes``, ``validate_write`` -- reads only the
    account spelling. Until this existed, a hand-configured install fetched its published model,
    stored it, and then silently discarded it ("stored digital model is unusable; using the
    hardcoded profile"), so an appliance with no hardcoded profile of its own got a generic one.
    Confirmed on hardware, onboarding an appliance with no account configured.

    Only the keys that differ are touched; everything else is carried through untouched, so a field
    this does not know about survives rather than being dropped.
    """
    out: list[dict] = []
    for entry in entries or ():
        if not isinstance(entry, Mapping) or not entry.get("name"):
            continue
        attr = {k: v for k, v in entry.items() if k not in ("variants", "description", "writeType")}
        if (desc := entry.get("description")) is not None:
            attr["desc"] = desc
        if (write_type := entry.get("writeType")) is not None:
            # Same I/G/IG vocabulary under the two names. Read by nothing here today; carried so the
            # two sources stay comparable and so it is there when something wants it.
            attr["operationType"] = write_type
        if (value_range := _value_range_from_variants(entry.get("variants"))) is not None:
            attr["valueRange"] = value_range
        out.append(attr)
    return out


# Rule sections that need their inner shape translated, not merely renamed.
PUBLIC_CONFIG_ADAPTERS = {
    "property": ("attributes", _adapt_property),
    "logicLimit": ("modifiers", _adapt_logic_limit),
    "logicPatch": ("constraints", _adapt_logic_patch),
}

# Field renames INSIDE a carried section, where the two schemas differ only by name.
PUBLIC_CONFIG_FIELD_RENAMES = {"alarms": {"description": "desc"}}


def normalize_public_config(doc: Mapping[str, Any]) -> dict:
    """Rename the catalogue's sections to the ones every consumer here already speaks.

    The publicly catalogued model and the account-scoped one are the same model in two spellings:
    ``property``/``logicLimit``/``logicPatch``/``alarm`` against
    ``attributes``/``modifiers``/``constraints``/``alarms``. Renaming here means
    :func:`haismart_hrdp.device_rules.merge_rules` and everything after it stays unaware there are
    two sources. A section already carrying the modern name is left alone, and anything unrecognised
    is passed through untouched rather than dropped.
    """
    out: dict[str, Any] = {}
    for key, value in doc.items():
        if key in PUBLIC_CONFIG_UNADAPTED:
            continue
        if key == PUBLIC_CONFIG_REASONS_SECTION:
            # code -> sentence. Entries without both are skipped rather than half-carried: a reason
            # is for display, so a malformed one must never reach a user, and never affects a lock.
            out["invalid_reasons"] = {
                str(item["code"]): str(item["description"])
                for item in value or ()
                if isinstance(item, Mapping) and item.get("code") and item.get("description")
            }
            continue
        if key in PUBLIC_CONFIG_ADAPTERS:
            target, adapt = PUBLIC_CONFIG_ADAPTERS[key]
            out[target] = adapt(value)
            continue
        name = PUBLIC_CONFIG_SECTIONS.get(key, key)
        renames = PUBLIC_CONFIG_FIELD_RENAMES.get(name)
        if renames and isinstance(value, list):
            value = [
                {renames.get(k, k): v for k, v in item.items()}
                if isinstance(item, Mapping) else item
                for item in value
            ]
        out[name] = value
    return out


async def get_public_device_config(
    product_code: str, *, transport: Transport | None = None
) -> dict:
    """A device's published model, by product code, **with no account and no token**.

    Two steps, like the account-scoped fetch: the catalogue is asked for the product code and
    answers with a download URL, a version and an MD5; the file is then fetched and its signature
    prefix stripped. Sections are renamed to the modern spelling on the way out
    (:func:`normalize_public_config`).

    This is a genuine catalogue rather than a listing of the caller's own devices, so it answers for
    hardware nobody here owns -- which is what makes it useful for a bug report, and for an install
    that was set up by hand and has no cloud credentials at all. It carries the attributes and their
    ranges, the ``alarms``, and -- the part that matters most -- the ``invisible`` flags that say
    which of a generic model's attributes a given unit actually has.

    ⚠️ It does **not** carry the conditional rules. Its rule sections use a different inner schema
    from the account-scoped model's, and renaming them without adapting them yields rules that parse
    to nothing, so they are dropped instead (see :data:`PUBLIC_CONFIG_UNADAPTED`). A device fetched
    this way therefore gets its feature set but no conditional availability, which locks nothing --
    the safe direction.

    ⚠️ It carries **no wire positions** -- there is no ``startWord``/``startBit`` anywhere in it. It
    is the semantic model, never the byte map.

    An unknown product code is reported as success with an empty URL rather than as an error, so
    that case raises here. Raises :class:`CloudError` on anything else that goes wrong.
    """
    send = transport or _httpx_transport
    body = json.dumps({"productCode": product_code}, separators=(",", ":"))
    resp = await send(
        Request("POST", PUBLIC_CONFIG_URL, {"Content-Type": "application/json"}, body)
    )
    if resp.status != 200:
        raise CloudError(f"public device config -> HTTP {resp.status}")
    payload = json.loads(resp.text or "{}")
    if str(payload.get("retCode")) != "00000":
        raise CloudError(
            f"public device config -> retCode {payload.get('retCode')}: {payload.get('retInfo')}"
        )
    data = payload.get("data") or {}
    url = data.get("url")
    if not url:
        # The catalogue answers 00000 with an empty url for a product code it has never heard of,
        # so success is not enough to go on.
        raise CloudError(f"no published model for product code {product_code!r}")
    got = await send(Request("GET", url, {}, ""))
    if got.status != 200:
        raise CloudError(f"public device config download -> HTTP {got.status}")
    digest = data.get("md5")
    if digest and hashlib.md5(got.text.encode()).hexdigest() != digest:
        raise CloudError("public device config download does not match its published MD5")
    return normalize_public_config(strip_signed_config(got.text))


def strip_signed_config(text: str) -> dict:
    """A cached ``*.signed.json`` is a 64-hex-char signature prefix followed by the JSON object."""
    body = text[64:] if len(text) > 64 and all(c in "0123456789abcdef" for c in text[:64]) else text
    start = body.find("{")
    return json.loads(body[start:] if start >= 0 else body)


# Account/token layer (SE-Asia). NOTE: this is the OAuth/account layer, a *different*
# auth than the device-center sign — the exact body is unconfirmed (marked in `refresh_token`).
ACCOUNT_REFRESH_PATH = "/uplussea/accounts/v1/user/refreshToken"


@dataclass(frozen=True)
class LocalKey:
    """A per-device localKey + its server version (`{"localkey":"%s","localkey_vers":%d}`)."""

    key: str
    version: int | None = None


# --- transport (injectable) ----------------------------------------------------


@dataclass
class Request:
    method: str
    url: str
    headers: dict[str, str]
    body: str


@dataclass
class Response:
    status: int
    text: str

    def json(self) -> dict:
        """Parse the body, raising :class:`CloudError` rather than ``JSONDecodeError``.

        A captive portal or proxy that answers HTTP 200 with HTML would otherwise raise a bare
        ``ValueError`` that escapes every ``except CloudError`` in the callers.
        """
        if not self.text:
            return {}
        try:
            return json.loads(self.text)
        except ValueError as err:
            raise CloudError(f"response was not JSON (HTTP {self.status}): {self.text[:200]}") from err


Transport = Callable[[Request], Awaitable[Response]]


HTTP_TIMEOUT = 15.0

# One shared httpx client per event loop. Constructing a client loads the CA bundle from DISK, which
# blocks — Home Assistant flags exactly that ("blocking call to load_verify_locations inside the event
# loop"), so the client is built in a worker thread and then reused instead of per request. Hosts that
# already own a client should inject it with :func:`httpx_transport` and skip this entirely.
_CLIENTS: weakref.WeakKeyDictionary[Any, Any] = weakref.WeakKeyDictionary()
_CLIENTS_LOCK = asyncio.Lock()


def httpx_transport(client: Any) -> Transport:
    """Wrap an existing ``httpx.AsyncClient`` as a :data:`Transport`.

    The way to plug this client into an async host application: pass the host's own long-lived client
    (in Home Assistant, ``homeassistant.helpers.httpx_client.get_async_client(hass)``) so no SSL
    context is ever built on the event loop and connections are pooled with the rest of the host's.
    """
    async def _transport(req: Request) -> Response:
        resp = await client.request(
            req.method,
            req.url,
            headers=req.headers,
            content=req.body.encode("utf-8"),
            timeout=HTTP_TIMEOUT,
        )
        return Response(status=resp.status_code, text=resp.text)

    return _transport


async def _async_default_client():  # pragma: no cover - needs httpx
    """The per-loop shared client, constructed off-loop on first use (see :data:`_CLIENTS`)."""
    try:
        import httpx
    except ImportError as err:
        raise RuntimeError("pip install httpx to use the default transport") from err
    loop = asyncio.get_running_loop()
    if (client := _CLIENTS.get(loop)) is not None:
        return client
    async with _CLIENTS_LOCK:
        if (client := _CLIENTS.get(loop)) is not None:  # built while we waited
            return client
        client = await loop.run_in_executor(
            None, lambda: httpx.AsyncClient(timeout=HTTP_TIMEOUT)
        )
        _CLIENTS[loop] = client
        return client


async def _httpx_transport(req: Request) -> Response:  # pragma: no cover - needs network + httpx
    return await httpx_transport(await _async_default_client())(req)


# --- client --------------------------------------------------------------------


class HaierCloud:
    """Device-center signed cloud client. Construct with app credentials + an account access token.

    Get a token via **email/password** with :meth:`login` (reproduces the account SDK's
    `/uam/v1/security/login`), or supply a `refreshToken` you already hold and mint an access token with
    :meth:`refresh_token`. Social logins (Google/Facebook) have no password to sign in with — those owners
    share their AC to a throwaway email/password account and log in with that.

    ⚠️ **`credentials.client_id` MUST be a per-install uSDK CLIENTID, not the app-level clientId.**
    The account token is bound to the terminal identified by that per-install client (a 32-hex value like
    `A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4`); :meth:`login` generates one. Sending the app clientId
    `uplusseaappadrd` instead yields
    HTTP 401 retCode 21016 ("Token not created by this terminal"); sending the per-install CLIENTID
    yields HTTP 200 on `DEVICE_LIST_PATH_V2`. (The sign does not cover clientId, so this is safe to set.)
    """

    def __init__(
        self,
        credentials: AppCredentials,
        access_token: str,
        *,
        zone_info: str = "0",
        domains: Domains | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.creds = credentials
        self.access_token = access_token
        # `zoneInfo` is the account's region code; REQUIRED for the account/refreshToken call
        # (its absence gives retCode 30003 "Authorization exception").
        self.zone_info = zone_info
        self.domains = domains or Domains()
        self._transport = transport or _httpx_transport

    # -- request pipeline (device-center signed) --
    def _headers(self, path: str, body: str, timestamp: str) -> dict[str, str]:
        sign = device_center_sign(
            self.creds.app_id, self.creds.app_key, timestamp, body, path
        )
        return {
            "appId": self.creds.app_id,
            "appVersion": self.creds.app_version,
            "apiVersion": "v1",
            "clientId": self.creds.client_id,
            "sequenceId": timestamp + "000010",
            "accessToken": self.access_token,
            "sign": sign,
            "timestamp": timestamp,
            "language": "en-us",
            "timezone": "8",
            "zoneInfo": self.zone_info,
            "Content-Type": "application/json;charset=UTF-8",
        }

    async def post(self, host: str, path: str, payload: dict) -> dict:
        """POST a device-center-signed JSON request; returns the parsed response."""
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        url = f"https://{host}{path}"
        timestamp = str(int(time.time() * 1000))
        headers = self._headers(urlsplit(url).path, body, timestamp)
        resp = await self._transport(Request("POST", url, headers, body))
        if resp.status != 200:
            raise CloudError(f"{path} -> HTTP {resp.status}: {resp.text[:200]}")
        return resp.json()

    async def get(self, host: str, path: str) -> dict:
        """GET a device-center-signed request (empty body); returns the parsed response."""
        url = f"https://{host}{path}"
        timestamp = str(int(time.time() * 1000))
        headers = self._headers(urlsplit(url).path, "", timestamp)
        resp = await self._transport(Request("GET", url, headers, ""))
        if resp.status != 200:
            raise CloudError(f"{path} -> HTTP {resp.status}: {resp.text[:200]}")
        return resp.json()

    async def get_digital_model(self, device_id: str) -> dict:
        """Fetch a device's **digital model** (the full per-attribute spec) — verified :
        ``POST uws-sgp.haieriot.net/shadow/v1/devdigitalmodels`` body ``{"deviceInfoList":[{"deviceId"}]}``.
        The model is returned as a stringified JSON under ``detailInfo[deviceId]``; parsed here into the
        dict shape :func:`haismart_hrdp.profile_from_device_config` expects (``attributes[]`` etc.), so the
        HA layer can self-build the correct AttributeProfile for ANY Haier AC model — no hand-coding."""
        body = json.dumps({"deviceInfoList": [{"deviceId": device_id}]}, separators=(",", ":"))
        url = f"https://{self.domains.uws}/shadow/v1/devdigitalmodels"
        timestamp = str(int(time.time() * 1000))
        headers = self._headers(urlsplit(url).path, body, timestamp)
        resp = await self._transport(Request("POST", url, headers, body))
        if resp.status != 200:
            raise CloudError(f"digital model -> HTTP {resp.status}: {resp.text[:200]}")
        data = resp.json()
        if str(data.get("retCode")) != "00000":
            raise CloudError(f"digital model -> retCode {data.get('retCode')}: {data.get('retInfo')}")
        raw = (data.get("detailInfo") or {}).get(device_id)
        if not raw:
            raise CloudError(f"digital model: no detailInfo for {device_id}")
        return json.loads(raw) if isinstance(raw, str) else raw

    async def list_devices_v2(self) -> list[CloudDevice]:
        """The account's devices via the verified path (``GET`` DEVICE_LIST_PATH_V2 on the uhome
        host). Returns parsed devices for config-flow discovery — id, name, deviceType, and uPlusId (the
        ``wifiType`` field). Needs a valid accessToken (refresh first)."""
        resp = await self.get(self.domains.uhome, DEVICE_LIST_PATH_V2)
        if str(resp.get("retCode")) != "00000":
            raise CloudError(f"device list -> retCode {resp.get('retCode')}: {resp.get('retInfo')}")
        out: list[CloudDevice] = []
        for d in (resp.get("data") or {}).get("deviceInfos", []):
            b = d.get("baseInfo") or {}
            e = d.get("extendedInfo") or {}
            out.append(
                CloudDevice(
                    device_id=b.get("deviceId", ""),
                    name=b.get("deviceName", ""),
                    device_type=b.get("deviceType", ""),
                    uplus_id=b.get("wifiType", ""),
                    online=bool(b.get("isOnline")),
                    prod_no=str(e.get("prodNo") or ""),
                    model=str(e.get("model") or ""),
                    brand=str(e.get("brand") or ""),
                    app_type_name=str(e.get("appTypeName") or ""),
                )
            )
        return out

    @staticmethod
    def _checked(resp: dict, what: str) -> dict:
        """Raise if the envelope reports a non-success ``retCode``.

        ``post``/``get`` only validate the HTTP status, so without this a caller happily treats
        ``{"retCode": "21016", "retInfo": "Token not created by this terminal"}`` as a device model.
        """
        ret = str(resp.get("retCode", "00000"))
        if ret not in ("00000", "", "None"):
            raise CloudError(f"{what} -> retCode {ret}: {resp.get('retInfo')}")
        return resp

    # -- known-good call --
    async def get_device_7d(self, device_id: str) -> dict:
        """7-day device data (TLV device-data query)."""
        return self._checked(
            await self.post(self.domains.uws, "/rcs/device/7d/query", {"deviceId": device_id}),
            "device 7d",
        )

    # -- device list (paths confirmed; response shape to confirm on first call) --
    async def list_user_devices(self) -> dict:
        """The account's devices — `/dcs/device-service-2c/get/user/device-list` (confirmed)."""
        return self._checked(
            await self.post(self.domains.uhome, DEVICE_LIST_PATH, {}), "user device list"
        )

    async def list_devices(self) -> dict:
        """Alt device list — the aggregate-query endpoint (also present)."""
        return self._checked(
            await self.post(self.domains.uhome, DEVICE_LIST_PATH_ALT, {}), "device list (alt)"
        )

    async def search_products(
        self,
        *,
        index: int = 0,
        count: int = 20,
        keys: str = "",
        app_type_code: str = "",
        brand_code: str = "",
    ) -> dict:
        """Page the product catalogue — every model the region publishes, with its **product code**.

        This is the model-picker's own backing call. Each row carries ``prodNo``, ``model``,
        ``appTypeCode``/``appTypeName`` and ``brandCode``, which is the only route we have from
        "a model number" to "a product code" — and the product code is what
        :func:`get_public_device_config` needs, so this is how an unfamiliar unit's published
        rules become reachable without its owner's account.

        ``count`` is capped at 20 by the server, so a full sweep pages on ``index``. Air
        conditioners are app types ``A120`` (central), ``A177`` (wall mounted) and ``A178``
        (floor standing).

        ⚠️ Needs the **per-install** ``client_id`` like every other account call; the app-level
        one gives retCode 21016.
        """
        payload: dict[str, object] = {"index": index, "count": min(count, 20)}
        for key, value in (
            ("keys", keys),
            ("appTypeCode", app_type_code),
            ("brandCode", brand_code),
        ):
            if value:
                payload[key] = value
        return self._checked(
            await self.post(self.domains.uhome, PRODUCT_SEARCH_PATH, payload), "product search"
        )

    async def list_ac_products(
        self, *, model: str = "", limit: int = 400
    ) -> list[CatalogueProduct]:
        """Air conditioners the catalogue publishes **for this account's region**, parsed.

        ⚠️ The region is not a detail: this catalogue is scoped by the ``zoneInfo`` header every
        device-center call carries -- the dialling code the account registered with. Asked as a
        Thai account it
        answers with 171 air conditioners; asked as a Pakistani one it answers with a different set,
        and a model absent from the first is present in the second. So a lookup that ignores the
        region can report a real appliance as unpublished -- which is exactly what happened to the
        first 209-byte unit reported here.

        ``model`` is passed to the server's own keyword search (its ``keys`` parameter), which
        matches model numbers rather than product codes: searching for a product code returns
        nothing, searching for the number on the label returns its row.

        Rows come from ``data.prodInfos``. Reading a different key -- there is no ``productList`` --
        made a first pass report zero rows for a product that was there, so the shape is parsed here,
        once, rather than in each caller.
        """
        out: list[CatalogueProduct] = []
        seen: set[str] = set()
        for app_type in AC_APP_TYPE_CODES:
            index = 0
            while len(out) < limit:
                reply = await self.search_products(
                    index=index, count=20, keys=model, app_type_code=app_type
                )
                rows = ((reply.get("data") or {}).get("prodInfos")) or []
                for row in rows:
                    code = row.get("prodNo")
                    if not code or code in seen:
                        continue
                    seen.add(code)
                    out.append(CatalogueProduct(
                        product_code=code,
                        model=row.get("model") or "",
                        app_type=row.get("appTypeCode") or "",
                        app_type_name=row.get("appTypeName") or "",
                        brand=row.get("brand") or "",
                    ))
                if len(rows) < 20:
                    break
                index += 20
        return out

    async def get_device_model(self, device_id: str) -> dict:
        """Device capability model — `/dcs/.../model-info/find/info` (confirmed). Drives the
        STD attribute set the HA integration exposes (analogous to banto6's `devdigitalmodels`)."""
        return self._checked(
            await self.post(self.domains.uhome, DEVICE_MODEL_PATH, {"deviceId": device_id}),
            "device model",
        )

    async def get_device_config(
        self, model: str, uplus_id: str, *, prod_no: str = "", device_type: str = ""
    ) -> dict:
        """Fetch a device's **constraintfile** — the full model, including the parts the device
        shadow does not carry: the conditional `modifiers` (which settings a unit ignores in which
        state), the `alarms` list, and the `constraints` (co-command rules).

        Two steps, because that is how the app does it. The account's resource service is asked for
        the device-config resource, and answers with a download URL, a version and an MD5; the file
        is then fetched from that URL and its signature prefix stripped. The URL cannot be
        constructed — the filename carries a build stamp — which is why a direct guess at the CDN
        path returns 404.

        ``model`` is the model number (e.g. ``HSU-24VRRA03TF``) and ``uplus_id`` the uPlusId, both
        of which the account device list provides. Both are required: the lookup returns an empty
        list if either is missing. Needs a valid accessToken.

        ⚠️ **The listing is scoped to the account, not to the arguments.** It answers with the
        configs published for the caller's own devices and reports success whatever ``model`` and
        ``uplus_id`` contain, so this is not a way to look up a model belonging to someone else --
        and the entry has to be picked out of the response by uPlusId rather than assumed. When the
        device is not among them this raises, because no rules at all is the safe direction and
        another device's rules are worse than none.
        """
        body = {
            "resType": DEVICE_CONFIG_RES_TYPE,
            "model": model,
            "typeId": uplus_id,
            "prodNo": prod_no,
            "deviceType": device_type,
        }
        resp = await self.post(self.domains.uhome, DEVICE_CONFIG_LIST_PATH, body)
        if str(resp.get("retCode")) != "00000":
            raise CloudError(
                f"device config list -> retCode {resp.get('retCode')}: {resp.get('retInfo')}"
            )
        resources = (resp.get("data") or {}).get("resources") or []
        # ⚠️ The listing is NOT filtered by what was asked for -- by ANY of it. It answers with the
        # device configs published for the ACCOUNT, with retCode 00000, whatever `model`, `typeId`
        # and even `resType` say: a model number that exists nowhere paired with another device's
        # uPlusId comes back with the caller's own device, and so does a `resType` this service has
        # never heard of. So the caller has to do the selecting,
        # and taking the first entry on trust would hand one device another device's rulebook:
        # its modifiers would make the wrong entities unavailable and its alarms would name the
        # wrong faults. An account with two different air conditioners is all that needs.
        # The uPlusId is what identifies the device here; the model number is the half whose
        # spelling varies (a sticker may read `HSU-24HFAB/013WUSDC(W)-T3` where the service says
        # `HSU-24HFAB`), so an exact `model@uPlusId` is preferred and the uPlusId alone decides.
        wanted = f"{model}@{uplus_id}"
        entry = next((r for r in resources if r.get("name") == wanted), None) or next(
            (r for r in resources if str(r.get("name", "")).endswith(f"@{uplus_id}")), None
        )
        if not entry or not entry.get("resUrl"):
            # No rules is the safe direction -- it locks nothing -- and a wrong model's rules are
            # not recoverable from once stored, so this refuses rather than approximates.
            served = ", ".join(str(r.get("name")) for r in resources) or "nothing"
            raise CloudError(f"no device config published for {wanted} (served: {served})")
        resp = await self._transport(Request("GET", entry["resUrl"], {}, ""))
        if resp.status != 200:
            raise CloudError(f"device config download -> HTTP {resp.status}")
        digest = entry.get("md5")
        if digest and hashlib.md5(resp.text.encode()).hexdigest() != digest:
            # the listing publishes the file's MD5, so a truncated or swapped download is caught
            # here rather than surfacing later as a model that parses but is not this device's
            raise CloudError("device config download does not match its published MD5")
        return strip_signed_config(resp.text)

    # -- account/token layer — verified  --
    @classmethod
    async def login(
        cls,
        credentials: AppCredentials,
        login_id: str,
        password: str,
        *,
        client_id: str | None = None,
        zone_info: str = "0",
        domains: Domains | None = None,
        transport: Transport | None = None,
    ) -> tuple[HaierCloud, LoginResult]:
        """Sign in with an email (or phone) + password; return a ready client + the :class:`LoginResult`.

        Reproduces the app's real SE-Asia H5 login: device-center-signed ``POST
        uhome-sea.haieriot.net/uplussea/accounts/v2/login`` with body ``{"username": <email/phone>,
        "password": <AES>, "sesame": <RSA-wrapped AES key>}`` (see :func:`encrypt_login_password`). **We
        choose the ``client_id``** (a fresh 32-hex uSDK CLIENTID) and the issued token is bound to it — so
        there is no "token not created by this terminal" (retCode 21016) problem; reuse ``result.client_id``
        for every later device-center call and to derive the gateway clientId.

        Only credential logins are reproducible; social logins (Google/Facebook) have no password — those
        owners share their AC to a throwaway email/password account and log in with that. Common non-success
        ``retCode``\\ s: ``30032`` account not registered / bad credentials, ``10001`` missing field. The login
        host is ``Domains.login`` (override via ``domains=``).
        """
        cid = (client_id or secrets.token_hex(16)).upper()
        client = cls(
            replace(credentials, client_id=cid),
            "",
            zone_info=zone_info,
            domains=domains,
            transport=transport,
        )
        pw_field, sesame = encrypt_login_password(password)
        body = {"username": login_id, "password": pw_field, "sesame": sesame}
        resp = await client.post(client.domains.login, LOGIN_PATH, body)
        ret = str(resp.get("retCode", "00000"))
        if ret not in ("00000", "", "None"):
            raise CloudError(f"login -> retCode {ret}: {resp.get('retInfo')}")
        result = LoginResult.from_response(resp, client_id=cid)
        if not (result.refresh_token or result.access_token):
            raise CloudError(f"login returned no tokens: {str(resp)[:200]}")
        client.access_token = result.access_token
        return client, result

    async def refresh_token(self, refresh_token: str) -> RefreshResult:
        """Exchange a **reusable** refreshToken for a fresh accessToken. Verified against the real
        cloud: ``POST`` the ``uhome`` host ``/uplussea/accounts/v1/user/refreshToken`` with body
        ``{"refreshToken": ...}`` and the full device-center envelope **including the ``zoneInfo`` header**
        (its absence returns retCode 30003 "Authorization exception"). Uses the device-center sign
        ``SHA-256(path+body+appId+appKey+timestamp)`` — same as the device-list, NOT a separate OAuth sign.

        The refreshToken is **reusable** (returned unchanged across refreshes), so it is the durable
        credential: a user signs in once (email/password), the refreshToken is stored, and this mints
        access tokens indefinitely — no re-login needed.
        On success the client's ``access_token`` is updated so the same instance keeps working.
        """
        resp = await self.post(
            self.domains.uhome, ACCOUNT_REFRESH_PATH, {"refreshToken": refresh_token}
        )
        if str(resp.get("retCode")) != "00000":
            raise CloudError(
                f"refreshToken -> retCode {resp.get('retCode')}: {resp.get('retInfo')}"
            )
        result = RefreshResult.from_response(resp)
        if not result.access_token:
            raise CloudError(
                f"refreshToken succeeded but returned no access token: {str(resp)[:200]}"
            )
        self.access_token = result.access_token
        return result


class CloudError(Exception):
    """A cloud request failed (non-200 or malformed response)."""
