"""Tests for the search and download services (offline mock path)."""

from __future__ import annotations

from ai_media_assistant.services.download_service import DownloadService
from ai_media_assistant.services.search_service import SearchService
from ai_media_assistant.shared.schemas import SearchQuery, TorrentResourceDTO


def test_search_finds_dune():
    result = SearchService().search("Dune Part Two")
    assert result.resources, "expected at least one resource"
    assert any("Dune" in r.title for r in result.resources)
    assert all(r.id is not None for r in result.resources)


def test_search_chinese_keyword():
    result = SearchService().search("沙丘2")
    assert result.resources
    assert any("Dune" in r.title for r in result.resources)


def test_search_with_structured_filters():
    result = SearchService().search(
        SearchQuery(
            keyword="Dune",
            resolution="2160P",
            quality="REMUX",
            min_seeders=100,
            min_size_gb=30,
        )
    )
    assert result.resources
    assert all((r.resolution or "").upper() == "2160P" for r in result.resources)
    assert all("REMUX" in (r.quality or "").upper() for r in result.resources)
    assert all(r.seeders >= 100 for r in result.resources)
    assert all(r.size_gb >= 30 for r in result.resources)


def test_apply_filters_category_alias_keeps_tv_and_unknown_for_zongyi():
    items = [
        TorrentResourceDTO(site_name="x", title="A", category="TV", seeders=10),
        TorrentResourceDTO(site_name="x", title="B", category=None, seeders=10),
        TorrentResourceDTO(site_name="x", title="C", category="Movie", seeders=10),
    ]
    out = SearchService._apply_filters(items, SearchQuery(category="综艺"))
    assert [r.title for r in out] == ["A", "B"]


def test_download_flow_and_progress():
    search = SearchService()
    download = DownloadService()

    best = search.best_match("Dune Part Two")
    assert best is not None
    task = download.download(best.id, confirm=True)
    assert task.id is not None
    assert task.qb_hash

    # Mock client advances progress each poll until completion.
    final = None
    for _ in range(10):
        final = download.refresh(task.id)
    assert final is not None
    assert final.progress == 100.0
    assert final.task_status.value == "completed"


def test_download_respects_custom_save_path():
    search = SearchService()
    download = DownloadService()

    best = search.best_match("Dune Part Two")
    assert best is not None
    task = download.download(best.id, confirm=True, save_path="/downloads/video/movie")

    assert task.id is not None
    assert task.save_path == "/downloads/video/movie"
