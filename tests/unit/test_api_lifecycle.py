from unittest.mock import AsyncMock, patch

import pytest

import src.api.app as app_module


async def test_lifespan_recreates_redis_after_shutdown(monkeypatch):
    monkeypatch.setattr(app_module, "_redis", None)
    client = AsyncMock()
    with patch("src.api.app.aioredis.Redis.from_url", return_value=client) as factory:
        for _ in range(2):
            async with app_module.lifespan(app_module.create_app()):
                assert app_module.get_redis() is client
            assert app_module._redis is None
    assert factory.call_count == 2
    assert client.aclose.await_count == 2


async def test_lifespan_closes_redis_on_exception(monkeypatch):
    monkeypatch.setattr(app_module, "_redis", None)
    client = AsyncMock()
    with (
        patch("src.api.app.aioredis.Redis.from_url", return_value=client),
        pytest.raises(RuntimeError),
    ):
        async with app_module.lifespan(app_module.create_app()):
            raise RuntimeError("application failed")
    client.aclose.assert_awaited_once()
    assert app_module._redis is None
