"""The unauthenticated byte-map fetch. No network: the transport is faked."""
import asyncio
import time

from haismart_extractor.device_config import async_fetch_device_config


async def test_a_hung_cdn_gives_up_at_the_timeout_rather_than_stalling_setup() -> None:
    """``timeout`` bounds each request: an appliance's setup must not wait on a CDN that never answers."""
    async def hang(_request):
        await asyncio.sleep(30)

    start = time.monotonic()
    assert await async_fetch_device_config("a" * 64, transport=hang, timeout=0.05) is None
    assert time.monotonic() - start < 5
