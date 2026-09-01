"""haismart-extractor — cloud client for the Haismart (Haier SE-Asia) platform.

Two pieces, both used by the Home Assistant integration:

* :mod:`~haismart_extractor.cloud` — account sign-in / token refresh, device list, digital model.
* :mod:`~haismart_extractor.gateway` — per-device ``localKey`` fetch over the cloud MQTT gateway.
"""
from __future__ import annotations

from .cloud import (
    SEA_APP_CREDENTIALS,
    AppCredentials,
    CloudConnectionError,
    CloudDevice,
    CloudError,
    Domains,
    HaierCloud,
    LocalKey,
    LoginResult,
    RefreshResult,
    device_center_sign,
    device_center_sign_payload,
    encrypt_login_password,
    httpx_transport,
)
from .gateway import (
    GatewayClient,
    GatewayCreds,
    GatewayError,
    derive_client_id,
    derive_gateway_auth,
    derive_gateway_password,
    generate_username_body,
    get_localkey_via_gateway,
    localkey_request_payload,
    parse_localkey_response,
)

__version__ = "0.1.0"

__all__ = [
    "SEA_APP_CREDENTIALS",
    "AppCredentials",
    "CloudConnectionError",
    "CloudDevice",
    "CloudError",
    "Domains",
    "GatewayClient",
    "GatewayCreds",
    "GatewayError",
    "HaierCloud",
    "LocalKey",
    "LoginResult",
    "RefreshResult",
    "__version__",
    "derive_client_id",
    "derive_gateway_auth",
    "derive_gateway_password",
    "device_center_sign",
    "device_center_sign_payload",
    "encrypt_login_password",
    "generate_username_body",
    "get_localkey_via_gateway",
    "httpx_transport",
    "localkey_request_payload",
    "parse_localkey_response",
]
