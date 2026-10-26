from datetime import datetime, timezone
from typing import Final

import httpx
import pytest

from litellm.proxy.management_endpoints.qos_news import (
    DEFAULT_NEWS_FEEDS,
    FEED_MAX_BYTES,
    NEWS_CACHE_SECONDS,
    NEWS_ITEMS_PER_SOURCE,
    NewsCache,
    NewsFeed,
    configured_feeds,
    fetch_feed,
    parse_feed,
)

RSS: Final = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Lab</title>
<item><title>Model &amp; release</title><link>https://lab.example/a</link>
<pubDate>Mon, 26 Oct 2026 08:00:00 +0800</pubDate>
<description><![CDATA[<p>New <b>weights</b> are out.</p>]]></description></item>
<item><title>Undated note</title><link>https://lab.example/b</link></item>
</channel></rss>"""

ATOM: Final = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Blog</title>
<entry><title>Atom post</title><link rel="alternate" href="https://blog.example/post"/>
<updated>2026-10-25T10:00:00Z</updated><summary>Short summary</summary></entry>
</feed>"""


class TestParseFeed:
    def test_reads_rss_items_as_plain_text_with_their_dates(self) -> None:
        first, undated = parse_feed(RSS, "Lab")

        assert (first.source, first.title, first.link, first.summary) == (
            "Lab",
            "Model & release",
            "https://lab.example/a",
            "New weights are out.",
        )
        assert first.published_at == datetime(2026, 10, 26, 0, 0, tzinfo=timezone.utc)
        assert undated.published_at is None

    def test_reads_atom_entries_falling_back_to_their_update_time(self) -> None:
        (entry,) = parse_feed(ATOM, "Blog")

        assert (entry.link, entry.summary) == ("https://blog.example/post", "Short summary")
        assert entry.published_at == datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc)

    def test_rejects_documents_that_are_not_feeds(self) -> None:
        with pytest.raises(ValueError):
            parse_feed(b"<html><body>Not a feed</body></html>", "Site")


def _transport(responses: dict[str, httpx.Response]) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: responses[str(request.url)])


class TestNews:
    @pytest.mark.asyncio
    async def test_a_broken_feed_is_reported_beside_the_news_of_the_working_ones(self) -> None:
        feeds: Final = (
            NewsFeed(name="Lab", url="https://lab.example/rss"),
            NewsFeed(name="Down", url="https://down.example/rss"),
        )
        transport: Final = _transport(
            {
                "https://lab.example/rss": httpx.Response(200, content=RSS),
                "https://down.example/rss": httpx.Response(503),
            }
        )
        async with httpx.AsyncClient(transport=transport) as client:
            news = await NewsCache().get(feeds, client)

        assert [item.title for item in news.items] == ["Model & release", "Undated note"]
        lab, down = news.sources
        assert (lab.items, lab.error) == (2, None)
        assert down.items == 0 and down.error is not None and "503" in down.error

    @pytest.mark.asyncio
    async def test_one_busy_publisher_cannot_fill_the_list(self) -> None:
        items: Final = b"".join(
            f"<item><title>Busy {index}</title><link>https://busy.example/{index}</link>"
            f"<pubDate>Mon, 26 Oct 2026 {10 + index % 10:02d}:00:00 +0000</pubDate></item>".encode()
            for index in range(20)
        )
        busy: Final = b'<rss version="2.0"><channel>' + items + b"</channel></rss>"
        feeds: Final = (
            NewsFeed(name="Busy", url="https://busy.example/rss"),
            NewsFeed(name="Lab", url="https://lab.example/rss"),
        )
        transport: Final = _transport(
            {
                "https://busy.example/rss": httpx.Response(200, content=busy),
                "https://lab.example/rss": httpx.Response(200, content=RSS),
            }
        )
        async with httpx.AsyncClient(transport=transport) as client:
            news = await NewsCache().get(feeds, client)

        assert sum(item.source == "Busy" for item in news.items) == NEWS_ITEMS_PER_SOURCE
        assert {item.source for item in news.items} == {"Busy", "Lab"}

    @pytest.mark.asyncio
    async def test_an_oversized_feed_is_refused(self) -> None:
        feed: Final = NewsFeed(name="Huge", url="https://huge.example/rss")
        transport: Final = _transport({feed.url: httpx.Response(200, content=b" " * (FEED_MAX_BYTES + 1))})
        async with httpx.AsyncClient(transport=transport) as client:
            result = await fetch_feed(client, feed)

        assert result.items == ()
        assert result.error is not None and "larger than" in result.error

    @pytest.mark.asyncio
    async def test_feeds_are_fetched_again_only_after_the_cache_expires(self) -> None:
        now = [1000.0]
        calls: list[str] = []  # mutable-ok: test double records each fetch

        def handle(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(200, content=RSS)

        cache: Final = NewsCache(clock=lambda: now[0])
        feeds: Final = (NewsFeed(name="Lab", url="https://lab.example/rss"),)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            await cache.get(feeds, client)
            now[0] += NEWS_CACHE_SECONDS - 1
            await cache.get(feeds, client)
            now[0] += 2
            await cache.get(feeds, client)

        assert len(calls) == 2


class TestConfiguredFeeds:
    def test_uses_the_defaults_until_feeds_are_configured(self) -> None:
        assert configured_feeds({}) == DEFAULT_NEWS_FEEDS
        assert configured_feeds({"qos_news_feeds": [{"name": "Lab", "url": "https://lab.example/rss"}]}) == (
            NewsFeed(name="Lab", url="https://lab.example/rss"),
        )
