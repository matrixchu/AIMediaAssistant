"""Tests for the real PT chain: Torznab parsing and backend selection."""

from __future__ import annotations

import importlib

import pytest

# A minimal but realistic Torznab/Jackett response.
_SAMPLE_TORZNAB = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Dune Part Two 2024 2160p UHD BluRay REMUX HDR</title>
      <guid>https://tracker.example/details/1</guid>
      <comments>https://tracker.example/details/1</comments>
      <pubDate>Mon, 10 Jun 2024 12:00:00 +0000</pubDate>
      <enclosure url="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&amp;dn=Dune"
                 length="84288733184" type="application/x-bittorrent" />
      <torznab:attr name="seeders" value="312" />
      <torznab:attr name="peers" value="12" />
      <torznab:attr name="size" value="84288733184" />
      <torznab:attr name="indexer" value="HDArea" />
      <torznab:attr name="category" value="2045" />
    </item>
    <item>
      <title>Some Low Seed Release 1080p WEB-DL</title>
      <enclosure url="magnet:?xt=urn:btih:ffffffffffffffffffffffffffffffffffffffff" length="100" />
      <torznab:attr name="seeders" value="0" />
    </item>
  </channel>
</rss>
"""


def _make_torznab_client(monkeypatch):
    from ai_media_assistant.shared import config

    config.get_settings.cache_clear()
    monkeypatch.setenv("PT_BACKEND", "torznab")
    monkeypatch.setenv("PT_MOCK", "false")
    monkeypatch.setenv("PT_BASE_URL", "http://127.0.0.1:9117/api")
    monkeypatch.setenv("PT_API_KEY", "test")
    monkeypatch.setenv("PT_MIN_SEEDERS", "1")

    from ai_media_assistant.clients.pt import torznab as torznab_mod

    importlib.reload(torznab_mod)
    return torznab_mod.TorznabPTClient()


def test_torznab_parses_and_filters(monkeypatch):
    client = _make_torznab_client(monkeypatch)

    class _FakeResp:
        content = _SAMPLE_TORZNAB.encode()

        def raise_for_status(self):
            return None

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            return _FakeResp()

    import ai_media_assistant.clients.pt.torznab as torznab_mod

    monkeypatch.setattr(torznab_mod.httpx, "Client", _FakeClient)

    results = client.search("Dune Part Two")
    # Low-seed item is filtered out by PT_MIN_SEEDERS=1.
    assert len(results) == 1
    dto = results[0]
    assert "Dune" in dto.title
    assert dto.seeders == 312
    assert dto.size_bytes == 84288733184
    assert dto.resolution == "2160P"
    assert dto.quality == "REMUX"
    assert dto.download_url.startswith("magnet:?xt=urn:btih:")
    assert dto.site_name == "HDArea"

    config_cleanup()


def test_backend_selector(monkeypatch):
    from ai_media_assistant.shared import config

    config.get_settings.cache_clear()
    monkeypatch.setenv("PT_MOCK", "false")
    monkeypatch.setenv("PT_BACKEND", "torznab")
    monkeypatch.setenv("PT_BASE_URL", "http://x")
    assert config.get_settings().effective_pt_backend == "torznab"

    config.get_settings.cache_clear()
    monkeypatch.setenv("PT_MOCK", "true")
    monkeypatch.setenv("PT_BACKEND", "mock")
    assert config.get_settings().effective_pt_backend == "mock"
    config_cleanup()


def config_cleanup():
    from ai_media_assistant.shared import config

    config.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _restore_settings():
    yield
    config_cleanup()
