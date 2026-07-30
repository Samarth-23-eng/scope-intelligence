import json
from datetime import datetime

from alerts import alert_engine


class FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params=None):
        return None

    def fetchall(self):
        return [
            {
                "id": 8,
                "competitor_id": 3,
                "competitor_name": "Example",
                "change_type": "pricing",
                "summary": "Pricing or packaging changed.",
                "significance": 0.2,
                "source_url": "https://example.com/pricing",
                "evidence_id": 11,
                "detected_at": datetime(2026, 7, 27, 12, 0, 0),
            }
        ]


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def cursor(self):
        return FakeCursor()


def test_pricing_change_creates_evidence_linked_warning(monkeypatch):
    monkeypatch.setattr(alert_engine, "get_connection", FakeConnection)
    monkeypatch.setattr(alert_engine, "_is_alert_duplicate", lambda key: False)

    alerts = alert_engine.check_page_changes()

    assert len(alerts) == 1
    assert alerts[0]["type"] == alert_engine.ALERT_PAGE_CHANGE
    assert alerts[0]["severity"] == "warning"
    assert alerts[0]["metadata"]["evidence_id"] == 11
    assert alerts[0]["metadata"]["dedupe_key"] == "page_change_8"


def test_recent_alerts_scan_only_stored_payloads(monkeypatch):
    alert = {
        "type": "page_change",
        "competitor_id": 3,
        "timestamp": "2026-07-30T12:00:00Z",
    }

    class FakeRedis:
        def scan_iter(self, match):
            assert match == f"{alert_engine.ALERT_STORED_PREFIX}*"
            return iter([f"{alert_engine.ALERT_STORED_PREFIX}page_change:3:1"])

        def get(self, key):
            return json.dumps(alert)

    monkeypatch.setattr(alert_engine, "_get_redis", FakeRedis)

    assert alert_engine.get_recent_alerts(competitor_id=3) == [alert]


def test_alert_check_scopes_every_detector(monkeypatch):
    seen = []
    monkeypatch.setattr(
        alert_engine,
        "check_new_signals",
        lambda competitor_id=None: seen.append(("signals", competitor_id)) or [],
    )
    monkeypatch.setattr(
        alert_engine,
        "check_new_predictions",
        lambda competitor_id=None: seen.append(("predictions", competitor_id)) or [],
    )
    monkeypatch.setattr(
        alert_engine,
        "check_summary_updates",
        lambda competitor_id=None: seen.append(("summaries", competitor_id)) or [],
    )
    monkeypatch.setattr(
        alert_engine,
        "check_page_changes",
        lambda competitor_id=None: seen.append(("changes", competitor_id)) or [],
    )

    assert alert_engine.run_alert_checks(competitor_id=9) == []
    assert seen == [
        ("signals", 9),
        ("predictions", 9),
        ("summaries", 9),
        ("changes", 9),
    ]
