"""Print every air conditioner on a Haier account, with its local key.

The escape hatch for when setup will not complete. The integration does all of this by itself, and
this exists for the case where it cannot: the key is the one value an appliance will never hand over
and an owner cannot read off a label, so being unable to fetch it is the one failure with no manual
workaround -- unless there is a way to ask for it directly. This is that way.

★ **It never talks to the air conditioner** -- only to Haier's servers -- so it does not have to
run on the Home Assistant machine, or even on the same network. Any computer with Python will do,
which is the easiest thing to tell somebody who is stuck::

    pip install 'haismart-extractor[cloud] @ git+https://github.com/enapt/haismart-local\
#subdirectory=packages/haismart-extractor'
    haismart-keys --username you@example.com --region 66

⚠️ The copy bundled inside an installed integration is **not** runnable from the Terminal & SSH
add-on: that container has no ``cryptography``, which the sign-in needs, and ``docker exec`` into
the core container is refused while the add-on's protection mode is on. Inside the core container
itself it runs fine (``cd /config/custom_components/haismart/vendor && python3 -m
haismart_extractor.cli ...``), so it is worth knowing, but it is not the instruction to give.

⚠️ The password is **prompted for**, never taken as an argument: an argument is recorded in shell
history and is visible to every process on the machine while it runs. Use ``--password-stdin`` to
pipe one in from a script.

⚠️ What it prints is a **secret**. A local key is the credential that controls the appliance from
anywhere on the network. Do not paste output into a bug report or a forum post -- the rest of the
output is safe, the key is not, and there is a ``--no-keys`` switch for exactly that.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
from typing import Any

from .cloud import SEA_APP_CREDENTIALS, CloudError, HaierCloud
from .gateway import GatewayClient, GatewayCreds, GatewayError

# Long enough for a TLS connect plus one round trip per appliance, short enough that somebody
# staring at a terminal does not conclude it has hung.
GATEWAY_TIMEOUT = 15.0
REDACTED = "(hidden -- rerun without --no-keys)"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m haismart_extractor.cli",
        description="Print the air conditioners on a Haier account, with their local keys.",
        epilog=(
            "The password is prompted for, never passed as an argument. Output contains secrets: "
            "a local key controls the appliance from anywhere on your network, so use --no-keys "
            "before sharing anything."
        ),
    )
    p.add_argument("--username", required=True, help="account email or phone number")
    p.add_argument(
        "--region",
        required=True,
        help=(
            "the phone dialling code of the country the ACCOUNT was registered in (66 Thailand, "
            "65 Singapore, ...). Not where the appliance is installed. Haier reports a wrong one "
            "as 'account is not registered', which reads like a wrong password."
        ),
    )
    p.add_argument(
        "--password-stdin",
        action="store_true",
        help="read the password from standard input instead of prompting, for scripting",
    )
    p.add_argument("--device", help="only this device ID (the module's MAC), instead of all")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument(
        "--no-keys",
        action="store_true",
        help="print everything except the keys, so the output is safe to share",
    )
    return p


async def _collect(username: str, password: str, region: str) -> tuple[Any, list[Any]]:
    """Sign in and list the account's appliances."""
    client, result = await HaierCloud.login(
        SEA_APP_CREDENTIALS, username, password, zone_info=region
    )
    return result, await client.list_devices_v2()


def _fetch_keys(result: Any, device_ids: list[str]) -> dict[str, Any]:
    """Every requested appliance's key, over one gateway connection.

    Appliances that fail are omitted rather than aborting the rest: one unplugged air conditioner
    must not deny somebody the key for the one they are actually trying to fix.
    """
    creds = GatewayCreds.derive(
        usdk_client_id=result.client_id, access_token=result.access_token
    )
    return GatewayClient(creds).get_localkeys(device_ids, timeout=GATEWAY_TIMEOUT)


def _rows(devices: list[Any], keys: dict[str, Any], *, hide: bool) -> list[dict[str, Any]]:
    out = []
    for d in devices:
        key = keys.get(d.device_id)
        out.append({
            "name": d.name or "",
            "device_id": d.device_id,
            "host_hint": "",
            "model": getattr(d, "model", "") or "",
            "product_code": getattr(d, "prod_no", "") or "",
            "uplus_id": getattr(d, "uplus_id", "") or "",
            "device_type": getattr(d, "device_type", "") or "",
            "online": getattr(d, "online", None),
            "local_key": (REDACTED if hide else key.key) if key else None,
            "localkey_version": key.version if key else None,
        })
    return out


def _print_human(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        print()
        print(f"  {row['name'] or row['device_id']}")
        print(f"    device ID (MAC)  {row['device_id']}")
        if row["local_key"] is None:
            print("    local key        NOT RETRIEVED -- see the message above")
        else:
            print(f"    local key        {row['local_key']}")
            print(f"    key version      {row['localkey_version']}")
        for label, field in (
            ("model", "model"), ("product code", "product_code"),
            ("wire model ID", "uplus_id"), ("device type", "device_type"),
        ):
            if row[field]:
                print(f"    {label:<16} {row[field]}")
        if row["online"] is not None:
            print(f"    online           {'yes' if row['online'] else 'no'}")
    print()
    print("  To add one by hand: Add Integration -> Haismart -> 'I already have this unit's")
    print("  local key'. Pick the appliance off the list and paste its key; the address and")
    print("  device ID are filled in for you.")


def main(argv: list[str] | None = None) -> int:
    """Parse, gather the password, then hand over to :func:`run`.

    Deliberately thin, and everything that can be decided without the network happens here. The work
    lives in an async function so that a caller -- a test, or anything embedding this -- owns the
    event loop. ``asyncio.run`` sets the current loop to None on exit, which is correct for a
    process about to exit and ruinous inside a longer-lived one.
    """
    args = _parser().parse_args(argv)

    try:
        import httpx  # noqa: F401
    except ImportError:
        # The library takes an injectable transport, so it does not require httpx -- but this tool
        # brings no host to inject one, and the failure would otherwise surface from deep inside a
        # request as something that reads like a bug rather than a missing package.
        print(
            "error: this needs the `httpx` package.\n"
            "  pip install httpx\n"
            "...or install the whole tool with its dependencies:\n"
            "  pip install 'haismart-extractor[cloud] @ "
            "git+https://github.com/enapt/haismart-local#subdirectory=packages/haismart-extractor'",
            file=sys.stderr,
        )
        return 2

    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("Haier account password: ")
    if not password:
        print("error: no password given", file=sys.stderr)
        return 2

    return asyncio.run(run(args, password))


async def run(args: argparse.Namespace, password: str) -> int:
    """Sign in, fetch the keys, print them. Returns the process exit code.

    0 everything, 1 could not sign in, 2 nothing to do (bad arguments, no devices), 3 signed in but
    at least one key did not come back -- which must not read as success, since the key is the whole
    reason for running this.
    """
    try:
        result, devices = await _collect(
            args.username, password, str(args.region).strip().lstrip("+")
        )
    except CloudError as err:
        print(f"error: sign-in failed -- {err}", file=sys.stderr)
        if "30032" in str(err):
            # The one field an owner cannot simply re-read, and the failure names the wrong thing.
            print(
                "hint: 30032 also means the region is wrong. It is the dialling code of the "
                "country the ACCOUNT was registered in, not where the appliance is.",
                file=sys.stderr,
            )
        return 1
    except (OSError, RuntimeError, TimeoutError) as err:
        print(f"error: could not reach Haier -- {err}", file=sys.stderr)
        return 1

    if args.device:
        wanted = "".join(c for c in args.device if c.isalnum()).upper()
        devices = [d for d in devices if d.device_id.upper() == wanted]
        if not devices:
            print(f"error: {args.device} is not on this account", file=sys.stderr)
            return 2
    if not devices:
        print("This account has no devices.", file=sys.stderr)
        return 2

    try:
        keys = await asyncio.to_thread(_fetch_keys, result, [d.device_id for d in devices])
    except (GatewayError, OSError, RuntimeError, TimeoutError) as err:
        # Sign-in worked, so say so: the natural conclusion from "it failed" is to go and check the
        # password that has in fact just been proven correct.
        print(
            f"error: signed in fine, but the key service could not be reached -- {err}\n"
            "It is reachable from most networks but not all; a firewall, a DNS filter or an "
            "appliance you have deliberately blocked will all look like this.",
            file=sys.stderr,
        )
        keys = {}

    rows = _rows(devices, keys, hide=args.no_keys)
    missing = [r["device_id"] for r in rows if r["local_key"] is None]
    if missing and keys:
        print(
            f"warning: no key came back for {', '.join(missing)} -- an appliance that is offline, "
            "or cut off from Haier, cannot be issued one.",
            file=sys.stderr,
        )

    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        _print_human(rows)
        if not args.no_keys:
            # stdout is buffered and stderr is not, so without this the warning about the output
            # appears ABOVE the output -- telling somebody not to share something they have not been
            # shown yet, which is the one placement that wastes it.
            sys.stdout.flush()
            print(
                "\n  A local key is a SECRET: it controls the appliance from anywhere on your\n"
                "  network. Do not paste this output into a bug report -- use --no-keys.",
                file=sys.stderr,
            )
    return 0 if not missing else 3


if __name__ == "__main__":
    raise SystemExit(main())
