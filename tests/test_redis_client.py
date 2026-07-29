import asyncio

from db import redis_client


class FakeRedis:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value


def test_diff_state_can_be_used_across_event_loops(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(redis_client, "get_client", lambda: client)

    assert asyncio.run(redis_client.set_last_seen(1, "web:test", "hash")) is True
    assert asyncio.run(redis_client.get_last_seen(1, "web:test")) == "hash"
