"""The escape hatch: print an account's appliances and their keys when setup will not.

Its whole reason for existing is that somebody is already stuck, so the cases that matter most are
the failures -- what it says, and what it exits with, when something does not work.
"""
from __future__ import annotations

import json

import pytest

from haismart_extractor.cli import _parser, main, run
from haismart_extractor.cloud import CloudDevice, CloudError, LoginResult
from haismart_extractor.gateway import LocalKey


async def _go(argv: list[str]) -> int:
    """Run the tool the way `main` does, minus the loop management `main` adds for a process.

    `main` is a thin wrapper whose only extra job is `asyncio.run`, and calling that inside a test
    session sets the current event loop to None -- which, from Python 3.13, breaks every later test
    in the package. So the logic is awaited here and `main` is covered only where it returns before
    reaching the loop.
    """
    return await run(_parser().parse_args([*argv]), "pw")


DEVICES = [
    CloudDevice("ACB722A2CBEC", "Downstairs", "0201203a", "UPLUSID", True, prod_no="AAC1UKZ01"),
    CloudDevice("ACB722A1EF66", "Upstairs", "0201203a", "UPLUSID", False, prod_no="AAC1UKZ01"),
]
KEYS = {
    "ACB722A2CBEC": LocalKey(key="a" * 32, version=46),
    "ACB722A1EF66": LocalKey(key="b" * 32, version=46),
}


@pytest.fixture
def signed_in(monkeypatch):
    """A working account and gateway, so a test can break exactly one thing."""
    result = LoginResult(access_token="AT", refresh_token="RT", client_id="C" * 32)

    async def collect(username, password, region):
        collect.called = (username, password, region)
        return result, list(DEVICES)

    monkeypatch.setattr("haismart_extractor.cli._collect", collect)
    monkeypatch.setattr(
        "haismart_extractor.cli._fetch_keys",
        lambda res, ids: {k: v for k, v in KEYS.items() if k in ids},
    )
    return collect


async def test_it_prints_each_appliance_with_its_key(signed_in, capsys) -> None:
    assert await _go(["--username", "me@x.com", "--region", "66"]) == 0
    out = capsys.readouterr().out
    assert "ACB722A2CBEC" in out and "a" * 32 in out
    assert "ACB722A1EF66" in out and "b" * 32 in out
    # the region is passed through as typed, minus any leading +
    assert signed_in.called[2] == "66"


async def test_no_keys_prints_everything_else(signed_in, capsys) -> None:
    """So that output can be shared. The identifiers are what a report needs; the key is not."""
    assert await _go(["--username", "me@x.com", "--region", "66", "--no-keys"]) == 0
    out = capsys.readouterr().out
    assert "a" * 32 not in out and "b" * 32 not in out
    assert "ACB722A2CBEC" in out and "AAC1UKZ01" in out


async def test_json_is_machine_readable_and_complete(signed_in, capsys) -> None:
    assert await _go(["--username", "me@x.com", "--region", "66", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["device_id"] for r in rows] == ["ACB722A2CBEC", "ACB722A1EF66"]
    assert rows[0]["local_key"] == "a" * 32
    assert rows[0]["localkey_version"] == 46
    assert rows[0]["product_code"] == "AAC1UKZ01"


async def test_one_appliance_can_be_singled_out(signed_in, capsys) -> None:
    """Separators and case vary with how a MAC is written down, so they must not matter."""
    assert await _go(["--username", "me@x.com", "--region", "66", "--json",
                 "--device", "ac:b7:22:a1:ef:66"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["device_id"] for r in rows] == ["ACB722A1EF66"]


async def test_a_wrong_region_is_named_as_a_possible_cause(signed_in, monkeypatch, capsys) -> None:
    """30032 says "account is not registered", which reads as a wrong password and is not.

    It is the one field an owner cannot simply re-read off a password manager, so the failure that
    most often means it has to say so.
    """
    async def fail(*a):
        raise CloudError("login -> retCode 30032: Account is not registered")

    monkeypatch.setattr("haismart_extractor.cli._collect", fail)
    assert await _go(["--username", "me@x.com", "--region", "44"]) == 1
    err = capsys.readouterr().err
    assert "30032" in err and "region" in err.lower()


async def test_a_gateway_failure_says_the_sign_in_worked(signed_in, monkeypatch, capsys) -> None:
    """Otherwise the natural next move is to check a password that was just proven correct."""
    def boom(res, ids):
        raise TimeoutError("timed out")

    monkeypatch.setattr("haismart_extractor.cli._fetch_keys", boom)
    code = await _go(["--username", "me@x.com", "--region", "66"])
    err = capsys.readouterr().err
    assert "signed in fine" in err
    assert "firewall" in err
    assert code == 3, "a run that produced no keys must not look like success"


async def test_one_missing_key_does_not_deny_the_others(signed_in, monkeypatch, capsys) -> None:
    """An unplugged appliance must not cost somebody the key for the one they are fixing."""
    monkeypatch.setattr(
        "haismart_extractor.cli._fetch_keys",
        lambda res, ids: {"ACB722A2CBEC": KEYS["ACB722A2CBEC"]},
    )
    code = await _go(["--username", "me@x.com", "--region", "66", "--json"])
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["local_key"] == "a" * 32
    assert rows[1]["local_key"] is None
    assert code == 3


async def test_an_unknown_device_is_refused_rather_than_silently_empty(signed_in, capsys) -> None:
    assert await _go(["--username", "me@x.com", "--region", "66",
                 "--device", "001122334455"]) == 2
    assert "not on this account" in capsys.readouterr().err


def test_main_stops_before_it_needs_a_network(monkeypatch, capsys) -> None:
    """`main` is only the wrapper, and this is all of it that can be reached without one.

    Kept deliberately: everything else drives `run` directly, so without this `main` -- the actual
    entry point people invoke -- would have no coverage at all.
    """
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
    assert main(["--username", "me@x.com", "--region", "66", "--password-stdin"]) == 2
    assert "no password" in capsys.readouterr().err


def test_the_password_is_never_an_argument() -> None:
    """An argument lands in shell history and is visible to every process while it runs."""
    from haismart_extractor.cli import _parser

    options = {a for action in _parser()._actions for a in action.option_strings}
    assert "--password" not in options
    assert "--password-stdin" in options


async def test_the_key_fetch_itself_works_end_to_end(monkeypatch, capsys) -> None:
    """Exercise the real derivation and request/parse path, not a stub of it.

    The other tests replace `_fetch_keys` so they can break one thing at a time; this one replaces
    only the socket, so credential derivation, the request body and the reply parsing all run.
    """
    from test_gateway import FakeMqtt

    from haismart_extractor.cloud import LoginResult
    from haismart_extractor.gateway import GatewayClient

    async def collect(username, password, region):
        return LoginResult(access_token="AT", refresh_token="RT", client_id="C" * 32), [DEVICES[0]]

    monkeypatch.setattr("haismart_extractor.cli._collect", collect)
    monkeypatch.setattr(
        "haismart_extractor.cli.GatewayClient",
        lambda creds: GatewayClient(creds, connect=lambda _c: FakeMqtt()),
    )
    assert await _go(["--username", "me@x.com", "--region", "66", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["device_id"] == "ACB722A2CBEC"
    assert rows[0]["local_key"] and rows[0]["localkey_version"]
