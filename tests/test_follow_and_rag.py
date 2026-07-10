"""Tests for follow service, RSS parsing and recommendations."""

from __future__ import annotations

from ai_media_assistant.clients.rss import parse_episode
from ai_media_assistant.services.download_service import DownloadService
from ai_media_assistant.services.follow_service import (
    FollowService,
    _normalize_title,
    _pick_best_per_episode,
    _title_matches_subscription,
    parse_release_title,
)
from ai_media_assistant.services.recommendation_service import RecommendationService
from ai_media_assistant.shared.schemas import TorrentResourceDTO


def test_follow_show_downloads_episodes():
    result = FollowService().follow_show("The Last of Us", season=2, confirm=True)
    assert result["subscription_id"] is not None
    assert result["episodes_downloaded"], "expected episodes to be downloaded"


def test_list_subscriptions_after_follow():
    follow = FollowService()
    follow.follow_show("Foundation", season=2, confirm=True)
    subs = follow.list_subscriptions()
    assert any(s.title == "Foundation" for s in subs)


def test_parse_episode_patterns():
    parsed = parse_episode("The Last of Us S02E05 2160p WEB-DL")
    assert parsed is not None
    assert parsed.season == 2
    assert parsed.episode == 5

    parsed_dotted = parse_episode("House.of.the.Dragon.S03.E02.2160p.WEB-DL")
    assert parsed_dotted is not None
    assert parsed_dotted.season == 3
    assert parsed_dotted.episode == 2

    parsed_cn = parse_episode("龙之家族 第三季 第2集 2160p")
    assert parsed_cn is not None
    assert parsed_cn.show_title == "龙之家族"
    assert parsed_cn.season == 3
    assert parsed_cn.episode == 2


def test_parse_release_title_for_scheduler_autofollow():
    parsed = parse_release_title("The Last of Us S02E05 2160p WEB-DL")
    assert parsed == ("The Last of Us", 2, 5)

    parsed_cn = parse_release_title("龙之家族 第三季 第2集 2160p WEB-DL")
    assert parsed_cn == ("龙之家族", 3, 2)


def test_follow_show_respects_preferred_variant_filter():
    result = FollowService().follow_show("The Last of Us", season=2, quality="1080P", confirm=True)
    assert result["subscription_id"] is not None
    # Mock catalog for this show is 2160P only, so 1080P preference should skip downloads.
    assert result["episodes_downloaded"] == []


def test_follow_show_can_skip_initial_sync_for_fast_response():
    result = FollowService().follow_show(
        "House of the Dragon",
        season=3,
        quality="2160P",
        confirm=True,
        initial_sync=False,
    )
    assert result["subscription_id"] is not None
    assert result["episodes_downloaded"] == []
    assert result.get("initial_sync_skipped") is True


def test_reconcile_subscription_backfills_missing_episodes():
    follow = FollowService()
    created = follow.follow_show(
        "House of the Dragon",
        season=3,
        quality="2160P",
        confirm=True,
        initial_sync=False,
    )
    sub_id = created["subscription_id"]

    out = follow.reconcile_subscription(sub_id, confirm=True)
    assert out["subscription_id"] == sub_id
    assert out["checked"] >= 1
    assert out["downloaded"]

    # Running reconcile again should not download duplicate episodes or variants.
    again = follow.reconcile_subscription(sub_id, confirm=True)
    assert again["downloaded"] == []


def test_pick_best_per_episode_keeps_one_release_per_episode():
    resources = [
        TorrentResourceDTO(site_name="x", title="House of the Dragon S03E01 2160p WEB-DL", quality="WEB-DL", seeders=50),
        TorrentResourceDTO(site_name="x", title="House of the Dragon S03E01 1080p WEB-DL", quality="WEB-DL", seeders=20),
        TorrentResourceDTO(site_name="x", title="House of the Dragon S03E02 2160p WEB-DL", quality="WEB-DL", seeders=40),
    ]
    picked = _pick_best_per_episode(resources, season=3, quality="2160P")
    assert [r.title for r in picked] == [
        "House of the Dragon S03E01 2160p WEB-DL",
        "House of the Dragon S03E02 2160p WEB-DL",
    ]


def test_follow_show_uses_series_season_save_path():
    download = DownloadService()
    before_max_id = max((t.id or 0 for t in download.list_tasks()), default=0)

    FollowService().follow_show("The Last of Us", season=2, confirm=True)

    new_tasks = [t for t in download.list_tasks() if (t.id or 0) > before_max_id]
    assert new_tasks
    assert all((t.save_path or "").startswith("/downloads/video/tv/The.Last.of.Us/Season 02/") for t in new_tasks)


def test_episode_save_path_prefers_english_alias_for_chinese_title():
    follow = FollowService()
    path = follow._episode_save_path(
        "龙之家族",
        3,
        resource_title="House of the Dragon S03E03 2160p WEB-DL",
    )
    assert path == "/downloads/video/tv/House.of.the.Dragon/Season 03/"


def test_title_matching_does_not_false_positive_for_unrelated_titles():
    sub = _normalize_title("龙之家族")
    rel = _normalize_title("Civilization")
    assert sub and rel
    assert _title_matches_subscription(rel, sub) is False


def test_recommendations_return_results():
    recs = RecommendationService().recommend("sci-fi movies")
    assert recs, "RAG should return recommendations"
    assert all(r.title for r in recs)


def test_recommendations_download_listing_query_routes_to_live_resources():
    recs = RecommendationService().recommend("Dune有哪些资源可以下载")
    assert recs, "download-listing intent should still return actionable results"
    assert any(r.resource is not None for r in recs)
    assert any("id=" in r.reason for r in recs)


def test_recommendations_resource_listing_without_download_word_routes_to_live_resources():
    recs = RecommendationService().recommend("Dune有哪些资源")
    assert recs, "resource-listing intent should route to live PT resources"
    assert any(r.resource is not None for r in recs)
