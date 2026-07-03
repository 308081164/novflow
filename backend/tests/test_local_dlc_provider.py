"""LocalDlcProvider 单元测试（mock HTTP）。"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models import User
from app.services.image_providers.base import ImageEngineError
from app.services.image_providers.local_dlc import LocalDlcProvider, parse_size


def test_parse_size_explicit():
    assert parse_size("768x432", "illustration") == (768, 432)


def test_parse_size_kind_default():
    assert parse_size(None, "cover") == (512, 768)


@pytest.mark.asyncio
async def test_local_dlc_health_ok():
    user = User(id=1, email="t@t.com", password_hash="x")
    user.local_dlc_base_url = "http://127.0.0.1:17860/v1"
    provider = LocalDlcProvider(user)

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"status": "ok", "tier": "lite", "model": "stub", "vram_mb": 4096}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.image_providers.local_dlc.httpx.AsyncClient", return_value=mock_client):
        data = await provider.health()

    assert data["status"] == "ok"
    mock_client.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_local_dlc_generate_connection_error():
    user = User(id=1, email="t@t.com", password_hash="x")
    provider = LocalDlcProvider(user, kind="illustration")

    import httpx

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.image_providers.local_dlc.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ImageEngineError, match="未运行"):
            await provider.generate(user, "test scene", size="768x432")
