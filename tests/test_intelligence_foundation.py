from intelligence import foundation
from intelligence.foundation import (
    ClaimStore,
    DocumentStore,
    RunTracker,
    apply_text_byte_budget,
    json_safe,
    parse_timestamp,
)


def test_canonical_url_removes_tracking_and_normalizes_host_path_and_query():
    canonical = DocumentStore.canonicalize_url(
        "HTTPS://Example.COM:443//news/item/?utm_source=test&b=2&a=1#section"
    )

    assert canonical == "https://example.com/news/item?a=1&b=2"


def test_chunking_is_deterministic_bounded_and_overlapping():
    content = " ".join(f"sentence-{index}." for index in range(120))

    first = DocumentStore.chunk_text(content, max_chars=240, overlap_chars=40)
    second = DocumentStore.chunk_text(content, max_chars=240, overlap_chars=40)

    assert first == second
    assert len(first) > 1
    assert all(0 <= start < end <= len(content) for start, end, _ in first)
    assert all(len(chunk) <= 240 for _, _, chunk in first)
    assert all(first[index + 1][0] < first[index][1] for index in range(len(first) - 1))


def test_long_documents_are_chunked_to_the_end_without_character_truncation():
    content = "\n\n".join(
        f"Evidence paragraph {index}: " + ("detail " * 45)
        for index in range(700)
    )
    normalized = DocumentStore.normalize_text(content)

    chunks = DocumentStore.chunk_text(
        content,
        max_chars=1600,
        overlap_chars=200,
    )

    assert len(content) > 200_000
    assert len(chunks) > 100
    assert chunks[0][0] == 0
    assert chunks[-1][1] == len(normalized)


def test_byte_budget_preserves_long_utf8_text_and_only_bounds_at_safety_limit():
    content = "Nestlé intelligence — " * 8_000

    preserved = apply_text_byte_budget(content, 1_000_000)
    bounded = apply_text_byte_budget(content, 10_003)

    assert preserved.text == content
    assert preserved.truncated is False
    assert bounded.truncated is True
    assert bounded.stored_bytes <= 10_003
    assert bounded.text.encode("utf-8").decode("utf-8") == bounded.text


def test_run_tracker_retries_and_records_each_attempt(monkeypatch):
    tracker = RunTracker(run_id=91)
    attempts = []
    finishes = []

    monkeypatch.setattr(tracker, "check_cancelled", lambda: None)

    def start_task(**kwargs):
        attempt = len(attempts) + 1
        attempts.append(kwargs)
        return attempt, attempt

    monkeypatch.setattr(tracker, "_start_task", start_task)
    monkeypatch.setattr(
        tracker,
        "_finish_task",
        lambda task_id, **kwargs: finishes.append((task_id, kwargs)),
    )

    operation_attempts = 0

    def flaky_operation():
        nonlocal operation_attempts
        operation_attempts += 1
        if operation_attempts == 1:
            raise RuntimeError("temporary source failure")
        return {"items": 7}

    result = tracker.execute(
        task_key="news.collect",
        stage="ingestion",
        agent_name="NewsCollectorAgent",
        operation=flaky_operation,
        max_attempts=2,
    )

    assert result == {"items": 7}
    assert len(attempts) == 2
    assert finishes[0][1]["status"] == "retrying"
    assert finishes[1][1]["status"] == "completed"


def test_json_helpers_make_pipeline_payloads_serializable():
    timestamp = parse_timestamp("2026-07-28T10:30:00Z")

    assert timestamp is not None
    assert timestamp.tzinfo is not None
    assert json_safe({"timestamp": timestamp, "values": {1, 2}})["timestamp"].startswith(
        "2026-07-28T10:30:00"
    )


def test_claim_store_rejects_invalid_citations_even_for_predictions(monkeypatch):
    class EmptyCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, params=None):
            return None

        def fetchall(self):
            return []

    class EmptyConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return EmptyCursor()

    monkeypatch.setattr(foundation, "get_connection", lambda: EmptyConnection())

    claim_id = ClaimStore(competitor_id=12).create(
        statement="The company will announce a new product.",
        claim_type="prediction",
        evidence_ids=[999999],
        status="proposed",
    )

    assert claim_id is None
