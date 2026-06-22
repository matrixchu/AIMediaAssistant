"""RSS feed fetching and episode title parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from time import mktime

import feedparser

from ...shared.logging import get_logger

logger = get_logger(__name__)

# Matches "Show Name S02E05", "Show.Name.S02E05", "Show 第2季 第5集", etc.
_SXXEXX = re.compile(r"^(?P<title>.+?)[ ._\-]+S(?P<season>\d{1,2})E(?P<episode>\d{1,3})", re.I)
_CN = re.compile(r"^(?P<title>.+?)\s*第\s*(?P<season>\d+)\s*季.*?第\s*(?P<episode>\d+)\s*集")


@dataclass
class RssEntry:
    guid: str
    title: str
    link: str | None
    publish_time: datetime | None


@dataclass
class ParsedEpisode:
    show_title: str
    season: int
    episode: int


def fetch_feed(feed_url: str) -> list[RssEntry]:
    """Fetch and parse an RSS feed into normalized entries."""
    parsed = feedparser.parse(feed_url)
    if parsed.bozo:
        logger.warning("RSS feed parse warning for %s: %s", feed_url, parsed.bozo_exception)
    entries: list[RssEntry] = []
    for e in parsed.entries:
        guid = getattr(e, "id", None) or getattr(e, "link", None) or getattr(e, "title", "")
        published = None
        if getattr(e, "published_parsed", None):
            published = datetime.fromtimestamp(mktime(e.published_parsed))
        entries.append(
            RssEntry(
                guid=str(guid),
                title=getattr(e, "title", ""),
                link=getattr(e, "link", None),
                publish_time=published,
            )
        )
    return entries


def parse_episode(title: str) -> ParsedEpisode | None:
    """Extract show title / season / episode from a release title."""
    for pattern in (_SXXEXX, _CN):
        m = pattern.match(title)
        if m:
            show = re.sub(r"[._]+", " ", m.group("title")).strip()
            return ParsedEpisode(
                show_title=show,
                season=int(m.group("season")),
                episode=int(m.group("episode")),
            )
    return None
