"""Tests for the member-PT-site RSS search backend."""

from __future__ import annotations

import importlib

import pytest

# A realistic private-tracker RSS feed: passkey in the enclosure download URL,
# size + seeders in the item.
_SAMPLE_PT_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>MyPT personal feed</title>
    <item>
      <title>Dune Part Two 2024 2160p UHD BluRay REMUX HDR</title>
      <link>https://mypt.example/details.php?id=1</link>
      <enclosure url="https://mypt.example/download.php?id=1&amp;passkey=SECRET123"
                 length="84288733184" type="application/x-bittorrent" />
      <pubDate>Mon, 10 Jun 2024 12:00:00 +0000</pubDate>
      <description>Size: 78.5 GB</description>
    </item>
    <item>
      <title>Interstellar 2014 1080p BluRay x264</title>
      <link>https://mypt.example/details.php?id=2</link>
      <enclosure url="https://mypt.example/download.php?id=2&amp;passkey=SECRET123"
                 length="12300000000" type="application/x-bittorrent" />
      <pubDate>Sun, 09 Jun 2024 12:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""


@pytest.fixture(autouse=True)
def _restore_settings():
    yield
    from ai_media_assistant.shared import config

    config.get_settings.cache_clear()


def _client_with_feed(monkeypatch, url: str):
    from ai_media_assistant.shared import config

    config.get_settings.cache_clear()
    monkeypatch.setenv("PT_BACKEND", "rss")
    monkeypatch.setenv("PT_MOCK", "false")
    monkeypatch.setenv("PT_RSS_URL", url)
    monkeypatch.setenv("PT_SITE_NAME", "mypt")
    monkeypatch.setenv("PT_MIN_SEEDERS", "0")

    import ai_media_assistant.clients.pt.rss as rss_mod

    importlib.reload(rss_mod)

    # feedparser.parse accepts a string of XML directly. Capture the real parse
    # first so the stub doesn't recurse into the patched function.
    real_parse = rss_mod.feedparser.parse

    def fake_parse(_url):
        return real_parse(_SAMPLE_PT_RSS)

    monkeypatch.setattr(rss_mod.feedparser, "parse", fake_parse)
    return rss_mod.RssPTClient()


def test_pt_rss_latest_feed_filters_by_keyword(monkeypatch):
    client = _client_with_feed(monkeypatch, "https://mypt.example/rss?passkey=SECRET123")
    results = client.search("Dune")
    assert len(results) == 1
    dto = results[0]
    assert "Dune" in dto.title
    assert dto.resolution == "2160P"
    assert dto.quality == "REMUX"
    assert dto.size_bytes == 84288733184
    # Download URL carries the passkey so qBittorrent can fetch it directly.
    assert "passkey=SECRET123" in dto.download_url
    assert dto.site_name == "mypt"


def test_pt_rss_searchable_feed_returns_all(monkeypatch):
    # With a {keyword} placeholder the feed is "searchable", so no local filter.
    client = _client_with_feed(
        monkeypatch, "https://mypt.example/rss?passkey=SECRET123&search={keyword}"
    )
    results = client.search("anything")
    assert len(results) == 2


def test_pt_rss_backend_selected(monkeypatch):
    from ai_media_assistant.shared import config

    config.get_settings.cache_clear()
    monkeypatch.setenv("PT_MOCK", "false")
    monkeypatch.setenv("PT_BACKEND", "rss")
    monkeypatch.setenv("PT_RSS_URL", "https://x/rss?passkey=y")
    assert config.get_settings().effective_pt_backend == "rss"
