from unittest import mock

# Standard path insertion
import httpx
import pytest

from litellm.proxy.proxy_server import app


@pytest.mark.asyncio
async def test_get_image_redirects_remote_logo_without_server_fetch(monkeypatch):
    """
    Remote logo URLs should be loaded by the browser, not fetched by the proxy.
    """
    monkeypatch.setenv("UI_LOGO_PATH", "http://invalid-url-12345.com/logo.jpg")

    with mock.patch("litellm.llms.custom_httpx.http_handler.AsyncHTTPHandler.get") as mock_get:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as ac:
            response = await ac.get("/get_image")

    assert response.status_code == 307
    assert response.headers["location"] == "http://invalid-url-12345.com/logo.jpg"
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_get_image_remote_logo_does_not_use_stale_cache(monkeypatch, tmp_path):
    """
    A stale pre-fix cache file should not mask a configured remote logo URL.
    """
    monkeypatch.setenv("UI_LOGO_PATH", "http://example.com/logo.jpg")
    monkeypatch.setenv("LITELLM_ASSETS_PATH", str(tmp_path))
    (tmp_path / "cached_logo.jpg").write_bytes(b"\xff\xd8\xff cached logo")

    with mock.patch("litellm.llms.custom_httpx.http_handler.AsyncHTTPHandler.get") as mock_get:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as ac:
            response = await ac.get("/get_image")

    assert response.status_code == 307
    assert response.headers["location"] == "http://example.com/logo.jpg"
    mock_get.assert_not_called()


async def _get_logo(path: str) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as ac:
        return await ac.get(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/get_image", "/get_image?theme=dark", "/get_image?variant=monogram"])
async def test_bundled_logo_must_be_revalidated_so_a_replaced_image_shows_up(monkeypatch, path):
    monkeypatch.delenv("UI_LOGO_PATH", raising=False)
    monkeypatch.delenv("UI_LOGO_PATH_DARK", raising=False)

    response = await _get_logo(path)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "etag" in response.headers


@pytest.mark.asyncio
async def test_custom_local_logo_must_be_revalidated(monkeypatch, tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    monkeypatch.setenv("UI_LOGO_PATH", str(logo))

    response = await _get_logo("/get_image")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
