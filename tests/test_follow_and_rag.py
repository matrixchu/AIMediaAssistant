"""Tests for follow service, RSS parsing and recommendations."""

from __future__ import annotations

from ai_media_assistant.clients.rss import parse_episode
from ai_media_assistant.services.follow_service import FollowService
from ai_media_assistant.services.recommendation_service import RecommendationService


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
