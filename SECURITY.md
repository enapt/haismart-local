# Security & responsible use

## Scope

This project provides **local** control of Haier air conditioners you own, on your own network. At
runtime it talks only to your ACs over the LAN (`:56800`). Your Haismart account is used at setup (and
on key rotation) to fetch each device's per-device `localKey` — the same operation the official app
performs.

## Handling secrets

- Your account credentials, `refreshToken`, `accessToken` and each AC's `localKey` are **secrets**.
  Keep them out of logs, screenshots, and public issues.
- **Diagnostics downloads redact all of them automatically**, so the file the issue templates ask for
  is safe to attach. The `deviceId` is redacted too — it is only the Wi-Fi module's MAC and not a
  credential, but it is a stable device identifier and nothing in a bug report needs it. The
  appliance's LAN address is redacted as well; the file keeps only whether it still matches the
  address the unit reports. The appliance's cloud model is kept, because its fault and refusal tables
  are what make a report diagnosable, with any per-device identifier inside it redacted. The decrypted
  status bytes are *not* redacted and are safe: they are the same sensor and setting values your remote
  displays, and they are what makes an unrecognised report layout diagnosable.
- Do **not** commit real credentials. `*.local.json` and similar are git-ignored; scrub any pasted logs.
- Test vectors and examples must use **illustrative** device ids, keys and addresses — never a real
  `localKey`, MAC or LAN address.
- The **Local key** diagnostic sensor is disabled by default because its value is a secret. The
  **Model ID** sensor is enabled by default and is not a secret — it identifies the model, not the unit,
  and is shared by every air conditioner of that type.

## Transport

- Local control is AES-encrypted with your device's `localKey` and never leaves your LAN.
- The one-time cloud calls (sign-in, key fetch) use **verified TLS**, including certificate and
  hostname validation. This matters because the key-fetch channel carries both your account token
  and the device key.

## Reporting a vulnerability

Please report security issues privately via a GitHub **Security Advisory** on this repository (or a
direct message to the maintainers) rather than a public issue. Include steps to reproduce and affected
versions. We aim to acknowledge within a few days.

## Responsible use

Use this only with hardware you own or are authorized to control. It is an interoperability tool, not a
means to access devices or accounts that aren't yours.
