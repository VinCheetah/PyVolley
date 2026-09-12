"""Tests unitaires pour le rate-limiter non-bloquant de AsyncHttpClient."""

import asyncio
import time
import pytest
from pyvolley.scrapers.async_http_client import AsyncHttpClient


@pytest.mark.anyio
async def test_async_rate_limiter_staggered():
    """Vérifie que les requêtes sont espacées du délai sans bloquer l'ordonnancement."""
    delay = 0.05
    client = AsyncHttpClient(request_delay=delay, max_concurrent=5)
    timestamps = []

    async def worker():
        await client._rate_limit()
        timestamps.append(time.monotonic())

    start = time.monotonic()
    await asyncio.gather(*[worker() for _ in range(5)])
    total_time = time.monotonic() - start

    # 5 requêtes avec delay 0.05s devraient prendre au moins 4 * 0.05s = 0.20s
    assert total_time >= 0.18
    # Et ne devraient pas excéder un délai raisonnable (ex: 0.50s)
    assert total_time <= 0.50
    assert len(timestamps) == 5

    await client.close()


@pytest.mark.anyio
async def test_async_rate_limiter_burst():
    """Vérifie que le burst permet à plusieurs requêtes de partir immédiatement."""
    delay = 0.05
    client = AsyncHttpClient(request_delay=delay, max_concurrent=5, burst=5)
    timestamps = []

    async def worker():
        await client._rate_limit()
        timestamps.append(time.monotonic())

    start = time.monotonic()
    await asyncio.gather(*[worker() for _ in range(5)])
    total_time = time.monotonic() - start

    # Avec burst=5, les 5 requêtes partent quasi-instantanément (< 0.04s)
    assert total_time < 0.04
    assert len(timestamps) == 5

    await client.close()
