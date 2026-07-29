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
    sent_keys = []
    monkeypatch.setattr(alert_engine, "get_connection", FakeConnection)
    monkeypatch.setattr(alert_engine, "_is_alert_duplicate", lambda key: False)
    monkeypatch.setattr(alert_engine, "_mark_alert_sent", sent_keys.append)

    alerts = alert_engine.check_page_changes()

    assert len(alerts) == 1
    assert alerts[0]["type"] == alert_engine.ALERT_PAGE_CHANGE
    assert alerts[0]["severity"] == "warning"
    assert alerts[0]["metadata"]["evidence_id"] == 11
    assert sent_keys == ["page_change_8"]
