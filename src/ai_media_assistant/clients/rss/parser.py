"""RSS feed fetching and episode title parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from time import mktime

import feedparser

from ...shared.logging import get_logger

logger = get_logger(__name__)

# Matches "Show Name S02E05", "Show.Name.S02.E05", etc.
_SXXEXX = re.compile(
    r"^(?P<title>.+?)[ ._\-]+S(?P<season>\d{1,2})[ ._\-]*E(?P<episode>\d{1,3})",
    re.I,
)
# Matches Chinese styles like "龙之家族 第三季 第2集".
_CN = re.compile(
    r"^(?P<title>.+?)\s*第\s*(?P<season>[0-9一二三四五六七八九十百零〇两]+)\s*季.*?第\s*(?P<episode>[0-9一二三四五六七八九十百零〇两]+)\s*[集话話]"
)


_CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _to_int(token: str) -> int | None:
    value = (token or "").strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)

    # Handle common Chinese numerals used in season/episode markers.
    if value == "十":
        return 10
    if "百" in value:
        left, _, right = value.partition("百")
        hundreds = _CN_DIGITS.get(left or "一")
        if hundreds is None:
            return None
        tail = _to_int(right) if right else 0
        return hundreds * 100 + (tail or 0)
    if "十" in value:
        left, _, right = value.partition("十")
        tens = _CN_DIGITS.get(left, 1 if left == "" else -1)
        if tens < 0:
            return None
        ones = _CN_DIGITS.get(right, 0 if right == "" else -1)
        if ones < 0:
            return None
        return tens * 10 + ones
    if len(value) > 1:
        digits: list[str] = []
        for ch in value:
            n = _CN_DIGITS.get(ch)
            if n is None:
                return None
            digits.append(str(n))
        return int("".join(digits))
    return _CN_DIGITS.get(value)


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
            season = _to_int(m.group("season"))
            episode = _to_int(m.group("episode"))
            if not season or not episode:
                return None
            return ParsedEpisode(
                show_title=show,
                season=season,
                episode=episode,
            )
    return None
