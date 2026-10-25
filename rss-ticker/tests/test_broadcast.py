# Copyright 2026 Art Cashin.
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio

import pytest

from rss_ticker.broadcast import MAX_QUEUE, Broadcaster
from rss_ticker.store import NewArticle, Store


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def add(store, url="https://x.example/rss", name="X"):
    return store.upsert_feed(url, name=name, now=0)


def articles(store, fid, specs):
    return store.insert_articles(
        fid, [NewArticle(g, t, None, None, ts) for g, t, ts in specs], now=1000
    )


async def drain(sub):
    out = []
    while not sub.queue.empty():
        out.append(sub.queue.get_nowait())
    return out


async def test_a_socket_receives_only_its_subscribed_feeds(store):
    a, b = add(store), add(store, url="https://y.example/rss", name="Y")
    bc = Broadcaster(store)
    s1, s2 = bc.subscribe(), bc.subscribe()
    bc.set_feeds(s1, {a})
    bc.set_feeds(s2, {b})
    await bc.publish(articles(store, b, [("g", "From Y", 1)]))
    # s1 named only `a`: B's article never reaches it.
    assert await drain(s1) == []
    assert [m["feed_id"] for m in await drain(s2)] == [b]


async def test_payload_shape(store):
    fid = add(store, name="Reuters")
    bc = Broadcaster(store)
    sub = bc.subscribe()
    bc.set_feeds(sub, {fid})
    await bc.publish(
        store.insert_articles(
            fid, [NewArticle("a", "Fed holds", "https://l", "s", 1, author="Jane")], now=1000
        )
    )
    msg = (await drain(sub))[0]
    assert set(msg) == {
        "id",
        "feed_id",
        "cursor",
        "title",
        "link",
        "summary",
        "source",
        "author",
        "published_at",
        "sort_at",
    }
    assert (msg["source"], msg["author"], msg["feed_id"]) == ("Reuters", "Jane", fid)


def test_counts_follow_the_sockets_and_drive_enabled(store):
    a, b = add(store), add(store, url="https://y.example/rss")
    store.disable_all_feeds()
    bc = Broadcaster(store)
    s1, s2 = bc.subscribe(), bc.subscribe()

    bc.set_feeds(s1, {a, b})
    assert (bc.subscriber_count(a), bc.subscriber_count(b)) == (1, 1)
    assert store.get_feed(a).enabled and store.get_feed(b).enabled

    bc.set_feeds(s2, {a})
    assert bc.subscriber_count(a) == 2

    bc.set_feeds(s1, {b})  # s1 drops a
    assert bc.subscriber_count(a) == 1
    assert store.get_feed(a).enabled

    bc.unsubscribe(s2)
    assert bc.subscriber_count(a) == 0
    assert not store.get_feed(a).enabled
    assert store.get_feed(b).enabled
    assert bc.session_count() == 1


def test_unsubscribe_is_idempotent(store):
    a = add(store)
    bc = Broadcaster(store)
    sub = bc.subscribe()
    bc.set_feeds(sub, {a})
    bc.unsubscribe(sub)
    bc.unsubscribe(sub)
    assert bc.subscriber_count(a) == 0
    assert store.get_feed(a).enabled is False


async def test_slow_client_is_dropped_not_awaited(store):
    fid = add(store)
    bc = Broadcaster(store)
    sub = bc.subscribe()
    bc.set_feeds(sub, {fid})
    for i in range(MAX_QUEUE):
        sub.queue.put_nowait({"filler": i})
    await asyncio.wait_for(bc.publish(articles(store, fid, [("a", "Fed holds", 1)])), timeout=1.0)
    assert sub.dropped is True
    assert sub.closed.is_set()
    assert bc.session_count() == 0
    # Dropping the socket released its subscription.
    assert bc.subscriber_count(fid) == 0
    assert store.get_feed(fid).enabled is False


async def test_unsubscribe_stops_delivery(store):
    fid = add(store)
    bc = Broadcaster(store)
    sub = bc.subscribe()
    bc.unsubscribe(sub)
    await bc.publish(articles(store, fid, [("a", "Fed holds", 1)]))
    assert await drain(sub) == []
