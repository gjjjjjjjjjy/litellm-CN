"""
AI news for the home dashboard, read from RSS 2.0 and Atom feeds.

Feeds are fetched on demand and kept per process for NEWS_CACHE_SECONDS, so a busy dashboard does not hit the
publishers on every refresh. A feed that cannot be fetched or parsed is reported with its error next to the
items of the feeds that worked.
"""

import asyncio
import html
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from itertools import chain
from typing import Final
from xml.etree import ElementTree

import httpx
from pydantic import ConfigDict, TypeAdapter, ValidationError

from litellm.types.llms.base import LiteLLMBaseModel
from litellm.types.qos import QosNewsItem, QosNewsResponse, QosNewsSource

NEWS_CACHE_SECONDS: Final = 1800
NEWS_ITEMS: Final = 40
NEWS_ITEMS_PER_SOURCE: Final = 8
NEWS_SUMMARY_CHARS: Final = 160
FEED_MAX_BYTES: Final = 4 * 1024 * 1024
FEED_TIMEOUT_SECONDS: Final = 10.0
NEWS_FEEDS_SETTING: Final = "qos_news_feeds"

_ATOM: Final = "{http://www.w3.org/2005/Atom}"
_TAGS: Final = re.compile(r"<[^>]+>")
_SPACES: Final = re.compile(r"\s+")


class NewsFeed(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    url: str


DEFAULT_NEWS_FEEDS: Final = (
    NewsFeed(name="量子位", url="https://www.qbitai.com/feed"),
    NewsFeed(name="InfoQ", url="https://www.infoq.cn/feed"),
    NewsFeed(name="Hugging Face", url="https://huggingface.co/blog/feed.xml"),
    NewsFeed(name="OpenAI", url="https://openai.com/news/rss.xml"),
    NewsFeed(name="Google AI", url="https://blog.google/technology/ai/rss/"),
)

_FEEDS: Final = TypeAdapter(tuple[NewsFeed, ...])


def configured_feeds(general_settings: Mapping[str, object]) -> tuple[NewsFeed, ...]:
    """The feeds listed under general_settings.qos_news_feeds, or the defaults when none are configured."""
    if NEWS_FEEDS_SETTING not in general_settings:
        return DEFAULT_NEWS_FEEDS
    return _FEEDS.validate_python(general_settings[NEWS_FEEDS_SETTING])


def _plain_text(markup: str) -> str:
    text: Final = _SPACES.sub(" ", html.unescape(_TAGS.sub(" ", markup))).strip()
    return text if len(text) <= NEWS_SUMMARY_CHARS else f"{text[:NEWS_SUMMARY_CHARS].rstrip()}…"


def _text(element: ElementTree.Element | None) -> str:
    return "" if element is None or element.text is None else element.text.strip()


def _rss_date(value: str) -> datetime | None:
    if value == "":
        return None
    try:
        parsed: Final = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _atom_date(value: str) -> datetime | None:
    if value == "":
        return None
    try:
        parsed: Final = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _rss_item(item: ElementTree.Element, source: str) -> QosNewsItem:
    return QosNewsItem(
        source=source,
        title=_plain_text(_text(item.find("title"))),
        link=_text(item.find("link")),
        summary=_plain_text(_text(item.find("description"))),
        published_at=_rss_date(_text(item.find("pubDate"))),
    )


def _atom_link(entry: ElementTree.Element) -> str:
    links: Final = entry.findall(f"{_ATOM}link")
    alternate: Final = next((link for link in links if link.get("rel", "alternate") == "alternate"), None)
    return "" if alternate is None else alternate.get("href", "")


def _atom_entry(entry: ElementTree.Element, source: str) -> QosNewsItem:
    summary: Final = entry.find(f"{_ATOM}summary")
    published: Final = _text(entry.find(f"{_ATOM}published"))
    return QosNewsItem(
        source=source,
        title=_plain_text(_text(entry.find(f"{_ATOM}title"))),
        link=_atom_link(entry),
        summary=_plain_text(_text(summary if summary is not None else entry.find(f"{_ATOM}content"))),
        published_at=_atom_date(published if published != "" else _text(entry.find(f"{_ATOM}updated"))),
    )


def parse_feed(document: bytes, source: str) -> tuple[QosNewsItem, ...]:
    """Items of an RSS 2.0 or Atom document; raises ValueError for anything else."""
    root: Final = ElementTree.fromstring(document)
    if root.tag == "rss":
        return tuple(_rss_item(item, source) for item in root.iterfind("channel/item"))
    if root.tag == f"{_ATOM}feed":
        return tuple(_atom_entry(entry, source) for entry in root.iterfind(f"{_ATOM}entry"))
    raise ValueError(f"not an RSS or Atom feed: <{root.tag}>")


@dataclass(frozen=True, slots=True)
class FeedResult:
    feed: NewsFeed
    items: tuple[QosNewsItem, ...]
    error: str | None
    fetched_at: datetime


async def _read_limited(response: httpx.Response) -> bytes:
    chunks: Final = [chunk async for chunk in response.aiter_bytes()]
    body: Final = b"".join(chunks)
    if len(body) > FEED_MAX_BYTES:
        raise ValueError(f"feed is larger than {FEED_MAX_BYTES} bytes")
    return body


async def fetch_feed(client: httpx.AsyncClient, feed: NewsFeed) -> FeedResult:
    fetched_at: Final = datetime.now(timezone.utc)
    try:
        async with client.stream("GET", feed.url) as response:
            response.raise_for_status()
            body: Final = await _read_limited(response)
        return FeedResult(feed=feed, items=parse_feed(body, feed.name), error=None, fetched_at=fetched_at)
    except (httpx.HTTPError, ElementTree.ParseError, ValueError, ValidationError) as error:
        return FeedResult(feed=feed, items=(), error=f"{type(error).__name__}: {error}", fetched_at=fetched_at)


def _recency(item: QosNewsItem) -> tuple[bool, float]:
    """Dated items first, newest first; undated items keep their feed order after them."""
    if item.published_at is None:
        return (False, 0.0)
    return (True, item.published_at.timestamp())


def _latest(items: Sequence[QosNewsItem]) -> list[QosNewsItem]:
    """A feed's newest NEWS_ITEMS_PER_SOURCE complete items, so one busy publisher cannot fill the list."""
    complete: Final = (item for item in items if item.title != "" and item.link != "")
    return sorted(complete, key=_recency, reverse=True)[:NEWS_ITEMS_PER_SOURCE]


def news_response(results: Sequence[FeedResult]) -> QosNewsResponse:
    newest_first: Final = sorted(
        chain.from_iterable(_latest(result.items) for result in results), key=_recency, reverse=True
    )
    return QosNewsResponse(
        items=tuple(newest_first[:NEWS_ITEMS]),
        sources=tuple(
            QosNewsSource(
                name=result.feed.name,
                url=result.feed.url,
                items=len(result.items),
                error=result.error,
                fetched_at=result.fetched_at,
            )
            for result in results
        ),
    )


@dataclass(frozen=True, slots=True)
class _Cached:
    feeds: tuple[NewsFeed, ...]
    response: QosNewsResponse
    stored_at: float


class NewsCache:
    """One fetch per NEWS_CACHE_SECONDS per feed list, shared by every request of this process."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = asyncio.Lock()
        self._cached: _Cached | None = None

    async def get(self, feeds: tuple[NewsFeed, ...], client: httpx.AsyncClient) -> QosNewsResponse:
        async with self._lock:
            cached: Final = self._cached
            if cached is not None and cached.feeds == feeds and self._clock() - cached.stored_at < NEWS_CACHE_SECONDS:
                return cached.response
            results: Final = await asyncio.gather(*(fetch_feed(client, feed) for feed in feeds))
            response: Final = news_response(results)
            self._cached = _Cached(feeds=feeds, response=response, stored_at=self._clock())
            return response
